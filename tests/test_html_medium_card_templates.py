from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parents[1] / "dnaby" / "templates"


@pytest.fixture
def environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("j2",)),
    )


def test_medium_card_templates_keep_dynamic_content_and_escape(environment: Environment) -> None:
    """中等卡片模板应保留空数据、长文本和动态条目，不拼接不可信 HTML。"""

    base = {
        "background": "data:image/png;base64,AA==",
        "font": "data:font/ttf;base64,AA==",
        "footer_text": "DNAUID",
        "header": {
            "avatar": "data:image/png;base64,AA==",
            "name": "旅行者 <script>",
            "uid": "10001",
            "level": 60,
            "stats": [{"label": "总活跃天数", "value": "999"}],
        },
    }
    rendered = {
        "cards/mh_simple.html.j2": environment.get_template("cards/mh_simple.html.j2").render(
            **base,
            width=1040,
            entries=[
                {
                    "icon": "data:image/png;base64,AA==",
                    "type_name": "角色",
                    "instances": [{"name": "很长很长的密函名称", "subscribed": True}],
                }
            ],
            refresh_text="59分钟59秒后刷新",
        ),
        "cards/mh_card.html.j2": environment.get_template("cards/mh_card.html.j2").render(
            **base,
            width=1700,
            height=900,
            cards=[
                {
                    "icon": "data:image/png;base64,AA==",
                    "type_name": "武器",
                    "instances": [{"name": "密函", "subscribed": False}],
                }
            ],
            refresh_text="5分钟后刷新",
        ),
        "cards/stamina.html.j2": environment.get_template("cards/stamina.html.j2").render(
            **base,
            width=2000,
            height=1100,
            notes=[
                {
                    "name": "备忘手记",
                    "current": 0,
                    "total": 0,
                    "icon": "data:image/png;base64,AA==",
                    "ratio": 0,
                }
            ],
            drafts=[],
        ),
        "cards/calendar.html.j2": environment.get_template("cards/calendar.html.j2").render(
            **base,
            width=1200,
            banner="data:image/png;base64,AA==",
            events=[
                {
                    "title": "<活动>",
                    "icon": "data:image/png;base64,AA==",
                    "date_range": "01.01 00:00 ~ 01.02 00:00",
                    "status": "进行中",
                    "left": "还剩1天",
                    "progress": 0.5,
                }
            ],
        ),
        "cards/sign_calendar.html.j2": environment.get_template("cards/sign_calendar.html.j2").render(
            **base,
            width=1300,
            achievements=[{"label": "皎皎积分", "value": "0"}],
            tasks=[],
            awards=[
                {
                    "day": 1,
                    "icon": "data:image/png;base64,AA==",
                    "amount": "1",
                    "signed": False,
                    "current": False,
                }
            ],
        ),
        "cards/role_info.html.j2": environment.get_template("cards/role_info.html.j2").render(
            **base,
            width=1200,
            achievements=[{"label": "角色数量", "value": "0"}],
            sections=[
                {
                    "title": "角色信息",
                    "items": [],
                }
            ],
        ),
        "cards/weekly_report.html.j2": environment.get_template("cards/weekly_report.html.j2").render(
            **base,
            width=1200,
            height=820,
            footer_image="data:image/png;base64,AA==",
            week_label="本周周报",
            period="2026-01-01 ~ 2026-01-07",
            categories=[
                {
                    "name": "资源",
                    "items": [
                        {
                            "icon": "data:image/png;base64,AA==",
                            "name": "一个不应被截断的周报资源完整名称",
                            "quality": "data:image/png;base64,AA==",
                            "total": "12",
                        }
                    ],
                },
                {"name": "空分类", "items": []},
            ],
        ),
    }

    for html in rendered.values():
        assert "width:" in html
        assert "<script>" not in html

    for template_name in (
        "cards/stamina.html.j2",
        "cards/sign_calendar.html.j2",
        "cards/role_info.html.j2",
        "cards/weekly_report.html.j2",
    ):
        assert "旅行者 &lt;script&gt;" in rendered[template_name]

    assert "很长很长的密函名称" in rendered["cards/mh_simple.html.j2"]
    assert "<活动>" not in rendered["cards/calendar.html.j2"]
    assert "&lt;活动&gt;" in rendered["cards/calendar.html.j2"]
    assert "本周暂无相关资源获取" in rendered["cards/weekly_report.html.j2"]
    assert "一个不应被截断的周报资源完整名称" in rendered["cards/weekly_report.html.j2"]
    assert "height: 820px" in rendered["cards/weekly_report.html.j2"]
    assert "left: 200px" in rendered["cards/weekly_report.html.j2"]
    assert "暂无已解锁条目" in rendered["cards/role_info.html.j2"]


def test_stamina_template_keeps_all_drafts_and_legacy_upward_positions(
    environment: Environment,
) -> None:
    drafts = [
        {"done": index % 2 == 0, "name": f"锻造-{index}", "state": "已完成"}
        for index in range(12)
    ]

    html = environment.get_template("cards/stamina.html.j2").render(
        background="data:image/png;base64,AA==",
        bar_background="data:image/png;base64,AA==",
        divider="data:image/png;base64,AA==",
        draft_background="data:image/png;base64,AA==",
        drafts=drafts,
        font="data:font/woff2;base64,AA==",
        foreground="data:image/png;base64,AA==",
        header={"avatar": "data:image/png;base64,AA==", "level": None, "name": "玩家", "stats": [], "uid": None},
        header_background="data:image/png;base64,AA==",
        height=1100,
        notes=[],
        running="data:image/png;base64,AA==",
        success="data:image/png;base64,AA==",
        width=2000,
    )

    assert html.count('<article class="stamina-card__draft') == 12
    assert "锻造-0" in html and "锻造-11" in html
    assert "top:880px" in html
    assert "top:-220px" in html
