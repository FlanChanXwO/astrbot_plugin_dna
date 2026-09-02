"""当前重规划的命令面、分组和权限契约。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from src.entry.commands import load_command_registry
from src.entry.event import EventActor
from src.infrastructure.config import DnabySettings
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.modules.admin.aliases import AdminAliasService
from src.modules.checkin.service import CheckinService
from src.modules.notices.mh_cache import MhSnapshotEnvelope, snapshot_fingerprint
from src.modules.player.contracts import PlayerCommandRequest
from tests.test_checkin import FakeCheckinTransport
from tests.test_goal1_o10_player_cache import _service as player_service_fixture

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_replanned_command_surface_uses_public_and_admin_boundaries() -> None:
    """帮助菜单只暴露当前发布契约中的命令。"""

    specs = {spec.id: spec for spec in load_command_registry()}

    expected = {
        "help",
        "account_login",
        "account_token_login",
        "account_logout",
        "account_switch",
        "account_delete_all",
        "account_delete",
        "account_list",
        "account_credentials",
        "refresh_admin_role_card",
        "refresh_role_card",
        "refresh_all_role_cards",
        "clear_role_cache",
        "clear_player_cache",
        "role_detail_card",
        "alias_add_delete",
        "alias_recover",
        "alias_list",
        "alias_all_list",
        "sign",
        "sign_auto_enable",
        "sign_auto_disable",
        "sign_calendar",
        "sign_all",
        "sign_result_subscribe",
        "ann_sub",
        "ann_unsub",
    }
    assert expected <= specs.keys()

    removed_ids = {
        "upload_panel_img",
        "list_panel_imgs",
        "delete_panel_img_by_id",
        "delete_all_panel_imgs",
        "delete_original_panel_img",
        "compress_panel_imgs",
        "update_log",
        "get_bound_token",
        "mh_test",
    }
    assert removed_ids.isdisjoint(specs)

    assert specs["help"].group == "信息查询"
    assert specs["help"].permission == "user"
    for command_id in ("alias_list", "alias_all_list"):
        assert specs[command_id].group == "图鉴"
        assert specs[command_id].permission == "user"

    for command_id in (
        "refresh_role_card",
        "refresh_all_role_cards",
        "clear_role_cache",
    ):
        assert specs[command_id].group == "角色信息"
        assert specs[command_id].permission == "user"
    assert specs["clear_player_cache"].group == "角色信息"
    assert specs["clear_player_cache"].permission == "user"

    for command_id in (
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
        "ann_sub",
        "ann_unsub",
    ):
        assert specs[command_id].group == "管理员功能"
        assert specs[command_id].permission == "admin"

    for command_id in (
        "sign_all",
        "sign_result_subscribe",
        "alias_add_delete",
        "alias_recover",
    ):
        assert specs[command_id].group == "bot主人功能"
        assert specs[command_id].permission == "admin"

    for command_id in ("mh_pic_subscribe", "mh_text_subscribe"):
        assert specs[command_id].permission == "user"

    assert re.match(specs["refresh_all_role_cards"].pattern, "kk刷新全部角色面板")
    assert re.match(specs["clear_role_cache"].pattern, "kk清理菲娜面板缓存")
    assert re.match(specs["sign_auto_enable"].pattern, "kk开启自动签到")
    assert re.match(specs["sign_auto_disable"].pattern, "kk关闭自动签到")
    assert re.match(specs["alias_add_delete"].pattern, "kk添加角色菲娜别名小菲")


def test_raw_token_output_is_not_exposed_by_legacy_login_compatibility() -> None:
    """App-only 登录兼容层不得再提供原始 token 输出接口。"""

    from src.modules.account import login_router
    from src.modules.account.login_service import DNALoginService

    assert not hasattr(DNALoginService, "get_cookie")
    assert "get_cookie" not in login_router.__all__


@pytest.mark.asyncio
async def test_help_layout_orders_groups_and_computes_height_from_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """帮助卡标题、分组和 footer 使用内容驱动布局，不依赖旧固定高度。"""

    from src.infrastructure.rendering import help as help_rendering

    class Renderer:
        data: dict[str, object] | None = None

        async def render(self, _template: str, data: dict[str, object], _spec: object) -> bytes:
            self.data = data
            return b"rendered"

    renderer = Renderer()
    monkeypatch.setattr(help_rendering, "_RENDERER", renderer)
    help_rendering.invalidate_help_cache()

    await help_rendering.get_help(
        registry=load_command_registry(),
        permission="user",
        version="v-test-layout",
    )

    assert renderer.data is not None
    sections = renderer.data["sections"]
    assert isinstance(sections, list)
    assert [section["name"] for section in sections[:5]] == [
        "账号管理",
        "皎皎角登录",
        "密函",
        "信息查询",
        "角色信息",
    ]
    assert all(section["height"] > 0 for section in sections)
    assert renderer.data["card_height"] != 5059
    template = (PROJECT_ROOT / "src/templates/cards/help.html.j2").read_text(
        encoding="utf-8",
    )
    assert "bottom: 20px" not in template
    assert ".help-card__footer { position: absolute" not in template


@pytest.mark.asyncio
async def test_auto_sign_flag_is_persisted_per_user_uid(tmp_path: Path) -> None:
    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        first = await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        second = await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="9876543210987",
            is_active=False,
        )
        assert first.auto_sign_enabled is True
        assert second.auto_sign_enabled is True
        assert await AccountBindingRepository.set_auto_sign_enabled(
            session,
            user_id="user-1",
            uid="1234567890123",
            enabled=False,
        )
        assert await AccountBindingRepository.set_auto_sign_enabled(
            session,
            user_id="user-1",
            uid="9876543210987",
            enabled=True,
        )
    async with database.session() as session:
        first = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid="1234567890123",
        )
        second = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid="9876543210987",
        )
        assert first is not None and first.auto_sign_enabled is False
        assert second is not None and second.auto_sign_enabled is True
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_all_skips_disabled_bindings(tmp_path: Path) -> None:
    database = AsyncDatabase(tmp_path / "checkin.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-2",
            uid="9876543210987",
            is_active=True,
            auto_sign_enabled=False,
        )
    service = CheckinService(
        database,
        FakeCheckinTransport(),
        object(),
        object(),
    )
    seen: list[str] = []

    async def fake_sign_one(actor, uid: str, credential_user_id: str):
        seen.append(uid)

    service._sign_one = fake_sign_one  # type: ignore[method-assign]
    summary = await service.auto_sign_all()

    assert seen == ["1234567890123"]
    assert "今日成功游戏签到 0 个账号" in summary
    await database.dispose()


@pytest.mark.asyncio
async def test_refresh_all_roles_only_returns_summary_without_rendering_cards(
    tmp_path: Path,
) -> None:
    from tests.test_goal1_o10_player_cache import MutableClock, _request

    clock = MutableClock()
    database, transport, renderer, _cache, service = await player_service_fixture(tmp_path, clock)
    try:
        response = await service.refresh_all_roles(_request())

        assert response.text == "角色面板刷新完成：成功 1 个，失败 0 个"
        assert transport.overview_calls == 1
        assert transport.role_detail_calls == 1
        assert renderer.detail_calls == 0
        await service.role_detail(
            PlayerCommandRequest(
                actor=EventActor("user-1", "bot-1", "group-1"),
                target_user_id=None,
                parameters={"char_name": "角色甲"},
            ),
        )
        assert transport.role_detail_calls == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_refresh_all_roles_summarizes_unexpected_role_failure_with_traceback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from tests.test_goal1_o10_player_cache import MutableClock, _request

    clock = MutableClock()
    database, _transport, _renderer, _cache, service = await player_service_fixture(
        tmp_path,
        clock,
    )

    async def fail_one_role(*_args, **_kwargs):
        raise RuntimeError("fixture-only role failure")

    service._fetch_detail_bundle = fail_one_role  # type: ignore[method-assign]
    try:
        response = await service.refresh_all_roles(_request())

        assert response.text == "角色面板刷新完成：成功 0 个，失败 1 个\n失败角色：角色甲"
        records = [
            record
            for record in caplog.records
            if "角色批量刷新出现未预期异常" in record.message
        ]
        assert len(records) == 1
        assert records[0].exc_info is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_role_detail_does_not_call_damage_api_or_render_damage_section(
    tmp_path: Path,
) -> None:
    from tests.test_goal1_o10_player_cache import MutableClock, _request

    clock = MutableClock()
    database, transport, renderer, _cache, service = await player_service_fixture(tmp_path, clock)
    try:
        response = await service.role_detail(_request(detail=True))

        assert response.image is not None
        assert transport.damage_calls == 0
        assert renderer.last_detail_damage is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_clear_role_cache_only_removes_selected_role_cache(tmp_path: Path) -> None:
    from tests.test_goal1_o10_player_cache import MutableClock, _request

    clock = MutableClock()
    database, transport, _renderer, _cache, service = await player_service_fixture(tmp_path, clock)
    try:
        await service.role_detail(_request(detail=True))
        response = await service.clear_role_cache(
            PlayerCommandRequest(
                actor=EventActor("user-1", "bot-1", "group-1"),
                target_user_id=None,
                parameters={"char_name": "角色甲"},
            ),
        )

        assert response.text == "角色【角色甲】缓存已清理"
        await service.role_detail(_request(detail=True))
        assert transport.role_detail_calls == 2
    finally:
        await database.dispose()


def test_auto_sign_migration_adds_default_without_touching_existing_bindings(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration.sqlite3"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "0004_app_credentials_only")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_bindings "
                    "(user_id, group_id, uid, is_active) "
                    "VALUES ('user-1', 'group-1', '1234567890123', 1)"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("account_bindings")
            }
            binding = connection.execute(
                text(
                    "SELECT user_id, uid, is_active, auto_sign_enabled "
                    "FROM account_bindings"
                )
            ).one()
        assert "auto_sign_enabled" in columns
        assert binding == ("user-1", "1234567890123", 1, 1)
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_secret_push_settings_are_typed_and_keep_configured_minute_and_retry() -> None:
    settings = DnabySettings.from_config(
        {
            "notifications": {
                "secret_push_minute": 17,
                "secret_retry_interval_seconds": 2.5,
            },
        },
    )

    assert settings.notifications.secret_push_minute == 17
    assert settings.notifications.secret_retry_interval_seconds == 2.5


def test_resource_generation_validator_uses_runtime_alias_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generation 目录与运行目录分离时，校验索引仍要读取运行期 custom 别名。"""

    from src.infrastructure.resources import generation

    class Manifest:
        file_hashes: ClassVar[dict[str, str]] = {}
        resource_version = "test"

        def validate_runtime_layout(self, _root: Path) -> Manifest:
            return self

    captured: dict[str, Path | None] = {}

    def fake_store_from_root(
        _root: str | Path,
        *,
        custom_alias_path: str | Path | None = None,
        custom_weapon_alias_path: str | Path | None = None,
    ) -> generation.EncyclopediaResourceStore:
        captured["char"] = None if custom_alias_path is None else Path(custom_alias_path)
        captured["weapon"] = (
            None
            if custom_weapon_alias_path is None
            else Path(custom_weapon_alias_path)
        )
        return generation.EncyclopediaResourceStore()

    monkeypatch.setattr(generation.ResourceManifest, "load", lambda _path: Manifest())
    monkeypatch.setattr(generation, "_validate_no_symlinks", lambda _root: None)
    monkeypatch.setattr(
        generation,
        "_validate_declared_file_hashes",
        lambda _root, _manifest: None,
    )
    monkeypatch.setattr(generation, "_validate_alias_file", lambda _path: None)
    monkeypatch.setattr(generation, "_validate_redeem_file", lambda _path: None)
    monkeypatch.setattr(generation, "_validate_schema_file", lambda _path: None)
    monkeypatch.setattr(generation, "_validate_asset_headers", lambda _root: None)
    monkeypatch.setattr(
        generation.EncyclopediaResourceStore,
        "from_root",
        fake_store_from_root,
    )

    char_custom = tmp_path / "alias_custom.json"
    weapon_custom = tmp_path / "weapon_alias_custom.json"
    validator = generation.ResourceGenerationValidator(
        custom_alias_path=char_custom,
        custom_weapon_alias_path=weapon_custom,
    )

    validator.validate(tmp_path, "a" * 40)

    assert captured == {"char": char_custom, "weapon": weapon_custom}


