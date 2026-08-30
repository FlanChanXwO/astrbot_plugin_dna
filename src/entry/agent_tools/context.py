"""从 AstrBot 官方 Agent context 提取可信事件身份。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext

from ...modules.agent_tools.contracts import AgentQueryRequest
from ..event import actor_from_event

_FORBIDDEN_IDENTITY_PARAMETERS = frozenset(
    {
        "user_id",
        "target_user_id",
        "bot_id",
        "credential_user_id",
        "uid",
    },
)


class AgentContextError(ValueError):
    """Agent context 缺少可验证的 AstrBot 事件身份。"""


def _unwrap_context(
    value: ContextWrapper[AstrAgentContext] | AstrAgentContext,
) -> AstrAgentContext:
    if isinstance(value, AstrAgentContext):
        return value
    nested = getattr(value, "context", None)
    if isinstance(nested, AstrAgentContext):
        return nested
    raise AgentContextError("Agent context 类型无效")


def agent_request_from_context(
    value: ContextWrapper[AstrAgentContext] | AstrAgentContext,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> AgentQueryRequest:
    """从 ``AstrAgentContext.event`` 构造当前用户查询请求。

    不读取工具参数中的身份字段，也不接受模型提供的用户/UID 覆盖值；当前
    Agent 查询固定以事件发送者为作用域，跨用户查询必须走聊天命令的隐私边界。
    """

    agent_context = _unwrap_context(value)
    try:
        actor = actor_from_event(agent_context.event)
    except ValueError as error:
        raise AgentContextError("事件身份无效") from error
    if actor is None:
        raise AgentContextError("事件身份不可用")

    normalized_parameters = dict(parameters) if parameters is not None else {}
    if not isinstance(parameters, Mapping) and parameters is not None:
        raise TypeError("Agent 查询 parameters 必须是映射")
    forbidden = _FORBIDDEN_IDENTITY_PARAMETERS.intersection(normalized_parameters)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"Agent 查询参数不得包含身份参数: {names}")
    return AgentQueryRequest(actor=actor, parameters=normalized_parameters)


__all__ = ["AgentContextError", "agent_request_from_context"]
