"""入口命令 registry 与 AstrBot handler 核心契约测试。"""

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
    load_command_registry,
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
        "account_token_login",
        "account_login",
        "account_logout",
        "account_switch",
        "account_delete_all",
        "account_delete",
        "account_list",
        "account_credentials",
        "role_info_card",
        "refresh_admin_role_card",
        "refresh_role_card",
        "refresh_all_role_cards",
        "clear_role_cache",
        "clear_player_cache",
        "role_detail_card",
        "role_original_image",
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
        "stamina",
        "weekly_report_current",
        "weekly_report_last",
        "calendar",
        "dna_wiki",
        "dna_guide",
        "dna_code",
        "alias_list",
        "alias_all_list",
        "alias_add_delete",
        "alias_recover",
        "sign",
        "sign_calendar",
        "sign_auto_enable",
        "sign_auto_disable",
        "sign_all",
        "sign_result_subscribe",
        "sign_group_report_subscribe",
        "mh",
        "mh_list",
        "ann",
        "mh_subscribe",
        "mh_subscribe_by_name",
        "mh_subscribe_cycle",
        "mh_pic_subscribe",
        "mh_text_subscribe",
        "ann_sub",
        "ann_unsub",
        "client_update",
        "client_update_subscribe",
        "client_update_unsubscribe",
        "resource_status",
        "download_resource",
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


def test_generated_admin_handler_uses_public_admin_permission_filter():
    """admin 命令统一使用 AstrBot 的管理员权限过滤器。"""

    class GeneratedAdminPlugin:
        __module__ = "tests.generated_admin_plugin"

    registry = CommandRegistry((_spec("admin_generated", permission="admin"),))
    install_command_handlers(GeneratedAdminPlugin, registry)
    metadata = star_handlers_registry.get_handler_by_full_name(
        "tests.generated_admin_plugin_handle_admin_generated",
    )

    assert metadata is not None
    permission_filters = [
        item
        for item in metadata.event_filters
        if isinstance(item, PermissionTypeFilter)
    ]
    assert len(permission_filters) == 1
    assert permission_filters[0].permission_type == filter.PermissionType.ADMIN


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


@pytest.mark.asyncio
async def test_generated_handler_returns_generic_message_for_render_failure():
    """图片渲染失败时，handler 不得把模板或服务内部细节暴露给用户。"""

    from src.rendering import T2IRenderError

    async def failing_use_case(_request: CommandRequest, _registry, **_parameters):
        raise T2IRenderError("secret-template-path")

    class GeneratedRenderPlugin:
        __module__ = "tests.generated_render_failure_plugin"

    registry = CommandRegistry(
        (
            CommandSpec(
                id="render_failure",
                pattern=r"^渲染$",
                group="测试",
                name="渲染",
                description="测试渲染失败",
                examples=("渲染",),
                permission="user",
                use_case=failing_use_case,
            ),
        ),
    )
    install_command_handlers(GeneratedRenderPlugin, registry)

    class Event:
        def get_message_str(self) -> str:
            return "渲染"

        def plain_result(self, text: str) -> tuple[str, str]:
            return ("plain", text)

    plugin = GeneratedRenderPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
        ),
    )

    method = plugin.handle_render_failure
    result = [item async for item in method(Event())]

    assert result == [("plain", "图片渲染失败，请稍后重试；管理员可查看日志了解详情。")]
    assert "secret-template-path" not in result[0][1]


def test_commands_manifest_is_generated_from_registry():
    """commands.json 必须与代码 registry 的可序列化投影完全一致。"""

    with open("commands.json", encoding="utf-8") as file:
        manifest = json.load(file)

    assert manifest == manifest_records(COMMAND_REGISTRY)
    assert {item["id"] for item in manifest} == {
        "help",
        "account_token_login",
        "account_login",
        "account_logout",
        "account_switch",
        "account_delete_all",
        "account_delete",
        "account_list",
        "account_credentials",
        "role_info_card",
        "refresh_admin_role_card",
        "refresh_role_card",
        "refresh_all_role_cards",
        "clear_role_cache",
        "clear_player_cache",
        "role_detail_card",
        "role_original_image",
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
        "stamina",
        "weekly_report_current",
        "weekly_report_last",
        "calendar",
        "dna_wiki",
        "dna_guide",
        "dna_code",
        "alias_list",
        "alias_all_list",
        "alias_add_delete",
        "alias_recover",
        "sign",
        "sign_calendar",
        "sign_auto_enable",
        "sign_auto_disable",
        "sign_all",
        "sign_result_subscribe",
        "sign_group_report_subscribe",
        "mh",
        "mh_list",
        "ann",
        "mh_subscribe",
        "mh_subscribe_by_name",
        "mh_subscribe_cycle",
        "mh_pic_subscribe",
        "mh_text_subscribe",
        "ann_sub",
        "ann_unsub",
        "client_update",
        "client_update_subscribe",
        "client_update_unsubscribe",
        "resource_status",
        "download_resource",
    }


