"""O18 Agent Tools：安全签到确认、幂等和生命周期契约。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext

from src.entry.agent_tools.lifecycle import AgentToolsLifecycle
from src.entry.agent_tools.signin import AgentSignTool, sign_intent_from_text
from src.entry.agent_tools.tools import AGENT_TOOL_NAMES
from src.entry.response import PlainTextResponse
from src.infrastructure.config import DnabySettings, generate_astrbot_schema
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import CheckinRenderer
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.checkin.contracts import DayAward, SignCalendar, SignStatus
from src.modules.checkin.service import CheckinService
from src.modules.privacy import PrivacyService

UID = "1234567890123"


class FakeEvent:
    """只暴露签到工具需要的 AstrBot 公开事件边界。"""

    unified_msg_origin = "aiocqhttp:group:1"

    def __init__(self, *, text: str = "请签到", message_id: str = "msg-1") -> None:
        self.message_str = text
        self.message_obj = SimpleNamespace(message_id=message_id)
        self._extra: dict[str, object] = {}

    def get_message_str(self) -> str:
        return self.message_str

    def get_sender_id(self) -> str:
        return "event-user"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> str:
        return "group-1"

    def get_extra(self, key: str, default: object = None) -> object:
        return self._extra.get(key, default)

    def set_extra(self, key: str, value: object) -> None:
        self._extra[key] = value


def _agent_wrapper(event: FakeEvent) -> ContextWrapper[AstrAgentContext]:
    agent_context = object.__new__(AstrAgentContext)
    agent_context.context = object()
    agent_context.event = event
    agent_context.extra = {}
    return ContextWrapper(context=agent_context)


class FakeCheckinTransport:
    """只记录调用并返回固定结果，保证本测试不会访问真实签到接口。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def get_sign_calendar(
        self,
        actor: object,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignCalendar:
        self.calls.append(("calendar", uid, credential_user_id))
        return SignCalendar(
            today_signed=False,
            signin_time=0,
            day_awards=(
                DayAward(
                    award_id=1,
                    period_id=1,
                    day_in_period=1,
                    award_name="测试奖励",
                    award_num=1,
                ),
            ),
        )

    async def game_sign(
        self,
        actor: object,
        uid: str,
        award: DayAward,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        self.calls.append(("game_sign", uid, credential_user_id))
        return SignStatus.DONE


async def _checkin_service(
    tmp_path: Path,
) -> tuple[AsyncDatabase, CheckinService, FakeCheckinTransport]:
    database = AsyncDatabase(tmp_path / "agent-sign.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="event-user",
            uid=UID,
            group_id="group-1",
            is_active=True,
        )
    transport = FakeCheckinTransport()
    service = CheckinService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=True),
        CheckinRenderer(
            database.path.parent / "rendered",
            EncyclopediaResourceStore.from_root(database.path.parent / "resources"),
        ),
        community_tasks=(),
    )
    return database, service, transport


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("签到", True),
        ("请帮我签到", True),
        ("确认签到", True),
        ("不要签到", False),
        ("我不想签到", False),
        ("为什么签到", False),
        ("确认不签到", False),
        ("kk签到", True),
        ("签到？", False),
        ("please don't sign", False),
    ),
)
def test_sign_intent_requires_explicit_affirmative_raw_text(
    raw: str,
    expected: bool,
) -> None:
    assert sign_intent_from_text(raw, prefixes=("kk",)) is expected


