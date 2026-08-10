"""AstrBot 原生响应转换边界。"""

from __future__ import annotations

from typing import Any


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

