"""登录页与外置回执的统一协调器。

命令只负责创建一次登录会话并立即返回链接；网页或外置服务完成认证后，
协调器把结果交回 ``AccountService``，由同一个事务边界保存角色和 App 凭据。
这样登录页不会再绕过 rewrite 直接调用 legacy 事件/数据库服务。
"""

from __future__ import annotations

import asyncio
import inspect
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from astrbot.api import logger
from astrbot.api.web import request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse

from ...entry.response import LoginResponse, PlainTextResponse
from ...infrastructure.config.settings import LoginSettings
from ...infrastructure.http.login_server import LocalLoginServer, Route
from ...infrastructure.rendering.qr import render_qr_code
from ...utils.api.auth import LoginChannel as LegacyLoginChannel
from ...utils.api.auth import create_device_code
from ...utils.resource.RESOURCE_PATH import DNA_TEMPLATES
from . import messages
from .contracts import (
    AccountActor,
    AccountTransportError,
    LoginAttempt,
    LoginChannel,
    LoginCredentials,
)
from .transport import LOGIN_TTL_S, LoginTransport, TransportError

ROUTE_PREFIX = "/astrbot_plugin_dna"


class LoginFlowAccountService(Protocol):
    """协调器需要的账号服务最小接口。"""

    async def login(
        self,
        actor: AccountActor,
        attempt: LoginAttempt,
    ) -> PlainTextResponse: ...

    async def login_with_credentials(
        self,
        actor: AccountActor,
        credentials: LoginCredentials,
    ) -> PlainTextResponse: ...


LoginNotifier = Callable[[AccountActor, PlainTextResponse], Awaitable[None]]


class LoginSubmitParams(BaseModel):
    """内置 App 登录页的提交参数。"""

    auth: str = Field(description="登录会话标识")
    mobile: str = Field(description="登录手机号")
    code: str = Field(description="短信验证码")


class LoginSmsCodeParams(BaseModel):
    """内置 App 登录页获取短信验证码的参数。"""

    auth: str = Field(description="登录会话标识")
    mobile: str = Field(description="接收验证码的手机号")
    validation: str = Field(default="", alias="vJson", description="验证码验证结果")


@dataclass(slots=True)
class _LoginSession:
    """单次登录会话的内部状态，不包含任何真实凭据。"""

    auth: str
    actor: AccountActor
    url: str
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    response: PlainTextResponse | None = None
    mobile: str | None = None
    dev_code: str | None = None
    task: asyncio.Task[None] | None = None


def _actor_key(actor: AccountActor) -> tuple[str, str, str | None]:
    """用消息作用域去重，避免同一个会话重复启动多个监听任务。"""

    return actor.user_id, actor.bot_id, actor.group_id


def _public_base(raw: str) -> str:
    """规范化配置中的公开地址，并确保只拼接一次插件路由前缀。"""

    value = raw.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    if value.endswith(ROUTE_PREFIX):
        return value
    return f"{value}{ROUTE_PREFIX}"


