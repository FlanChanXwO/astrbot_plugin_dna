"""O13：运行期临时文件不得落入插件源码目录。"""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

from astrbot.api.star import StarTools


def test_qr_login_uses_astrbot_runtime_data_dir(monkeypatch, tmp_path: Path) -> None:
    """二维码登录应把兼容 helper 的临时路径交给 AstrBot 数据目录。"""
    from src.modules.account import login_router
    from src.utils.session import EventContext, Sender

    runtime_root = tmp_path / "plugin-data"
    monkeypatch.setattr(
        StarTools,
        "get_data_dir",
        staticmethod(lambda _plugin_name: runtime_root),
    )

    config_values = {
        "DNAQRLogin": True,
        "DNALoginForward": False,
    }
    monkeypatch.setattr(
        login_router.DNAConfig,
        "get_config",
        staticmethod(
            lambda key: SimpleNamespace(data=config_values.get(key, False)),
        ),
    )

    qr_calls: list[tuple[str, Path, str]] = []

    async def fake_get_qrcode_base64(url: str, path: Path, name: str) -> bytes:
        qr_calls.append((url, path, name))
        return b"qr"

    monkeypatch.setattr(login_router, "get_qrcode_base64", fake_get_qrcode_base64)

    sent: list[list] = []

    async def immediate_send(chain: list) -> None:
        sent.append(chain)

    user_id = "../../outside/goal1-o13-qr"
    ctx = EventContext(
        user_id=user_id,
        bot_id="onebot",
        user_type="direct",
    )
    sender = Sender(ctx, immediate_send=immediate_send)

    asyncio.run(login_router.send_login(sender, ctx, "https://example.test/login"))

    assert len(sent) == 1
    expected_qr_path = (
        runtime_root
        / "login_qr"
        / f"{hashlib.sha256(user_id.encode('utf-8')).hexdigest()}.gif"
    )
    assert qr_calls == [
        (
            "https://example.test/login",
            expected_qr_path,
            "onebot",
        )
    ]
    assert Path(login_router.__file__).parent not in qr_calls[0][1].parents
