"""v0.1 命令 registry 与 AstrBot handler 生成契约测试。"""

from __future__ import annotations

import inspect
import json
from types import ModuleType, SimpleNamespace

import pytest
from astrbot.api.event import filter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.filter.regex import RegexFilter
from astrbot.core.star.star_handler import star_handlers_registry

from main import COMMAND_REGISTRY, DnabyPlugin
from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    install_command_handlers,
    manifest_records,
)
from src.entry.response import PlainTextResponse, ResponseFactory


async def _noop_use_case(_request: CommandRequest, _registry, **_parameters):
    return "ok"


def _spec(
    command_id: str = "lookup",
    pattern: str = r"^查(?P<name>.+)$",
    permission: str = "user",
) -> CommandSpec:
    return CommandSpec(
        id=command_id,
        pattern=pattern,
        group="测试",
        name="查询",
        description="测试查询",
        examples=("查二重螺旋",),
        permission=permission,
        use_case=_noop_use_case,
    )


def test_explicit_registry_loads_only_implemented_commands():
    """显式模块索引只暴露已实现的 use case。"""

    assert [spec.id for spec in COMMAND_REGISTRY] == [
        "help",
        "account_login",
        "account_logout",
        "account_bind",
        "account_switch",
        "account_delete_all",
        "account_delete",
        "account_list",
        "account_credentials",
        "privacy_enable_peek_personal",
        "privacy_disable_peek_personal",
        "privacy_enable_uid_hidden",
        "privacy_disable_uid_hidden",
        "privacy_enable_peek_admin",
        "privacy_disable_peek_admin",
        "privacy_enable_peek_all",
        "privacy_disable_peek_all",
        "privacy_cancel_peek_all",
        "privacy_enable_uid_hidden_admin",
        "privacy_disable_uid_hidden_admin",
        "privacy_enable_uid_hidden_all",
        "privacy_disable_uid_hidden_all",
        "privacy_cancel_uid_hidden_all",
    ]
    assert COMMAND_REGISTRY.get("help").name == "帮助"


def test_registry_rejects_invalid_permission_and_duplicate_loading():
    """权限枚举、重复模块和重复命令必须显式失败。"""

    with pytest.raises(ValueError, match="permission"):
        CommandSpec(
            id="bad_permission",
            pattern=r"^坏$",
            group="测试",
            name="坏权限",
            description="坏权限",
            examples=("坏",),
            permission="superuser",
            use_case=_noop_use_case,
        )

    module = ModuleType("tests.fake_commands")
    module.__dict__["COMMAND_SPECS"] = (_spec(),)
    with pytest.raises(ValueError, match="重复加载"):
        CommandRegistry.from_modules((module, module))

    duplicate = ModuleType("tests.fake_duplicate_commands")
    duplicate.__dict__["COMMAND_SPECS"] = (_spec(), _spec("lookup_other"))
    with pytest.raises(ValueError, match="正则"):
        CommandRegistry.from_modules((duplicate,))


def test_registry_validates_named_groups_and_examples():
    """named group 和示例由 registry 编译、检查并暴露给生成器。"""

    registry = CommandRegistry((_spec(),))

    assert registry.named_parameters("lookup") == ("name",)
    assert registry.get("lookup").examples == ("查二重螺旋",)

    with pytest.raises(ValueError, match="示例"):
        CommandSpec(
            id="broken_example",
            pattern=r"^查(?P<name>.+)$",
            group="测试",
            name="查询",
            description="测试查询",
            examples=("帮助",),
            permission="user",
            use_case=_noop_use_case,
        )


def test_generated_method_is_a_real_async_generator_with_public_filters():
    """动态方法有独立正则、权限过滤器和正确模块路径。"""

    class GeneratedPlugin:
        """避免复用入口类，便于验证一次安装。"""

        __module__ = "tests.generated_plugin"

    class_registry = CommandRegistry((_spec("lookup_generated"),))
    install_command_handlers(GeneratedPlugin, class_registry)

    method = getattr(
        GeneratedPlugin,
        f"handle_{class_registry.get('lookup_generated').id}",
    )
    assert inspect.isasyncgenfunction(method)
    assert method.__module__ == GeneratedPlugin.__module__

    metadata = star_handlers_registry.get_handler_by_full_name(
        "tests.generated_plugin_handle_lookup_generated",
    )
    assert metadata is not None
    assert any(isinstance(item, RegexFilter) for item in metadata.event_filters)
    permission_filters = [
        item
        for item in metadata.event_filters
        if isinstance(item, PermissionTypeFilter)
    ]
    assert len(permission_filters) == 1
    assert permission_filters[0].permission_type == filter.PermissionType.MEMBER


@pytest.mark.asyncio
async def test_generated_handler_reparses_its_named_parameters():
    """handler 自己重跑 pattern，named group 只流向自己的 use case。"""

    seen: dict[str, object] = {}

    async def use_case(_request: CommandRequest, _registry, **parameters):
        seen.update(parameters)
        return PlainTextResponse("命中")

    class GeneratedPlugin:
        __module__ = "tests.generated_named_plugin"

    registry = CommandRegistry(
        (
            CommandSpec(
                id="named_generated",
                pattern=r"^查(?P<name>.+)$",
                group="测试",
                name="查询",
                description="测试查询",
                examples=("查二重螺旋",),
                permission="user",
                use_case=use_case,
            ),
        ),
    )
    install_command_handlers(GeneratedPlugin, registry)

    class Event:
        def get_message_str(self) -> str:
            return "查二重螺旋"

        def plain_result(self, text: str) -> tuple[str, str]:
            return ("plain", text)

    plugin = GeneratedPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
        ),
    )

    method = getattr(plugin, f"handle_{registry.get('named_generated').id}")
    result = [item async for item in method(Event())]

    assert seen == {"name": "二重螺旋"}
    assert result == [("plain", "命中")]


def test_commands_manifest_is_generated_from_registry():
    """commands.json 必须与代码 registry 的可序列化投影完全一致。"""

    with open("commands.json", encoding="utf-8") as file:
        manifest = json.load(file)

    assert manifest == manifest_records(COMMAND_REGISTRY)
    assert {item["id"] for item in manifest} == {
        "help",
        "account_login",
        "account_logout",
        "account_bind",
        "account_switch",
        "account_delete_all",
        "account_delete",
        "account_list",
        "account_credentials",
        "privacy_enable_peek_personal",
        "privacy_disable_peek_personal",
        "privacy_enable_uid_hidden",
        "privacy_disable_uid_hidden",
        "privacy_enable_peek_admin",
        "privacy_disable_peek_admin",
        "privacy_enable_peek_all",
        "privacy_disable_peek_all",
        "privacy_cancel_peek_all",
        "privacy_enable_uid_hidden_admin",
        "privacy_disable_uid_hidden_admin",
        "privacy_enable_uid_hidden_all",
        "privacy_disable_uid_hidden_all",
        "privacy_cancel_uid_hidden_all",
    }


@pytest.mark.asyncio
async def test_help_shows_implemented_commands_only():
    """帮助输出来自同一个 registry，未迁移命令不得出现。"""

    class Event:
        def get_message_str(self) -> str:
            return "帮助"

        def plain_result(self, text: str) -> str:
            return text

    plugin = DnabyPlugin(SimpleNamespace(), {})
    result = [item async for item in plugin.handle_help(Event())]

    assert len(result) == 1
    assert "帮助" in result[0]
    assert "签到" not in result[0]
    assert "登录" in result[0]
