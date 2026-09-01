"""Goal 4 / Task 14：查询命令接收 At，写命令隔离目标。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import At, Plain

from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    install_command_handlers,
)
from src.entry.response import ResponseFactory


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
