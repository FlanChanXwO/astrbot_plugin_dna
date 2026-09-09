"""Agent Tools 的注册和注销生命周期。"""

from __future__ import annotations

import inspect
from asyncio import Lock
from builtins import BaseExceptionGroup
from collections.abc import Mapping, Sequence
from typing import Any

from astrbot.api import logger

from ...modules.agent_tools.queries import AgentQueryCatalog
from .signin import AgentSignTool
from .tools import AGENT_TOOL_NAMES, build_agent_tools

AGENT_SIGN_TOOL_NAME = "dnaby_sign"


class AgentToolsLifecycle:
    """管理一组 Agent Tools，确保热重载不会重复注册或残留处理器。"""

    def __init__(
        self,
        *,
        context: object,
        enabled: bool,
        services: Mapping[str, object],
        command_prefixes: Sequence[str] = (),
        plugin_context: object | None = None,
        catalog: AgentQueryCatalog | None = None,
    ) -> None:
        self.context = context
        self.enabled = enabled
        self.services = services
        self.command_prefixes = tuple(command_prefixes)
        self.plugin_context = plugin_context
        self.catalog = catalog
        self._started = False
        self._registered_names: tuple[str, ...] = ()
        self._tools: tuple[object, ...] = ()
        self._lock = Lock()

    @property
    def started(self) -> bool:
        """返回 Agent Tools 是否已经完成注册。"""

        return self._started

    @property
    def registered_names(self) -> tuple[str, ...]:
        """返回本生命周期实例当前拥有的工具名。"""

        return self._registered_names

    @staticmethod
    def _tool_names(tools: Sequence[object]) -> tuple[str, ...]:
        names = tuple(getattr(tool, "name", "") for tool in tools)
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise TypeError("Agent Tools 名称不能为空")
        if len(set(names)) != len(names):
            raise ValueError("Agent Tools 名称重复")
        return names

    async def _maybe_await(self, value: object) -> None:
        if inspect.isawaitable(value):
            await value

    def _retain_registered_tools(self, names: Sequence[str]) -> None:
        """只保留仍可能存在于 Context 中的工具，供后续注销重试。"""

        retained_names = tuple(names)
        tools_by_name = {getattr(tool, "name", ""): tool for tool in self._tools}
        self._registered_names = retained_names
        self._tools = tuple(
            tools_by_name[name] for name in retained_names if name in tools_by_name
        )

    async def _unregister_names(
        self,
        remove: Any,
        names: Sequence[str],
    ) -> tuple[tuple[str, ...], list[BaseException]]:
        """注销工具并返回失败残留，确保单个失败不阻断其余清理。"""

        remaining: list[str] = []
        errors: list[BaseException] = []
        for name in names:
            try:
                await self._maybe_await(remove(name))
            except BaseException as error:  # noqa: BLE001
                logger.warning(
                    "[dnaby][agent_tools] 工具注销失败: %s (%s)",
                    name,
                    type(error).__name__,
                )
                remaining.append(name)
                errors.append(error)
        return tuple(remaining), errors

    @staticmethod
    def _raise_unregister_errors(
        message: str,
        errors: Sequence[BaseException],
    ) -> None:
        if not errors:
            return
        if len(errors) == 1:
            raise errors[0]
        raise BaseExceptionGroup(message, list(errors))

    def _build_tools(self) -> tuple[list[object], tuple[str, ...]]:
        checkin_service = self.services.get("checkin_service")
        if checkin_service is None:
            raise TypeError("Agent 签到工具需要 checkin_service")
        read_only_tools = build_agent_tools(
            services=self.services,
            catalog=self.catalog,
            plugin_context=self.plugin_context,
        )
        tools: list[object] = [*read_only_tools]
        tools.append(
            AgentSignTool(
                checkin_service=checkin_service,
                command_prefixes=self.command_prefixes,
                plugin_context=self.plugin_context,
            ),
        )
        names = self._tool_names(tools)
        expected_names = (*AGENT_TOOL_NAMES, AGENT_SIGN_TOOL_NAME)
        if names != expected_names:
            raise ValueError("Agent Tools 清单与注册顺序不一致")
        return tools, names

    def _registration_methods(self) -> tuple[Any, Any]:
        add = getattr(self.context, "add_llm_tools", None)
        remove = getattr(self.context, "unregister_llm_tool", None)
        if not callable(add) or not callable(remove):
            raise TypeError(
                "Agent Tools 生命周期需要 AstrBot Context.add_llm_tools 与 unregister_llm_tool",
            )
        return add, remove

    async def start(self) -> None:
        """按一次性批量注册 Agent Tools；禁用时保持完全空操作。"""

        async with self._lock:
            if self._started:
                return
            if not self.enabled and not self._registered_names:
                return
            add, remove = self._registration_methods()

            if self._registered_names:
                remaining, cleanup_errors = await self._unregister_names(
                    remove,
                    self._registered_names,
                )
                self._retain_registered_tools(remaining)
                self._raise_unregister_errors(
                    "多个 Agent Tools 残留注销失败",
                    cleanup_errors,
                )

            tools, names = self._build_tools()
            self._tools = tuple(tools)
            self._registered_names = names
            try:
                await self._maybe_await(add(*tools))
            except BaseException as registration_error:
                remaining, cleanup_errors = await self._unregister_names(
                    remove,
                    names,
                )
                self._retain_registered_tools(remaining)
                self._started = False
                if cleanup_errors:
                    raise BaseExceptionGroup(
                        "Agent Tools 注册失败且残留清理失败",
                        [registration_error, *cleanup_errors],
                    ) from registration_error
                raise
            self._tools = tuple(tools)
            self._registered_names = names
            self._started = True

    async def stop(self) -> None:
        """注销本实例拥有的全部工具，并在多项失败时继续清理。"""

        async with self._lock:
            if not self._started and not self._registered_names:
                return
            remove = getattr(self.context, "unregister_llm_tool", None)
            if not callable(remove):
                raise TypeError(
                    "Agent Tools 注销需要 AstrBot Context.unregister_llm_tool",
                )

            remaining, errors = await self._unregister_names(
                remove,
                self._registered_names,
            )
            self._retain_registered_tools(remaining)
            self._started = False
            self._raise_unregister_errors("多个 Agent Tools 注销失败", errors)


__all__ = ["AGENT_SIGN_TOOL_NAME", "AgentToolsLifecycle"]
