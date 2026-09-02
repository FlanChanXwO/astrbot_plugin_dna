"""登录展示配置必须作用于当前 rewrite 登录入口。"""

from __future__ import annotations

import pytest

from src.entry.response import LoginResponse, ResponseFactory
from src.infrastructure.config.settings import LoginSettings
from src.modules.account.contracts import AccountActor
from src.modules.account.login_flow import LoginFlowCoordinator


class FakeLoginServer:
    def __init__(self) -> None:
        self.started = False
        self.base_url = "https://login.test/astrbot_plugin_dnaby"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


class FakeAccountService:
    async def login(self, *_args: object, **_kwargs: object) -> None:
        return None


def _actor(*, group_id: str | None = "group-1") -> AccountActor:
    return AccountActor("user-1", "bot-1", group_id)


@pytest.mark.asyncio
async def test_qr_login_returns_qr_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def render_qr_code(url: str) -> bytes:
        assert "/dna/i/" in url
        return b"qr-png"

    monkeypatch.setattr(
        "src.modules.account.login_flow.render_qr_code",
        render_qr_code,
    )
    flow = LoginFlowCoordinator(
        FakeAccountService(),
        LoginSettings(transport="local", qr_login=True),
        account_transport=object(),
        local_server=FakeLoginServer(),
    )

    await flow.start()
    try:
        response = await flow.begin(_actor())
    finally:
        await flow.stop()

    assert isinstance(response, LoginResponse)
    assert response.qr_bytes == b"qr-png"
    assert "请扫描下方二维码" in response.text
    assert response.forward is False


@pytest.mark.asyncio
async def test_tencent_docs_and_forward_login_are_applied() -> None:
    flow = LoginFlowCoordinator(
        FakeAccountService(),
        LoginSettings(
            transport="local",
            tencent_docs=True,
            forward_login=True,
        ),
        account_transport=object(),
        local_server=FakeLoginServer(),
    )

    await flow.start()
    try:
        response = await flow.begin(_actor())
    finally:
        await flow.stop()

    assert isinstance(response, LoginResponse)
    assert "https://docs.qq.com/scenario/link.html?url=" in response.text
    assert response.qr_bytes is None
    assert response.forward is True


def test_response_factory_converts_login_forward_to_nodes() -> None:
    event = type("Event", (), {"chain_result": lambda self, value: value})()
    response = LoginResponse(
        text="登录地址：https://login.test",
        qr_bytes=b"qr-png",
        forward=True,
    )

    result = ResponseFactory().build(event, response)

    from astrbot.api.message_components import Nodes

    assert isinstance(result, Nodes)
    assert result.nodes[0].content[0].text == response.text
