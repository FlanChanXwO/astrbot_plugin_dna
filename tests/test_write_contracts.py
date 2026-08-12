"""Task 19 写入型命令的离线契约、权限审计与 dispatch 边界。

真实账户禁止执行登录/签到/绑定/订阅/隐私写入；这些能力只在 fake transport +
隔离 SQLite + 模拟事件 + 旧逻辑 fixture 中验证。本契约明确：离线验证不等于真实
行为已验证，真实平台写入验收边界由 Task 30 记录。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.response import ResponseFactory
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import CheckinRenderer, NoticesRenderer
from src.infrastructure.resources import EncyclopediaResourceStore
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.account.contracts import AccountActor, LoginAttempt, LoginResult
from src.modules.account.service import AccountService
from src.modules.checkin.contracts import (
    CommunityTask,
    DayAward,
    SignCalendar,
    SignPeriod,
    SignRoleInfo,
    SignStatus,
    TaskProcess,
)
from src.modules.checkin.service import CheckinService
from src.modules.notices.ann_state import AnnStateStore
from src.modules.notices.contracts import AnnDetail, AnnSnapshot, MhSnapshot
from src.modules.notices.service import NoticesService
from src.modules.operations.service import PanelService
from src.modules.privacy.service import PrivacyService

TESTS_DIR = Path(__file__).resolve().parent

# 全部已实现的写入型命令及其要求的权限边界（与 legacy 命令清单一致）。
WRITE_COMMANDS: dict[str, str] = {
    "account_login": "user",
    "account_logout": "user",
    "account_bind": "user",
    "account_switch": "user",
    "account_delete_all": "user",
    "account_delete": "user",
    "privacy_enable_peek_personal": "user",
    "privacy_disable_peek_personal": "user",
    "privacy_enable_uid_hidden": "user",
    "privacy_disable_uid_hidden": "user",
    "privacy_enable_peek_admin": "admin",
    "privacy_disable_peek_admin": "admin",
    "privacy_enable_peek_all": "admin",
    "privacy_disable_peek_all": "admin",
    "privacy_cancel_peek_all": "admin",
    "privacy_enable_uid_hidden_admin": "admin",
    "privacy_disable_uid_hidden_admin": "admin",
    "privacy_enable_uid_hidden_all": "admin",
    "privacy_disable_uid_hidden_all": "admin",
    "privacy_cancel_uid_hidden_all": "admin",
    "sign": "user",
    "sign_all": "owner",
    "sign_result_subscribe": "owner",
    "mh_subscribe_by_name": "user",
    "mh_subscribe_cycle": "user",
    "mh_pic_subscribe": "admin",
    "mh_text_subscribe": "admin",
    "mh_test": "owner",
    "ann_sub": "admin",
    "ann_unsub": "admin",
    "upload_panel_img": "owner",
    "list_panel_imgs": "owner",
    "delete_panel_img_by_id": "owner",
    "delete_all_panel_imgs": "owner",
    "delete_original_panel_img": "owner",
    "compress_panel_imgs": "owner",
    "resource_status": "owner",
    "download_resource": "owner",
    "update_log": "owner",
}

# 每条写入型命令对应的离线契约测试文件与其代表性用例（审计注册的覆盖）。
CONTRACT_COVERAGE: dict[str, tuple[str, tuple[str, ...]]] = {
    "account_login": (
        "test_account.py",
        (
            "test_login_success_persists_roles_and_credentials_without_leaking_secrets",
            "test_login_transport_errors_are_visible_but_do_not_leak_details",
        ),
    ),
    "account_logout": (
        "test_account.py",
        ("test_bind_switch_delete_logout_lifecycle_uses_normalized_records",),
    ),
    "account_bind": (
        "test_account.py",
        ("test_bind_switch_delete_logout_lifecycle_uses_normalized_records",),
    ),
    "account_switch": (
        "test_account.py",
        ("test_bind_switch_delete_logout_lifecycle_uses_normalized_records",),
    ),
    "account_delete": (
        "test_account.py",
        (
            "test_bind_switch_delete_logout_lifecycle_uses_normalized_records",
            "test_list_and_delete_all_remove_normalized_records",
        ),
    ),
    "account_delete_all": (
        "test_account.py",
        ("test_list_and_delete_all_remove_normalized_records",),
    ),
    "privacy_enable_peek_personal": (
        "test_privacy.py",
        ("test_personal_privacy_defaults_and_group_force_precedence",),
    ),
    "privacy_disable_peek_personal": (
        "test_privacy.py",
        ("test_personal_privacy_defaults_and_group_force_precedence",),
    ),
    "privacy_enable_uid_hidden": (
        "test_privacy.py",
        ("test_personal_privacy_defaults_and_group_force_precedence",),
    ),
    "privacy_disable_uid_hidden": (
        "test_privacy.py",
        ("test_personal_privacy_defaults_and_group_force_precedence",),
    ),
    "privacy_enable_peek_admin": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_disable_peek_admin": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_enable_peek_all": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_disable_peek_all": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_cancel_peek_all": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_enable_uid_hidden_admin": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_disable_uid_hidden_admin": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_enable_uid_hidden_all": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_disable_uid_hidden_all": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "privacy_cancel_uid_hidden_all": ("test_privacy_commands.py", ("test_registry_exposes_all_privacy_commands_with_admin_boundary",)),
    "sign": (
        "test_checkin.py",
        ("test_manual_sign_completes_game_and_community_and_saves_record",),
    ),
    "sign_all": (
        "test_checkin.py",
        ("test_sign_all_aggregates_success_and_failure",),
    ),
    "sign_result_subscribe": (
        "test_checkin.py",
        (
            "test_subscribe_sign_result_adds_and_dedupes",
            "test_unsubscribe_sign_result_removes_subscription",
        ),
    ),
    "mh_subscribe_by_name": (
        "test_notices_subscriptions.py",
        ("test_subscribe_mh_adds_names_and_dedupes", "test_unsubscribe_mh_removes_names"),
    ),
    "mh_subscribe_cycle": (
        "test_notices_subscriptions.py",
        ("test_mh_subscriptions_shows_time_window",),
    ),
    "mh_pic_subscribe": (
        "test_notices_subscriptions.py",
        ("test_toggle_mh_pic_and_text_are_session_scoped",),
    ),
    "mh_text_subscribe": (
        "test_notices_subscriptions.py",
        ("test_toggle_mh_pic_and_text_are_session_scoped",),
    ),
    "mh_test": (
        "test_notices_subscriptions.py",
        ("test_test_mh_push_sends_to_current_session",),
    ),
    "ann_sub": (
        "test_notices_subscriptions.py",
        ("test_ann_sub_unsub_group_scoped", "test_ann_sub_requires_group"),
    ),
    "ann_unsub": (
        "test_notices_subscriptions.py",
        ("test_ann_sub_unsub_group_scoped",),
    ),
    "upload_panel_img": (
        "test_operations.py",
        ("test_upload_panel_img_saves_webp_and_reports_count",),
    ),
    "list_panel_imgs": (
        "test_operations.py",
        ("test_list_panel_imgs_returns_chain_with_images",),
    ),
    "delete_panel_img_by_id": (
        "test_operations.py",
        ("test_delete_panel_img_by_id",),
    ),
    "delete_all_panel_imgs": (
        "test_operations.py",
        ("test_delete_all_panel_imgs_removes_directory",),
    ),
    "delete_original_panel_img": (
        "test_operations.py",
        ("test_delete_original_panel_img_reports_unsupported",),
    ),
    "compress_panel_imgs": (
        "test_operations.py",
        ("test_compress_panel_imgs",),
    ),
    "resource_status": (
        "test_operations.py",
        ("test_resource_status_reports_manifest_state",),
    ),
    "download_resource": (
        "test_resource_service.py",
        ("test_download_all_reports_clone_and_update", "test_download_all_failures_are_visible"),
    ),
    "update_log": (
        "test_resource_service.py",
        ("test_update_log_shows_commits_or_visible_failure",),
    ),
}


def test_write_command_permissions_are_audited() -> None:
    """每条写入型命令的权限边界必须与审计清单一致，且全部已注册。"""

    specs = {spec.id: spec for spec in load_command_registry()}
    assert set(WRITE_COMMANDS) <= specs.keys()
    for command_id, expected in WRITE_COMMANDS.items():
        assert specs[command_id].permission == expected, command_id


def test_every_write_command_has_an_offline_contract_test_file() -> None:
    """写入型能力必须有离线契约测试文件且包含代表性用例。"""

    assert set(CONTRACT_COVERAGE) == set(WRITE_COMMANDS)
    for command_id, (file_name, test_names) in CONTRACT_COVERAGE.items():
        source = (TESTS_DIR / file_name).read_text(encoding="utf-8")
        for test_name in test_names:
            assert f"def {test_name}(" in source or f"async def {test_name}(" in source, (
                f"{command_id} 缺少离线契约用例 {test_name}"
            )


class FakeAccountTransport:
    """不触碰网络的账号 transport fixture。"""

    def __init__(self, page_url: str = "https://login.test/session") -> None:
        self.page_url = page_url
        self.actors: list[AccountActor] = []

    async def begin_login(self, actor: AccountActor) -> str:
        self.actors.append(actor)
        return self.page_url

    async def authenticate(self, attempt: LoginAttempt) -> LoginResult:
        raise AssertionError("离线契约不应触发登录终态 authenticate")


class FakeCheckinTransport:
    """不触碰网络的签到 transport fixture。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_sign_calendar(self, actor, uid, *, credential_user_id) -> SignCalendar:
        self.calls.append("get_sign_calendar")
        return SignCalendar(
            today_signed=False,
            user_gold=123,
            signin_time=3,
            day_awards=tuple(
                DayAward(
                    award_id=index,
                    period_id=9,
                    day_in_period=day,
                    award_name=f"奖励{day}",
                    award_num=5,
                    icon_url=f"icon://award-{day}",
                )
                for index, day in enumerate(range(1, 8))
            ),
            period=SignPeriod(period_id=9, name="周期甲", over_days=7, start_date=0, end_date=0),
            role_info=SignRoleInfo(role_id="101", role_name="角色甲", level=60),
        )

    async def game_sign(self, actor, uid, award, *, credential_user_id) -> SignStatus:
        self.calls.append("game_sign")
        return SignStatus.DONE

    async def get_task_process(self, actor, uid, *, credential_user_id) -> TaskProcess:
        self.calls.append("get_task_process")
        return TaskProcess(
            daily_tasks=(
                CommunityTask(mark_name="bbs_sign", remark="签到", complete_times=0, times=1),
            ),
        )

    async def bbs_sign(self, actor, uid, *, credential_user_id) -> SignStatus:
        self.calls.append("bbs_sign")
        return SignStatus.DONE

    async def have_sign_in(self, actor, uid, *, credential_user_id) -> int:
        self.calls.append("have_sign_in")
        return 12

    async def get_role_overview(self, actor, uid, *, credential_user_id):
        self.calls.append("get_role_overview")
        from src.modules.player.contracts import RoleOverview

        return RoleOverview(
            role_id="role-1",
            role_name="测试玩家",
            level=42,
            achievement_total=3,
            params=[],
            role_chars=[],
            ranged_weapons=[],
            close_weapons=[],
        )

    async def get_post_list(self, actor, uid, *, credential_user_id):
        self.calls.append("get_post_list")
        return ()

    async def get_post_detail(self, actor, uid, post, *, credential_user_id) -> bool:
        self.calls.append("get_post_detail")
        return True

    async def do_like(self, actor, uid, post, *, credential_user_id) -> bool:
        self.calls.append("do_like")
        return True

    async def do_share(self, actor, uid, *, credential_user_id) -> bool:
        self.calls.append("do_share")
        return True

    async def do_reply(self, actor, uid, post, *, credential_user_id) -> bool:
        self.calls.append("do_reply")
        return True


