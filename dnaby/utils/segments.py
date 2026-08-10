"""原生消息段：替代 gsucore ``MessageSegment`` 的最小对象。

业务代码沿用 ``MessageSegment.text/image/at/node`` 写法；``Sender`` 统一解释。
命名避免与 PIL ``Image`` 冲突。
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image as PILImage

__all__ = [
    "AtSegment",
    "ImageSegment",
    "MessageSegment",
    "NodeSegment",
    "Segment",
    "TextSegment",
]


@dataclass
class TextSegment:
    content: str


@dataclass
class ImageSegment:
    # bytes / PIL 图片 / http(s) url / 本地文件路径
    value: bytes | PILImage.Image | str


@dataclass
class AtSegment:
    user_id: str
    name: str = ""


@dataclass
class NodeSegment:
    msgs: list  # 嵌套 segment 列表（转发节点）


Segment = TextSegment | ImageSegment | AtSegment | NodeSegment


class MessageSegment:
    """与 gsucore ``MessageSegment`` 同名接口的最小实现。"""

    @staticmethod
    def text(content: str) -> TextSegment:
        return TextSegment(content)

    @staticmethod
    def image(value: bytes | PILImage.Image | str) -> ImageSegment:
        return ImageSegment(value)

    @staticmethod
    def at(user_id: str | int) -> AtSegment:
        return AtSegment(str(user_id))

    @staticmethod
    def node(msgs: list) -> NodeSegment:
        return NodeSegment(msgs)
