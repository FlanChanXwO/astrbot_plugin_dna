"""goal-1 第一阶段的原版行为 Red 契约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import At, AtAll

from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    install_command_handlers,
    load_command_registry,
)
from src.entry.event import target_user_from_event
from src.entry.response import ResponseFactory


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


@pytest.mark.asyncio
async def test_handler_snapshots_effective_permission_for_the_use_case() -> None:
    """handler 应从当前 AstrBot 事件快照权限，而不是让 use case 再读 event。"""

    seen: list[str] = []

    async def use_case(
        request: CommandRequest,
        _registry: CommandRegistry,
        **_parameters: object,
    ) -> str:
        seen.append(request.permission)
        return "ok"

    class GeneratedPermissionPlugin:
        __module__ = "tests.generated_permission_plugin"

    spec = CommandSpec(
        id="permission_snapshot",
        pattern=r"^权限测试$",
        group="测试",
        name="权限测试",
        description="权限测试",
        examples=("权限测试",),
        permission="user",
        use_case=use_case,
    )
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedPermissionPlugin, registry)
    plugin = GeneratedPermissionPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(commands=registry, responses=ResponseFactory(), services={}),
    )

    class AdminEvent:
        def get_message_str(self) -> str:
            return "权限测试"

        def is_admin(self) -> bool:
            return True

        def plain_result(self, text: str) -> str:
            return text

    result = [
        item
        async for item in plugin.handle_permission_snapshot(AdminEvent())
    ]

    assert result == ["ok"]
    assert seen == ["admin"]


@pytest.mark.asyncio
async def test_handler_passes_last_valid_target_to_use_case() -> None:
    """所有命令 handler 都应把消息链最后一个有效 At 传给 use case。"""

    seen: list[str | None] = []

    async def use_case(
        request: CommandRequest,
        _registry: CommandRegistry,
        **_parameters: object,
    ) -> str:
        seen.append(request.target_user_id)
        return "ok"

    class GeneratedTargetPlugin:
        __module__ = "tests.generated_target_plugin"

    spec = CommandSpec(
        id="target_snapshot",
        pattern=r"^目标测试$",
        group="测试",
        name="目标测试",
        description="目标测试",
        examples=("目标测试",),
        permission="user",
        use_case=use_case,
    )
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedTargetPlugin, registry)
    plugin = GeneratedTargetPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(commands=registry, responses=ResponseFactory(), services={}),
    )

    class MentionEvent:
        def get_message_str(self) -> str:
            return "目标测试"

        def plain_result(self, text: str) -> str:
            return text

        def get_sender_id(self) -> str:
            return "actor-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def get_messages(self) -> list[object]:
            return [
                At(qq="target-first"),
                At(qq="bot-1"),
                AtAll(),
                At(qq="target-last"),
            ]

    result = [
        item
        async for item in plugin.handle_target_snapshot(MentionEvent())
    ]

    assert result == ["ok"]
    assert seen == ["target-last"]


@pytest.mark.asyncio
async def test_help_card_uses_visible_registry_commands_and_metadata_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """帮助卡只应渲染当前权限可见的 registry 命令，并显示 metadata 版本。"""

    import src.infrastructure.rendering.help as help_renderer

    class Renderer:
        def __init__(self) -> None:
            self.data: dict[str, object] | None = None

        async def render(
            self,
            _template_name: str,
            data: dict[str, object],
            _spec: object,
        ) -> bytes:
            self.data = data
            return b"help-card"

    renderer = Renderer()
    monkeypatch.setattr(help_renderer, "_RENDERER", renderer)
    monkeypatch.setattr(help_renderer, "font_data_uri", lambda _: "font")
    monkeypatch.setattr(help_renderer, "image_data_uri", lambda _: "image")
    help_renderer.invalidate_help_cache()
    registry = CommandRegistry(
        (
            _spec("visible_user", "用户命令", "user"),
            _spec("hidden_admin", "管理员命令", "admin"),
        ),
    )

    result = await help_renderer.get_help(
        prefix="dna",
        registry=registry,
        permission="user",
    )

    assert result == b"help-card"
    assert renderer.data is not None
    sections = renderer.data["sections"]
    assert isinstance(sections, list)
    items = [item for section in sections for item in section["items"]]
    assert [item["name"] for item in items] == ["用户命令"]
    assert items[0]["example"] == "dna用户命令"
    assert renderer.data["lines"] == []
    assert renderer.data["version"] == "v0.1.0"


@pytest.mark.asyncio
async def test_help_cache_is_keyed_and_invalidated_by_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """帮助渲染按前缀/权限/版本缓存，显式失效后必须重新渲染。"""

    import src.infrastructure.rendering.help as help_renderer

    class Renderer:
        def __init__(self) -> None:
            self.calls = 0

        async def render(
            self,
            _template_name: str,
            _data: dict[str, object],
            _spec: object,
        ) -> bytes:
            self.calls += 1
            return f"card-{self.calls}".encode()

    renderer = Renderer()
    monkeypatch.setattr(help_renderer, "_RENDERER", renderer)
    monkeypatch.setattr(help_renderer, "font_data_uri", lambda _: "font")
    monkeypatch.setattr(help_renderer, "image_data_uri", lambda _: "image")
    help_renderer.invalidate_help_cache()
    registry = CommandRegistry((_spec("cache_user", "缓存命令", "user"),))

    assert await help_renderer.get_help(
        prefix="kk", registry=registry, permission="user", version="v1"
    ) == b"card-1"
    assert await help_renderer.get_help(
        prefix="kk", registry=registry, permission="user", version="v1"
    ) == b"card-1"
    assert await help_renderer.get_help(
        prefix="dna", registry=registry, permission="user", version="v1"
    ) == b"card-2"
    assert await help_renderer.get_help(
        prefix="dna", registry=registry, permission="admin", version="v1"
    ) == b"card-3"
    assert await help_renderer.get_help(
        prefix="dna", registry=registry, permission="admin", version="v2"
    ) == b"card-4"

    help_renderer.invalidate_help_cache()
    assert await help_renderer.get_help(
        prefix="dna", registry=registry, permission="admin", version="v2"
    ) == b"card-5"


@pytest.mark.asyncio
async def test_runtime_termination_invalidates_help_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runtime 停止时必须清掉帮助卡缓存，下一次加载使用新实例。"""

    from src.bootstrap import PluginRuntime

    cleared: list[str] = []

    class Lifecycle:
        async def terminate(self) -> None:
            return None

    monkeypatch.setattr(
        "src.infrastructure.rendering.help.invalidate_help_cache",
        lambda: cleared.append("help"),
    )
    runtime = PluginRuntime(
        context=SimpleNamespace(),
        config=None,
        lifecycle=Lifecycle(),
        events=SimpleNamespace(),
        responses=SimpleNamespace(),
        commands=CommandRegistry(()),
        settings=SimpleNamespace(),
        services={},
    )

    await runtime.terminate()

    assert cleared == ["help"]
