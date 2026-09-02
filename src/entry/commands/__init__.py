"""显式命令 registry 与 AstrBot handler 生成器。

命令模块通过 ``src.modules.index`` 显式列出；registry 是每个插件 runtime
自己的不可变视图，不依赖旧的全局 dispatch。每个 ``CommandSpec`` 会生成
一个独立的 async-generator class method，并通过 AstrBot 公开 decorator
注册自己的正则和权限过滤器。
"""

from __future__ import annotations

import inspect
import json
import keyword
import re
import traceback
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, cast

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.star.filter.regex import RegexFilter

from ...infrastructure.rendering.errors import HtmlRenderError
from ...infrastructure.utils.logger import logger
from ...utils.msgs.notify import HTML_RENDER_FAILED
from ..event import (
    EventActor,
    actor_from_event,
    command_text_from_event,
    images_from_event,
    reply_id_from_event,
    target_user_from_event,
)
from ..response import CommandResponse, PlainTextResponse

PermissionName = Literal["user", "admin"]
MentionPolicy = Literal["ignore", "query", "admin_target"]
CommandUseCase = Callable[
    ...,
    Awaitable[CommandResponse | str | None]
    | AsyncGenerator[CommandResponse | str, None],
]

_PERMISSIONS = {"user", "admin"}
COMMAND_PREFIX = "kk"
COMMAND_EXECUTION_FAILED = "命令执行失败，请稍后重试；管理员可查看日志了解详情。"
COMMAND_GROUP_ORDER: tuple[str, ...] = (
    "账号管理",
    "皎皎角登录",
    "密函",
    "信息查询",
    "角色信息",
    "隐私控制",
    "签到服务",
    "管理员功能",
    "bot主人功能",
    "图鉴",
    "攻略",
    "兑换码",
    "公告",
    "资源管理",
)


def _ordered_groups(groups: Iterable[str]) -> list[str]:
    """按帮助卡约定排序，未知分组保持其首次出现顺序。"""

    preferred = {name: index for index, name in enumerate(COMMAND_GROUP_ORDER)}
    first_seen: dict[str, int] = {}
    for index, name in enumerate(groups):
        first_seen.setdefault(name, index)
    return sorted(
        first_seen,
        key=lambda name: (preferred.get(name, len(preferred)), first_seen[name]),
    )


def _log_command_exception(
    message: str,
    *args: object,
    error: BaseException,
) -> None:
    """记录完整调用栈，但用固定异常正文替换可能含敏感数据的原文。"""

    redacted = traceback.TracebackException(
        type(error),
        RuntimeError("exception details redacted"),
        error.__traceback__,
        capture_locals=False,
    )
    # Traceback 默认会把源码行一起输出；源码行可能包含测试用例或日志正文，
    # 因此保留文件、行号和调用栈，但主动移除源码上下文及原始异常正文。
    for frame in redacted.stack:
        frame._line = ""
    logger.exception(
        f"{message}\n%s",
        *args,
        "".join(redacted.format()),
        exc_info=False,
    )


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """传给 use case 的框架无关命令输入。"""

    command_id: str
    text: str
    parameters: Mapping[str, Any]
    actor: EventActor | None = None
    permission: PermissionName = "user"
    services: Mapping[str, object] = field(default_factory=dict)
    target_user_id: str | None = None
    reply_id: str | None = None
    images: tuple[str, ...] = ()
    matched_prefix: str = "kk"

    def __post_init__(self) -> None:
        """校验入口已经快照的调用者权限，避免 use case 接收未知角色。"""

        if self.permission not in _PERMISSIONS:
            raise ValueError(f"调用者权限无效: {self.permission!r}")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """声明一个已经实现的正则命令。"""

    id: str
    pattern: str
    group: str
    name: str
    description: str
    examples: tuple[str, ...]
    permission: PermissionName
    use_case: CommandUseCase
    mention_policy: MentionPolicy = "ignore"

    def __post_init__(self) -> None:
        """在命令进入 registry 前验证它能安全生成 handler。"""

        if not self.id or not self.id.isidentifier() or keyword.iskeyword(self.id):
            raise ValueError(f"命令 id 必须是 Python 标识符: {self.id!r}")
        if not self.pattern:
            raise ValueError(f"命令 {self.id} 的 pattern 不能为空")
        try:
            compiled = re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"命令 {self.id} 的正则无效: {exc}") from exc
        if self.permission not in _PERMISSIONS:
            raise ValueError(
                f"命令 {self.id} 的 permission 无效: {self.permission!r}; "
                f"允许值为 {sorted(_PERMISSIONS)}",
            )
        if self.mention_policy not in {"ignore", "query", "admin_target"}:
            raise ValueError(
                f"命令 {self.id} 的 mention_policy 无效: {self.mention_policy!r}"
            )
        if not self.group or not self.name or not self.description:
            raise ValueError(f"命令 {self.id} 的 group/name/description 不能为空")
        if not callable(self.use_case) or not (
            inspect.iscoroutinefunction(self.use_case)
            or inspect.isasyncgenfunction(self.use_case)
        ):
            raise ValueError(f"命令 {self.id} 的 use_case 必须是 async callable")

        examples = (
            (self.examples,) if isinstance(self.examples, str) else tuple(self.examples)
        )
        if any(not isinstance(example, str) for example in examples):
            raise ValueError(f"命令 {self.id} 的 examples 必须全部是字符串")
        for example in examples:
            if example and compiled.match(example) is None:
                raise ValueError(
                    f"命令 {self.id} 的示例不匹配 pattern: {example!r}",
                )
        object.__setattr__(self, "examples", examples)