async def _database(tmp_path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "write-contracts.sqlite3")
    await database.create_schema_for_tests()
    return database


async def _account_service(db: AsyncDatabase) -> AccountService:
    return AccountService(
        db,
        FakeAccountTransport(),
        max_bind_count=3,
    )


async def _privacy_service(db: AsyncDatabase) -> PrivacyService:
    return PrivacyService(db, allow_mention_query=True)


async def _checkin_service(db: AsyncDatabase, tmp_path) -> CheckinService:
    return CheckinService(
        db,
        FakeCheckinTransport(),
        PrivacyService(db, allow_mention_query=True),
        CheckinRenderer(
            tmp_path / "rendered",
            EncyclopediaResourceStore.from_root(tmp_path / "resources"),
        ),
        game_enabled=True,
        community_enabled=True,
        community_tasks=("bbs_sign",),
        subscriptions=SubscriptionStore(tmp_path / "subscriptions.json"),
    )


class FakeNoticesTransport:
    """不触碰网络的密函/公告 transport fixture。"""

    async def get_mh(self, actor, uid, *, credential_user_id) -> MhSnapshot:
        return MhSnapshot()

    async def get_mh_any(self) -> MhSnapshot:
        return MhSnapshot()

    async def get_ann_list(self) -> AnnSnapshot:
        return AnnSnapshot()

    async def get_ann_detail(self, post_id: str) -> AnnDetail:
        return AnnDetail(post_id=post_id, title="", blocks=())


