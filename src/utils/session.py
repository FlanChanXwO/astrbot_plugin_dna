"""原生会话适配层：``EventContext`` + ``Sender``。

替代 gsucore 的 ``Event`` / ``Bot``：

- ``EventContext``：从 AstrMessageEvent 提取业务代码读取的只读字段。
- ``Sender``：累积 ``send(...)`` 的发送载荷，handler 末尾统一转为 AstrBot 结果。

业务函数签名从 ``(bot: Bot, ev: Event)`` 改为 ``(sender: Sender, ctx: EventContext)``。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator, Iterable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from .segments import AtSegment, ImageSegment, NodeSegment, Segment, TextSegment

__all__ = ["EventContext", "SendPayload", "Sender"]


@dataclass
class EventContext:
    """业务代码读取的事件字段（替代 gsucore ``Event``）。"""

    message_str: str = ""
    user_id: str = ""
    bot_id: str = ""
    group_id: str = ""
    at: str = ""
    text: str = ""
    command: str = ""
    raw_text: str = ""
    regex_dict: dict[str, str] = field(default_factory=dict)
    regex_group: tuple[str, ...] = ()
    image_list: list = field(default_factory=list)
    reply: str = ""
    user_pm: int = 6
    user_type: str = "group"
    unified_msg_origin: str = ""
    platform: str = ""
    at_list: list = field(default_factory=list)
    msg: list = field(default_factory=list)
    WS_BOT_ID: str = ""
    real_bot_id: str = ""

    @property
    def is_direct(self) -> bool:
        return self.user_type == "direct"

    def bot_self_id(self) -> str:
        return self.platform or self.bot_id


# 一次 send 的载荷：文本 / 字节 / PIL 图片 / 文件路径 / segment / 它们的列表
SendPayload = str | bytes | PILImage.Image | Path | Segment | Iterable["SendPayload"]
ImmediateSend = Callable[[list[Any]], Awaitable[None]]


class _SendResult:
    """同步入队结果的可等待句柄，兼容旧 handler 的 ``await sender.send``。"""

    def __await__(self) -> Generator[None, None, None]:
        if False:
            yield None
        return None


class Sender:
    """累积发送消息；``to_chains()`` 转为 AstrBot 组件链。"""

    def __init__(
        self,
        ctx: EventContext,
        immediate_send: ImmediateSend | None = None,
    ) -> None:
        self.ctx = ctx
        self._immediate_send = immediate_send
        # 每个元素 = 一次 send() 的组件链（segment 列表）
        self.messages: list[list[Segment]] = []

    # ---- 业务接口 ----
    def send(
        self,
        msg: SendPayload,
        at_sender: bool = False,
        wait_recall: bool = False,
    ) -> _SendResult:
        """入队消息；保留 ``wait_recall`` 以兼容旧调用方。

        AstrBot handler 先收集结果链，发送完成后的 message id 不在此层可用；
        因此 await 该返回值只返回 None，原图缓存逻辑会自然跳过。
        """
        segs = self._prepare_segments(msg, at_sender)
        if segs:
            self.messages.append(segs)
        return _SendResult()

    async def send_now(
        self,
        msg: SendPayload,
        at_sender: bool = False,
    ) -> None:
        """立即发送一条消息；未绑定回调时退回当前事件的消息队列。"""
        segs = self._prepare_segments(msg, at_sender)
        if not segs:
            return
        if self._immediate_send is None:
            self.messages.append(segs)
            return

        from astrbot.api import message_components as Comp

        chain = [
            component
            for seg in segs
            if (component := self._to_component(seg, Comp)) is not None
        ]
        if chain:
            await self._immediate_send(chain)

    def send_option(self, im: bytes) -> None:
        """兼容 gsucore ``bot.send_option``：帮助卡片图片。"""
        self.send(im)

    def _prepare_segments(self, msg: SendPayload, at_sender: bool) -> list[Segment]:
        segs = self._parse(msg)
        if at_sender and self.ctx.user_id:
            segs.insert(0, AtSegment(self.ctx.user_id))
        return segs

    @staticmethod
    def _parse(msg: SendPayload) -> list[Segment]:
        if msg is None:
            return []
        if isinstance(msg, Segment):
            return [msg]
        if isinstance(msg, str):
            return [TextSegment(msg)]
        if isinstance(msg, bytes):
            return [ImageSegment(msg)]
        if isinstance(msg, PILImage.Image):
            return [ImageSegment(msg)]
        if isinstance(msg, Path):
            return [ImageSegment(str(msg))]
        if isinstance(msg, Iterable):
            out: list[Segment] = []
            for item in msg:
                out.extend(Sender._parse(item))
            return out
        # 兜底：未识别类型转文本
        return [TextSegment(str(msg))]

    # ---- 结果转换 ----
    def to_chains(self) -> list[list]:
        """返回 list[list[BaseMessageComponent]]，供 handler yield。"""
        from astrbot.api import message_components as Comp  # 惰性导入

        chains: list[list] = []
        for segs in self.messages:
            chain: list = []
            for seg in segs:
                comp = self._to_component(seg, Comp)
                if comp is not None:
                    chain.append(comp)
            if chain:
                chains.append(chain)
        return chains

    @staticmethod
    def _to_component(seg: Segment, Comp) -> Any:
        if isinstance(seg, TextSegment):
            return Comp.Plain(seg.content)
        if isinstance(seg, ImageSegment):
            value = seg.value
            if isinstance(value, bytes):
                return Comp.Image.fromBytes(value)
            if isinstance(value, PILImage.Image):
                buf = BytesIO()
                value.convert("RGB").save(buf, format="PNG")
                return Comp.Image.fromBytes(buf.getvalue())
            s = str(value)
            if s.startswith(("http://", "https://")):
                return Comp.Image.fromURL(s)
            return Comp.Image.fromFileSystem(s)
        if isinstance(seg, AtSegment):
            return Comp.At(qq=seg.user_id, name=seg.name or "")
        if isinstance(seg, NodeSegment):
            nodes = []
            for inner in seg.msgs:
                inner_segs = inner if isinstance(inner, list) else [inner]
                content = []
                for s in Sender._parse(inner_segs):
                    comp = Sender._to_component(s, Comp)
                    if comp is not None:
                        content.append(comp)
                nodes.append(Comp.Node(content=content))
            if nodes:
                if len(nodes) == 1:
                    return nodes[0]
                return Comp.Nodes(nodes)
        return None
