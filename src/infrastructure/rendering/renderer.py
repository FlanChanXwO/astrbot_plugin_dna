"""Jinja2 模板到 AstrBot T2I 的适配器。"""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from jinja2 import Environment, FileSystemLoader, TemplateError, select_autoescape

from .errors import RenderResultError, T2IRenderError, TemplateRenderError
from .image_inspector import inspect_image
from .spec import RenderSpec

logger = logging.getLogger(__name__)
_WARN_BYTES = 1024 * 1024


class T2IRenderer(Protocol):
    """AstrBot 全局 ``html_renderer`` 的最小可测试协议。"""

    async def render_custom_template(
        self,
        tmpl_str: str,
        tmpl_data: dict[str, Any],
        return_url: bool = False,
        options: dict[str, object] | None = None,
    ) -> bytes | str | Path: ...


class HtmlRenderer:
    """加载模板、渲染 HTML，并归一化 AstrBot T2I 结果。"""

    def __init__(
        self,
        template_dir: Path | None = None,
        *,
        t2i: T2IRenderer | None = None,
        environment: Environment | None = None,
    ) -> None:
        if template_dir is not None:
            self.template_dir = template_dir
        else:
            src_templates = Path(__file__).parents[2] / "templates"
            if src_templates.exists():
                self.template_dir = src_templates
            else:
                self.template_dir = Path(__file__).parents[3] / "dnaby" / "templates"
        self._t2i = t2i
        self._environment = environment or Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(
                enabled_extensions=("html", "j2", "jinja", "jinja2"),
                default_for_string=True,
            ),
        )

    async def render(
        self,
        template_name: str,
        data: dict[str, Any],
        spec: RenderSpec,
    ) -> bytes:
        """渲染指定模板并返回符合 ``spec`` 的图片 bytes。"""

        started_at = perf_counter()

        try:
            template = self._environment.get_template(template_name)
            html = template.render(**data)
        except TemplateError as exc:
            raise TemplateRenderError(
                f"模板渲染失败: {template_name}", cause=exc
            ) from exc
        except OSError as exc:
            raise TemplateRenderError(
                f"模板读取失败: {template_name}", cause=exc
            ) from exc

        t2i = self._get_t2i()
        t2i_started_at = perf_counter()
        try:
            result = await t2i.render_custom_template(
                tmpl_str=html,
                tmpl_data={},
                return_url=False,
                options=spec.options(),
            )
        except Exception as exc:
            raise T2IRenderError("AstrBot T2I 服务调用失败", cause=exc) from exc

        t2i_elapsed = perf_counter() - t2i_started_at
        image_bytes = self._coerce_result(result, spec)
        total_elapsed = perf_counter() - started_at
        log = logger.warning if len(image_bytes) > _WARN_BYTES else logger.info
        log(
            "T2I 渲染完成 template=%s format=%s canvas=%sx%s "
            "t2i=%.3fs total=%.3fs bytes=%s",
            template_name,
            spec.image_format,
            spec.width,
            spec.height or "auto",
            t2i_elapsed,
            total_elapsed,
            len(image_bytes),
        )
        return image_bytes

    def _get_t2i(self) -> T2IRenderer:
        if self._t2i is not None:
            return self._t2i
        try:
            from astrbot.core import html_renderer
        except ImportError as exc:
            raise T2IRenderError(
                "无法导入 AstrBot 全局 html_renderer", cause=exc
            ) from exc
        self._t2i = html_renderer
        return html_renderer

    @staticmethod
    def _coerce_result(result: bytes | str | Path, spec: RenderSpec) -> bytes:
        if isinstance(result, bytes):
            data = result

        elif isinstance(result, (str, Path)):
            path = Path(result)
            try:
                data = path.read_bytes()
            except (OSError, ValueError) as exc:
                raise RenderResultError(
                    f"T2I 返回路径不可读: {result!s}", cause=exc
                ) from exc
        else:
            raise RenderResultError(f"T2I 返回了不支持的类型: {type(result).__name__}")

        # 网络渲染失败时服务可能返回可读的 HTML 错误页，必须在消息发送前显式拒绝。
        # 这里只检查 JPEG/PNG 容器结构，不解码像素，也不经过 Pillow 重编码。
        expected_media_type = (
            "image/png" if spec.image_format == "png" else "image/jpeg"
        )
        expected_name = "PNG" if spec.image_format == "png" else "JPEG"
        try:
            inspect_image(data, media_type=expected_media_type)
        except ValueError as exc:
            actual_media_type = (
                "image/jpeg"
                if data.startswith(b"\xff\xd8")
                else "image/png"
                if data.startswith(b"\x89PNG\r\n\x1a\n")
                else None
            )
            if (
                actual_media_type is not None
                and actual_media_type != expected_media_type
            ):
                actual_name = "JPEG" if actual_media_type == "image/jpeg" else "PNG"
                raise RenderResultError(
                    f"T2I 返回格式不匹配，期望 {expected_name}，实际为 {actual_name}",
                    cause=exc,
                ) from exc
            raise RenderResultError("T2I 返回结果不是可解码的图片", cause=exc) from exc
        return data
