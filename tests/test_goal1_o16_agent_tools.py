"""O16 Agent Tools 上下文、typed contract 与共享查询 Red 契约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext

from src.entry.agent_tools.context import AgentContextError, agent_request_from_context
from src.entry.commands import CommandRequest
from src.entry.event import EventActor
from src.entry.response import PlainTextResponse
from src.modules.agent_tools.contracts import AgentQueryRequest, AgentQueryResult
from src.modules.agent_tools.queries import build_query_catalog


class FakeEvent:
    """只暴露 AstrBot Agent adapter 需要的公开事件方法。"""

    unified_msg_origin = "aiocqhttp:group:1"

    def __init__(self, *, user_id: str = "event-user") -> None:
        self._user_id = user_id

    def get_sender_id(self) -> str:
        return self._user_id

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> str:
        return "group-1"


def _agent_wrapper(event: object | None = None) -> ContextWrapper[AstrAgentContext]:
    # 只绕过官方 dataclass 对真实框架实例的构造校验，适配器仍读取真实的 event 字段。
    agent_context = object.__new__(AstrAgentContext)
    agent_context.context = object()
    agent_context.event = event if event is not None else FakeEvent()
    agent_context.extra = {}
    return ContextWrapper(context=agent_context)


def test_agent_request_reads_identity_only_from_astr_agent_context_event() -> None:
    request = agent_request_from_context(
        _agent_wrapper(),
        parameters={"char_name": "角色甲"},
    )

    assert request.actor == EventActor(
        user_id="event-user",
        bot_id="bot-1",
        group_id="group-1",
        unified_msg_origin="aiocqhttp:group:1",
    )
    assert request.target_user_id is None
    assert request.parameters == {"char_name": "角色甲"}


def test_agent_request_rejects_model_supplied_identity_parameters() -> None:
    with pytest.raises(ValueError, match="身份参数"):
        agent_request_from_context(
            _agent_wrapper(),
            parameters={"user_id": "attacker"},
        )


def test_agent_request_requires_a_valid_astrbot_event_actor() -> None:
    with pytest.raises(AgentContextError, match="事件身份"):
        agent_request_from_context(_agent_wrapper(object()))


def test_agent_query_result_has_stable_typed_envelope() -> None:
    result = AgentQueryResult.success(
        kind="stamina",
        data={"value": 10},
        cache="fresh",
    )

    assert result.to_dict() == {
        "ok": True,
        "kind": "stamina",
        "data": {"value": 10},
        "cache": "fresh",
        "error": None,
    }
    with pytest.raises(ValueError, match="成功响应不得携带 error"):
        AgentQueryResult(ok=True, kind="stamina", error="伪造错误")
    with pytest.raises(ValueError, match="失败响应必须携带 error"):
        AgentQueryResult(ok=False, kind="stamina")


@pytest.mark.asyncio
async def test_chat_and_agent_route_to_the_same_domain_query(monkeypatch) -> None:
    from src.modules.agent_tools import queries
    from src.modules.encyclopedia.commands import stamina_use_case

    class FakeEncyclopediaService:
        async def stamina(self, _request):
            return PlainTextResponse("unused")

        async def weekly_report(self, _request):
            return PlainTextResponse("unused")

        async def calendar(self, _request):
            return PlainTextResponse("unused")

        async def wiki(self, _request):
            return PlainTextResponse("unused")

        async def guide(self, _request):
            return PlainTextResponse("unused")

        async def codes(self, _request):
            return PlainTextResponse("unused")

        async def alias_list(self, _request):
            return PlainTextResponse("unused")

        async def alias_all_list(self, _request):
            return PlainTextResponse("unused")

    service = FakeEncyclopediaService()
    actor = EventActor(user_id="event-user", bot_id="bot-1")
    calls: list[tuple[object, AgentQueryRequest]] = []

    async def shared_query(service_arg, request: AgentQueryRequest):
        calls.append((service_arg, request))
        return PlainTextResponse("shared")

    monkeypatch.setattr(queries, "stamina_query", shared_query)
    chat_request = CommandRequest(
        command_id="stamina",
        text="体力",
        parameters={},
        actor=actor,
        services={"encyclopedia_service": service},
    )

    chat_response = await stamina_use_case(chat_request, object())
    agent_result = await build_query_catalog(
        encyclopedia_service=service,
    ).execute(
        "stamina",
        AgentQueryRequest(actor=actor),
    )

    assert chat_response == PlainTextResponse("shared")
    assert agent_result.data == PlainTextResponse("shared")
    assert len(calls) == 2
    assert all(call[0] is service for call in calls)
    assert all(call[1].actor == actor for call in calls)


@pytest.mark.asyncio
async def test_query_catalog_reports_unknown_query_explicitly() -> None:
    catalog = build_query_catalog(encyclopedia_service=SimpleNamespace())

    result = await catalog.execute(
        "missing",
        AgentQueryRequest(actor=EventActor(user_id="u", bot_id="b")),
    )

    assert result.ok is False
    assert result.kind == "unsupported"
