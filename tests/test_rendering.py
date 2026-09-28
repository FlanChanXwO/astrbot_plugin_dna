"""渲染链路核心回归测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.infrastructure.rendering import (
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


@pytest.mark.asyncio
async def test_renderer_does_not_rewrite_global_t2i_network_strategy(
    template_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """插件渲染不得覆盖 AstrBot 全局配置的 T2I 地址。"""

    import astrbot.core

    network_strategy = type(
        "NetworkStrategy",
        (),
        {
            "BASE_RENDER_URL": "https://soulter.top/text2img",
            "endpoints": ["https://soulter.top/text2img"],
        },
    )()
    t2i = FakeT2I()
    t2i.network_strategy = network_strategy
    monkeypatch.setattr(astrbot.core, "html_renderer", t2i)

    await HtmlRenderer(template_dir).render(
        "card.html",
        {"width": 100, "text": "ok"},
        RenderSpec(100),
    )

    assert network_strategy.BASE_RENDER_URL == "https://soulter.top/text2img"
    assert network_strategy.endpoints == ["https://soulter.top/text2img"]


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


def test_coerce_result_validates_container_without_pillow_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """常规 T2I 结果校验只读容器结构，不能进入 Pillow 解码路径。"""

    import src.infrastructure.rendering.renderer as renderer_module

    payload = _jpeg_bytes()

    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("常规 T2I 校验不应调用 Image.open")

    monkeypatch.setattr(Image, "open", fail_open)
    assert (
        renderer_module.HtmlRenderer._coerce_result(
            payload,
            RenderSpec(width=1, image_format="jpeg"),
        )
        == payload
    )


@pytest.mark.asyncio
async def test_weapon_template_uses_independent_archive_layout_and_all_fields() -> None:
    """独立武器卡突出武器主视觉，不复用角色详情区块或账号资料。"""

    templates = Path(__file__).parents[1] / "src" / "templates"
    t2i = FakeT2I(_jpeg_bytes())
    renderer = HtmlRenderer(templates, t2i=t2i)
    weapon = {
        "attribute_background": "data:image/png;base64,attr",
        "attributes": [
            {"icon": "", "label": label, "value": value}
            for label, value in (
                ("武器类型", "近战"),
                ("攻击", "777"),
                ("暴击率", "150%"),
                ("暴击伤害", "10%"),
                ("攻击速度", "1.2"),
                ("触发率", "30%"),
            )
        ],
        "icon": "data:image/png;base64,weapon",
        "level": 80,
        "modes": [
            {
                "background": "data:image/png;base64,mode-frame",
                "icon": "data:image/png;base64,mode-icon",
                "level": "+2",
                "name": "武器楔",
                "side": "left",
            }
        ],
        "name": "近战甲",
        "skill_level": 5,
        "title": "武器详情",
        "weapon_background": "",
    }

    await renderer.render(
        "cards/weapon_detail.html.j2",
        {
            "background": "",
            "font": "",
            "footer_image": "",
            "header": {
                "avatar": "data:image/png;base64,avatar",
                "avatar_frame": "data:image/png;base64,avatar-frame",
                "level": 42,
                "level_background": "data:image/png;base64,level",
                "name": "测试玩家",
                "stats": [],
                "uid": "123456",
            },
            "profile_background": "data:image/png;base64,profile",
            "weapon": weapon,
            "width": 1000,
        },
        RenderSpec(width=1000, full_page=True, image_format="jpeg"),
    )

    html = str(t2i.calls[0]["tmpl_str"])
    assert 'data-weapon-card="archive"' in html
    assert 'data-weapon-section="shared"' not in html
    assert "weapon-detail__visual" in html
    assert "weapon-detail__specs" in html
    assert "weapon-detail__modules" in html
    assert "weapon-detail__profile" in html
    assert "data:image/png;base64,attr" in html
    assert "data:image/png;base64,mode-frame" in html
    assert "data:image/png;base64,avatar-frame" in html
    assert "data:image/png;base64,profile" in html
    assert "测试玩家" in html
    assert "UID 123456" in html
    for expected in (
        "近战甲",
        "Lv.80",
        "精炼等级 5",
        "武器类型",
        "攻击",
        "暴击率",
        "暴击伤害",
        "攻击速度",
        "触发率",
        "武器楔",
    ):
        assert expected in html

    role_template = (templates / "cards/role_detail.html.j2").read_text(
        encoding="utf-8"
    )
    weapon_template = (templates / "cards/weapon_detail.html.j2").read_text(
        encoding="utf-8"
    )
    assert "{{ weapon_section(weapon) }}" in role_template
    assert "{{ weapon_section(weapon) }}" not in weapon_template
    assert "weapon-detail__profile" in weapon_template
