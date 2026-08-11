"""隐私命令声明和 typed request 适配。"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .service import PrivacyService


def _service_and_actor(
    request: CommandRequest,
) -> tuple[PrivacyService, Any] | PlainTextResponse:
    """在命令边界检查 runtime 注入和调用者作用域。"""

    if request.actor is None:
        return PlainTextResponse(messages.PRIVACY_CONTEXT_UNAVAILABLE)
    service = request.services.get("privacy_service")
    if service is None:
        return PlainTextResponse(messages.PRIVACY_SERVICE_UNAVAILABLE)
    return cast(PrivacyService, service), request.actor


async def _call(
    request: CommandRequest,
    method: str,
    *args: Any,
) -> PlainTextResponse:
    """统一执行隐私 service 方法，未知注入显式失败。"""

    target = _service_and_actor(request)
    if isinstance(target, PlainTextResponse):
        return target
    service, actor = target
    operation = getattr(service, method, None)
    if not callable(operation):
        return PlainTextResponse(messages.PRIVACY_SERVICE_UNAVAILABLE)
    result = operation(actor, *args)
    if not isinstance(result, Awaitable):
        raise TypeError(f"隐私 use case {method} 必须返回 awaitable")
    response = await result
    if not isinstance(response, PlainTextResponse):
        raise TypeError(f"隐私 use case {method} 返回了未知响应")
    return response


async def privacy_enable_peek_personal_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """允许他人查看自己的游戏信息。"""

    return await _call(request, "set_personal_peek", True)


async def privacy_disable_peek_personal_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """禁止他人查看自己的游戏信息。"""

    return await _call(request, "set_personal_peek", False)


async def privacy_enable_uid_hidden_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """隐藏自己的 UID。"""

    return await _call(request, "set_personal_uid_hidden", True)


async def privacy_disable_uid_hidden_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """显示自己的 UID。"""

    return await _call(request, "set_personal_uid_hidden", False)


async def privacy_enable_peek_admin_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """允许被 @ 玩家被他人查看。"""

    return await _call(request, "set_target_peek", request.target_user_id, True)


async def privacy_disable_peek_admin_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """禁止被 @ 玩家被他人查看。"""

    return await _call(request, "set_target_peek", request.target_user_id, False)


async def privacy_enable_peek_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """开启群组全体允许查看。"""

    return await _call(request, "set_group_peek", True)


async def privacy_disable_peek_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """开启群组全体防偷窥。"""

    return await _call(request, "set_group_peek", False)


async def privacy_cancel_peek_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """取消群组全体偷窥强制设置。"""

    return await _call(request, "cancel_group_peek")


async def privacy_enable_uid_hidden_admin_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """为被 @ 玩家隐藏 UID。"""

    return await _call(request, "set_target_uid_hidden", request.target_user_id, True)


async def privacy_disable_uid_hidden_admin_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """为被 @ 玩家显示 UID。"""

    return await _call(request, "set_target_uid_hidden", request.target_user_id, False)


async def privacy_enable_uid_hidden_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """开启群组全体隐藏 UID。"""

    return await _call(request, "set_group_uid_hidden", True)


async def privacy_disable_uid_hidden_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """开启群组全体显示 UID。"""

    return await _call(request, "set_group_uid_hidden", False)


async def privacy_cancel_uid_hidden_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """取消群组全体 UID 隐藏强制设置。"""

    return await _call(request, "cancel_group_uid_hidden")


COMMAND_SPECS = (
    CommandSpec(
        id="privacy_enable_peek_personal",
        pattern=r"^(?:开偷窥|关闭偷窥防护)$",
        group="隐私控制",
        name="开偷窥",
        description="允许被其它人查看自己的游戏信息",
        examples=("开偷窥",),
        permission="user",
        use_case=privacy_enable_peek_personal_use_case,
    ),
    CommandSpec(
        id="privacy_disable_peek_personal",
        pattern=r"^(?:防偷窥|开启偷窥防护)$",
        group="隐私控制",
        name="防偷窥",
        description="禁止被其它人查看自己的游戏信息",
        examples=("防偷窥",),
        permission="user",
        use_case=privacy_disable_peek_personal_use_case,
    ),
    CommandSpec(
        id="privacy_enable_uid_hidden",
        pattern=r"^(?:隐藏UID|隐藏uid)$",
        group="隐私控制",
        name="隐藏UID",
        description="在生成的卡片中隐藏自己的UID",
        examples=("隐藏UID",),
        permission="user",
        use_case=privacy_enable_uid_hidden_use_case,
    ),
    CommandSpec(
        id="privacy_disable_uid_hidden",
        pattern=r"^(?:显示UID|显示uid)$",
        group="隐私控制",
        name="显示UID",
        description="在生成的卡片中显示自己的UID",
        examples=("显示UID",),
        permission="user",
        use_case=privacy_disable_uid_hidden_use_case,
    ),
    CommandSpec(
        id="privacy_enable_peek_admin",
        pattern=r"^指定开偷窥$",
        group="群管理员功能",
        name="指定开偷窥",
        description="允许会话中被艾特的玩家被其它人查看该玩家的游戏信息",
        examples=("指定开偷窥",),
        permission="admin",
        use_case=privacy_enable_peek_admin_use_case,
    ),
    CommandSpec(
        id="privacy_disable_peek_admin",
        pattern=r"^指定防偷窥$",
        group="群管理员功能",
        name="指定防偷窥",
        description="禁止会话中被艾特的玩家被其它人查看该玩家的游戏信息",
        examples=("指定防偷窥",),
        permission="admin",
        use_case=privacy_disable_peek_admin_use_case,
    ),
    CommandSpec(
        id="privacy_enable_peek_all",
        pattern=r"^全体开偷窥$",
        group="群管理员功能",
        name="全体开偷窥",
        description="允许会话中所有玩家相互查看自己的游戏信息",
        examples=("全体开偷窥",),
        permission="admin",
        use_case=privacy_enable_peek_all_use_case,
    ),
    CommandSpec(
        id="privacy_disable_peek_all",
        pattern=r"^全体防偷窥$",
        group="群管理员功能",
        name="全体防偷窥",
        description="禁止会话中所有玩家相互查看自己的游戏信息",
        examples=("全体防偷窥",),
        permission="admin",
        use_case=privacy_disable_peek_all_use_case,
    ),
    CommandSpec(
        id="privacy_cancel_peek_all",
        pattern=r"^取消全体偷窥$",
        group="群管理员功能",
        name="取消全体偷窥",
        description="取消全体偷窥设置，恢复个人设置",
        examples=("取消全体偷窥",),
        permission="admin",
        use_case=privacy_cancel_peek_all_use_case,
    ),
    CommandSpec(
        id="privacy_enable_uid_hidden_admin",
        pattern=r"^指定隐藏UID$",
        group="群管理员功能",
        name="指定隐藏UID",
        description="为会话中被艾特的玩家开启UID隐藏",
        examples=("指定隐藏UID",),
        permission="admin",
        use_case=privacy_enable_uid_hidden_admin_use_case,
    ),
    CommandSpec(
        id="privacy_disable_uid_hidden_admin",
        pattern=r"^指定显示UID$",
        group="群管理员功能",
        name="指定显示UID",
        description="为会话中被艾特的玩家关闭UID隐藏",
        examples=("指定显示UID",),
        permission="admin",
        use_case=privacy_disable_uid_hidden_admin_use_case,
    ),
    CommandSpec(
        id="privacy_enable_uid_hidden_all",
        pattern=r"^全体隐藏UID$",
        group="群管理员功能",
        name="全体隐藏UID",
        description="强制会话中所有玩家隐藏UID",
        examples=("全体隐藏UID",),
        permission="admin",
        use_case=privacy_enable_uid_hidden_all_use_case,
    ),
    CommandSpec(
        id="privacy_disable_uid_hidden_all",
        pattern=r"^全体显示UID$",
        group="群管理员功能",
        name="全体显示UID",
        description="强制会话中所有玩家显示UID",
        examples=("全体显示UID",),
        permission="admin",
        use_case=privacy_disable_uid_hidden_all_use_case,
    ),
    CommandSpec(
        id="privacy_cancel_uid_hidden_all",
        pattern=r"^取消全体UID隐藏$",
        group="群管理员功能",
        name="取消全体UID隐藏",
        description="取消全体UID隐藏设置，恢复个人设置",
        examples=("取消全体UID隐藏",),
        permission="admin",
        use_case=privacy_cancel_uid_hidden_all_use_case,
    ),
)


__all__ = ["COMMAND_SPECS"]
