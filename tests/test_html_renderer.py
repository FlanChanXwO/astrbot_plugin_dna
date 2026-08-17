from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from dnaby.rendering import (
    HtmlRenderer,
    RenderResultError,
    RenderSpec,
    T2IRenderError,
    TemplateRenderError,
)


def _png_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (1, 1), "black").save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (1, 1), "black").save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeT2I:
    def __init__(self, result: object | None = None) -> None:
        self.result = _png_bytes() if result is None else result
        self.calls: list[dict[str, object]] = []

    async def render_custom_template(
        self,
        tmpl_str: str,
        tmpl_data: dict[str, Any],
        return_url: bool = False,
        options: dict[str, object] | None = None,
    ) -> Any:
        kwargs = {
            "tmpl_str": tmpl_str,
            "tmpl_data": tmpl_data,
            "return_url": return_url,
            "options": options,
        }
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture()
def template_dir(tmp_path: Path) -> Path:
    (tmp_path / "card.html").write_text(
        "<body><main style='width: {{ width }}px'>{{ text }}</main></body>",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_renderer_escapes_template_data_and_forwards_png_options(
    template_dir: Path,
) -> None:
    t2i = FakeT2I()
    renderer = HtmlRenderer(template_dir, t2i=t2i)

    result = await renderer.render(
        "card.html",
        {"width": 640, "text": "<script>alert(1)</script>"},
        RenderSpec(width=640, height=120, full_page=False),
    )

    assert result.startswith(b"\x89PNG")
    call = t2i.calls[0]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in str(call["tmpl_str"])
    assert call["tmpl_data"] == {}
    assert call["return_url"] is False
    assert call["options"] == {
        "full_page": False,
        "type": "png",
        "scale": "css",
        "viewport_width": 640,
        "viewport_height": 120,
        "clip": {"x": 0, "y": 0, "width": 640, "height": 120},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("as_string", [False, True])
async def test_renderer_supports_full_page_and_path_results(
    template_dir: Path,
    tmp_path: Path,
    as_string: bool,
) -> None:
    result_path = tmp_path / "result.png"
    result_path.write_bytes(_png_bytes())
    t2i = FakeT2I(str(result_path) if as_string else result_path)
    renderer = HtmlRenderer(template_dir, t2i=t2i)

    result = await renderer.render(
        "card.html",
        {"width": 100, "text": "ok"},
        RenderSpec(width=100, full_page=True),
    )

    assert result.startswith(b"\x89PNG")
    assert t2i.calls[0]["options"] == {
        "full_page": True,
        "type": "png",
        "scale": "css",
        "viewport_width": 100,
    }


@pytest.mark.asyncio
async def test_renderer_forwards_jpeg_quality_and_validates_result(
    template_dir: Path,
) -> None:
    t2i = FakeT2I(_jpeg_bytes())
    renderer = HtmlRenderer(template_dir, t2i=t2i)

    result = await renderer.render(
        "card.html",
        {"width": 640, "text": "ok"},
        RenderSpec(width=640, image_format="jpeg"),
    )

    assert result.startswith(b"\xff\xd8")
    assert t2i.calls[0]["options"] == {
        "full_page": True,
        "type": "jpeg",
        "quality": 85,
        "scale": "css",
        "viewport_width": 640,
    }


@pytest.mark.asyncio
async def test_renderer_rejects_result_format_mismatch(template_dir: Path) -> None:
    renderer = HtmlRenderer(template_dir, t2i=FakeT2I(_jpeg_bytes()))

    with pytest.raises(RenderResultError, match="期望 PNG"):
        await renderer.render("card.html", {"width": 100, "text": "x"}, RenderSpec(100))


@pytest.mark.asyncio
async def test_renderer_classifies_t2i_and_result_errors(template_dir: Path) -> None:
    renderer = HtmlRenderer(template_dir, t2i=FakeT2I(RuntimeError("offline")))
    with pytest.raises(T2IRenderError) as error:
        await renderer.render("card.html", {"width": 100, "text": "x"}, RenderSpec(100))
    assert error.value.cause is not None

    renderer = HtmlRenderer(template_dir, t2i=FakeT2I(object()))
    with pytest.raises(RenderResultError):
        await renderer.render("card.html", {"width": 100, "text": "x"}, RenderSpec(100))

    renderer = HtmlRenderer(template_dir, t2i=FakeT2I(b"<html>t2i error</html>"))
    with pytest.raises(RenderResultError, match="可解码的图片"):
        await renderer.render("card.html", {"width": 100, "text": "x"}, RenderSpec(100))


@pytest.mark.asyncio
async def test_renderer_classifies_template_errors(template_dir: Path) -> None:
    renderer = HtmlRenderer(template_dir, t2i=FakeT2I())
    with pytest.raises(TemplateRenderError):
        await renderer.render("missing.html", {}, RenderSpec(100))


def test_render_spec_rejects_ambiguous_screenshot() -> None:
    with pytest.raises(ValueError):
        RenderSpec(width=100, full_page=False)
    with pytest.raises(ValueError):
        RenderSpec(
            width=100,
            height=10,
            full_page=True,
            clip={"x": 0, "y": 0, "width": 1, "height": 1},
        )
    with pytest.raises(ValueError, match="PNG"):
        RenderSpec(width=100, quality=85)
    with pytest.raises(ValueError, match="quality"):
        RenderSpec(width=100, image_format="jpeg", quality=101)
    with pytest.raises(ValueError, match="格式"):
        RenderSpec(width=100, image_format="webp")  # type: ignore[arg-type]
