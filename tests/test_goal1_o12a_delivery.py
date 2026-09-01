"""O12-A 公告投递状态、失败重试与跨功能缓存隔离契约。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices import messages
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore
from src.modules.notices.ann_state import AnnStateStore
from src.modules.notices.contracts import AnnBlock, AnnDetail, NoticesTransportError
from src.utils import utils as utils_module
from src.utils.api.request_util import DNAApiResp
from src.utils.api.requests import DNAApi
from tests.test_notices import _ann_snapshot
from tests.test_notices_subscriptions import _database_with_binding, _request, _service


class _AnnouncementTransport:
    def __init__(self, *, detail_error: Exception | None = None) -> None:
        self.detail_error = detail_error
        self.detail_calls = 0

    async def get_ann_list(self):
        return _ann_snapshot()

    async def get_ann_detail(self, post_id: str):
        self.detail_calls += 1
        if self.detail_error is not None:
            raise self.detail_error
        return AnnDetail(
            post_id=post_id,
            title=f"公告 {post_id}",
            blocks=(AnnBlock(kind="text", text="正文"),),
        )


class _AnnouncementRenderer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = 0

    async def render_ann_detail(self, detail: AnnDetail):
        self.calls += 1
        path = self.root / f"{detail.post_id}.png"
        self.root.mkdir(parents=True, exist_ok=True)
        path.touch()
        return SimpleNamespace(path=path)


@pytest.mark.asyncio
async def test_announcement_partial_target_failure_is_retried_without_resending_success(
    tmp_path: Path,
) -> None:
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    legacy = AnnStateStore(tmp_path / "ann_state.json")
    await legacy.merge([1000, 1002])
    await subscriptions.add(
        messages.ANN_SUBSCRIBE,
        provenance="chat_command",
        origin="platform:group:fail",
        user_id="user-1",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.ANN_SUBSCRIBE,
        provenance="chat_command",
        origin="platform:group:ok",
        user_id="user-2",
        bot_id="bot-1",
    )

    failed = {"platform:group:fail"}
    pushed: list[str] = []

    async def push(origin: str, _payload: object) -> None:
        if origin in failed:
            raise ConnectionError("temporary delivery failure")
        pushed.append(origin)

    transport = _AnnouncementTransport()
    service = _service(
        database,
        transport,
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    renderer = _AnnouncementRenderer(tmp_path / "rendered")
    service.renderer = renderer

    first = await service.poll_ann_now()
    failed.clear()
    second = await service.poll_ann_now()

    assert first == 1
    assert second == 1
    assert pushed == ["platform:group:ok", "platform:group:fail"]
    assert renderer.calls == 2
    persisted_legacy = AnnStateStore(tmp_path / "ann_state.json")
    assert 1001 in await persisted_legacy.known_ids()
    state = json.loads((tmp_path / "ann_delivery_state.json").read_text())
    record = state["announcements"]["1001"]
    assert set(record["observed_targets"]) == {
        "platform:group:fail",
        "platform:group:ok",
    }
    assert set(record["delivered_targets"]) == set(record["observed_targets"])
    await database.dispose()


@pytest.mark.asyncio
async def test_announcement_delivery_does_not_backfill_target_added_after_first_observation(
    tmp_path: Path,
) -> None:
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    legacy = AnnStateStore(tmp_path / "ann_state.json")
    await legacy.merge([1000, 1002])
    await subscriptions.add(messages.ANN_SUBSCRIBE, provenance="chat_command", origin="platform:group:first")
    failed = True
    pushed: list[str] = []

    async def push(origin: str, _payload: object) -> None:
        nonlocal failed
        if origin == "platform:group:first" and failed:
            raise ConnectionError("temporary delivery failure")
        pushed.append(origin)

    transport = _AnnouncementTransport()
    service = _service(
        database,
        transport,
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    service.renderer = _AnnouncementRenderer(tmp_path / "rendered")

    assert await service.poll_ann_now() == 0
    await subscriptions.add(messages.ANN_SUBSCRIBE, provenance="chat_command", origin="platform:group:late")
    failed = False

    assert await service.poll_ann_now() == 1
    assert pushed == ["platform:group:first"]
    await database.dispose()


@pytest.mark.asyncio
async def test_announcement_detail_failure_skips_round_and_retries_without_title_fallback(
    tmp_path: Path,
) -> None:
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    legacy = AnnStateStore(tmp_path / "ann_state.json")
    await legacy.merge([1000, 1002])
    await subscriptions.add(messages.ANN_SUBSCRIBE, provenance="chat_command", origin="platform:group:g1")
    transport = _AnnouncementTransport(detail_error=RuntimeError("bad detail"))
    pushed: list[object] = []

    async def push(_origin: str, payload: object) -> None:
        pushed.append(payload)

    service = _service(
        database,
        transport,
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    service.renderer = _AnnouncementRenderer(tmp_path / "rendered")

    assert await service.poll_ann_now() == 0
    assert pushed == []
    transport.detail_error = None

    assert await service.poll_ann_now() == 1
    assert len(pushed) == 1
    assert isinstance(pushed[0], Path)
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_announcement_detail_failure_uses_fixed_message(
    tmp_path: Path,
) -> None:
    database = await _database_with_binding(tmp_path)
    transport = _AnnouncementTransport(
        detail_error=NoticesTransportError(
            "network",
            resource="公告详情",
            detail="secret upstream response",
        ),
    )
    service = _service(database, transport, tmp_path)

    response = await service.ann(_request("公告 1", {"index": "1"}))

    assert response.text == messages.ANN_DETAIL_FAILED
    await database.dispose()


@pytest.mark.asyncio
async def test_legacy_announcement_ids_are_migrated_as_processed_without_backfill(
    tmp_path: Path,
) -> None:
    legacy = AnnStateStore(tmp_path / "ann_state.json")
    await legacy.merge([1001, 1002])

    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    await delivery.migrate_legacy_ids(await legacy.known_ids())

    records = await delivery.records()
    assert records["1001"].legacy_processed is True
    assert records["1002"].legacy_processed is True
    assert await delivery.pending_targets("1001", ["platform:group:new"]) == ()


@pytest.mark.asyncio
async def test_legacy_announcement_state_rejects_non_list_without_silent_reset(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ann_state.json"
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="公告状态文件损坏"):
        await AnnStateStore(path).known_ids()


@pytest.mark.asyncio
async def test_delivery_state_rolls_back_memory_when_persisting_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    original_save = delivery._save_unlocked

    def fail_save() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(delivery, "_save_unlocked", fail_save)
    with pytest.raises(OSError, match="disk full"):
        await delivery.pending_targets("1001", ["platform:group:first"])

    monkeypatch.setattr(delivery, "_save_unlocked", original_save)
    assert await delivery.pending_targets("1001", ["platform:group:retry"]) == (
        "platform:group:retry",
    )


@pytest.mark.asyncio
async def test_timed_async_cache_supports_parameterized_keys() -> None:
    calls: list[str] = []

    @utils_module.timed_async_cache(3600, key_builder=lambda value: value)
    async def read(value: str) -> str:
        calls.append(value)
        return value

    assert await read("a") == "a"
    assert await read("b") == "b"
    assert await read("a") == "a"
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_public_ip_does_not_cache_fallback_and_isolates_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, value: str) -> None:
            self.text = value

        def json(self) -> dict[str, str]:
            return {"ip": self.text, "origin": self.text}

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            raise httpx.HTTPError("network down")

    monkeypatch.setattr(utils_module.httpx, "AsyncClient", FailingClient)
    fallback = await utils_module.get_public_ip("cache-fallback-host")
    assert fallback == "cache-fallback-host"

    class SuccessClient:
        value = "203.0.113.10"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response(self.value)

    monkeypatch.setattr(utils_module.httpx, "AsyncClient", SuccessClient)
    assert await utils_module.get_public_ip("cache-fallback-host") == "203.0.113.10"

    SuccessClient.value = "203.0.113.11"
    assert await utils_module.get_public_ip("cache-host-a") == "203.0.113.11"
    SuccessClient.value = "203.0.113.12"
    assert await utils_module.get_public_ip("cache-host-b") == "203.0.113.12"


@pytest.mark.asyncio
async def test_api_caches_are_isolated_by_credentials_and_api_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.utils.api.requests as requests_module

    api = DNAApi()
    responses = iter(
        [
            DNAApiResp.ok(data={"seen": "a"}),
            DNAApiResp.ok(data={"seen": "b"}),
            DNAApiResp.ok(data={"seen": "c"}),
            DNAApiResp.ok(data={"seen": "d"}),
            DNAApiResp.ok(data={"key": "rsa-a"}),
            DNAApiResp.ok(data={"key": "rsa-b"}),
        ],
    )
    calls: list[tuple[str, str | None]] = []

    async def request(
        url: str,
        _method: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs,
    ):
        headers = headers or kwargs.get("header", {})
        calls.append((url, headers.get("token")))
        return next(responses)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(api, "_dna_request", request)
    monkeypatch.setattr(requests_module.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        requests_module,
        "LOGIN_LOG_URL",
        "https://login-cache-a.example/user/login/log",
    )

    first = await api.login_log("token-a", "dev-a")
    second = await api.login_log("token-b", "dev-b")
    assert first.data == {"seen": "a"}
    assert second.data == {"seen": "b"}

    user_a = SimpleNamespace(
        user_id="user-a",
        bot_id="bot-a",
        uid="uid-a",
        cookie="post-token-a",
        dev_code="post-dev-a",
        status="",
        d_num="",
        refresh_token="",
    )
    user_b = SimpleNamespace(
        user_id="user-b",
        bot_id="bot-b",
        uid="uid-b",
        cookie="post-token-b",
        dev_code="post-dev-b",
        status="",
        d_num="",
        refresh_token="",
    )
    post_cache_key = requests_module._post_list_cache_key(api, user_a)
    for raw_identity in ("user-a", "bot-a", "uid-a", "post-token-a", "post-dev-a"):
        assert raw_identity not in post_cache_key
    monkeypatch.setattr(
        requests_module,
        "GET_POST_LIST_URL",
        "https://post-cache-a.example/forum/list",
    )
    post_a = await api.get_post_list(user_a)
    post_b = await api.get_post_list(user_b)
    assert post_a.data == {"seen": "c"}
    assert post_b.data == {"seen": "d"}
    assert calls[:4] == [
        ("https://login-cache-a.example/user/login/log", "token-a"),
        ("https://login-cache-a.example/user/login/log", "token-b"),
        ("https://post-cache-a.example/forum/list", "post-token-a"),
        ("https://post-cache-a.example/forum/list", "post-token-b"),
    ]

    monkeypatch.setattr(
        requests_module,
        "GET_RSA_PUBLIC_KEY_URL",
        "https://rsa-cache-a.example/config/getRsaPublicKey",
    )
    rsa_a = await api.get_rsa_public_key()
    monkeypatch.setattr(
        requests_module,
        "GET_RSA_PUBLIC_KEY_URL",
        "https://rsa-cache-b.example/config/getRsaPublicKey",
    )
    rsa_b = await api.get_rsa_public_key()
    assert rsa_a == "rsa-a"
    assert rsa_b == "rsa-b"


@pytest.mark.asyncio
async def test_login_start_logs_and_errors_do_not_include_auth_or_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.modules.account.transport as transport_module

    class Response:
        status_code = 200
        text = ""

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    logs: list[str] = []
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(transport_module.logger, "debug", lambda message: logs.append(message))
    await transport_module._Base("https://login.example").start(
        auth="secret-auth",
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-1",
    )
    assert all("secret-auth" not in message for message in logs)

    class ErrorClient(Client):
        async def post(self, *_args, **_kwargs):
            response = Response()
            response.status_code = 502
            response.text = "secret-response-body"
            return response

    monkeypatch.setattr(transport_module.httpx, "AsyncClient", ErrorClient)
    with pytest.raises(transport_module.TransportError) as error:
        await transport_module._Base("https://login.example").start(
            auth="secret-auth",
            user_id="user-1",
            bot_id="bot-1",
            group_id="group-1",
        )
    assert "secret-response-body" not in str(error.value)