class CommandRegistry:
    """显式命令声明的只读索引。"""

    __slots__ = ("_by_id", "_by_pattern", "_prefixes", "_specs")

    def __init__(
        self,
        specs: Iterable[CommandSpec],
        *,
        prefixes: Iterable[str] = (),
    ) -> None:
        specs_tuple = tuple(specs)
        by_id: dict[str, CommandSpec] = {}
        by_pattern: dict[str, CommandSpec] = {}
        for spec in specs_tuple:
            if not isinstance(spec, CommandSpec):
                raise TypeError("命令模块只能导出 CommandSpec")
            if spec.id in by_id:
                raise ValueError(f"命令 id 重复: {spec.id}")
            if spec.pattern in by_pattern:
                previous = by_pattern[spec.pattern].id
                raise ValueError(
                    f"命令正则重复: {spec.pattern!r} ({previous}, {spec.id})",
                )
            by_id[spec.id] = spec
            by_pattern[spec.pattern] = spec
        self._specs = specs_tuple
        self._by_id = by_id
        self._by_pattern = by_pattern
        self._prefixes = tuple(prefixes)

    @classmethod
    def from_modules(cls, modules: Iterable[ModuleType]) -> CommandRegistry:
        """从显式模块索引加载命令，并拒绝重复加载。"""

        loaded_modules: set[str] = set()
        specs: list[CommandSpec] = []
        for module in modules:
            module_name = module.__name__
            if module_name in loaded_modules:
                raise ValueError(f"命令模块重复加载: {module_name}")
            loaded_modules.add(module_name)
            module_specs = getattr(module, "COMMAND_SPECS", None)
            if module_specs is None:
                raise ValueError(f"命令模块缺少 COMMAND_SPECS: {module_name}")
            specs.extend(module_specs)
        return cls(specs)

    def __iter__(self):
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def prefixes(self) -> tuple[str, ...]:
        """返回构造 registry 时使用的命令前缀，用于帮助示例重绘。"""

        return self._prefixes

    def get(self, command_id: str) -> CommandSpec:
        """按稳定 id 取得命令；未知 id 显式失败。"""

        try:
            return self._by_id[command_id]
        except KeyError as exc:
            raise KeyError(f"未知命令: {command_id}") from exc

    def named_parameters(self, command_id: str) -> tuple[str, ...]:
        """返回指定命令正则中的 named group，按出现顺序排列。"""

        spec = self.get(command_id)
        compiled = re.compile(spec.pattern)
        return tuple(
            name
            for name, _index in sorted(
                compiled.groupindex.items(),
                key=lambda item: item[1],
            )
        )

    def match(self, message: str) -> MatchedCommand | None:
        """根据正则匹配文本命令，返回第一个匹配到的命令和捕获参数。"""
        for spec in self._specs:
            m = re.match(spec.pattern, message)
            if m is not None:
                return MatchedCommand(
                    command=spec,
                    match=m,
                    parameters=m.groupdict(),
                )
        return None

    def visible_specs(
        self, permission: PermissionName = "user"
    ) -> tuple[CommandSpec, ...]:
        """返回当前调用者可见的命令；admin 同时继承 user 命令。"""

        if permission not in _PERMISSIONS:
            raise ValueError(f"调用者权限无效: {permission!r}")
        if permission == "admin":
            return self._specs
        return tuple(spec for spec in self._specs if spec.permission == "user")

    def render_help(self, permission: PermissionName = "user") -> str:
        """从同一 registry 渲染当前已实现且对调用者可见的帮助文本。"""

        grouped: dict[str, list[CommandSpec]] = {}
        for spec in self.visible_specs(permission):
            grouped.setdefault(spec.group, []).append(spec)

        lines = ["可用命令："]
        for group in _ordered_groups(grouped):
            group_specs = grouped[group]
            lines.append("")
            lines.append(f"【{group}】")
            for spec in group_specs:
                examples = " / ".join(spec.examples)
                suffix = f"（示例：{examples}）" if examples else ""
                lines.append(f"{spec.name}：{spec.description}{suffix}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class MatchedCommand:
    command: CommandSpec
    match: re.Match[str]
    parameters: dict[str, Any]


def _prefix_pattern(pattern: str, prefixes: Iterable[str] = (COMMAND_PREFIX,)) -> str:
    """给生产命令统一添加触发前缀，模块内仍保留易读的原始正则。"""

    prefixes_list = list(dict.fromkeys(prefixes))
    has_empty = "" in prefixes_list
    non_empty = [p for p in prefixes_list if p]
    sorted_non_empty = sorted(non_empty, key=lambda s: (-len(s), s))

    if len(sorted_non_empty) == 0:
        prefix_expr = ""
    elif len(sorted_non_empty) == 1:
        escaped = re.escape(sorted_non_empty[0])
        prefix_expr = f"(?:{escaped})?" if has_empty else escaped
    else:
        escaped_parts = [re.escape(p) for p in sorted_non_empty]
        joined = "|".join(escaped_parts)
        prefix_expr = f"(?:{joined})?" if has_empty else f"(?:{joined})"

    if pattern.startswith("^"):
        return f"^{prefix_expr}{pattern[1:]}"
    return f"^{prefix_expr}{pattern}"


def _prefix_spec(
    spec: CommandSpec, prefixes: Iterable[str] = (COMMAND_PREFIX,)
) -> CommandSpec:
    """生成带前缀的公开命令声明，同时保持原 use case 不变。"""

    primary_prefix = next((p for p in prefixes if p), "")
    return CommandSpec(
        id=spec.id,
        pattern=_prefix_pattern(spec.pattern, prefixes=prefixes),
        group=spec.group,
        name=spec.name,
        description=spec.description,
        examples=tuple(f"{primary_prefix}{example}" for example in spec.examples),
        permission=spec.permission,
        use_case=spec.use_case,
        mention_policy=spec.mention_policy,
    )


def load_command_registry(
    modules: Iterable[ModuleType] | None = None,
    prefixes: Iterable[str] | None = None,
    prefix: str | None = None,
) -> CommandRegistry:
    """加载代码声明的命令模块索引。"""

    if prefixes is not None:
        norm_prefixes = tuple(prefixes)
    elif prefix is not None:
        norm_prefixes = (prefix,)
    else:
        norm_prefixes = (COMMAND_PREFIX,)

    if modules is None:
        from ...modules.index import COMMAND_MODULES

        modules = COMMAND_MODULES
    raw_registry = CommandRegistry.from_modules(modules)
    return CommandRegistry(
        (_prefix_spec(spec, prefixes=norm_prefixes) for spec in raw_registry),
        prefixes=norm_prefixes,
    )


def _canonical_symbol_path(callable_: Callable[..., Any]) -> str:
    """将动态 namespace 下的 use case 路径归一为可提交的插件路径。"""

    module = callable_.__module__
    marker = ".src."
    if marker in module:
        module = module[module.index("src.") :]
    return f"{module}.{callable_.__name__}"


def manifest_records(registry: CommandRegistry) -> list[dict[str, Any]]:
    """返回可直接序列化到 ``commands.json`` 的 registry 投影。"""

    return [
        {
            "id": spec.id,
            "pattern": spec.pattern,
            "group": spec.group,
            "name": spec.name,
            "description": spec.description,
            "examples": list(spec.examples),
            "permission": spec.permission,
            "use_case": _canonical_symbol_path(spec.use_case),
        }
        for spec in registry
    ]


def write_command_manifest(path: str | Path, registry: CommandRegistry) -> None:
    """将 registry 生成物写入 manifest 文件。"""

    target = Path(path)
    target.write_text(
        json.dumps(manifest_records(registry), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _permission_filter(permission: PermissionName) -> filter.PermissionType:
    """把插件权限映射为 AstrBot 公开权限过滤器。"""

    if permission == "user":
        return filter.PermissionType.MEMBER
    return filter.PermissionType.ADMIN


def _permission_from_event(event: AstrMessageEvent) -> PermissionName:
    """从 AstrBot 当前事件快照调用者权限，不读取配置或插件自定义角色。"""

    is_admin = getattr(event, "is_admin", None)
    return "admin" if callable(is_admin) and bool(is_admin()) else "user"


async def execute_use_case(
    spec: CommandSpec,
    request: CommandRequest,
    registry: CommandRegistry,
) -> AsyncGenerator[CommandResponse, None]:
    """执行一个已选定的 use case，并归一为框架无关响应 DTO。"""

    result = spec.use_case(request, registry, **request.parameters)
    if inspect.isawaitable(result):
        result = await result

    if inspect.isasyncgen(result):
        async_generator = cast(AsyncGenerator[Any, None], result)
        async for item in async_generator:
            adapted = _adapt_response(item)
            if adapted is not None:
                yield adapted
        return

    adapted = _adapt_response(result)
    if adapted is not None:
        yield adapted


def _adapt_response(result: Any) -> CommandResponse | None:
    """把简单文本便利值转换为 DTO，其余未知类型显式失败。"""

    if result is None:
        return None
    if isinstance(result, str):
        return PlainTextResponse(result)
    if isinstance(result, PlainTextResponse):
        return result
    if isinstance(result, CommandResponse):
        return result
    raise TypeError(f"未知命令响应类型: {type(result).__name__}")


class _DynamicRegexFilter(RegexFilter):
    """根据当前插件实例配置的 command_prefix 动态匹配命令的 RegexFilter。"""

    def __init__(self, fallback_pattern: str, command_id: str) -> None:
        super().__init__(fallback_pattern)
        self.command_id = command_id

    def filter(self, event: AstrMessageEvent, cfg: Any) -> bool:
        from astrbot.core.star.star_manager import star_map

        message = command_text_from_event(event)
        for star_meta in star_map.values():
            if star_meta.name == "astrbot_plugin_dnaby" and star_meta.star_cls:
                runtime = getattr(star_meta.star_cls, "_runtime", None)
                if runtime is not None and hasattr(runtime, "commands"):
                    spec = runtime.commands.get(self.command_id)
                    return bool(re.search(spec.pattern, message))
        return bool(self.regex.search(message))


def _make_handler(
    spec: CommandSpec,
    plugin_module: str,
    handler_name: str,
    fallback_registry: CommandRegistry | None = None,
):
    """生成一个拥有独立正则重匹配逻辑的 async-generator 方法。"""

    default_registry = fallback_registry or CommandRegistry((spec,))

    async def handler(
        self: Any,
        event: AstrMessageEvent,
        **provided_parameters: Any,
    ) -> AsyncGenerator[Any, None]:
        runtime = getattr(self, "_runtime", None)
        active_spec = spec
        try:
            message = command_text_from_event(event)
            active_registry = getattr(runtime, "commands", None)
            active_spec = (
                active_registry.get(spec.id)
                if active_registry is not None
                else spec
            )
            match = re.match(active_spec.pattern, message)
            if match is None:
                return
            parameters = dict(match.groupdict())
            parameters.update(provided_parameters)
            actor = actor_from_event(event)
            configured_prefixes: list[str] = ["kk"]
            if runtime is not None and hasattr(runtime, "settings"):
                display_settings = getattr(runtime.settings, "display", None)
                if display_settings is not None:
                    configured_prefixes = getattr(
                        display_settings,
                        "command_prefixes",
                        [getattr(display_settings, "command_prefix", "kk")],
                    )

            matched_prefix = configured_prefixes[0] if configured_prefixes else "kk"
            sorted_prefixes = sorted(
                [p for p in configured_prefixes if p],
                key=len,
                reverse=True,
            )
            for p in sorted_prefixes:
                if message.startswith(p):
                    matched_prefix = p
                    break
            else:
                if "" in configured_prefixes:
                    matched_prefix = ""

            request = CommandRequest(
                command_id=active_spec.id,
                text=message,
                parameters=parameters,
                actor=actor,
                permission=_permission_from_event(event),
                target_user_id=(
                    target_user_from_event(
                        event,
                        bot_id=actor.bot_id if actor is not None else None,
                    )
                    if active_spec.mention_policy in {"query", "admin_target"}
                    else None
                ),
                reply_id=reply_id_from_event(event),
                services=getattr(runtime, "services", {}),
                images=images_from_event(event),
                matched_prefix=matched_prefix,
            )
            async for result in execute_use_case(
                active_spec,
                request,
                active_registry if active_registry is not None else default_registry,
            ):
                yield runtime.responses.build(event, result)
        except HtmlRenderError as error:
            _log_command_exception(
                "命令 %s 图片渲染失败 kind=%s",
                active_spec.id,
                error.kind,
                error=error,
            )
            yield runtime.responses.build(event, PlainTextResponse(HTML_RENDER_FAILED))
        except Exception as error:  # noqa: BLE001
            _log_command_exception(
                "命令执行失败 command=%s category=%s",
                active_spec.id,
                type(error).__name__,
                error=error,
            )
            yield runtime.responses.build(
                event,
                PlainTextResponse(COMMAND_EXECUTION_FAILED),
            )

    handler.__name__ = handler_name
    handler.__qualname__ = handler_name
    handler.__module__ = plugin_module
    handler.__doc__ = spec.description
    return handler


def install_command_handlers(plugin_cls: type[Any], registry: CommandRegistry) -> None:
    """将 registry 中的每个命令安装为一个带公开 decorator 的 class method。"""
    from astrbot.core.star.filter.regex import RegexFilter
    from astrbot.core.star.register.star_handler import get_handler_or_create

    command_ids = tuple(spec.id for spec in registry)
    installed = getattr(plugin_cls, "__dnaby_command_ids__", None)
    if installed is not None:
        if installed != command_ids:
            raise ValueError("同一个插件类重复安装了不同的命令 registry")
        return

    method_names = {f"handle_{spec.id}" for spec in registry}
    collisions = method_names.intersection(plugin_cls.__dict__)
    if collisions:
        raise ValueError(f"动态命令方法名冲突: {sorted(collisions)}")

    for spec in registry:
        handler_name = f"handle_{spec.id}"
        handler = _make_handler(spec, plugin_cls.__module__, handler_name, registry)
        handler = filter.regex(spec.pattern, desc=spec.description)(handler)
        handler = filter.permission_type(_permission_filter(spec.permission))(handler)
        from astrbot.core.star.star_handler import EventType

        handler_md = get_handler_or_create(handler, EventType.AdapterMessageEvent)
        for idx, f in enumerate(handler_md.event_filters):
            if isinstance(f, RegexFilter):
                handler_md.event_filters[idx] = _DynamicRegexFilter(
                    spec.pattern, spec.id
                )
        setattr(plugin_cls, handler_name, handler)
    plugin_cls.__dnaby_command_ids__ = command_ids


__all__ = [
    "COMMAND_EXECUTION_FAILED",
    "COMMAND_GROUP_ORDER",
    "COMMAND_PREFIX",
    "CommandRegistry",
    "CommandRequest",
    "CommandSpec",
    "CommandUseCase",
    "PermissionName",
    "execute_use_case",
    "install_command_handlers",
    "load_command_registry",
    "manifest_records",
    "write_command_manifest",
]
