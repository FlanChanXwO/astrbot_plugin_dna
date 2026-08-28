"""Goal 2 / Task 12：Dashboard Admin Web 路由与认证边界契约。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from astrbot.api.web import PluginRequest, bind_request_context
from astrbot.dashboard.api.plugins import _match_registered_web_api
from starlette.datastructures import Headers, QueryParams

from src.entry.admin_web import ADMIN_WEB_PREFIX, AdminWebAdapter, _response
from src.infrastructure.persistence import AsyncDatabase
from src.modules.admin import (
    AdminAccount,
    AdminAccountService,
    AdminApiResponse,
    AdminError,
    AdminErrorCode,
    CredentialPayload,
    AdminPreviewService,
    MembershipCapability,
)


class _RawRequest:
    """为 AstrBot PluginRequest 提供最小可用的 Starlette 请求形状。"""

    def __init__(self, *, method: str = "GET", payload: object = None) -> None:
        self.method = method
        self.url = SimpleNamespace(path=f"{ADMIN_WEB_PREFIX}/bootstrap")
        self.headers = Headers({"content-type": "application/json"})
        self.cookies: dict[str, str] = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.query_params = QueryParams()
        self._payload = payload

    async def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _response_body(response) -> dict[str, object]:
    return json.loads(response.body)


def _request_context(
    *,
    username: str | None,
    method: str = "GET",
    payload: object = None,
):
    request = PluginRequest(
        _RawRequest(method=method, payload=payload),
        username=username,
    )
    return bind_request_context(request)


def test_admin_routes_are_unique_and_dashboard_scoped() -> None:
    adapter = AdminWebAdapter({})

    routes = adapter.routes()
    route_keys = {
        (route.path, method.upper()) for route in routes for method in route.methods
    }

    assert routes
    assert len(route_keys) == sum(len(route.methods) for route in routes)
    assert {route.path.split("/")[3] for route in routes} >= {
        "bootstrap",
        "accounts",
        "tasks",
        "targets",
        "members",
        "panels",
        "aliases",
    }
    assert all(route.path.startswith(f"{ADMIN_WEB_PREFIX}/") for route in routes)


def test_literal_user_account_routes_precede_uid_routes() -> None:
    adapter = AdminWebAdapter({})
    registered = [
        (route.path, route.handler, list(route.methods), route.description)
        for route in adapter.routes()
    ]

    for path, method, expected_handler, expected_params in (
        (
            f"{ADMIN_WEB_PREFIX}/accounts/users/user-1/delete-preview",
            "GET",
            "preview_delete_user",
            {"user_id": "user-1"},
        ),
        (
            f"{ADMIN_WEB_PREFIX}/accounts/users/user-1/delete",
            "POST",
            "delete_user",
            {"user_id": "user-1"},
        ),
    ):
        matched = _match_registered_web_api(registered, path, method)
        assert matched is not None
        handler, params = matched
        assert handler.__name__ == expected_handler
        assert params == expected_params


@pytest.mark.parametrize(
    ("code", "status_code", "message"),
    (
        (AdminErrorCode.VALIDATION, 400, "请求参数无效"),
        (AdminErrorCode.CONFLICT, 409, "操作与当前状态冲突"),
        (AdminErrorCode.UNSUPPORTED, 501, "当前平台不支持此操作"),
        (AdminErrorCode.NOT_FOUND, 404, "资源不存在"),
        (AdminErrorCode.UPSTREAM, 502, "上游服务暂时不可用，请稍后重试"),
        (AdminErrorCode.PARTIAL, 207, "操作部分完成，请核对结果后重试"),
        (AdminErrorCode.INTERNAL, 500, "管理服务内部错误，请稍后重试"),
    ),
)
def test_admin_error_codes_map_to_safe_http_responses(
    code: AdminErrorCode,
    status_code: int,
    message: str,
) -> None:
    response = _response(
        AdminApiResponse.failure(AdminError(code, "内部路径 /srv/secret token=secret"))
    )

    assert response.status_code == status_code
    assert response.headers["cache-control"] == "no-store"
    assert _response_body(response)["error"]["message"] == message  # type: ignore[index]


@pytest.mark.asyncio
async def test_admin_web_requires_dashboard_username_before_service_call() -> None:
    class _MustNotRun:
        async def membership_capability(self):
            raise AssertionError("unauthenticated request reached the service")

    adapter = AdminWebAdapter({"admin_api_service": _MustNotRun()})

    with _request_context(username=None):
        response = await adapter.bootstrap()

    body = _response_body(response)
    assert response.status_code == 401
    assert body["ok"] is False
    assert body["error"]["code"] == "unauthorized"  # type: ignore[index]
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_bootstrap_exposes_metadata_version_and_membership_capability() -> None:
    class _AdminApi:
        async def membership_capability(self):
            return AdminApiResponse.success(
                MembershipCapability(True, platform="aiocqhttp")
            )

    adapter = AdminWebAdapter({"admin_api_service": _AdminApi()})

    with _request_context(username="dashboard-admin"):
        response = await adapter.bootstrap()

    body = _response_body(response)
    assert response.status_code == 200
    assert body["ok"] is True
    data = cast(dict[str, Any], body["data"])
    assert data["version"] == "v0.1.0"
    assert data["capabilities"]["membership_probe"]["supported"] is True


@pytest.mark.asyncio
async def test_bootstrap_does_not_hide_membership_service_failure() -> None:
    class _BrokenAdminApi:
        async def membership_capability(self):
            return AdminApiResponse.failure(
                AdminError(AdminErrorCode.INTERNAL, "内部详情不应返回")
            )

    adapter = AdminWebAdapter({"admin_api_service": _BrokenAdminApi()})

    with _request_context(username="dashboard-admin"):
        response = await adapter.bootstrap()

    body = _response_body(response)
    assert response.status_code == 500
    assert body == {
        "ok": False,
        "error": {
            "code": "internal",
            "message": "管理服务内部错误，请稍后重试",
        },
    }


@pytest.mark.asyncio
async def test_account_detail_explicitly_returns_credentials_with_no_store() -> None:
    account = AdminAccount(
        user_id="user-1",
        uid="uid-1",
        group_id=None,
        is_active=True,
        has_app_credentials=True,
        has_web_credentials=True,
        credentials=CredentialPayload(
            app_cookie="app-secret",
            web_token="web-secret",
        ),
    )

    class _Accounts:
        async def get_account(
            self, user_id: str, uid: str, *, include_credentials=True
        ):
            assert (user_id, uid) == ("user-1", "uid-1")
            assert include_credentials is True
            return AdminApiResponse.success(account)

    adapter = AdminWebAdapter({"admin_account_service": _Accounts()})

    with _request_context(username="dashboard-admin"):
        response = await adapter.get_account("user-1", "uid-1")

    body = _response_body(response)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = cast(dict[str, Any], body["data"])
    assert data["credentials"] == {
        "app_cookie": "app-secret",
        "app_device_code": "",
        "app_d_num": "",
        "app_refresh_token": "",
        "app_status": "",
        "web_token": "web-secret",
        "web_device_code": "",
        "web_d_num": "",
        "web_refresh_token": "",
        "web_status": "",
    }


@pytest.mark.asyncio
async def test_internal_exception_is_mapped_without_exception_details() -> None:
    class _Tasks:
        async def list_tasks(self):
            raise RuntimeError("/srv/private/dnaby.sqlite3 token=secret-value")

    adapter = AdminWebAdapter({"admin_api_service": _Tasks()})

    with _request_context(username="dashboard-admin"):
        response = await adapter.list_tasks()

    body = _response_body(response)
    serialized = json.dumps(body, ensure_ascii=False)
    assert response.status_code == 500
    assert body["ok"] is False
    assert body["error"]["code"] == "internal"  # type: ignore[index]
    assert "/srv/private" not in serialized
    assert "secret-value" not in serialized


@pytest.mark.asyncio
async def test_task_permanent_delete_requires_explicit_confirmation() -> None:
    class _Tasks:
        def __init__(self) -> None:
            self.calls = 0

        async def delete_task(self, task_id: str):
            self.calls += 1
            return AdminApiResponse.success({"id": task_id})

    service = _Tasks()
    adapter = AdminWebAdapter({"admin_api_service": service})

    with _request_context(username="dashboard-admin", method="POST", payload={}):
        rejected = await adapter.delete_task("dnaby_sign_daily")
    assert rejected.status_code == 400
    assert service.calls == 0
    assert _response_body(rejected)["error"]["code"] == "validation"  # type: ignore[index]

    with _request_context(
        username="dashboard-admin",
        method="POST",
        payload={"confirmed": True},
    ):
        accepted = await adapter.delete_task("dnaby_sign_daily")
    assert accepted.status_code == 200
    assert service.calls == 1


@pytest.mark.asyncio
async def test_build_runtime_wires_admin_web_services_and_registers_once(
    tmp_path,
) -> None:
    from src.bootstrap import build_runtime

    registered: list[tuple[str, object, list[str], str]] = []

    def register_web_api(
        route: str,
        handler: object,
        methods: list[str],
        description: str,
    ) -> None:
        registered.append((route, handler, methods, description))

    context = SimpleNamespace(
        register_web_api=register_web_api,
    )
    runtime = build_runtime(
        context,
        {},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    assert isinstance(runtime.services["admin_account_service"], AdminAccountService)
    assert isinstance(runtime.services["admin_preview_service"], AdminPreviewService)

    await runtime.initialize()
    await runtime.initialize()
    await runtime.terminate()
    await runtime.terminate()

    assert registered
    assert len({(args[0], tuple(args[2])) for args in registered}) == len(registered)
