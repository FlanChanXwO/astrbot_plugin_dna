"""账号 transport 的基础错误和 legacy 纯 API 适配器。

适配器不依赖旧事件、Sender 或数据库模型；它只把原 API 的响应映射为
account domain contract。网络依赖按调用时导入，使离线 fixture 不需要创建
真实客户端或登录会话。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ...modules.account.contracts import (
    AccountActor,
    AccountTransportError,
    LoginAttempt,
    LoginChannel,
    LoginCredentials,
    LoginResult,
    RoleInfo,
    TransportErrorKind,
)


def _response_error(response: Any) -> AccountTransportError:
    """把 legacy API 失败响应归类，不把 msg/data 原文带进异常。"""

    code = getattr(response, "code", None)
    if code == -999:
        kind = TransportErrorKind.NETWORK
    elif isinstance(code, int) and code >= 400:
        kind = TransportErrorKind.STATUS
    else:
        kind = TransportErrorKind.SERVER
    return AccountTransportError(
        kind,
        detail=f"api response code={code!r}",
        status_code=code if isinstance(code, int) and code >= 400 else None,
    )


def _raise_if_failed(response: Any) -> Any:
    """检查 API response 的公开成功标志。"""

    if not getattr(response, "is_success", False):
        raise _response_error(response)
    return response


def _role_infos(channel: LoginChannel, data: Any) -> tuple[RoleInfo, ...]:
    """解析 App 多角色或 Web 默认角色为统一 role DTO。"""

    from dnaby.utils.api.model import DNARoleForToolRes, DNARoleListRes
    from dnaby.utils.constants.constants import DNA_GAME_ID

    if channel is LoginChannel.APP:
        payload = DNARoleListRes.model_validate(data)
        roles: list[RoleInfo] = []
        for game in payload.roles:
            if game.gameId != DNA_GAME_ID:
                continue
            for role in game.showVoList:
                roles.append(
                    RoleInfo(
                        uid=role.roleId,
                        name=role.roleName,
                        is_default=role.isDefault == 1,
                    )
                )
        return tuple(roles)

    payload = DNARoleForToolRes.model_validate(data)
    role_show = payload.roleInfo.roleShow
    return (
        RoleInfo(
            uid=role_show.roleId,
            name=role_show.roleName,
            is_default=True,
        ),
    )


class DnaApiAccountTransport:
    """复用旧项目纯 API 请求逻辑的 typed account transport。

    page_url_provider 是可选的外部登录页提供器；没有实际页面服务时，
    begin_login 会显式报错，不会把一个不存在的地址伪装成可用登录链路。
    """

    def __init__(
        self,
        *,
        page_url_provider: Callable[[AccountActor], Awaitable[str]] | None = None,
    ) -> None:
        self._page_url_provider = page_url_provider

    async def begin_login(self, actor: AccountActor) -> str:
        """向已配置的页面服务请求本次 actor 的临时登录地址。"""

        if self._page_url_provider is None:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail="login page provider is not configured",
            )
        url = await self._page_url_provider(actor)
        if not url.strip():
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail="login page provider returned empty URL",
            )
        return url

    async def authenticate(self, attempt: LoginAttempt) -> LoginResult:
        """使用 legacy DNAApi 完成 token 或短信登录，并统一角色结果。"""

        try:
            from dnaby.utils import dna_api
            from dnaby.utils.api.auth import create_device_code
            from dnaby.utils.api.model import DNALoginRes
        except ImportError:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail="legacy API adapter is unavailable",
            ) from None

        if attempt.mode == "sms":
            return await self._authenticate_sms(
                dna_api,
                DNALoginRes,
                create_device_code,
                attempt,
            )
        return await self._authenticate_token(
            dna_api,
            create_device_code,
            attempt,
        )

    async def _authenticate_sms(
        self,
        api: Any,
        login_model: Any,
        create_device_code: Callable[[Any], str],
        attempt: LoginAttempt,
    ) -> LoginResult:
        """执行单一渠道的短信登录。"""

        try:
            from dnaby.utils.api.auth import LoginChannel as LegacyLoginChannel

            legacy_channel = LegacyLoginChannel(attempt.channel.value)
            dev_code = create_device_code(legacy_channel)
            method = (
                api.login_app
                if attempt.channel is LoginChannel.APP
                else api.login_web
            )
            response = _raise_if_failed(
                await method(attempt.mobile, attempt.code, dev_code),
            )
            login_data = login_model.model_validate(response.data)
            if login_data.isComplete == 0:
                return LoginResult.failed()
            credentials = LoginCredentials(
                channel=attempt.channel,
                token=login_data.token,
                dev_code=dev_code,
                d_num=login_data.dNum or "",
                refresh_token=login_data.refreshToken,
            )
            roles = await self._get_roles(
                api,
                credentials,
            )
            return LoginResult.success(credentials, roles=roles)
        except AccountTransportError:
            raise
        except (OSError, asyncio.TimeoutError) as exc:
            raise AccountTransportError(
                TransportErrorKind.NETWORK,
                detail=f"login request failed: {type(exc).__name__}",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"login response parsing failed: {type(exc).__name__}",
            ) from None

    async def _authenticate_token(
        self,
        api: Any,
        create_device_code: Callable[[Any], str],
        attempt: LoginAttempt,
    ) -> LoginResult:
        """按 legacy 顺序尝试 App，再尝试 Web token 角色接口。"""

        from dnaby.utils.api.auth import LoginChannel as LegacyLoginChannel

        errors: list[AccountTransportError] = []
        for channel in (LoginChannel.APP, LoginChannel.WEB):
            try:
                legacy_channel = LegacyLoginChannel(channel.value)
                credentials = LoginCredentials(
                    channel=channel,
                    token=attempt.token,
                    dev_code=create_device_code(legacy_channel),
                )
                roles = await self._get_roles(
                    api,
                    credentials,
                )
                return LoginResult.success(credentials, roles=roles)
            except AccountTransportError as exc:
                errors.append(exc)
            except (OSError, asyncio.TimeoutError) as exc:
                errors.append(
                    AccountTransportError(
                        TransportErrorKind.NETWORK,
                        detail=f"token request failed: {type(exc).__name__}",
                    ),
                )
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                errors.append(
                    AccountTransportError(
                        TransportErrorKind.SERVER,
                        detail=f"token response parsing failed: {type(exc).__name__}",
                    ),
                )
        if errors:
            raise errors[-1]
        raise AccountTransportError(
            TransportErrorKind.SERVER,
            detail="token role negotiation returned no result",
        )

    async def _get_roles(
        self,
        api: Any,
        credentials: LoginCredentials,
    ) -> tuple[RoleInfo, ...]:
        """读取角色列表；空或结构变化均作为服务端失败显露给上层。"""

        if credentials.channel is LoginChannel.APP:
            response = _raise_if_failed(
                await api.get_app_role_list(
                    credentials.token,
                    credentials.dev_code,
                ),
            )
            return _role_infos(credentials.channel, response.data)

        from dnaby.utils.api.auth import get_token_user_id

        if get_token_user_id(credentials.token) is None:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail="web token payload is invalid",
            )
        response = _raise_if_failed(
            await api.get_web_default_role(
                credentials.token,
                credentials.dev_code,
            ),
        )
        return _role_infos(credentials.channel, response.data)


__all__ = [
    "AccountTransportError",
    "DnaApiAccountTransport",
    "TransportErrorKind",
]
