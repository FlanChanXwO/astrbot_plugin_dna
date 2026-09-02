"""账号命令声明。

每条命令拥有自己的正则和 use case；模块不读取 AstrBot event，也不修改
registry。命令处理只负责把 typed request 交给 AccountService。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .service import AccountService, parse_login_attempt


def _service_and_actor(
    request: CommandRequest,
) -> tuple[AccountService, Any] | PlainTextResponse:
    """在命令边界检查 runtime 注入和事件作用域。"""

    if request.actor is None:
        return PlainTextResponse(messages.ACCOUNT_CONTEXT_UNAVAILABLE)
    service = request.services.get("account_service")
    if service is None:
        return PlainTextResponse(messages.ACCOUNT_SERVICE_UNAVAILABLE)
    return cast(AccountService, service), request.actor


async def _call(
    request: CommandRequest,
    method: str,
    *args: Any,
) -> PlainTextResponse:
    """统一执行已存在的 account service 方法，失败时不伪造成功。"""

    target = _service_and_actor(request)
    if isinstance(target, PlainTextResponse):
        return target
    service, actor = target
    operation = getattr(service, method, None)
    if not callable(operation):
        return PlainTextResponse(messages.ACCOUNT_SERVICE_UNAVAILABLE)
    result = operation(actor, *args)
    if not isinstance(result, Awaitable):
        raise TypeError(f"账号 use case {method} 必须返回 awaitable")
    response = await result
    if not isinstance(response, PlainTextResponse):
        raise TypeError(f"账号 use case {method} 返回了未知响应")
    return response


async def account_login_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
) -> PlainTextResponse:
    """执行登录页启动、token 登录或手机号验证码登录。"""

    target = _service_and_actor(request)
    if isinstance(target, PlainTextResponse):
        return target
    service, actor = target
    argument = str(parameters.get("arg", "")).strip()
    if argument == "":
        return await service.begin_login(actor)
    try:
        attempt = parse_login_attempt(argument)
    except ValueError:
        return PlainTextResponse(messages.INVALID_LOGIN_INPUT)
    return await service.login(actor, attempt)


async def account_logout_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """退出当前登录。"""

    return await _call(request, "logout")


async def account_token_login_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
) -> PlainTextResponse:
    """执行显式 token 登录；凭据仍只进入 App 登录事务。"""

    target = _service_and_actor(request)
    if isinstance(target, PlainTextResponse):
        return target
    service, actor = target
    argument = str(parameters.get("arg", "")).strip()
    try:
        attempt = parse_login_attempt(argument)
    except ValueError:
        return PlainTextResponse(messages.INVALID_LOGIN_INPUT)
    if attempt.mode != "token":
        return PlainTextResponse(messages.INVALID_LOGIN_INPUT)
    return await service.login(actor, attempt)


async def account_bind_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
) -> PlainTextResponse:
    """绑定 UID。"""

    return await _call(request, "bind_uid", str(parameters.get("uid", "")))


async def account_switch_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
) -> PlainTextResponse:
    """切换当前 UID。"""

    return await _call(request, "switch_uid", str(parameters.get("uid", "")))


async def account_delete_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
) -> PlainTextResponse:
    """删除一个 UID。"""

    return await _call(request, "delete_uid", str(parameters.get("uid", "")))


async def account_delete_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """删除当前作用域的全部 UID。"""

    return await _call(request, "delete_all")


async def account_list_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """查询当前绑定列表；隐私遮罩由后续 privacy use case 接管。"""

    return await _call(request, "list_bindings")


async def account_credentials_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """查询凭据状态摘要。"""

    return await _call(request, "credentials")


COMMAND_SPECS = (
    CommandSpec(
        id="account_token_login",
        pattern=r"^(?:token登录|登录token)\s*(?P<arg>.*)$",
        group="皎皎角登录",
        name="token登录",
        description="使用 App token 登录，不输出原始凭据",
        examples=("token登录" + "t" * 40,),
        permission="user",
        use_case=account_token_login_use_case,
    ),
    CommandSpec(
        id="account_login",
        pattern=r"^(?:登录|登陆|登入|登龙|login)\s*(?P<arg>.*)$",
        group="账号管理",
        name="登录",
        description="皎皎角登录（登录页/短信验证码/token）",
        examples=("登录", "登录" + "t" * 40),
        permission="user",
        use_case=account_login_use_case,
    ),
    CommandSpec(
        id="account_logout",
        pattern=r"^(?:退出登录|登出|logout)$",
        group="账号管理",
        name="退出登录",
        description="退出当前登录",
        examples=("退出登录",),
        permission="user",
        use_case=account_logout_use_case,
    ),
    CommandSpec(
        id="account_bind",
        pattern=r"^绑定\s*(?P<uid>\S*)$",
        group="账号管理",
        name="绑定UID",
        description="绑定一个 UID",
        examples=("绑定1234567890123",),
        permission="user",
        use_case=account_bind_use_case,
    ),
    CommandSpec(
        id="account_switch",
        pattern=r"^切换\s*(?P<uid>\S*)$",
        group="账号管理",
        name="切换UID",
        description="切换当前 UID",
        examples=("切换1234567890123",),
        permission="user",
        use_case=account_switch_use_case,
    ),
    CommandSpec(
        id="account_delete_all",
        pattern=r"^删除全部(?:UID|uid)?$",
        group="账号管理",
        name="删除全部UID",
        description="删除当前作用域的全部 UID",
        examples=("删除全部UID",),
        permission="user",
        use_case=account_delete_all_use_case,
    ),
    CommandSpec(
        id="account_delete",
        pattern=r"^删除\s*(?P<uid>(?!全部(?:UID|uid)?$)\d*)$",
        group="账号管理",
        name="删除UID",
        description="删除一个 UID",
        examples=("删除1234567890123",),
        permission="user",
        use_case=account_delete_use_case,
    ),
    CommandSpec(
        id="account_list",
        pattern=r"^查看(?:UID|uid)?$",
        group="账号管理",
        name="查看UID",
        description="查看当前绑定 UID",
        examples=("查看UID",),
        permission="user",
        use_case=account_list_use_case,
    ),
    CommandSpec(
        id="account_credentials",
        pattern=r"^(?:获取ck|获取CK|获取Token|获取token|获取TOKEN)$",
        group="账号管理",
        name="获取凭据状态",
        description="查看当前登录账号的凭据状态（严格脱敏）",
        examples=("获取ck",),
        permission="user",
        use_case=account_credentials_use_case,
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "account_bind_use_case",
    "account_credentials_use_case",
    "account_delete_all_use_case",
    "account_delete_use_case",
    "account_list_use_case",
    "account_login_use_case",
    "account_logout_use_case",
    "account_switch_use_case",
    "account_token_login_use_case",
]
