"""Goal 6 T19：跨 runtime 恢复与 legacy 官方 WS 代理回归契约。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from src.bootstrap import build_runtime
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.checkin import messages as checkin_messages
from src.modules.checkin.contracts import (
    DayAward,
    SignCalendar,
    SignStatus,
    TaskProcess,
)
from src.utils.api.requests import DNAApi
from src.utils.api import ws_manager as ws_manager_module


class _AppTransportSpy:
    """捕获统一 App transport 的 typed 网络配置和关闭调用。"""

    def __init__(self) -> None:
        self.network: tuple[str, str] | None = None
        self.close_calls = 0

    def set_network(self, *, api_base_url: str, proxy_url: str) -> None:
        self.network = (api_base_url, proxy_url)

    async def close(self) -> None:
        self.close_calls += 1


class _FakeWebSocketApp:
    """只记录 websocket-client 实际收到的 run_forever 参数。"""

    instances: list[_FakeWebSocketApp] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.run_options: dict[str, Any] | None = None
        self.run_started = threading.Event()
        self.closed = False
        self.__class__.instances.append(self)

    def run_forever(self, **options: Any) -> None:
        self.run_options = options
        self.run_started.set()

    def close(self) -> None:
        self.closed = True


def _build_legacy_ws_probe(
    monkeypatch: pytest.MonkeyPatch,
    proxy_url: str,
) -> tuple[
    DNAApi, _AppTransportSpy, ws_manager_module.WebSocketManager, _FakeWebSocketApp
]:
    """从 DNAApi 公共配置入口启动一次 legacy 业务 WS。"""

    manager = ws_manager_module.WebSocketManager()
    transport = _AppTransportSpy()
    _FakeWebSocketApp.instances = []
    monkeypatch.setattr(ws_manager_module, "_ws_manager", manager)
    monkeypatch.setattr(ws_manager_module.websocket, "WebSocketApp", _FakeWebSocketApp)
    monkeypatch.setattr(manager, "_start_heartbeat", lambda *_args: None)

    api = DNAApi(app_transport=transport)  # type: ignore[arg-type]
    api.configure_network(
        api_base_url="https://api.example.test",
        proxy_url=proxy_url,
    )
    connection = manager.get_connection("token", "device")
    assert connection is not None
    fake = _FakeWebSocketApp.instances[0]
    assert fake.run_started.wait(2)
    return api, transport, manager, fake


def test_dna_api_configures_legacy_ws_with_same_proxy_and_closes_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """typed proxy_url 必须同时进入 REST facade 和 legacy 官方 WS。"""

    proxy_url = "http://user:p%40ss@proxy.example.test:18080"
    api, transport, manager, fake = _build_legacy_ws_probe(monkeypatch, proxy_url)

    assert transport.network == ("https://api.example.test", proxy_url)
    assert fake.run_options is not None
    assert fake.run_options["http_proxy_host"] == "proxy.example.test"
    assert fake.run_options["http_proxy_port"] == 18080
    assert fake.run_options["proxy_type"] == "http"
    assert fake.run_options["http_proxy_auth"] == ("user", "p@ss")

    import asyncio

    asyncio.run(api.close())

    assert transport.close_calls == 1
    assert fake.closed is True
    assert manager.get_active_tokens() == []


def test_dna_api_empty_proxy_forces_legacy_ws_direct_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空代理必须显式覆盖宿主代理环境，保持 legacy WS 直连。"""

    api, transport, manager, fake = _build_legacy_ws_probe(monkeypatch, "")

    assert transport.network == ("https://api.example.test", "")
    assert fake.run_options is not None
    assert fake.run_options["http_no_proxy"] == ["*"]
    assert "http_proxy_host" not in fake.run_options
    assert "proxy_type" not in fake.run_options

    import asyncio

    asyncio.run(api.close())

    assert transport.close_calls == 1
    assert fake.closed is True
    assert manager.get_active_tokens() == []


