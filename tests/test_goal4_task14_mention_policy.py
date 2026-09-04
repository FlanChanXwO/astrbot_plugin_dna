"""Goal 4 / Task 14：查询命令接收 At，写命令隔离目标。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import At, Plain
from astrbot.core.star.filter.regex import RegexFilter
from astrbot.core.star.star_handler import star_handlers_registry

from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    install_command_handlers,
)
from src.entry.event import mention_target_from_event
from src.entry.response import ResponseFactory
from src.utils.msgs.notify import MENTION_TARGET_UNRESOLVED


def _spec(policy: str) -> CommandSpec:
    async def use_case(
        request: CommandRequest, _registry: CommandRegistry, **_params: object
    ):
        return request.target_user_id or "none"

    return CommandSpec(
        id=f"policy_{policy}",
        pattern=r"^查询$",
        group="测试",
        name="策略",
        description="策略",
        examples=("查询",),
        permission="user",
        use_case=use_case,
        mention_policy=policy,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "expected"),
    (("query", "target"), ("ignore", "none"), ("admin_target", "target")),
)
async def test_generated_handler_applies_mention_policy(
    policy: str, expected: str
) -> None:
    spec = _spec(policy)
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=lambda: [At(qq="target"), Plain("查询")],
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )
    result = [item async for item in getattr(Plugin(), f"handle_{spec.id}")(event)]
    assert result == [expected]


def test_production_query_and_write_commands_have_explicit_mention_policy() -> None:
    from src.entry.commands import load_command_registry

    registry = load_command_registry()
    query_ids = {
        "role_info_card",
        "role_detail_card",
        "role_original_image",
        "stamina",
        "client_update",
        "weekly_report_current",
        "weekly_report_last",
        "calendar",
        "dna_wiki",
        "dna_guide",
        "dna_code",
        "alias_list",
        "alias_all_list",
        "mh",
        "mh_list",
        "ann",
        "sign_calendar",
    }
    admin_target_ids = {
        "privacy_enable_peek_admin",
        "privacy_disable_peek_admin",
        "privacy_enable_uid_hidden_admin",
        "privacy_disable_uid_hidden_admin",
    }
    for command_id in query_ids:
        assert registry.get(command_id).mention_policy == "query"
    for command_id in admin_target_ids:
        assert registry.get(command_id).mention_policy == "admin_target"
    for spec in registry:
        if spec.id not in query_ids | admin_target_ids:
            assert spec.mention_policy == "ignore"


@pytest.mark.asyncio
async def test_query_command_supports_inline_mention_tokens() -> None:
    """适配器把 @ 目标留在纯文本标记中时仍应解析目标。"""

    spec = _spec("query")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=lambda: [Plain("查询<@!target>")],
        get_message_str=lambda: "查询<@!target>",
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )

    result = [item async for item in Plugin().handle_policy_query(event)]

    assert result == ["target"]


@pytest.mark.asyncio
async def test_query_command_recovers_raw_onebot_mention_segment() -> None:
    """OneBot 适配器丢失 At 组件时，仍从公开原始消息段恢复目标。"""

    spec = _spec("query")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=lambda: [Plain("查询")],
        get_message_str=lambda: "查询",
        message_obj=SimpleNamespace(
            raw_message={
                "self_id": "bot",
                "message": [
                    {"type": "at", "data": {"qq": "target"}},
                    {"type": "text", "data": {"text": "查询"}},
                ],
            }
        ),
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )

    result = [item async for item in Plugin().handle_policy_query(event)]

    assert result == ["target"]


@pytest.mark.asyncio
async def test_query_command_reports_unresolved_mention() -> None:
    """消息链有损时不能静默把带 @ 的查询改成查询调用者。"""

    spec = _spec("query")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=lambda: [At(qq=""), Plain("查询")],
        get_message_str=lambda: "@查询",
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )

    result = [item async for item in Plugin().handle_policy_query(event)]

    assert result == [MENTION_TARGET_UNRESOLVED]


def test_mention_command_priority_precedes_generic_wake_listener() -> None:
    """带 @ 的正则命令必须先于 WakePro 的通用唤醒监听器执行。"""

    spec = _spec("query")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14_priority"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    metadata = star_handlers_registry.get_handler_by_full_name(
        "tests.goal4_task14_priority_handle_policy_query",
    )

    assert metadata is not None
    # WakePro 的通用监听器使用 priority=99999；查询命令必须排在它之前，
    # 否则它会把“@别人”的消息当成非唤醒消息并提前 stop_event。
    assert metadata.extras_configs.get("priority", 0) > 99999


@pytest.mark.asyncio
async def test_mention_command_stops_later_handlers_after_response() -> None:
    """查询命令产出响应后要阻止后续 handler 清掉该响应。"""

    spec = _spec("query")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14_stop"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    stopped = False

    def stop_event() -> None:
        nonlocal stopped
        stopped = True

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=lambda: [Plain("查询"), At(qq="target")],
        get_message_str=lambda: "查询 @target",
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
        stop_event=stop_event,
    )

    result = [item async for item in Plugin().handle_policy_query(event)]

    assert result == ["target"]
    assert stopped is True


@pytest.mark.asyncio
async def test_query_command_handles_onebot_display_text_without_message_chain() -> None:
    """OneBot 只回传展示文本时，命令仍应解析目标并执行。"""

    async def use_case(
        request: CommandRequest, _registry: CommandRegistry, **_params: object
    ):
        return request.target_user_id or "none"

    spec = CommandSpec(
        id="onebot_display_query",
        pattern=r"^kk卡片$",
        group="测试",
        name="策略",
        description="策略",
        examples=("kk卡片",),
        permission="user",
        use_case=use_case,
        mention_policy="query",
    )
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14_onebot_display"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=list,
        get_message_str=lambda: "kk卡片 @雾理魔理莎(1957719129)",
        message_obj=SimpleNamespace(
            raw_message={
                "message": [
                    {"type": "text", "data": {"text": "kk卡片"}},
                    {"type": "at", "data": {"qq": "1957719129"}},
                ],
            }
        ),
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )

    result = [item async for item in Plugin().handle_onebot_display_query(event)]

    assert result == ["1957719129"]


def test_registered_filter_accepts_onebot_display_mention_suffix() -> None:
    """注册到 AstrBot 的兜底正则也要接受 OneBot 的 @ 展示文本。"""

    spec = _spec("admin_target")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14_onebot_filter"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    metadata = star_handlers_registry.get_handler_by_full_name(
        "tests.goal4_task14_onebot_filter_handle_policy_admin_target",
    )
    assert metadata is not None
    regex_filters = [
        item for item in metadata.event_filters if isinstance(item, RegexFilter)
    ]
    assert len(regex_filters) == 1
    for message in (
        "查询 @雾理魔理莎(1957719129)",
        "查询@雾理魔理莎",
    ):
        assert regex_filters[0].regex.search(message) is not None


def test_mention_target_recovers_onebot_display_id_without_message_segment() -> None:
    """只有 OneBot 展示文本时，也不能静默退回调用者。"""

    event = SimpleNamespace(
        get_messages=lambda: [Plain("kk卡片 @雾理魔理莎(1957719129)")],
        get_message_str=lambda: "kk卡片 @雾理魔理莎(1957719129)",
    )

    result = mention_target_from_event(event)

    assert result.target_user_id == "1957719129"
    assert result.has_unresolved_mention is False


@pytest.mark.asyncio
async def test_query_command_reports_onebot_display_name_without_id() -> None:
    """只有 OneBot 展示的昵称、没有可用 QQ 号时必须明确提示。"""

    spec = _spec("query")
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task14_onebot_unresolved"
        _runtime = SimpleNamespace(
            commands=registry,
            services={},
            responses=ResponseFactory(),
        )

    install_command_handlers(Plugin, registry)
    event = SimpleNamespace(
        get_messages=lambda: [Plain("查询@雾理魔理莎")],
        get_message_str=lambda: "查询@雾理魔理莎",
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )

    result = [item async for item in Plugin().handle_policy_query(event)]

    assert result == [MENTION_TARGET_UNRESOLVED]
