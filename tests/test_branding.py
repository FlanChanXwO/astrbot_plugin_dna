from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rendered_brand_surfaces_use_display_name() -> None:
    help_template = (ROOT / "src/templates/cards/help.html.j2").read_text(
        encoding="utf-8"
    )
    login_template = (ROOT / "src/templates/index.html.j2").read_text(encoding="utf-8")
    calendar_template = (ROOT / "src/templates/cards/calendar.html.j2").read_text(
        encoding="utf-8"
    )

    assert "狩月终端帮助" in help_template
    assert "<title>狩月终端 登录</title>" in login_template
    assert '<div class="logo-text">狩月终端</div>' in login_template
    assert "<h1>登录狩月终端</h1>" in login_template
    assert "狩月终端 | 二重螺旋活动列表一栏 | 皎皎角" in calendar_template

    assert "DNA帮助" not in help_template
    assert "<title>DNA 登录</title>" not in login_template
    assert '<div class="logo-text">DNA</div>' not in login_template
    assert "<h1>登录 DNA</h1>" not in login_template
    assert "DNA | 二重螺旋活动列表一栏 | 皎皎角" not in calendar_template


def test_login_template_keeps_static_fallback_and_defers_media_loading():
    login_template = (ROOT / "src/templates/index.html.j2").read_text(encoding="utf-8")

    assert "login_media.video_url" in login_template
    assert "login_media.audio_url" in login_template
    assert "prefers-reduced-motion: reduce" in login_template
    assert 'aria-pressed="false"' in login_template
    assert "data-video-src" in login_template
    assert "data-audio-src" in login_template
    assert "herobox-img.yingxiong.com/post/1748784746036602530.jpg" in login_template



def test_login_surfaces_use_canonical_plugin_logo() -> None:
    login_template = (ROOT / "src/templates/index.html.j2").read_text(encoding="utf-8")
    not_found_template = (ROOT / "src/templates/404.html.j2").read_text(
        encoding="utf-8"
    )

    assert 'href="{{ plugin_logo }}"' in login_template
    assert 'src="{{ plugin_logo }}"' in login_template
    assert 'alt="狩月终端 Logo"' in login_template
    assert 'href="{{ plugin_logo }}"' in not_found_template

    for legacy_reference in (
        "Head_Songlu.png",
        "松露角色头像",
        "https://herobox-img.yingxiong.com/h5/img/logo_1.png",
    ):
        assert legacy_reference not in login_template
        assert legacy_reference not in not_found_template


def test_plugin_uses_single_root_logo_asset() -> None:
    assert (ROOT / "logo.png").is_file()
    assert not (ROOT / "ICON.png").exists()

    text_paths = (
        ROOT / "README.md",
        ROOT / "src/utils/image.py",
        ROOT / "src/infrastructure/rendering/help.py",
        ROOT / "src/utils/resource/RESOURCE_PATH.py",
    )
    for path in text_paths:
        content = path.read_text(encoding="utf-8")
        assert "ICON.png" not in content
        assert "logo.png" in content