class _RuntimeContext:
    """只提供 runtime 组装、生命周期和签到摘要推送所需的宿主接口。"""

    def __init__(self) -> None:
        self.sent_origins: list[str] = []

    def register_web_api(self, *_args: object) -> None:
        return None

    async def send_message(self, origin: str, _message: object) -> None:
        self.sent_origins.append(origin)


class _RestartCheckinTransport:
    """跨 runtime 测试用的最小离线签到 transport。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_sign_calendar(
        self,
        _actor: object,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignCalendar:
        assert credential_user_id
        self.calls.append(("calendar", uid))
        return SignCalendar(
            today_signed=False,
            signin_time=0,
            day_awards=(
                DayAward(
                    award_id=1,
                    period_id=1,
                    day_in_period=1,
                    award_name="测试奖励",
                    award_num=1,
                ),
            ),
        )

    async def game_sign(
        self,
        _actor: object,
        uid: str,
        _award: DayAward,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        assert credential_user_id
        self.calls.append(("game", uid))
        return SignStatus.DONE

    async def get_task_process(
        self,
        _actor: object,
        uid: str,
        *,
        credential_user_id: str,
    ) -> TaskProcess:
        raise AssertionError(
            f"社区任务不应在空任务配置下调用: {uid}/{credential_user_id}"
        )


def _restart_runtime_config() -> dict[str, object]:
    return {
        "login": {"transport": "local", "port": 0},
        "sign_in": {
            "community_tasks": [],
            "concurrency_interval_seconds": [0, 0],
        },
        "notifications": {"announcement_enabled": False},
        "client_updates": {"enabled": False},
    }


@pytest.mark.asyncio
async def test_runtime_restart_restores_auto_sign_selection_and_subscription(
    tmp_path: Path,
) -> None:
    """runtime A 终止后，runtime B 必须恢复 UID 开关和旧签到结果订阅。"""

    db_path = tmp_path / "dnaby.sqlite3"
    database_a = AsyncDatabase(db_path)
    await database_a.create_schema_for_tests()
    async with database_a.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-disabled",
            uid="uid-disabled",
            auto_sign_enabled=False,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-enabled",
            uid="uid-enabled",
            auto_sign_enabled=True,
        )

    subscription_path = tmp_path / "subscriptions.json"
    old_subscriptions = SubscriptionStore(subscription_path)
    await old_subscriptions.add(
        checkin_messages.SIGN_RESULT_SUBSCRIBE,
        origin="private:user-report",
        user_id="user-report",
        user_type="direct",
    )

    config = _restart_runtime_config()
    context_a = _RuntimeContext()
    runtime_a = build_runtime(
        context_a,
        config,
        database=database_a,
        checkin_transport=_RestartCheckinTransport(),
    )
    await runtime_a.initialize()
    assert runtime_a.lifecycle.started is True
    await runtime_a.terminate()
    assert runtime_a.lifecycle.started is False

    context_b = _RuntimeContext()
    transport_b = _RestartCheckinTransport()
    database_b = AsyncDatabase(db_path)
    runtime_b = build_runtime(
        context_b,
        config,
        database=database_b,
        checkin_transport=transport_b,
    )
    try:
        await runtime_b.initialize()
        text = await runtime_b.services["sign_scheduler"].run_sign_once()  # type: ignore[union-attr]
    finally:
        await runtime_b.terminate()

    assert "签到" in text
    assert transport_b.calls == [
        ("calendar", "uid-enabled"),
        ("game", "uid-enabled"),
    ]
    assert context_b.sent_origins == ["private:user-report"]

    database_check = AsyncDatabase(db_path)
    async with database_check.session() as session:
        bindings = await AccountBindingRepository.list_all(session)
    await database_check.dispose()
    assert [(binding.uid, binding.auto_sign_enabled) for binding in bindings] == [
        ("uid-disabled", False),
        ("uid-enabled", True),
    ]
