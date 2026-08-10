"""框架无关响应 DTO 到 AstrBot 原生结果的转换边界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlainTextResponse:
    """纯文本 use case 响应。"""

    text: str


@dataclass(frozen=True, slots=True)
class ChainResponse:
    """消息链 use case 响应。"""

    components: Any


@dataclass(frozen=True, slots=True)
class ImageResponse:
    """图片 use case 响应。"""

    image: Any


CommandResponse = PlainTextResponse | ChainResponse | ImageResponse


class ResponseFactory:
    """集中调用 AstrBot 事件的原生结果构造方法。

    业务 use case 不应直接依赖 ``plain_result``/``chain_result``；后续命令层
    只把框架无关 DTO 交给此类转换。
    """

    @staticmethod
    def plain(event: Any, text: str) -> Any:
        """构造 AstrBot 原生纯文本结果。"""

        return event.plain_result(text)

    @staticmethod
    def chain(event: Any, components: Any) -> Any:
        """构造 AstrBot 原生消息链结果。"""

        return event.chain_result(components)

    @staticmethod
    def image(event: Any, image: Any) -> Any:
        """构造 AstrBot 原生图片结果。"""

        return event.image_result(image)

    @classmethod
    def build(cls, event: Any, response: CommandResponse) -> Any:
        """将框架无关 DTO 转换为 AstrBot 原生结果。"""

        if isinstance(response, PlainTextResponse):
            return cls.plain(event, response.text)
        if isinstance(response, ChainResponse):
            return cls.chain(event, response.components)
        if isinstance(response, ImageResponse):
            return cls.image(event, response.image)
        raise TypeError(f"未知命令响应类型: {type(response).__name__}")


__all__ = [
    "ChainResponse",
    "CommandResponse",
    "ImageResponse",
    "PlainTextResponse",
    "ResponseFactory",
]
