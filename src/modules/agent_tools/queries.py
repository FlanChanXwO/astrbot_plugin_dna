"""聊天命令与 Agent Tools 共享的领域查询入口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ...entry.response import CommandResponse
from ..encyclopedia.contracts import EncyclopediaRequest
from ..encyclopedia.service import EncyclopediaService
from .contracts import AgentQueryRequest, AgentQueryResult

QueryHandler = Callable[[AgentQueryRequest], Awaitable[Any]]


class AgentQueryCatalog:
    """按显式名称调用已批准的只读领域查询。"""

    def __init__(self, handlers: Mapping[str, QueryHandler]) -> None:
        normalized: dict[str, QueryHandler] = {}
        for name, handler in handlers.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Agent 查询名称不能为空")
            if not callable(handler):
                raise TypeError(f"Agent 查询 {name!r} 必须是 callable")
            normalized_name = name.strip()
            if normalized_name in normalized:
                raise ValueError(f"Agent 查询名称重复: {normalized_name}")
            normalized[normalized_name] = handler
        self._handlers = normalized

    @property
    def names(self) -> tuple[str, ...]:
        """返回稳定的查询名称顺序。"""

        return tuple(self._handlers)

    async def execute(
        self,
        name: str,
        request: AgentQueryRequest,
    ) -> AgentQueryResult[Any]:
        """执行查询；未知名称返回明确的 unsupported 结果。"""

        if not isinstance(request, AgentQueryRequest):
            raise TypeError("Agent 查询 request 类型无效")
        normalized_name = name.strip() if isinstance(name, str) else ""
        handler = self._handlers.get(normalized_name)
        if handler is None:
            return AgentQueryResult.failure(
                kind="unsupported",
                error=f"不支持的查询: {normalized_name or '<empty>'}",
            )
        data = await handler(request)
        return AgentQueryResult.success(kind=normalized_name, data=data)


async def stamina_query(
    service: EncyclopediaService,
    request: AgentQueryRequest,
) -> CommandResponse:
    """调用现有便笺领域 service；聊天和 Agent 均复用此函数。"""

    return await service.stamina(
        EncyclopediaRequest(
            actor=request.actor,
            target_user_id=request.target_user_id,
            parameters=dict(request.parameters),
            text=request.text,
        ),
    )


def build_query_catalog(*, encyclopedia_service: EncyclopediaService) -> AgentQueryCatalog:
    """构造当前阶段已批准的只读查询 catalog。"""

    async def query_stamina(request: AgentQueryRequest) -> CommandResponse:
        return await stamina_query(encyclopedia_service, request)

    return AgentQueryCatalog({"stamina": query_stamina})


__all__ = [
    "AgentQueryCatalog",
    "build_query_catalog",
    "stamina_query",
]
