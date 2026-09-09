"""Dashboard 紧凑表格改造的服务端分页契约测试。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from src.infrastructure.scheduler_state import (
    SchedulerRegistry,
    SchedulerTaskDefinition,
)
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.admin import (
    AdminAccount,
    AdminAccountService,
    AdminAliasService,
    AdminApiResponse,
    AdminApiService,
    AdminPage,
    AdminPagination,
    CredentialPayload,
    MembershipCapability,
    MembershipProbeResult,
    MembershipScanResult,
    MembershipStatus,
)
from src.modules.notices import messages as notices_messages


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


async def _seed_account(
    database: AsyncDatabase,
    *,
    user_id: str,
    uid: str,
    group_id: str | None = None,
    is_active: bool = True,
    credentials: CredentialPayload | None = None,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            group_id=group_id,
            is_active=is_active,
        )
        if credentials is not None:
            await CredentialRepository.add(
                session,
                user_id=user_id,
                uid=uid,
                **credentials.to_plaintext_dict(),
            )


def test_admin_pagination_validates_supported_page_sizes_and_serializes_empty_pages() -> None:
    assert AdminPagination().page == 1
    assert AdminPagination(page=2, page_size=50, search="  Alpha ").search == "Alpha"

    with pytest.raises(ValueError):
        AdminPagination(page=0)
    with pytest.raises(ValueError):
        AdminPagination(page_size=15)

    page = AdminPage.from_items((), AdminPagination(page=3, page_size=20))
    assert page.items == ()
    assert page.page == 3
    assert page.total == 0
    assert page.total_pages == 0
    assert page.to_dict() == {
        "items": [],
        "page": 3,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }


@pytest.mark.asyncio
async def test_account_page_filters_binding_pairs_and_only_loads_current_page_credentials(
    database: AsyncDatabase,
) -> None:
    secret = CredentialPayload(app_cookie="only-this-page-secret")
    await _seed_account(
        database,
        user_id="alpha",
        uid="1001",
        group_id="group-a",
        credentials=secret,
    )
    await _seed_account(
        database,
        user_id="alpha",
        uid="1002",
        group_id="group-b",
        is_active=False,
    )
    await _seed_account(
        database,
        user_id="beta",
        uid="2001",
        group_id="group-c",
    )

    response = await AdminAccountService(database).list_accounts_page(
        AdminPagination(page=1, page_size=10, search="alpha"),
        include_credentials=True,
    )

    assert response.ok is True
    assert response.data is not None
    assert [(item.user_id, item.uid) for item in response.data.items] == [
        ("alpha", "1001"),
        ("alpha", "1002"),
    ]
    assert response.data.total == 2
    assert response.data.total_pages == 1
    assert response.data.items[0].credentials is not None
    assert response.data.items[0].credentials.app_cookie == "only-this-page-secret"


@pytest.mark.asyncio
async def test_alias_page_searches_canonical_default_custom_and_effective_values(
    tmp_path: Path,
) -> None:
    default_path = tmp_path / "alias" / "char_alias.json"
    default_path.parent.mkdir(parents=True)
    default_path.write_text(
        '{"角色甲": ["默认甲"], "角色乙": ["默认乙"]}',
        encoding="utf-8",
    )
    custom_path = tmp_path / "alias_custom.json"
    custom_path.write_text('{"角色甲": ["自定义甲"]}', encoding="utf-8")
    service = AdminAliasService(default_path, custom_path=custom_path)

    response = await service.list_role_aliases_page(
        AdminPagination(page=1, page_size=10, search="自定义甲")
    )

    assert response.ok is True
    assert response.data is not None
    assert [item.canonical_name for item in response.data.items] == ["角色甲"]
    assert response.data.items[0].effective_aliases == ("默认甲", "自定义甲")


@pytest.mark.asyncio
async def test_target_page_filters_task_before_paging_and_supports_search(
    tmp_path: Path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:one",
        group_id="one",
        uid="u1",
    )
    await subscriptions.add(
        notices_messages.ANN_SUBSCRIBE,
        origin="group:two",
        group_id="two",
        uid="u2",
    )
    registry = SchedulerRegistry(tmp_path / "scheduler.json")
    registry.register(
        SchedulerTaskDefinition(
            id="dnaby_mh_push",
            name="密函推送",
            schedule="hourly@00:00",
        )
    )
    api = AdminApiService(registry, subscriptions)

    response = await api.list_targets_page(
        "dnaby_mh_push",
        AdminPagination(page=1, page_size=10, search="group:one"),
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data.total == 1
    assert response.data.items[0].unified_msg_origin == "group:one"


@pytest.mark.asyncio
async def test_membership_page_keeps_full_scan_safety_flags_when_results_are_sliced(
    tmp_path: Path,
) -> None:
    full_scan = MembershipScanResult(
        user_id="user-1",
        results=(
            MembershipProbeResult("user-1", "group-1", MembershipStatus.ABSENT),
            MembershipProbeResult("user-1", "group-2", MembershipStatus.UNKNOWN),
        ),
        capability=MembershipCapability(True, platform="aiocqhttp"),
    )

    class MembershipStub:
        async def scan_user(self, user_id: str):
            assert user_id == "user-1"
            return AdminApiResponse.success(full_scan)

    registry = SchedulerRegistry(tmp_path / "scheduler.json")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    api = AdminApiService(registry, subscriptions, membership_service=MembershipStub())

    response = await api.scan_members(
        "user-1",
        AdminPagination(page=1, page_size=10),
    )

    assert response.ok is True
    assert response.data is not None
    assert len(response.data.items) == 2
    assert len(response.data.results) == 2
    assert response.data.total == 2
    assert response.data.has_unknown is True
    assert response.data.can_delete_user is False


def test_dashboard_uses_compact_tables_pagination_modals_dynamic_brand_and_no_icon_glyphs() -> None:
    page_root = Path(__file__).parents[1] / "pages" / "dashboard"
    html = (page_root / "index.html").read_text(encoding="utf-8")
    bridge = (page_root / "js" / "bridge.js").read_text(encoding="utf-8")
    store = (page_root / "js" / "store.js").read_text(encoding="utf-8")
    app = (page_root / "app.js").read_text(encoding="utf-8")
    css = (page_root / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert "logo.png" in html
    assert "狩月终端" in html or "狩月终端" in store
    assert "getContext" in bridge
    assert "displayName" in bridge
    assert html.lower().count("<svg") == 0
    assert all(icon not in html for icon in ("×", "⌄", ">!</"))
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert '@keydown="handleKeydown"' in html
    assert "handleKeydown" in store
    assert 'document.addEventListener("keydown"' in app
    assert 'class="modal' in html
    assert 'class="data-table' in html
    assert "pageSizeOptions" in store
    assert "page_size" in bridge
    assert "accountPage" in store
    assert "aliasPage" in store
    assert "targetPage" in store
    assert "memberPage" in store
    assert "@media (max-width: 767px)" in css
    assert "data-label" in css
    assert "calc(100% - var(--sidebar-width))" in css


def test_admin_web_pagination_query_defaults_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.entry import admin_web

    monkeypatch.setattr(
        admin_web,
        "request",
        SimpleNamespace(query={"page": "2", "page_size": "50", "search": " role "}),
    )
    pagination = admin_web._pagination_from_query()
    assert pagination == AdminPagination(page=2, page_size=50, search="role")

    monkeypatch.setattr(
        admin_web,
        "request",
        SimpleNamespace(query={"page_size": "15"}),
    )
    with pytest.raises(admin_web._RequestValidation):
        admin_web._pagination_from_query()


@pytest.mark.asyncio
async def test_admin_web_routes_paginated_accounts_and_redacts_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.entry import admin_web

    captured: dict[str, object] = {}

    class AccountServiceStub:
        async def list_accounts_page(
            self,
            pagination: AdminPagination,
            *,
            include_credentials: bool,
        ) -> AdminApiResponse[AdminPage]:
            captured["pagination"] = pagination
            captured["include_credentials"] = include_credentials
            account = AdminAccount(
                user_id="alpha",
                uid="1001",
                group_id="group-a",
                is_active=True,
                has_app_credentials=True,
                app_status="已配置",
                credentials=CredentialPayload(app_cookie="must-not-leak"),
            )
            return AdminApiResponse.success(
                AdminPage.from_items(
                    (account,),
                    pagination,
                    total=21,
                )
            )
    monkeypatch.setattr(
        admin_web,
        "request",
        SimpleNamespace(
            username="dashboard-admin",
            query={
                "page": "2",
                "page_size": "20",
                "search": " alpha ",
                "include_credentials": "false",
            },
        ),
    )
    response = await admin_web.AdminWebAdapter(
        {"admin_account_service": AccountServiceStub()}
    ).list_accounts()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert captured["pagination"] == AdminPagination(page=2, page_size=20, search="alpha")
    assert captured["include_credentials"] is False
    body = json.loads(response.body)
    assert body["data"]["page"] == 2
    assert body["data"]["page_size"] == 20
    assert body["data"]["total"] == 21
    assert body["data"]["total_pages"] == 2
    assert body["data"]["items"][0]["credentials"] is None


@pytest.mark.asyncio
async def test_admin_web_rejects_invalid_page_size_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.entry import admin_web

    class MustNotRun:
        async def list_accounts_page(self, *args: object, **kwargs: object):
            raise AssertionError("invalid pagination reached service")

    monkeypatch.setattr(
        admin_web,
        "request",
        SimpleNamespace(
            username="dashboard-admin",
            query={"page_size": "15"},
        ),
    )
    response = await admin_web.AdminWebAdapter(
        {"admin_account_service": MustNotRun()}
    ).list_accounts()

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body)["error"]["code"] == "validation"
