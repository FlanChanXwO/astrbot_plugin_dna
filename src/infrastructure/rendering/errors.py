"""渲染层异常类型。

异常携带稳定的 ``kind``，供 handler 记录内部原因并向用户返回统一文案；
底层编程错误不在业务 handler 中被静默吞掉。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class HtmlRenderErrorKind(StrEnum):
    """渲染失败的可观测分类。"""

    TEMPLATE = "template"
    ASSET = "asset"
    T2I = "t2i"
    RESULT = "result"


class HtmlRenderError(RuntimeError):
    """统一渲染异常，保留分类和原始异常。"""

    kind: Final[HtmlRenderErrorKind]
    cause: BaseException | None

    def __init__(
        self,
        message: str,
        *,
        kind: HtmlRenderErrorKind,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.cause = cause


class TemplateRenderError(HtmlRenderError):
    """模板加载或本地 Jinja 渲染失败。"""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, kind=HtmlRenderErrorKind.TEMPLATE, cause=cause)


class AssetRenderError(HtmlRenderError):
    """本地素材读取或 data URI 编码失败。"""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, kind=HtmlRenderErrorKind.ASSET, cause=cause)


class T2IRenderError(HtmlRenderError):
    """AstrBot T2I 调用失败。"""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, kind=HtmlRenderErrorKind.T2I, cause=cause)


class RenderResultError(HtmlRenderError):
    """T2I 返回值无法转换为图片 bytes。"""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, kind=HtmlRenderErrorKind.RESULT, cause=cause)