class LoginFlowProvider(Protocol):
    """命令层使用的登录页提供器。"""

    async def begin(self, actor: AccountActor) -> PlainTextResponse | LoginResponse: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class LoginFlowCoordinator:
    """统一管理 local/http_poll/sse/ws 登录流程和生命周期。"""

    def __init__(
        self,
        account_service: LoginFlowAccountService,
        settings: LoginSettings,
        *,
        account_transport: Any,
        external_transport: LoginTransport | None = None,
        local_server: LocalLoginServer | None = None,
        notify: LoginNotifier | None = None,
    ) -> None:
        self.account_service = account_service
        self.settings = settings
        self.account_transport = account_transport
        self.notify = notify
        self._sessions: dict[tuple[str, str, str | None], _LoginSession] = {}
        self._session_lock = asyncio.Lock()
        self._started = False
        self._external_transport = external_transport
        if settings.transport == "local":
            self.local_server = local_server or LocalLoginServer(
                self._routes(),
                host=settings.bind_host,
                port=settings.port,
            )
        else:
            self.local_server = None

    @property
    def active_session_count(self) -> int:
        """返回当前等待中的会话数，供生命周期测试和诊断使用。"""

        return len(self._sessions)

    @property
    def external_transport(self) -> LoginTransport | None:
        """返回当前外置监听 transport。"""

        return self._external_transport

    @property
    def public_url(self) -> str:
        """返回登录页公开基址；配置地址优先于本地 socket 地址。"""

        configured = self.settings.url.strip()
        if configured:
            return _public_base(configured)
        if self.local_server is None:
            raise RuntimeError("当前登录模式没有本地登录服务")
        return self.local_server.base_url

    async def start(self) -> None:
        """启动 local listener；外置模式只在 begin 时创建监听任务。"""

        async with self._session_lock:
            if self._started:
                return
            if self.local_server is not None:
                await self.local_server.start()
            self._started = True

    async def stop(self) -> None:
        """取消所有等待、清空会话并释放 local listener。"""

        async with self._session_lock:
            tasks = [
                session.task for session in self._sessions.values() if session.task
            ]
            for task in tasks:
                if task is not asyncio.current_task():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._sessions.clear()
            if self.local_server is not None:
                await self.local_server.stop()
            self._started = False

    async def begin(self, actor: AccountActor) -> PlainTextResponse | LoginResponse:
        """创建登录会话并按登录展示配置返回地址、二维码或合并转发。"""

        async with self._session_lock:
            if not self._started:
                return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)

            key = _actor_key(actor)
            existing = self._sessions.get(key)
            if existing is not None and not existing.completed.is_set():
                return await self._build_login_response(actor, existing.url)

            auth = secrets.token_urlsafe(32)
            try:
                url = await self._start_transport(actor, auth)
            except (AccountTransportError, TransportError) as error:
                logger.warning(
                    "登录流程启动失败 operation=begin kind=%s",
                    type(error).__name__,
                )
                return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
            except (OSError, asyncio.TimeoutError) as error:
                logger.warning(
                    "登录流程启动失败 operation=begin kind=%s",
                    type(error).__name__,
                )
                return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
            except Exception as error:  # noqa: BLE001
                # 第三方适配器可能把服务端正文放进异常；仅记录类别，避免泄露凭据。
                logger.error(
                    "登录流程启动出现未预期异常 kind=%s",
                    type(error).__name__,
                )
                return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)

            normalized_url = url.strip()
            if not normalized_url:
                logger.warning("登录流程启动失败 operation=begin kind=empty_url")
                return PlainTextResponse(messages.LOGIN_EMPTY_URL)

            session = _LoginSession(auth=auth, actor=actor, url=normalized_url)
            self._sessions[key] = session
            session.task = asyncio.create_task(
                self._wait_for_completion(key, session),
                name="dnaby-login-wait",
            )
            return await self._build_login_response(actor, normalized_url)

    async def _build_login_response(
        self, actor: AccountActor, url: str
    ) -> PlainTextResponse | LoginResponse:
        """把登录展示配置应用到当前 rewrite 入口，而不是只留在 legacy 路由。"""

        forward = self.settings.forward_login and not (
            actor.group_id is None and actor.bot_id == "onebot"
        )
        if self.settings.qr_login:
            try:
                qr_bytes = await render_qr_code(url)
            except Exception as error:  # noqa: BLE001
                logger.error("登录二维码生成失败 kind=%s", type(error).__name__)
                return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
            return LoginResponse(
                text=(
                    f"[二重螺旋] 您的id为【{actor.user_id}】\n"
                    "请扫描下方二维码获取登录地址，并复制地址到浏览器打开\n"
                ),
                qr_bytes=qr_bytes,
                forward=forward,
                need_at=bool(actor.group_id),
            )
        if self.settings.tencent_docs:
            url = f"https://docs.qq.com/scenario/link.html?url={url}"
            text = (
                f"[二重螺旋] 您的id为【{actor.user_id}】\n"
                "请复制地址到浏览器打开\n"
                f" {url}\n"
                "登录地址10分钟内有效"
            )
            return LoginResponse(
                text=text,
                forward=forward,
                need_at=bool(actor.group_id),
            )
        if forward:
            return LoginResponse(
                text=messages.login_page(url),
                forward=True,
            )
        return PlainTextResponse(messages.login_page(url))

    async def _start_transport(self, actor: AccountActor, auth: str) -> str:
        if self.settings.transport == "local":
            return f"{self.public_url}/dna/i/{auth}"
        transport = self._external_transport
        if transport is None:
            raise TransportError("外置登录服务未配置")
        return await transport.start(
            auth=auth,
            user_id=actor.user_id,
            bot_id=actor.bot_id,
            group_id=actor.group_id,
        )

    async def _wait_for_completion(
        self,
        key: tuple[str, str, str | None],
        session: _LoginSession,
    ) -> None:
        response: PlainTextResponse | None = None
        try:
            if self.settings.transport == "local":
                try:
                    async with asyncio.timeout(LOGIN_TTL_S):
                        await session.completed.wait()
                except TimeoutError:
                    response = PlainTextResponse(messages.LOGIN_EXPIRED)
                else:
                    response = session.response or PlainTextResponse(
                        messages.LOGIN_SERVICE_FAILED,
                    )
            else:
                response = await self._wait_external(session)
        except asyncio.CancelledError:
            raise
        except (TransportError, AccountTransportError) as error:
            logger.warning(
                "登录流程等待失败 operation=listen kind=%s",
                type(error).__name__,
            )
            response = PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        except (OSError, asyncio.TimeoutError) as error:
            logger.warning(
                "登录流程等待失败 operation=listen kind=%s",
                type(error).__name__,
            )
            response = PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        except Exception as error:  # noqa: BLE001
            # transport/第三方异常可能携带服务端正文或凭据；此处只记录类别，
            # 具体协议错误已在各自 adapter 中转换为安全的分类错误。
            logger.error(
                "登录流程等待出现未预期异常 kind=%s",
                type(error).__name__,
            )
            response = PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        finally:
            # 两次字典操作之间没有 await，事件循环不会插入 begin；身份判断
            # 防止旧任务清理时误删同一作用域已经替换的新会话。
            session.completed.set()
            if self._sessions.get(key) is session:
                self._sessions.pop(key, None)
            if response is not None:
                await self._notify(session.actor, response)

    async def _wait_external(self, session: _LoginSession) -> PlainTextResponse:
        transport = self._external_transport
        if transport is None:
            return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        result = await transport.listen(session.auth)
        if result is None or result.status == "expired":
            return PlainTextResponse(messages.LOGIN_EXPIRED)
        if result.status == "cancelled":
            return PlainTextResponse(messages.LOGIN_CANCELLED)
        if result.status != "success":
            return PlainTextResponse(messages.LOGIN_FAILED)
        if result.channel != LoginChannel.APP:
            logger.warning("登录流程收到不支持的渠道 kind=unsupported_channel")
            return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        try:
            credentials = LoginCredentials(
                channel=LoginChannel.APP,
                token=result.token,
                dev_code=result.dev_code,
                d_num=result.d_num,
                refresh_token=result.refresh_token,
            )
        except ValueError:
            logger.warning("登录流程收到空凭据 kind=empty_credentials")
            return PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        return await self.account_service.login_with_credentials(
            session.actor,
            credentials,
        )

    async def _notify(self, actor: AccountActor, response: PlainTextResponse) -> None:
        if self.notify is None or actor.unified_msg_origin is None:
            return
        try:
            result = self.notify(actor, response)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # noqa: BLE001
            logger.error(
                "登录完成通知失败 kind=%s",
                type(error).__name__,
            )

    def _find_session(self, auth: str) -> _LoginSession | None:
        return next(
            (session for session in self._sessions.values() if session.auth == auth),
            None,
        )

    async def _login_page(self, auth: str) -> HTMLResponse:
        session = self._find_session(auth)
        if session is None:
            return self._not_found_page()
        template = DNA_TEMPLATES.get_template("index.html.j2")
        base_url = self.public_url
        page_url = f"{base_url}/dna/i/{auth}"
        return HTMLResponse(
            template.render(
                server_url=base_url,
                auth=auth,
                userId=session.actor.user_id,
                login_mode="app",
                app_login_url=page_url,
            )
        )

    @staticmethod
    def _not_found_page() -> HTMLResponse:
        template = DNA_TEMPLATES.get_template("404.html.j2")
        return HTMLResponse(template.render(), status_code=404)

    async def _get_sms_code(self) -> dict[str, bool | str]:
        payload = await request.json(default=None)
        if not isinstance(payload, dict):
            return {"success": False, "msg": "无效请求"}
        try:
            data = LoginSmsCodeParams.model_validate(payload)
        except (TypeError, ValueError):
            return {"success": False, "msg": "无效请求"}
        session = self._find_session(data.auth)
        if session is None:
            return {"success": False, "msg": "登录超时"}
        try:
            LoginAttempt.from_sms(data.mobile, "0000")
        except ValueError:
            return {"success": False, "msg": "无效手机号"}
        if not data.validation.strip():
            return {"success": False, "msg": "无效请求"}

        dev_code = session.dev_code or create_device_code(LegacyLoginChannel.APP)
        request_sms_code = getattr(self.account_transport, "request_sms_code", None)
        if not callable(request_sms_code):
            logger.warning("登录流程请求短信失败 kind=unsupported_transport")
            return {"success": False, "msg": messages.LOGIN_SERVICE_FAILED}
        try:
            result = request_sms_code(data.mobile, data.validation, dev_code)
            if inspect.isawaitable(result):
                result = await result
        except (AccountTransportError, OSError, asyncio.TimeoutError) as error:
            logger.warning(
                "登录流程请求短信失败 kind=%s",
                type(error).__name__,
            )
            return {"success": False, "msg": messages.LOGIN_SERVICE_FAILED}
        except Exception as error:  # noqa: BLE001
            # 短信服务异常可能包含响应正文；只保留异常类别供排查。
            logger.error(
                "登录流程请求短信出现未预期异常 kind=%s",
                type(error).__name__,
            )
            return {"success": False, "msg": messages.LOGIN_SERVICE_FAILED}
        if result is False:
            return {"success": False, "msg": messages.LOGIN_SERVICE_FAILED}
        session.mobile = data.mobile
        session.dev_code = dev_code
        return {"success": True, "msg": "验证码已发送"}

    async def _submit_login(self) -> dict[str, bool | str]:
        payload = await request.json(default=None)
        if not isinstance(payload, dict):
            return {"success": False, "msg": "无效请求"}
        try:
            data = LoginSubmitParams.model_validate(payload)
        except (TypeError, ValueError):
            return {"success": False, "msg": "无效请求"}
        session = self._find_session(data.auth)
        if session is None:
            return {"success": False, "msg": "登录超时"}
        if session.mobile != data.mobile or not session.dev_code:
            return {"success": False, "msg": "请先为该手机号获取验证码"}
        try:
            attempt = LoginAttempt.from_sms(
                data.mobile,
                data.code,
                dev_code=session.dev_code,
            )
        except ValueError:
            return {"success": False, "msg": "无效手机号或验证码"}
        try:
            response = await self.account_service.login(session.actor, attempt)
        except Exception as error:  # noqa: BLE001
            logger.error(
                "登录流程认证出现未预期异常 kind=%s",
                type(error).__name__,
            )
            response = PlainTextResponse(messages.LOGIN_SERVICE_FAILED)
        session.response = response
        session.completed.set()
        return {"success": True}

    def _routes(self) -> list[Route]:
        """只注册 App 登录页面、短信和提交路由。"""

        return [
            (
                f"{ROUTE_PREFIX}/dna/i/{{auth}}",
                self._login_page,
                ["GET"],
                "App 登录页",
            ),
            (
                f"{ROUTE_PREFIX}/dna/login",
                self._submit_login,
                ["POST"],
                "App 登录提交",
            ),
            (
                f"{ROUTE_PREFIX}/dna/getSmsCode",
                self._get_sms_code,
                ["POST"],
                "App 获取短信验证码",
            ),
        ]


# 兼容现有 import 名称；新的入口统一使用协调器实现。
LoginFlowService = LoginFlowCoordinator


__all__ = [
    "ROUTE_PREFIX",
    "LoginFlowCoordinator",
    "LoginFlowProvider",
    "LoginFlowService",
    "LoginSmsCodeParams",
    "LoginSubmitParams",
]
