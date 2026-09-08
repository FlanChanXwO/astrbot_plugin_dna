from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.star import StarTools
from astrbot.api.web import request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse

from ...infrastructure.config.settings import DNAConfig
from ...utils import TimedCache, dna_api, get_public_ip
from ...utils.api.auth import (
    LoginChannel,
    LoginCredentials,
    create_device_code,
)
from ...utils.image_utils import get_qrcode_base64
from ...utils.msgs.notify import (
    dna_code_login_fail,
    dna_login_timeout,
    send_dna_notify,
    send_dna_text,
)
from ...utils.resource.RESOURCE_PATH import DNA_TEMPLATES
from ...utils.segments import MessageSegment
from ...utils.session import EventContext, Sender
from .login_helps import (
    get_token,
    is_valid_chinese_phone_number,
    is_validate_code,
)
from .login_service import DNALoginService
from .transport import TransportError, build_transport

if TYPE_CHECKING:
    from ...infrastructure.http.login_server import LocalLoginServer

ROUTE_PREFIX = "/astrbot_plugin_dna"

cache = TimedCache(timeout=600, maxsize=10)
_local_login_server: LocalLoginServer | None = None


def bind_local_login_server(server: LocalLoginServer | None) -> None:
    """绑定 local 模式服务，让登录页链接使用实际监听地址。"""
    global _local_login_server
    _local_login_server = server


class LoginSubmission(BaseModel):
    mobile: str = Field(description="登录手机号")
    code: str = Field(description="短信验证码")
    dev_code: str | None = Field(default=None, description="登录设备码")


class LoginSession(BaseModel):
    auth: str = Field(description="登录会话标识")
    user_id: str = Field(description="机器人用户标识")
    app_dev_code: str | None = Field(default=None, description="App 设备码")
    app_mobile: str | None = Field(default=None, description="App 已成功发码的手机号")
    submission: LoginSubmission | None = Field(
        default=None, description="待处理的登录提交"
    )


class LoginSubmitParams(BaseModel):
    auth: str = Field(description="登录会话标识")
    mobile: str = Field(description="登录手机号")
    code: str = Field(description="短信验证码")


class SmsCodeParams(BaseModel):
    auth: str = Field(description="登录会话标识")
    mobile: str = Field(description="接收验证码的手机号")
    v_json: str = Field(alias="vJson", description="CAPTCHA 验证结果")


async def page_login(sender: Sender, ctx: EventContext) -> None:
    transport_name = DNAConfig.get_config("DNALoginTransport").data.strip()
    if transport_name in {"", "local"}:
        await page_login_local(sender, ctx, await get_dna_login_url())
        return

    base_url = DNAConfig.get_config("DNALoginUrl").data.strip()
    if base_url == "":
        logger.warning(f"[DNA登录] 接入方式为 {transport_name} 但 DNALoginUrl 未配置")
        await send_dna_notify(sender, ctx, "登录服务请求失败! 请稍后再试")
        return
    await page_login_other(sender, ctx, base_url)


async def token_login(sender: Sender, ctx: EventContext, token: str) -> None:
    login_service = DNALoginService(sender, ctx)
    login_result = await login_service.dna_login_by_token(token=token.strip())
    await send_dna_notify(sender, ctx, login_result)


async def get_dna_login_url() -> str:
    url = DNAConfig.get_config("DNALoginUrl").data.strip()
    if url != "":
        if url.startswith("http"):
            return f"{url.rstrip('/')}{ROUTE_PREFIX}"
        return f"https://{url}{ROUTE_PREFIX}"

    if _local_login_server is not None:
        return _local_login_server.base_url

    host = (
        DNAConfig.get_config("DNALoginBindHost").data
        if hasattr(DNAConfig, "get_config")
        else "127.0.0.1"
    )
    port = (
        DNAConfig.get_config("DNALoginPort").data
        if hasattr(DNAConfig, "get_config")
        else 6189
    )
    if host == "localhost" or host == "127.0.0.1":
        public_host = "localhost"
    else:
        public_host = await get_public_ip(host)
    return f"http://{public_host}:{port}{ROUTE_PREFIX}"


