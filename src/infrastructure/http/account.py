"""账号 transport 的基础错误和 legacy 纯 API 适配器。

适配器不依赖旧事件、Sender 或数据库模型；它只把原 API 的响应映射为
account domain contract。网络依赖按调用时导入，使离线 fixture 不需要创建
真实客户端或登录会话。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .auth import is_credential_failure
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
    elif is_credential_failure(response):
        kind = TransportErrorKind.CREDENTIAL
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


def _role_infos(data: Any) -> tuple[RoleInfo, ...]:
    """解析 App 多角色为统一 role DTO。"""

    from ...utils.api.model import DNARoleListRes
    from ...utils.constants.constants import DNA_GAME_ID

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
            from ...utils import dna_api
            from ...utils.api.auth import create_device_code
            from ...utils.api.model import DNALoginRes
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

    async def authenticate_credentials(
        self,
        credentials: LoginCredentials,
    ) -> LoginResult:
        """读取外部登录回执对应的角色，不重新生成或改写凭据。"""

        if credentials.channel is not LoginChannel.APP:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail="only App credentials are supported",
            )
        try:
            from ...utils import dna_api

            roles = await self._get_roles(dna_api, credentials)
            return LoginResult.success(credentials, roles=roles)
        except AccountTransportError:
            raise
        except (OSError, asyncio.TimeoutError) as exc:
            raise AccountTransportError(
                TransportErrorKind.NETWORK,
                detail=f"credential validation failed: {type(exc).__name__}",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"credential validation failed: {type(exc).__name__}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"credential validation failed: {type(exc).__name__}",
            ) from None

    async def request_sms_code(
        self,
        mobile: str,
        validation: str,
        dev_code: str,
    ) -> None:
        """请求内置 App 登录页所需的短信验证码。"""

        try:
            from ...utils import dna_api

            response = await dna_api.get_app_sms_code(mobile, validation, dev_code)
            _raise_if_failed(response)
        except AccountTransportError:
            raise
        except (OSError, asyncio.TimeoutError) as exc:
            raise AccountTransportError(
                TransportErrorKind.NETWORK,
                detail=f"sms request failed: {type(exc).__name__}",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"sms response parsing failed: {type(exc).__name__}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"sms request failed: {type(exc).__name__}",
            ) from None

    async def _authenticate_sms(
        self,
        api: Any,
        login_model: Any,
        create_device_code: Callable[[Any], str],
        attempt: LoginAttempt,
    ) -> LoginResult:
        """执行单一渠道的短信登录。"""

        try:
            from ...utils.api.auth import LoginChannel as LegacyLoginChannel

            dev_code = attempt.dev_code or create_device_code(LegacyLoginChannel.APP)
            response = _raise_if_failed(
                await api.login_app(attempt.mobile, attempt.code, dev_code),
            )
            login_data = login_model.model_validate(response.data)
            if login_data.isComplete == 0:
                return LoginResult.failed()
            credentials = LoginCredentials(
                channel=LoginChannel.APP,
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
        except Exception as exc:  # noqa: BLE001
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"login request failed: {type(exc).__name__}",
            ) from None

    async def _authenticate_token(
        self,
        api: Any,
        create_device_code: Callable[[Any], str],
        attempt: LoginAttempt,
    ) -> LoginResult:
        """使用 App token 读取角色列表。"""

        from ...utils.api.auth import LoginChannel as LegacyLoginChannel

        try:
            credentials = LoginCredentials(
                channel=LoginChannel.APP,
                token=attempt.token,
                dev_code=attempt.dev_code or create_device_code(LegacyLoginChannel.APP),
            )
            roles = await self._get_roles(api, credentials)
            return LoginResult.success(credentials, roles=roles)
        except AccountTransportError:
            raise
        except (OSError, asyncio.TimeoutError) as exc:
            raise AccountTransportError(
                TransportErrorKind.NETWORK,
                detail=f"token request failed: {type(exc).__name__}",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"token response parsing failed: {type(exc).__name__}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise AccountTransportError(
                TransportErrorKind.SERVER,
                detail=f"token request failed: {type(exc).__name__}",
            ) from None

    async def _get_roles(
        self,
        api: Any,
        credentials: LoginCredentials,
    ) -> tuple[RoleInfo, ...]:
        """读取角色列表；空或结构变化均作为服务端失败显露给上层。"""

        response = _raise_if_failed(
            await api.get_app_role_list(
                credentials.token,
                credentials.dev_code,
            ),
        )
        return _role_infos(response.data)


__all__ = [
    "AccountTransportError",
    "DnaApiAccountTransport",
    "TransportErrorKind",
]