def test_mh_snapshot_envelope_accepts_a_snapshot_ready_at_the_hour_boundary() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from tests.test_notices import _mh_snapshot

    snapshot = _mh_snapshot()
    window_start = datetime(2026, 8, 30, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    envelope = MhSnapshotEnvelope(
        snapshot=snapshot,
        window_start=window_start,
        fetched_at=window_start,
        fingerprint=snapshot_fingerprint(snapshot),
    )

    assert envelope.fetched_at == window_start


@pytest.mark.asyncio
async def test_notice_scheduler_uses_configured_secret_push_minute() -> None:
    from src.infrastructure.notices_scheduler import NoticesScheduler

    class Notices:
        async def push_mh_now(self) -> int:
            return 0

        async def poll_ann_now(self) -> int:
            return 0

    scheduler = NoticesScheduler(Notices(), push_minute=17)

    assert scheduler.push_time == (17, 0)
    snapshots = await scheduler.registry.list_snapshots()
    mh_task = next(item for item in snapshots if item.id == "dnaby_mh_push")
    assert mh_task.schedule == "hourly@17:00"


@pytest.mark.asyncio
async def test_alias_admin_supports_character_and_weapon_layers_and_recovery(
    tmp_path: Path,
) -> None:
    resource_alias = tmp_path / "resources" / "alias"
    resource_alias.mkdir(parents=True)
    char_default = resource_alias / "char_alias.json"
    weapon_default = resource_alias / "weapon_alias.json"
    char_default.write_text(json.dumps({"菲娜": ["小菲"]}), encoding="utf-8")
    weapon_default.write_text(json.dumps({"武器甲": ["甲"]}), encoding="utf-8")
    char_custom = tmp_path / "char_alias_custom.json"
    weapon_custom = tmp_path / "weapon_alias_custom.json"
    char_custom.write_text('{"菲娜": ["旧自定义"]}', encoding="utf-8")
    weapon_custom.write_text("{}", encoding="utf-8")
    service = AdminAliasService(
        char_default,
        weapon_alias_path=weapon_default,
        custom_path=char_custom,
        weapon_custom_path=weapon_custom,
    )

    added = await service.add_weapon_alias("武器甲", "大剑")
    assert added.ok is True
    catalog = await service.reload_defaults()
    assert catalog.ok is True
    assert catalog.data is not None
    assert catalog.data.weapon("武器甲").custom_aliases == ("大剑",)
    assert catalog.data.role("菲娜").custom_aliases == ("旧自定义",)

    forced = await service.recover_aliases(force=True)
    assert forced.ok is True
    assert forced.data is not None
    assert forced.data.weapon("武器甲").custom_aliases == ()
    assert forced.data.role("菲娜").custom_aliases == ()
