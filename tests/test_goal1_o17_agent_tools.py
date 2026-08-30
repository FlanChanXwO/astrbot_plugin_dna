"""O17 纯查询 Agent Tools、JSON envelope 与图片发送 Red 契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from astrbot.api.message_components import Image
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import BaseModel

from src.entry.agent_tools.tools import (
    AGENT_TOOL_NAMES,
    _json_value,
    build_agent_tools,
    register_agent_tools,
)
from src.entry.event import EventActor
from src.entry.response import ImageResponse, PlainTextResponse
from src.modules.agent_tools.queries import build_query_catalog


class FakeEvent:
    """只暴露 O17 adapter 使用的公开事件方法。"""

    unified_msg_origin = "aiocqhttp:group:1"

    def __init__(self, *, send_error: Exception | None = None) -> None:
        self.sent: list[object] = []
        self.send_error = send_error

    def get_sender_id(self) -> str:
        return "event-user"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> str:
        return "group-1"

    async def send(self, message: object) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)


def _agent_wrapper(event: FakeEvent | None = None) -> ContextWrapper[AstrAgentContext]:
    # 绕过官方 dataclass 对真实框架实例的构造校验，仍通过真实 event 字段取身份。
    agent_context = object.__new__(AstrAgentContext)
    agent_context.context = object()
    agent_context.event = event if event is not None else FakeEvent()
    agent_context.extra = {}
    return ContextWrapper(context=agent_context)


class FakePlayerService:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path
        self.requests: list[object] = []

    async def role_overview(self, request):
        self.requests.append(request)
        return ImageResponse(str(self.image_path), temporary=True)

    async def role_detail(self, request):
        self.requests.append(request)
        return PlainTextResponse("角色详情")

    async def original_image(self, request):
        self.requests.append(request)
        return PlainTextResponse("原图")


class FakeEncyclopediaService:
    async def stamina(self, _request):
        return PlainTextResponse("体力")

    async def weekly_report(self, _request):
        return PlainTextResponse("周报")

    async def calendar(self, _request):
        return PlainTextResponse("日历")

    async def wiki(self, _request):
        return PlainTextResponse("图鉴")

    async def guide(self, _request):
        return PlainTextResponse("攻略")

    async def codes(self, _request):
        return PlainTextResponse("兑换码")

    async def alias_all_list(self, _request):
        return PlainTextResponse("目录")


class FakeNoticesService:
    async def mh(self, _request):
        return PlainTextResponse("密函")

    async def mh_list(self, _request):
        return PlainTextResponse("密函列表")

    async def mh_subscriptions(self, _request):
        return PlainTextResponse("我的订阅")

    async def ann(self, _request):
        return PlainTextResponse("公告")


class FakeCheckinService:
    async def sign_calendar(self, _request):
        return PlainTextResponse("签到日历")


class PrivatePayload(BaseModel):
    path: Path
    binary: bytes


class FakeToolContext:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add_llm_tools(self, *tools: object) -> None:
        self.added.extend(tools)


def _services(player: FakePlayerService) -> dict[str, object]:
    return {
        "player_service": player,
        "encyclopedia_service": FakeEncyclopediaService(),
        "notices_service": FakeNoticesService(),
        "checkin_service": FakeCheckinService(),
    }


def test_register_agent_tools_uses_official_context_registration(
    tmp_path: Path,
) -> None:
    context = FakeToolContext()
    registered = register_agent_tools(
        context,
        services=_services(FakePlayerService(tmp_path / "role.png")),
    )

    assert [tool.name for tool in registered] == list(AGENT_TOOL_NAMES)
    assert context.added == registered


def test_json_serializer_rejects_paths_and_binary_inside_pydantic_models() -> None:
    with pytest.raises(TypeError, match="本地数据"):
        _json_value(PrivatePayload(path=Path("/private/token"), binary=b"secret"))


def test_build_agent_tools_exposes_only_approved_queries_and_no_identity_args(
    tmp_path: Path,
) -> None:
    tools = build_agent_tools(
        services=_services(FakePlayerService(tmp_path / "role.png")),
    )

    assert [tool.name for tool in tools] == list(AGENT_TOOL_NAMES)
    forbidden = {
        "user_id",
        "target_user_id",
        "bot_id",
        "credential_user_id",
        "uid",
    }
    for tool in tools:
        assert not forbidden.intersection(tool.parameters["properties"])


def test_query_catalog_contains_all_approved_read_only_queries(
    tmp_path: Path,
) -> None:
    catalog = build_query_catalog(
        player_service=FakePlayerService(tmp_path / "role.png"),
        encyclopedia_service=FakeEncyclopediaService(),
        notices_service=FakeNoticesService(),
        checkin_service=FakeCheckinService(),
    )

    assert {
        "player_overview",
        "player_role_detail",
        "stamina",
        "weekly_report_current",
        "weekly_report_last",
        "calendar",
        "wiki",
        "guide",
        "codes",
        "role_directory",
        "mh",
        "mh_list",
        "mh_subscriptions",
        "announcement_list",
        "announcement_detail",
        "sign_calendar",
    } == set(catalog.names)


@pytest.mark.asyncio
async def test_default_agent_result_is_json_without_local_image_path(tmp_path: Path) -> None:
    image_path = tmp_path / "private-rendered.png"
    image_path.write_bytes(b"not sent in model context")
    event = FakeEvent()
    tool = next(
        tool
        for tool in build_agent_tools(services=_services(FakePlayerService(image_path)))
        if tool.name == "dnaby_player_overview"
    )

    payload = json.loads(await tool.call(_agent_wrapper(event)))

    assert set(payload) == {"ok", "kind", "data", "cache", "error"}
    assert payload["ok"] is True
    assert payload["data"] == {
        "type": "image",
        "available": True,
        "incomplete": False,
    }
    assert str(image_path) not in json.dumps(payload, ensure_ascii=False)
    assert event.sent == []


@pytest.mark.asyncio
async def test_send_image_sends_to_current_event_and_returns_only_status(tmp_path: Path) -> None:
    image_path = tmp_path / "private-rendered.png"
    image_path.write_bytes(b"not sent in model context")
    event = FakeEvent()
    tool = next(
        tool
        for tool in build_agent_tools(services=_services(FakePlayerService(image_path)))
        if tool.name == "dnaby_player_overview"
    )

    payload = json.loads(await tool.call(_agent_wrapper(event), send_image=True))

    assert payload == {
        "ok": True,
        "kind": "player_overview",
        "data": {"image_sent": True},
        "cache": None,
        "error": None,
    }
    assert len(event.sent) == 1
    assert isinstance(event.sent[0].chain[0], Image)
    assert str(image_path) not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_send_image_failure_is_explicit_and_never_success(tmp_path: Path) -> None:
    image_path = tmp_path / "private-rendered.png"
    image_path.write_bytes(b"not sent in model context")
    event = FakeEvent(send_error=RuntimeError(str(image_path)))
    tool = next(
        tool
        for tool in build_agent_tools(services=_services(FakePlayerService(image_path)))
        if tool.name == "dnaby_player_overview"
    )

    payload = json.loads(await tool.call(_agent_wrapper(event), send_image=True))

    assert payload["ok"] is False
    assert payload["data"] == {"image_sent": False}
    assert payload["error"]
    assert str(image_path) not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_agent_query_maps_model_parameters_to_typed_domain_request(
    tmp_path: Path,
) -> None:
    player = FakePlayerService(tmp_path / "role.png")
    tool = next(
        tool
        for tool in build_agent_tools(services=_services(player))
        if tool.name == "dnaby_player_role_detail"
    )

    payload = json.loads(
        await tool.call(
            _agent_wrapper(),
            char_name="角色甲",
            weapon_name_1="武器乙",
        )
    )

    assert payload["ok"] is True
    request = player.requests[0]
    assert request.actor == EventActor(
        user_id="event-user",
        bot_id="bot-1",
        group_id="group-1",
        unified_msg_origin="aiocqhttp:group:1",
    )
    assert request.parameters == {
        "char_name": "角色甲",
        "weapon_name_1": "武器乙",
    }


@pytest.mark.asyncio
async def test_identity_override_is_a_structured_tool_failure(tmp_path: Path) -> None:
    tool = next(
        tool
        for tool in build_agent_tools(
            services=_services(FakePlayerService(tmp_path / "role.png"))
        )
        if tool.name == "dnaby_player_overview"
    )

    payload = json.loads(await tool.call(_agent_wrapper(), user_id="attacker"))

    assert payload["ok"] is False
    assert payload["kind"] == "player_overview"
    assert "身份参数" in payload["error"]


@pytest.mark.asyncio
async def test_non_image_tool_does_not_accept_send_image(tmp_path: Path) -> None:
    tool = next(
        tool
        for tool in build_agent_tools(
            services=_services(FakePlayerService(tmp_path / "role.png"))
        )
        if tool.name == "dnaby_codes"
    )

    assert "send_image" not in tool.parameters["properties"]
    payload = json.loads(await tool.call(_agent_wrapper(), send_image=True))

    assert payload["ok"] is False
    assert "send_image" in payload["error"]
