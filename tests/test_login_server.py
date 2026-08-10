"""本地登录 HTTP 服务集成测试。"""

import asyncio

import aiohttp


def test_local_login_server_serves_login_page():
    from dnaby.dna_user.local_server import LocalLoginServer
    from dnaby.dna_user.login_router import LoginSession, cache, get_routes

    auth = "test-local-login-auth"
    cache.set(auth, LoginSession(auth=auth, user_id="user-1"))

    async def scenario():
        server = LocalLoginServer(get_routes(), host="127.0.0.1", port=0)
        await server.start()
        try:
            async with aiohttp.ClientSession() as client:
                async with client.get(f"{server.base_url}/dna/i/{auth}") as response:
                    assert response.status == 200
                    assert "登录" in await response.text()
                async with client.get(f"{server.base_url}/dna/i/missing-auth") as response:
                    assert response.status == 404
                async with client.post(
                    f"{server.base_url}/dna/login",
                    json={"auth": auth, "mobile": "13800138000", "code": "1234"},
                ) as response:
                    assert response.status == 200
                    payload = await response.json()
                    assert payload["success"] is False
                    assert "先为该手机号获取验证码" in payload["msg"]
        finally:
            await server.stop()

    try:
        asyncio.run(scenario())
    finally:
        cache.delete(auth)


def test_login_url_uses_started_local_server():
    from dnaby.dna_user.local_server import LocalLoginServer
    from dnaby.dna_user.login_router import (
        bind_local_login_server,
        get_dna_login_url,
        get_routes,
    )

    async def scenario():
        server = LocalLoginServer(get_routes(), host="127.0.0.1", port=0)
        await server.start()
        bind_local_login_server(server)
        try:
            assert await get_dna_login_url() == server.base_url
        finally:
            bind_local_login_server(None)
            await server.stop()

    asyncio.run(scenario())


def test_login_link_is_sent_before_waiting_for_submission(monkeypatch):
    """登录链接必须先发出，不能被本地登录等待循环延迟。"""
    from dnaby.dna_user.login_router import send_login
    from dnaby.utils.session import EventContext, Sender

    async def no_uid_hidden(*args):
        return False

    monkeypatch.setattr(
        "dnaby.utils.msgs.notify.is_uid_hidden",
        no_uid_hidden,
    )

    sent = []

    async def immediate_send(chain):
        sent.append(chain)

    ctx = EventContext(
        user_id="user-1",
        bot_id="onebot",
        user_type="direct",
    )
    sender = Sender(ctx, immediate_send=immediate_send)

    asyncio.run(send_login(sender, ctx, "http://localhost:6189/login"))

    assert sender.messages == []
    assert len(sent) == 1
    assert "http://localhost:6189/login" in sent[0][0].text
