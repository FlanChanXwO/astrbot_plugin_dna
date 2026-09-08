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