async def send_login(sender: Sender, ctx: EventContext, url: str) -> None:
    at_sender = bool(ctx.group_id)
    if DNAConfig.get_config("DNAQRLogin").data:
        # 二维码 helper 保留旧 path 参数；文件名使用摘要，避免外部 user_id 逃出运行期目录。
        qr_name = hashlib.sha256(ctx.user_id.encode("utf-8")).hexdigest()
        path = (
            Path(StarTools.get_data_dir("astrbot_plugin_dna"))
            / "login_qr"
            / f"{qr_name}.gif"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        qr_items = [
            MessageSegment.text(f"[二重螺旋] 您的id为【{ctx.user_id}】\n"),
            MessageSegment.text(
                "请扫描下方二维码获取登录地址，并复制地址到浏览器打开\n"
            ),
            MessageSegment.image(await get_qrcode_base64(url, path, ctx.bot_id)),
        ]

        if DNAConfig.get_config("DNALoginForward").data:
            if not ctx.group_id and ctx.bot_id == "onebot":
                await sender.send_now(qr_items)
            else:
                await sender.send_now(MessageSegment.node(qr_items))
        else:
            await sender.send_now(qr_items, at_sender=at_sender)

        if path.exists():
            path.unlink()
        return

    if DNAConfig.get_config("DNATencentWord").data:
        url = f"https://docs.qq.com/scenario/link.html?url={url}"
    lines = [
        f"[二重螺旋] 您的id为【{ctx.user_id}】",
        "请复制地址到浏览器打开",
        f" {url}",
        "登录地址10分钟内有效",
    ]
    if DNAConfig.get_config("DNALoginForward").data:
        if not ctx.group_id and ctx.bot_id == "onebot":
            await send_dna_text(sender, ctx, "\n".join(lines), immediate=True)
        else:
            await sender.send_now(MessageSegment.node(lines))
    else:
        await send_dna_text(
            sender,
            ctx,
            "\n".join(lines),
            need_at=at_sender,
            immediate=True,
        )


async def page_login_other(sender: Sender, ctx: EventContext, url: str) -> None:
    auth_token = get_token(ctx.user_id)
    transport = build_transport(url)
    try:
        page_url = await transport.start(
            auth=auth_token,
            user_id=ctx.user_id,
            bot_id=ctx.bot_id,
            group_id=ctx.group_id,
        )
    except TransportError as error:
        logger.warning(f"[DNA登录] 外置 start 失败 user_id={ctx.user_id}: {error}")
        await send_dna_notify(sender, ctx, "登录服务请求失败! 请稍后再试")
        return

    await send_login(sender, ctx, page_url)
    if cache.get(auth_token):
        return
    cache.set(auth_token, True)
    try:
        result = await transport.listen(auth_token)
    except TransportError as error:
        logger.warning(f"[DNA登录] 外置 listen 失败 user_id={ctx.user_id}: {error}")
        await send_dna_notify(sender, ctx, "登录服务请求失败! 请稍后再试")
        return
    finally:
        cache.delete(auth_token)

    if result is None or result.status == "expired":
        await dna_login_timeout(sender, ctx)
        return
    if result.status == "cancelled":
        await send_dna_notify(sender, ctx, "登录已取消")
        return
    if result.status != "success":
        logger.warning(
            f"[DNA登录] 外置 listen 返回失败状态 user_id={ctx.user_id} "
            f"status={result.status}"
        )
        await send_dna_notify(sender, ctx, "登录服务请求失败! 请稍后再试")
        return
    token = result.token.strip()
    dev_code = result.dev_code.strip()
    if token == "" or dev_code == "":
        logger.warning(f"[DNA登录] 外置返回成功但凭据为空 user_id={ctx.user_id}")
        await send_dna_notify(sender, ctx, "登录服务请求失败! 请稍后再试")
        return

    credentials = LoginCredentials(
        channel=LoginChannel.APP,
        token=token,
        dev_code=dev_code,
        refresh_token=result.refresh_token,
        d_num=result.d_num,
    )
    login_service = DNALoginService(sender, ctx)
    login_result = await login_service.login_with_credentials(credentials)
    await send_dna_notify(sender, ctx, login_result)


async def page_login_local(sender: Sender, ctx: EventContext, url: str) -> None:
    login_auth = get_token(ctx.user_id)
    active_session = cache.get(login_auth)
    if isinstance(active_session, LoginSession):
        await send_login(sender, ctx, f"{url}/dna/i/{login_auth}")
        return

    session = LoginSession(auth=login_auth, user_id=ctx.user_id)
    cache.set(login_auth, session)
    await send_login(sender, ctx, f"{url}/dna/i/{login_auth}")
    try:
        async with asyncio.timeout(600):
            while True:
                current_session = cache.get(login_auth)
                if current_session is None:
                    await dna_login_timeout(sender, ctx)
                    return
                if not isinstance(current_session, LoginSession):
                    raise TypeError("登录会话类型错误")
                if current_session.submission is not None:
                    cache.delete(login_auth)
                    submission = current_session.submission
                    await code_login(
                        sender,
                        ctx,
                        f"{submission.mobile},{submission.code}",
                        is_page=True,
                        dev_code=submission.dev_code,
                    )
                    return
                await asyncio.sleep(3)
    except asyncio.TimeoutError:
        cache.delete(login_auth)
        await dna_login_timeout(sender, ctx)
    except TypeError as error:
        cache.delete(login_auth)
        logger.error(f"[DNA登录] user_id={ctx.user_id}: {error}")
        await send_dna_notify(sender, ctx, "登录服务请求失败! 请稍后再试")


async def code_login(
    sender: Sender,
    ctx: EventContext,
    text: str,
    *,
    is_page: bool = False,
    dev_code: str | None = None,
) -> None:
    try:
        phone_number, code = text.split(",")
        if not is_valid_chinese_phone_number(phone_number):
            raise ValueError("无效手机号")
        if not is_validate_code(code):
            raise ValueError("无效验证码")
    except ValueError:
        if is_page:
            await send_dna_notify(sender, ctx, "无效手机号或验证码")
        else:
            await dna_code_login_fail(sender, ctx)
        return

    login_service = DNALoginService(sender, ctx)
    login_result = await login_service.login(
        mobile=phone_number,
        code=code,
        dev_code=dev_code,
    )
    await send_dna_notify(sender, ctx, login_result)


async def _render_login_page(
    auth: str,
) -> HTMLResponse:
    login_session = cache.get(auth)
    if not isinstance(login_session, LoginSession):
        template = DNA_TEMPLATES.get_template("404.html.j2")
        return HTMLResponse(template.render(), status_code=404)

    server_url = await get_dna_login_url()
    template = DNA_TEMPLATES.get_template("index.html.j2")
    return HTMLResponse(
        template.render(
            server_url=server_url,
            auth=auth,
            userId=login_session.user_id,
        )
    )


async def dna_login_index(auth: str) -> HTMLResponse:
    return await _render_login_page(auth)


async def _submit_login(
    data: LoginSubmitParams,
) -> dict[str, bool | str]:
    login_session = cache.get(data.auth)
    if not isinstance(login_session, LoginSession):
        return {"success": False, "msg": "登录超时"}
    if not is_valid_chinese_phone_number(data.mobile):
        return {"success": False, "msg": "无效手机号或验证码"}
    if not is_validate_code(data.code):
        return {"success": False, "msg": "无效手机号或验证码"}

    dev_code = login_session.app_dev_code
    if dev_code is None or login_session.app_mobile != data.mobile:
        return {
            "success": False,
            "msg": "请先为该手机号获取验证码",
        }

    submission = LoginSubmission(
        mobile=data.mobile,
        code=data.code,
        dev_code=dev_code,
    )
    cache.set(
        data.auth,
        login_session.model_copy(update={"submission": submission}),
    )
    return {"success": True}


async def _parse_submit_params() -> LoginSubmitParams | None:
    data = await request.json(default=None)
    if not isinstance(data, dict):
        return None
    try:
        return LoginSubmitParams.model_validate(data)
    except Exception:  # noqa: BLE001
        return None


async def _parse_sms_code_params() -> SmsCodeParams | None:
    data = await request.json(default=None)
    if not isinstance(data, dict):
        return None
    try:
        return SmsCodeParams.model_validate(data)
    except Exception:  # noqa: BLE001
        return None


async def dna_login() -> dict[str, bool | str]:
    data = await _parse_submit_params()
    if data is None:
        return {"success": False, "msg": "无效请求"}
    return await _submit_login(data)


async def dna_app_get_sms_code() -> dict[str, bool | str]:
    data = await _parse_sms_code_params()
    if data is None:
        return {"success": False, "msg": "无效请求"}
    login_session = cache.get(data.auth)
    if not isinstance(login_session, LoginSession):
        return {"success": False, "msg": "登录超时"}
    if not is_valid_chinese_phone_number(data.mobile):
        return {"success": False, "msg": "无效手机号"}

    dev_code = login_session.app_dev_code
    if dev_code is None:
        dev_code = create_device_code(LoginChannel.APP)
        login_session = login_session.model_copy(update={"app_dev_code": dev_code})
        cache.set(data.auth, login_session)

    result = await dna_api.get_app_sms_code(
        data.mobile,
        data.v_json,
        dev_code,
    )
    if result.is_success:
        current_session = cache.get(data.auth)
        if not isinstance(current_session, LoginSession):
            return {"success": False, "msg": "登录超时"}
        cache.set(
            data.auth,
            current_session.model_copy(update={"app_mobile": data.mobile}),
        )
        return {"success": True, "msg": "验证码已发送"}
    return {"success": False, "msg": result.throw_msg()}


def get_routes() -> list[tuple[str, Callable, list[str], str]]:
    return [
        (f"{ROUTE_PREFIX}/dna/i/{{auth}}", dna_login_index, ["GET"], "App 登录页"),
        (f"{ROUTE_PREFIX}/dna/login", dna_login, ["POST"], "App 登录提交"),
        (
            f"{ROUTE_PREFIX}/dna/getSmsCode",
            dna_app_get_sms_code,
            ["POST"],
            "App 获取短信验证码",
        ),
    ]


__all__ = [
    "LoginSession",
    "LoginSubmission",
    "LoginSubmitParams",
    "SmsCodeParams",
    "bind_local_login_server",
    "cache",
    "code_login",
    "dna_app_get_sms_code",
    "dna_login",
    "dna_login_index",
    "get_dna_login_url",
    "get_routes",
    "page_login",
    "send_login",
    "token_login",
]
