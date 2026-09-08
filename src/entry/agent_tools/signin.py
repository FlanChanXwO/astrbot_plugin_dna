"""Agent 签到工具的原始消息确认边界。"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext

from ...modules.agent_tools.contracts import AgentQueryResult
from ...modules.checkin.contracts import CheckinCommandRequest
from .context import agent_request_from_context
from .tools import _result_json

_SIGN_TERMS = (
    "签到",
    "社区签到",
    "每日任务",
    "社区任务",
    "库街区签到",
)
_NEGATIVE_MARKERS = (
    "不要",
    "别",
    "不",
    "取消",
    "停止",
    "暂停",
    "暂不",
    "不用",
    "无需",
    "拒绝",
)
_QUESTION_MARKERS = (
    "是否",
    "为什么",
    "为何",
    "要不要",
    "需不需要",
    "能否",
    "是不是",
    "吗",
    "呢",
)
_AFFIRMATIVE_PREFIXES = (
    "请",
    "请帮我",
    "帮我",
    "给我",
    "我要",
    "我想",
    "执行",
    "开始",
    "进行",
    "确认",
    "同意",
    "可以",
    "好的",
    "好吧",
    "立即",
    "马上",
    "去",
    "我去",
)
_ENGLISH_NEGATIVE_PATTERN = re.compile(
    r"\b(?:no|not|never|don't|do\s+not|cancel|stop)\b",
)
_ENGLISH_SIGN_PHRASES = (
    "sign",
    "pleasesign",
    "confirmsign",
    "executesign",
    "startsign",
    "yessign",
    "oksign",
)


def _compact_message(text: str) -> str:
    """折叠空白和标点，便于识别被正常输入分隔的命令短语。"""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "S"))
    )


def sign_intent_from_text(
    text: object,
    *,
    prefixes: Sequence[str] = (),
) -> bool:
    """判断原始消息是否明确要求执行签到。

    该判断故意只接受短而明确的肯定表达。否定或疑问标记优先于肯定标记，
    避免模型把“是否签到”“不要签到”之类的上下文误当成写操作确认。
    """

    if not isinstance(text, str) or not text.strip():
        return False

    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    compact = _compact_message(text)
    if any(marker in compact for marker in _NEGATIVE_MARKERS):
        return False
    if _ENGLISH_NEGATIVE_PATTERN.search(normalized) is not None:
        return False
    if any(marker in compact for marker in _QUESTION_MARKERS):
        return False
    if "?" in normalized or "？" in normalized:
        return False

    direct_terms: set[str] = set(_SIGN_TERMS)
    direct_terms.update(_ENGLISH_SIGN_PHRASES)
    direct_terms.update(
        prefix + term for prefix in _AFFIRMATIVE_PREFIXES for term in _SIGN_TERMS
    )
    for prefix in prefixes:
        if isinstance(prefix, str) and prefix.strip():
            direct_terms.add(_compact_message(prefix) + "签到")
            direct_terms.add(_compact_message(prefix) + "sign")
    return compact in direct_terms


def _failure(error: str) -> str:
    """构造签到工具统一 JSON 失败 envelope。"""

    return _result_json(AgentQueryResult.failure(kind="sign", error=error))


def _context_event(value: ContextWrapper[AstrAgentContext]) -> Any:
    agent_context = getattr(value, "context", None)
    event = getattr(agent_context, "event", None)
    if event is None:
        raise ValueError("Agent context 缺少原始消息事件")
    return event


def _raw_message(event: Any) -> str:
    getter = getattr(event, "get_message_str", None)
    raw = getter() if callable(getter) else getattr(event, "message_str", None)
    if not isinstance(raw, str):
        raise TypeError("当前事件不提供原始消息文本")
    return raw


def _message_id(event: Any) -> str:
    message_object = getattr(event, "message_obj", None)
    value = getattr(message_object, "message_id", None)
    if value is None:
        value = getattr(event, "message_id", None)
    if value is None or not str(value).strip():
        raise ValueError("无法验证原始消息 ID，已拒绝签到")
    return str(value).strip()


def _event_cache(event: Any) -> tuple[Any, Any]:
    getter = getattr(event, "get_extra", None)
    setter = getattr(event, "set_extra", None)
    if not callable(getter) or not callable(setter):
        raise TypeError("当前事件不支持签到幂等校验")
    return getter, setter


_SIGN_LOCK_EXTRA = "dnaby_agent_sign_lock"
_SIGN_RESULT_EXTRA = "dnaby_agent_sign_result"


class AgentSignTool(FunctionTool):
    """仅允许由当前原始消息明确确认的当前用户签到工具。"""

    name = "dnaby_sign"

    def __init__(
        self,
        *,
        checkin_service: object,
        command_prefixes: Sequence[str] = (),
        plugin_context: object | None = None,
    ) -> None:
        super().__init__(
            name=self.name,
            description=(
                "执行当前消息用户当前激活 UID 的签到。仅当原始消息明确表示肯定签到意图时可用；"
                "不接受确认、用户 ID、UID 或其他目标参数，并按消息 ID 幂等。"
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=None,
        )
        self.checkin_service = checkin_service
        self.command_prefixes = tuple(command_prefixes)
        if plugin_context is not None:
            module_path = getattr(plugin_context, "__module__", None)
            if isinstance(module_path, str) and module_path:
                self.handler_module_path = module_path

    @staticmethod
    def _cached_result(getter: Any, message_id: str) -> str | None:
        cached = getter(_SIGN_RESULT_EXTRA, None)
        if cached is None:
            return None
        if not isinstance(cached, dict):
            raise TypeError("签到幂等缓存格式无效")
        if cached.get("message_id") != message_id:
            raise ValueError("当前事件的消息 ID 与签到幂等缓存不一致")
        result = cached.get("result")
        if not isinstance(result, str):
            raise TypeError("签到幂等缓存结果无效")
        return result

    @staticmethod
    def _store_result(setter: Any, message_id: str, result: str) -> None:
        setter(
            _SIGN_RESULT_EXTRA,
            {"message_id": message_id, "result": result},
        )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> str:
        if kwargs:
            return _failure("签到确认必须来自原始消息，不接受工具参数")

        try:
            event = _context_event(context)
            raw_text = _raw_message(event)
        except (TypeError, ValueError) as error:
            logger.warning(
                "[dnaby][agent_tools] 签到原始消息校验失败: %s",
                type(error).__name__,
            )
            return _failure(str(error))

        if not sign_intent_from_text(raw_text, prefixes=self.command_prefixes):
            return _failure("原始消息未明确确认签到")

        try:
            message_id = _message_id(event)
            getter, setter = _event_cache(event)
            lock = getter(_SIGN_LOCK_EXTRA, None)
            if lock is None:
                # get/set 之间没有 await；同一事件的协程会共享首次写入的锁。
                lock = asyncio.Lock()
                setter(_SIGN_LOCK_EXTRA, lock)
            if not isinstance(lock, asyncio.Lock):
                raise TypeError("签到幂等锁格式无效")
        except (TypeError, ValueError) as error:
            logger.warning(
                "[dnaby][agent_tools] 签到幂等校验失败: %s",
                type(error).__name__,
            )
            return _failure(str(error))

        async with lock:
            try:
                cached = self._cached_result(getter, message_id)
                if cached is not None:
                    return cached
                agent_request = agent_request_from_context(context)
                request = CheckinCommandRequest(
                    actor=agent_request.actor,
                    target_user_id=None,
                    parameters={},
                    text=raw_text,
                )
                response = await self.checkin_service.manual_sign(request)  # type: ignore[attr-defined]
                result = _result_json(
                    AgentQueryResult.success(kind="sign", data=response),
                )
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "[dnaby][agent_tools] 签到执行失败: %s",
                    type(error).__name__,
                )
                result = _failure("签到执行失败")
            try:
                self._store_result(setter, message_id, result)
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "[dnaby][agent_tools] 签到幂等结果记录失败: %s",
                    type(error).__name__,
                )
                return _failure("签到结果无法完成幂等记录")
            return result


__all__ = ["AgentSignTool", "sign_intent_from_text"]