@pytest.mark.asyncio
async def test_sign_tool_uses_current_active_uid_and_dedupes_same_message(
    tmp_path: Path,
) -> None:
    database, service, transport = await _checkin_service(tmp_path)
    try:
        tool = AgentSignTool(checkin_service=service, command_prefixes=("kk",))
        event = FakeEvent()
        wrapper = _agent_wrapper(event)

        first, second = await asyncio.gather(
            tool.call(wrapper),
            tool.call(wrapper),
        )

        assert first == second
        payload = json.loads(first)
        assert payload["ok"] is True
        assert payload["kind"] == "sign"
        assert payload["data"] == {
            "type": "text",
            "text": "签到状态: ✅ 已完成\n社区任务:\n-----------------------------",
        }
        assert payload["cache"] is None
        assert payload["error"] is None
        assert transport.calls == [
            ("calendar", UID, "event-user"),
            ("game_sign", UID, "event-user"),
        ]
        assert tool.parameters == {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_sign_tool_dedupes_same_event_across_wrapper_instances() -> None:
    class CountingService:
        def __init__(self) -> None:
            self.calls: list[object] = []

        async def manual_sign(self, request: object) -> PlainTextResponse:
            self.calls.append(request)
            return PlainTextResponse("签到完成")

    service = CountingService()
    tool = AgentSignTool(checkin_service=service)
    event = FakeEvent(message_id="same-message")

    first = await tool.call(_agent_wrapper(event))
    second = await tool.call(_agent_wrapper(event))

    assert second == first
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_sign_tool_rejects_model_confirmation_target_and_missing_message_id() -> (
    None
):
    class CountingService:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def manual_sign(self, request: object) -> PlainTextResponse:
            self.calls.append(request)
            return PlainTextResponse("不应执行")

    service = CountingService()
    tool = AgentSignTool(checkin_service=service, command_prefixes=("kk",))

    for arguments in (
        {"confirmed": True},
        {"target_user_id": "attacker"},
        {"uid": "9999999999999"},
    ):
        result = json.loads(await tool.call(_agent_wrapper(FakeEvent()), **arguments))
        assert result["ok"] is False
        assert "原始消息" in result["error"]

    missing_id_event = FakeEvent(message_id="")
    result = json.loads(await tool.call(_agent_wrapper(missing_id_event)))
    assert result["ok"] is False
    assert "消息 ID" in result["error"]
    assert service.calls == []


@pytest.mark.asyncio
async def test_sign_tool_rejects_negative_or_ambiguous_raw_message() -> None:
    class CountingService:
        async def manual_sign(self, request: object) -> PlainTextResponse:
            raise AssertionError("否定消息不应触发签到")

    tool = AgentSignTool(checkin_service=CountingService(), command_prefixes=("kk",))
    for text in ("不要签到", "是否签到", "为什么签到"):
        payload = json.loads(
            await tool.call(_agent_wrapper(FakeEvent(text=text))),
        )
        assert payload["ok"] is False
        assert "确认" in payload["error"]


class FakeToolContext:
    """记录官方 Context 工具注册/注销调用。"""

    def __init__(self) -> None:
        self.add_calls: list[tuple[str, ...]] = []
        self.unregister_calls: list[str] = []
        self.web_calls: list[tuple[object, ...]] = []

    def register_web_api(self, *args: object) -> None:
        self.web_calls.append(args)

    def add_llm_tools(self, *tools: object) -> None:
        self.add_calls.append(tuple(getattr(tool, "name", "") for tool in tools))

    def unregister_llm_tool(self, name: str) -> None:
        self.unregister_calls.append(name)


def _lifecycle_services() -> dict[str, object]:
    return {
        "player_service": object(),
        "encyclopedia_service": object(),
        "notices_service": object(),
        "checkin_service": object(),
    }


@pytest.mark.asyncio
async def test_agent_tools_lifecycle_total_switch_and_hot_reload_are_idempotent() -> (
    None
):
    context = FakeToolContext()
    lifecycle = AgentToolsLifecycle(
        context=context,
        enabled=True,
        services=_lifecycle_services(),
        command_prefixes=("kk",),
    )
    expected_names = (*AGENT_TOOL_NAMES, "dnaby_sign")

    await lifecycle.start()
    await lifecycle.start()
    assert lifecycle.started is True
    assert lifecycle.registered_names == expected_names
    assert context.add_calls == [expected_names]

    await lifecycle.stop()
    await lifecycle.stop()
    assert lifecycle.started is False
    assert context.unregister_calls == list(expected_names)

    await lifecycle.start()
    assert context.add_calls == [expected_names, expected_names]
    await lifecycle.stop()
    assert context.unregister_calls == [*expected_names, *expected_names]


@pytest.mark.asyncio
async def test_agent_tools_disabled_registers_nothing() -> None:
    context = FakeToolContext()
    lifecycle = AgentToolsLifecycle(
        context=context,
        enabled=False,
        services=_lifecycle_services(),
    )

    await lifecycle.start()
    await lifecycle.stop()

    assert lifecycle.started is False
    assert lifecycle.registered_names == ()
    assert context.add_calls == []
    assert context.unregister_calls == []


def test_agent_tools_config_has_one_explicit_total_switch() -> None:
    assert DnabySettings.from_config({}).agent_tools.enabled is False
    assert (
        DnabySettings.from_config(
            {"agent_tools": {"enabled": True}},
        ).agent_tools.enabled
        is True
    )
    schema = generate_astrbot_schema()
    assert schema["ai"]["items"]["agent_tools_enabled"]["type"] == "bool"
    assert schema["ai"]["items"]["agent_tools_enabled"]["default"] is False


@pytest.mark.asyncio
async def test_runtime_initialize_and_terminate_register_agent_tools_once(
    tmp_path: Path,
) -> None:
    from src.bootstrap import build_runtime

    context = FakeToolContext()
    runtime = build_runtime(
        context,
        {"agent_tools": {"enabled": True}, "login": {"port": 0}},
        database=AsyncDatabase(tmp_path / "runtime.sqlite3"),
    )
    expected_names = (*AGENT_TOOL_NAMES, "dnaby_sign")
    try:
        await runtime.initialize()
        await runtime.initialize()
        assert context.add_calls == [expected_names]

        await runtime.terminate()
        await runtime.terminate()
        assert context.unregister_calls == list(expected_names)
    finally:
        await runtime.terminate()
