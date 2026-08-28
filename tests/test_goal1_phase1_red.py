"""goal-1 第一阶段的原版行为 Red 契约。"""

from __future__ import annotations

from astrbot.api.message_components import At, AtAll

from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    load_command_registry,
)
from src.entry.event import target_user_from_event


async def _noop_use_case(
    _request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: object,
) -> None:
    return None


def _spec(command_id: str, name: str, permission: str) -> CommandSpec:
    return CommandSpec(
        id=command_id,
        pattern=f"^{name}$",
        group="测试",
        name=name,
        description=name,
        examples=(name,),
        permission=permission,
        use_case=_noop_use_case,
    )


def test_help_text_is_filtered_by_caller_permission() -> None:
    """普通用户不应看到 admin 命令，管理员应看到两类命令。"""

    registry = CommandRegistry(
        (
            _spec("user_command", "用户命令", "user"),
            _spec("admin_command", "管理员命令", "admin"),
        ),
    )

    user_help = registry.render_help(permission="user")
    admin_help = registry.render_help(permission="admin")

    assert "用户命令" in user_help
    assert "管理员命令" not in user_help
    assert "用户命令" in admin_help
    assert "管理员命令" in admin_help


def test_target_user_uses_the_last_valid_mention() -> None:
    """原版 At 语义取最后一个有效目标，忽略机器人和全体 At。"""

    class MentionEvent:
        def get_messages(self) -> list[object]:
            return [
                At(qq="target-first"),
                At(qq="bot-1"),
                AtAll(),
                At(qq="target-last"),
            ]

    assert target_user_from_event(MentionEvent(), bot_id="bot-1") == "target-last"


def test_public_registry_uses_only_user_and_admin_permissions() -> None:
    """公开命令权限收敛为 user/admin，不再暴露插件自定义 owner。"""

    assert all(
        spec.permission in {"user", "admin"}
        for spec in load_command_registry()
    )


def test_update_log_is_not_a_registered_chat_command() -> None:
    """更新记录改由仓库 CHANGELOG 承担，不再进入聊天命令清单。"""

    assert "update_log" not in {spec.id for spec in load_command_registry()}
