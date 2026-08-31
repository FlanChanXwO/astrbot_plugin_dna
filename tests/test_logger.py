"""插件日志包装器契约测试。"""

from __future__ import annotations

from typing import Any

import src.infrastructure.utils.logger as logger_module
from src.entry.event import EventActor
from src.modules.account.contracts import (
    AccountTransportError,
    LoginAttempt,
    TransportErrorKind,
)
from src.modules.account.service import AccountService
from src.modules.checkin.contracts import CheckinFailureKind, CheckinTransportError
from src.modules.checkin.service import CheckinService
from src.modules.encyclopedia.contracts import (
    EncyclopediaFailureKind,
    EncyclopediaTransportError,
)
from src.modules.encyclopedia.service import EncyclopediaService
from src.modules.notices.contracts import (
    NoticeRequest,
    NoticesFailureKind,
    NoticesTransportError,
)
from src.modules.notices.service import NoticesService
from src.modules.player.contracts import PlayerFailureKind, PlayerTransportError
from src.modules.player.service import PlayerService


class _Recorder:
    """记录底层 AstrBot logger 调用，避免测试依赖具体日志实现。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def record(msg: object, *args: Any, **kwargs: Any) -> None:
            self.calls.append((name, msg, args, kwargs))

        return record


def test_prefixed_logger_forwards_message_and_default_stacklevel(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)

    logger = logger_module.PrefixedLogger()
    logger.warning("upstream failed: %s", "status")

    assert recorder.calls == [
        (
            "warning",
            "[astrbot_plugin_dnaby] upstream failed: %s",
            ("status",),
            {"stacklevel": 2},
        ),
    ]


def test_prefixed_logger_preserves_explicit_stacklevel(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)

    logger_module.PrefixedLogger().error("failed", stacklevel=9)

    assert recorder.calls[0][3] == {"stacklevel": 9}


def test_get_logger_returns_singleton() -> None:
    assert logger_module.get_logger() is logger_module.get_logger()


class _FailingAccountTransport:
    """让账号 service 进入用户可见的 transport 错误出口。"""

    async def begin_login(self, _actor):
        raise AccountTransportError(TransportErrorKind.NETWORK)

    async def authenticate(self, _attempt):
        raise AccountTransportError(
            TransportErrorKind.STATUS,
            detail="upstream secret detail",
            status_code=502,
        )


def test_account_transport_error_is_logged_without_detail(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)
    service = AccountService(
        database=None,
        transport=_FailingAccountTransport(),
        max_bind_count=1,
    )

    # 该 service 分支只返回稳定聊天文案，同时应把可排查字段写入 AstrBot 日志。
    import asyncio

    asyncio.run(
        service.login(
            actor=None,
            attempt=LoginAttempt.from_token("login-token"),
        ),
    )

    assert recorder.calls == [
        (
            "warning",
            "[astrbot_plugin_dnaby] 账号请求失败 operation=%s kind=%s status_code=%s",
            ("login", "status", 502),
            {"stacklevel": 2},
        ),
    ]
    assert "upstream secret detail" not in repr(recorder.calls)


def test_player_transport_error_is_logged_without_detail(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)

    PlayerService._transport_response(
        PlayerTransportError(
            PlayerFailureKind.STATUS,
            resource="角色概览",
            detail="upstream secret detail",
        ),
    )

    assert recorder.calls == [
        (
            "warning",
            "[astrbot_plugin_dnaby] 玩家请求失败 kind=%s resource=%s",
            ("status", "角色概览"),
            {"stacklevel": 2},
        ),
    ]
    assert "upstream secret detail" not in repr(recorder.calls)


def test_encyclopedia_transport_error_is_logged_without_detail(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)

    EncyclopediaService._transport_response(
        EncyclopediaTransportError(
            EncyclopediaFailureKind.SERVER,
            resource="周报",
            detail="upstream secret detail",
        ),
    )

    assert recorder.calls == [
        (
            "warning",
            "[astrbot_plugin_dnaby] 资料请求失败 kind=%s resource=%s",
            ("server", "周报"),
            {"stacklevel": 2},
        ),
    ]
    assert "upstream secret detail" not in repr(recorder.calls)


def test_checkin_transport_error_is_logged_without_detail(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)

    CheckinService._transport_response(
        CheckinTransportError(
            CheckinFailureKind.NETWORK,
            resource="签到日历",
            detail="upstream secret detail",
        ),
    )

    assert recorder.calls == [
        (
            "warning",
            "[astrbot_plugin_dnaby] 签到请求失败 kind=%s resource=%s",
            ("network", "签到日历"),
            {"stacklevel": 2},
        ),
    ]
    assert "upstream secret detail" not in repr(recorder.calls)


class _FailingNoticesTransport:
    """让公告 service 进入用户可见的 transport 错误出口。"""

    async def get_ann_list(self):
        raise NoticesTransportError(
            NoticesFailureKind.STATUS,
            resource="公告列表",
            detail="upstream secret detail",
        )


def test_notices_transport_error_is_logged_without_detail(monkeypatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(logger_module, "_astrbot_logger", recorder)
    service = NoticesService(
        database=None,
        transport=_FailingNoticesTransport(),
        privacy=None,
        renderer=None,
    )

    import asyncio

    asyncio.run(
        service.ann(
            NoticeRequest(
                actor=EventActor("user-1", "bot-1"),
                target_user_id=None,
            ),
        ),
    )

    assert recorder.calls == [
        (
            "warning",
            "[astrbot_plugin_dnaby] 通知请求失败 operation=%s kind=%s resource=%s",
            ("ann_list", "status", "公告列表"),
            {"stacklevel": 2},
        ),
    ]
    assert "upstream secret detail" not in repr(recorder.calls)