async def _notices_service(db: AsyncDatabase, tmp_path) -> NoticesService:
    return NoticesService(
        db,
        FakeNoticesTransport(),
        PrivacyService(db, allow_mention_query=True),
        NoticesRenderer(
            tmp_path / "rendered",
            EncyclopediaResourceStore.from_root(tmp_path / "resources"),
        ),
        subscriptions=SubscriptionStore(tmp_path / "subscriptions.json"),
        ann_state=AnnStateStore(tmp_path / "ann_state.json"),
        push=None,
    )


async def _services(db: AsyncDatabase, tmp_path) -> dict[str, object]:
    return {
        "account_service": await _account_service(db),
        "privacy_service": await _privacy_service(db),
        "checkin_service": await _checkin_service(db, tmp_path),
        "notices_service": await _notices_service(db, tmp_path),
        "panel_service": PanelService(
            tmp_path / "panel_custom",
            resource_root=tmp_path / "resources",
            resolve_char_id=lambda name: "101",
            panel_dir_for=lambda char_id: f"role-{char_id}",
        ),
    }


class _Event:
    """提供 AstrBot 公开事件方法的离线 fixture。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.unified_msg_origin = "platform:group:g1"

    def get_message_str(self) -> str:
        return self.text

    def get_sender_id(self) -> str:
        return "user-1"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> str:
        return "group-1"

    def get_messages(self) -> list:
        return []

    def plain_result(self, text: str) -> str:
        return text

    def chain_result(self, components: object) -> object:
        return components

    def image_result(self, image: object) -> object:
        return image


async def _dispatch(command_id: str, services: dict[str, object]) -> list:
    spec = load_command_registry().get(command_id)
    registry = CommandRegistry((spec,))

    class GeneratedWritePlugin:
        __module__ = "tests.generated_write_plugin"

    install_command_handlers(GeneratedWritePlugin, registry)
    plugin = GeneratedWritePlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services=services,
        ),
    )
    handler = getattr(plugin, f"handle_{command_id}")
    return [item async for item in handler(_Event(spec.examples[0]))]


@pytest.mark.asyncio
@pytest.mark.parametrize("command_id", sorted(WRITE_COMMANDS))
async def test_every_write_command_dispatches_offline(tmp_path, command_id: str) -> None:
    """每条写入型命令都能在 fake transport + 隔离 SQLite + 模拟事件下离线出结果。"""

    db = await _database(tmp_path)
    try:
        services = await _services(db, tmp_path)
        result = await _dispatch(command_id, services)
        assert len(result) == 1
        assert result[0] is not None
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_sign_write_touches_only_injected_transport(tmp_path) -> None:
    """离线签到的写路径只调用注入的 fake transport，不触碰真实网络边界。"""

    db = await _database(tmp_path)
    try:
        async with db.transaction() as session:
            await AccountBindingRepository.add(
                session,
                user_id="user-1",
                bot_id="bot-1",
                uid="1234567890123",
                group_id="group-1",
                is_active=True,
            )
        services = await _services(db, tmp_path)
        result = await _dispatch("sign", services)
        service = cast(CheckinService, services["checkin_service"])
        transport = cast(FakeCheckinTransport, service.transport)
        assert len(result) == 1
        assert {"get_sign_calendar", "game_sign", "get_task_process", "bbs_sign"} <= set(
            transport.calls
        )
    finally:
        await db.dispose()
