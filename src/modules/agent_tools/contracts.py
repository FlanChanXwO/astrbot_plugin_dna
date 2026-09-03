"""Agent Tools 使用的框架无关 typed request/result。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, Protocol, TypeVar

from ...entry.event import EventActor

ResultData = TypeVar("ResultData")


@dataclass(frozen=True, slots=True)
class AgentQueryRequest:
    """一次 Agent 查询的可信请求。

    Agent 入口只从当前事件构造 ``actor``；``target_user_id`` 仅供聊天命令
    复用同一领域查询时携带已经由命令入口解析过的 @ 目标，不能由 Agent 工具
    参数设置。
    """

    actor: EventActor
    target_user_id: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    text: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.actor, EventActor):
            raise TypeError("Agent 查询 actor 必须是 EventActor")
        if self.target_user_id is not None:
            if not isinstance(self.target_user_id, str):
                raise TypeError("Agent 查询 target_user_id 必须是字符串或 None")
            target_user_id = self.target_user_id.strip()
            object.__setattr__(self, "target_user_id", target_user_id or None)
        if not isinstance(self.parameters, Mapping):
            raise TypeError("Agent 查询 parameters 必须是映射")
        if any(not isinstance(key, str) for key in self.parameters):
            raise TypeError("Agent 查询参数名必须是字符串")
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )
        if not isinstance(self.text, str):
            raise TypeError("Agent 查询 text 必须是字符串")


@dataclass(frozen=True, slots=True)
class AgentQueryPresentation:
    """给 Agent 同时提供结构化数据和可选直发响应。"""

    data: object
    direct_response: object | None = None


@dataclass(frozen=True, slots=True)
class AgentQueryResult(Generic[ResultData]):
    """Agent 查询的稳定结果 envelope。

    ``data`` 暂时保留领域响应对象，由后续 Agent adapter 负责转成 JSON 或发送
    图片；结构化数据和可选直发响应使用 ``AgentQueryPresentation`` 携带；这样领域层
    不需要依赖 AstrBot。``to_dict`` 固定 envelope 字段，避免后续工具各自发明返回形状。
    """

    ok: bool
    kind: str
    data: ResultData | None = None
    cache: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError("Agent 查询 ok 必须是 bool")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("Agent 查询 kind 不能为空")
        object.__setattr__(self, "kind", self.kind.strip())
        error = self.error
        if self.ok and error not in (None, ""):
            raise ValueError("成功响应不得携带 error")
        if not self.ok and (not isinstance(error, str) or not error.strip()):
            raise ValueError("失败响应必须携带 error")

    @classmethod
    def success(
        cls,
        kind: str,
        data: ResultData | None = None,
        *,
        cache: str | None = None,
    ) -> AgentQueryResult[ResultData]:
        """建立成功查询结果。"""

        return cls(ok=True, kind=kind, data=data, cache=cache)

    @classmethod
    def failure(
        cls,
        kind: str,
        error: str,
        *,
        data: ResultData | None = None,
        cache: str | None = None,
    ) -> AgentQueryResult[ResultData]:
        """建立带明确错误信息的查询结果。"""

        return cls(ok=False, kind=kind, data=data, cache=cache, error=error)

    def to_dict(self) -> dict[str, object]:
        """返回固定字段的 envelope；data 的最终 JSON 化由 entry adapter 负责。"""

        return {
            "ok": self.ok,
            "kind": self.kind,
            "data": self.data,
            "cache": self.cache,
            "error": self.error,
        }


class AgentQueryUseCase(Protocol):
    """一个可被聊天命令和 Agent adapter 共同调用的领域查询。"""

    async def __call__(self, request: AgentQueryRequest) -> Any:
        """用可信请求执行查询并返回领域响应。"""


__all__ = [
    "AgentQueryPresentation",
    "AgentQueryRequest",
    "AgentQueryResult",
    "AgentQueryUseCase",
]