@pytest.mark.asyncio
async def test_help_shows_implemented_commands_only(monkeypatch: pytest.MonkeyPatch):
    """帮助输出来自同一个 registry，未迁移命令不得出现。"""

    from io import BytesIO

    from PIL import Image

    class FakeRenderer:
        async def render(self, _template_name, _data, _spec):
            image = Image.new("RGB", (2020, 5001), "white")
            output = BytesIO()
            image.save(output, format="JPEG")
            return output.getvalue()

    monkeypatch.setattr("src.infrastructure.rendering.help._RENDERER", FakeRenderer())

    class Event:
        def get_message_str(self) -> str:
            return "kk帮助"

        def plain_result(self, text: str) -> str:
            return text

    plugin = DnabyPlugin(SimpleNamespace(), {})
    result = [item async for item in plugin.handle_help(Event())]

    assert len(result) == 1

    with Image.open(result[0]) as image:
        assert image.width == 2020
        assert image.height > 5000


def test_load_command_registry_supports_custom_prefix():
    dna_registry = load_command_registry(prefix="dna")
    assert dna_registry.get("role_info_card").pattern.startswith("^dna")
    assert dna_registry.get("role_info_card").examples[0].startswith("dna")
    assert (
        dna_registry.get("stamina").pattern
        == "^dna(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$"
    )

    empty_prefix_registry = load_command_registry(prefix="")
    assert (
        empty_prefix_registry.get("stamina").pattern
        == "^(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$"
    )
    assert empty_prefix_registry.get("stamina").examples == ("日常",)


@pytest.mark.asyncio
async def test_plugin_handles_custom_prefix_dynamically():
    class Event:
        def __init__(self, message: str) -> None:
            self.message = message

        def get_message_str(self) -> str:
            return self.message

        def get_sender_id(self) -> str:
            return "10001"

        def get_self_id(self) -> str:
            return "20002"

        def plain_result(self, text: str) -> tuple[str, str]:
            return ("plain", text)

    plugin = DnabyPlugin(SimpleNamespace(), {"display": {"command_prefix": "dna"}})
    res_dna = [
        item async for item in plugin.handle_resource_status(Event("dna资源状态"))
    ]
    assert len(res_dna) == 1
    assert "资源状态" in res_dna[0][1]

    res_kk = [item async for item in plugin.handle_resource_status(Event("kk资源状态"))]
    assert len(res_kk) == 0


def test_load_command_registry_supports_multiple_prefixes():
    """支持多前缀列表，例如 ['kk', 'dna'] 或包含空前缀。"""
    multi_registry = load_command_registry(prefixes=["kk", "dna"])
    stamina_spec = multi_registry.get("stamina")
    assert (
        stamina_spec.pattern
        == "^(?:dna|kk)(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$"
    )
    assert stamina_spec.examples[0].startswith("kk")

    matched_kk = multi_registry.match("kk体力")
    assert matched_kk is not None
    assert matched_kk.command.id == "stamina"

    matched_dna = multi_registry.match("dna体力")
    assert matched_dna is not None
    assert matched_dna.command.id == "stamina"

    # 包含空字符串时支持无前缀
    multi_empty = load_command_registry(prefixes=["kk", ""])
    assert (
        multi_empty.get("stamina").pattern
        == "^(?:kk)?(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$"
    )
    assert multi_empty.match("体力") is not None
    assert multi_empty.match("kk体力") is not None


@pytest.mark.asyncio
async def test_plugin_handles_multiple_prefixes_dynamically():
    """插件配置多前缀列表时，各前缀均能正确触发。"""

    class Event:
        def __init__(self, message: str) -> None:
            self.message = message

        def get_message_str(self) -> str:
            return self.message

        def get_sender_id(self) -> str:
            return "10001"

        def get_self_id(self) -> str:
            return "20002"

        def plain_result(self, text: str) -> tuple[str, str]:
            return ("plain", text)

    plugin = DnabyPlugin(
        SimpleNamespace(), {"display": {"command_prefixes": ["kk", "dna"]}}
    )
    res_dna = [
        item async for item in plugin.handle_resource_status(Event("dna资源状态"))
    ]
    assert len(res_dna) == 1
    assert "资源状态" in res_dna[0][1]

    res_kk = [item async for item in plugin.handle_resource_status(Event("kk资源状态"))]
    assert len(res_kk) == 1
    assert "资源状态" in res_kk[0][1]


@pytest.mark.asyncio
async def test_help_card_examples_adapt_to_matched_prefix():
    """当用户使用特定的前缀（例如 dna帮助）触发时，帮助卡片显示对应的前缀。"""
    from src.infrastructure.rendering.help import _help_sections, _load_help_data

    plugin_help = _load_help_data()
    sections_dna = _help_sections(plugin_help, prefix="dna")
    first_item = sections_dna[0]["items"][0]
    assert first_item["example"].startswith("dna")

    sections_empty = _help_sections(plugin_help, prefix="")
    first_item_empty = sections_empty[0]["items"][0]
    assert not first_item_empty["example"].startswith("kk")
