"""Task 11 隐私命令的 registry、权限和 AstrBot @ 目标边界测试。"""

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import At, AtAll
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.event import EventActor, target_user_from_event
from src.entry.response import PlainTextResponse, ResponseFactory


class Event:
    """只实现命令 handler 所需的 AstrBot 公开事件方法。"""

    def __init__(self, message: str, *, target: str | None = "target-1") -> None:
        self.message = message
        self.target = target

    def get_message_str(self) -> str:
        return self.message

    def get_sender_id(self) -> str:
        return "admin-1"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> str:
        return "group-1"

    def get_messages(self) -> list[object]:
        return [] if self.target is None else [At(qq=self.target)]

    def plain_result(self, text: str) -> str:
        return text


class FakePrivacyService:
    """观察命令层是否传递 actor 与解析后的 @ 目标。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, EventActor, str | None]] = []

    async def set_target_peek(
        self,
        actor: EventActor,
        target_user_id: str | None,
        allow_peek: bool,
    ) -> PlainTextResponse:
        self.calls.append((f"peek:{allow_peek}", actor, target_user_id))
        return PlainTextResponse("命令边界已传递")


def test_registry_exposes_all_privacy_commands_with_admin_boundary() -> None:
    """个人命令是 member，指定/全体命令全部声明为 admin。"""
    registry = load_command_registry()
    privacy = [spec for spec in registry if spec.id.startswith("privacy_")]

    assert len(privacy) == 14
    assert {
        spec.id for spec in privacy if spec.permission == "user"
    } == {
        "privacy_enable_peek_personal",
        "privacy_disable_peek_personal",
        "privacy_enable_uid_hidden",
        "privacy_disable_uid_hidden",
    }
    assert all(spec.permission == "admin" for spec in privacy if spec.permission != "user")


def test_generated_admin_privacy_handler_uses_astrbot_admin_filter() -> None:
    """admin 命令的声明必须落成 AstrBot 公共 ADMIN 权限过滤器。"""

    class GeneratedAdminPrivacyPlugin:
        __module__ = "tests.generated_admin_privacy_plugin"

    spec = next(
        spec
        for spec in load_command_registry()
        if spec.id == "privacy_enable_peek_all"
    )
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedAdminPrivacyPlugin, registry)
    metadata = star_handlers_registry.get_handler_by_full_name(
        "tests.generated_admin_privacy_plugin_handle_privacy_enable_peek_all",
    )

    assert metadata is not None
    permission_filters = [
        item for item in metadata.event_filters if isinstance(item, PermissionTypeFilter)
    ]
    assert len(permission_filters) == 1
    assert permission_filters[0].permission_type.name == "ADMIN"


def test_target_extraction_skips_bot_and_at_all() -> None:
    """无效的机器人/全体 @ 不应被当成隐私目标。"""

    class MentionEvent:
        def get_messages(self) -> list[object]:
            return [At(qq="bot-1"), AtAll(), At(qq="target-2")]

    assert target_user_from_event(MentionEvent(), bot_id="bot-1") == "target-2"


@pytest.mark.asyncio
async def test_generated_privacy_handler_extracts_at_target_from_public_event_api() -> None:
    """管理员命令从 AstrBot 消息链的 At 组件提取目标，不读取 legacy ctx.at。"""

    class GeneratedPrivacyPlugin:
        __module__ = "tests.generated_privacy_plugin"

    registry = CommandRegistry(
        (spec for spec in load_command_registry() if spec.id == "privacy_enable_peek_admin"),
    )
    install_command_handlers(GeneratedPrivacyPlugin, registry)
    service = FakePrivacyService()
    plugin = GeneratedPrivacyPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"privacy_service": service},
        ),
    )

    handler = plugin.handle_privacy_enable_peek_admin
    result = [item async for item in handler(Event("kk指定开偷窥"))]

    assert result == ["命令边界已传递"]
    assert service.calls == [
        ("peek:True", EventActor("admin-1", "bot-1", "group-1"), "target-1"),
    ]


@pytest.mark.asyncio
async def test_generated_privacy_handler_passes_missing_target_explicitly() -> None:
    """没有 @ 目标时不猜测用户，也不把管理员本人当成目标。"""

    class GeneratedMissingTargetPlugin:
        __module__ = "tests.generated_missing_target_plugin"

    registry = CommandRegistry(
        (spec for spec in load_command_registry() if spec.id == "privacy_enable_peek_admin"),
    )
    install_command_handlers(GeneratedMissingTargetPlugin, registry)
    service = FakePrivacyService()
    plugin = GeneratedMissingTargetPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"privacy_service": service},
        ),
    )

    handler = plugin.handle_privacy_enable_peek_admin
    result = [item async for item in handler(Event("kk指定开偷窥", target=None))]

    assert result == ["命令边界已传递"]
    assert service.calls[0][2] is None
