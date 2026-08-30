"""聊天命令与 Agent Tools 共享的领域查询入口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ...entry.response import CommandResponse
from ..checkin.contracts import CheckinCommandRequest
from ..encyclopedia.contracts import EncyclopediaRequest
from ..notices.contracts import NoticeRequest
from ..player.contracts import PlayerCommandRequest
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
        if isinstance(data, AgentQueryResult):
            return data
        return AgentQueryResult.success(kind=normalized_name, data=data)


async def stamina_query(
    service: Any,
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


def _player_request(request: AgentQueryRequest) -> PlayerCommandRequest:
    return PlayerCommandRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters),
    )


def _encyclopedia_request(
    request: AgentQueryRequest,
    *,
    parameters: Mapping[str, Any] | None = None,
    text: str | None = None,
) -> EncyclopediaRequest:
    return EncyclopediaRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters if parameters is None else parameters),
        text=request.text if text is None else text,
    )


def _notice_request(
    request: AgentQueryRequest,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> NoticeRequest:
    return NoticeRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters if parameters is None else parameters),
        text=request.text,
        matched_prefix="kk",
    )


def _checkin_request(request: AgentQueryRequest) -> CheckinCommandRequest:
    return CheckinCommandRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters),
        text=request.text,
    )


async def player_overview_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    """复用玩家角色/武器概览 service。"""

    return await service.role_overview(_player_request(request))


async def player_role_detail_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    """复用玩家角色详情 service。"""

    return await service.role_detail(_player_request(request))


async def weekly_report_query(
    service: Any,
    request: AgentQueryRequest,
    *,
    week_type: int,
) -> CommandResponse:
    parameters = dict(request.parameters)
    parameters["week_type"] = week_type
    return await service.weekly_report(
        _encyclopedia_request(request, parameters=parameters),
    )


async def weekly_report_current_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await weekly_report_query(service, request, week_type=1)


async def weekly_report_last_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await weekly_report_query(service, request, week_type=2)


async def calendar_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.calendar(_encyclopedia_request(request))


async def wiki_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.wiki(_encyclopedia_request(request))


async def guide_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.guide(_encyclopedia_request(request))


async def codes_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.codes(_encyclopedia_request(request))


async def role_directory_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    directory_type = str(request.parameters.get("directory_type", "characters")).strip().lower()
    if directory_type not in {"characters", "weapons"}:
        raise ValueError("directory_type 只支持 characters 或 weapons")
    text = "武器列表" if directory_type == "weapons" else "角色列表"
    return await service.alias_all_list(_encyclopedia_request(request, text=text))


async def mh_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.mh(_notice_request(request))


async def mh_list_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.mh_list(_notice_request(request))


async def mh_subscriptions_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.mh_subscriptions(_notice_request(request))


async def announcement_list_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.ann(_notice_request(request, parameters={}))


async def announcement_detail_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    index = str(request.parameters.get("index", "")).strip()
    if not index:
        raise ValueError("公告详情必须提供 index")
    return await service.ann(
        _notice_request(request, parameters={"index": index}),
    )


async def sign_calendar_query(service: Any, request: AgentQueryRequest) -> CommandResponse:
    return await service.sign_calendar(_checkin_request(request))


def _bind_query(
    service: Any,
    query: Callable[[Any, AgentQueryRequest], Awaitable[Any]],
) -> QueryHandler:
    async def bound(request: AgentQueryRequest) -> Any:
        return await query(service, request)

    return bound


def build_query_catalog(
    *,
    player_service: Any | None = None,
    encyclopedia_service: Any | None = None,
    notices_service: Any | None = None,
    checkin_service: Any | None = None,
) -> AgentQueryCatalog:
    """构造已批准的只读查询 catalog；仅为已注入的领域 service 建立入口。"""

    handlers: dict[str, QueryHandler] = {}
    if player_service is not None:
        handlers.update(
            {
                "player_overview": _bind_query(player_service, player_overview_query),
                "player_role_detail": _bind_query(
                    player_service,
                    player_role_detail_query,
                ),
            }
        )
    if encyclopedia_service is not None:
        async def query_stamina(request: AgentQueryRequest) -> CommandResponse:
            return await stamina_query(encyclopedia_service, request)

        handlers.update(
            {
                "stamina": query_stamina,
                "weekly_report_current": _bind_query(
                    encyclopedia_service,
                    weekly_report_current_query,
                ),
                "weekly_report_last": _bind_query(
                    encyclopedia_service,
                    weekly_report_last_query,
                ),
                "calendar": _bind_query(encyclopedia_service, calendar_query),
                "wiki": _bind_query(encyclopedia_service, wiki_query),
                "guide": _bind_query(encyclopedia_service, guide_query),
                "codes": _bind_query(encyclopedia_service, codes_query),
                "role_directory": _bind_query(
                    encyclopedia_service,
                    role_directory_query,
                ),
            }
        )
    if notices_service is not None:
        handlers.update(
            {
                "mh": _bind_query(notices_service, mh_query),
                "mh_list": _bind_query(notices_service, mh_list_query),
                "mh_subscriptions": _bind_query(
                    notices_service,
                    mh_subscriptions_query,
                ),
                "announcement_list": _bind_query(
                    notices_service,
                    announcement_list_query,
                ),
                "announcement_detail": _bind_query(
                    notices_service,
                    announcement_detail_query,
                ),
            }
        )
    if checkin_service is not None:
        handlers["sign_calendar"] = _bind_query(
            checkin_service,
            sign_calendar_query,
        )
    return AgentQueryCatalog(handlers)


__all__ = [
    "AgentQueryCatalog",
    "announcement_detail_query",
    "announcement_list_query",
    "build_query_catalog",
    "calendar_query",
    "codes_query",
    "guide_query",
    "mh_list_query",
    "mh_query",
    "mh_subscriptions_query",
    "player_overview_query",
    "player_role_detail_query",
    "role_directory_query",
    "sign_calendar_query",
    "stamina_query",
    "weekly_report_current_query",
    "weekly_report_last_query",
    "wiki_query",
]
