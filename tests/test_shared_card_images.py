"""重复装饰资源只内联一次，空列表与不同底图保持可用。"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape


def card_payload(template: str, source: str, *, empty: bool = False) -> dict:
    item = {
        "name": "测试条目",
        "icon": "",
        "image": "",
        "element": None,
        "grade": None,
        "level": 80,
        "unlocked": True,
        "type": "weapon",
        "quality": source,
        "total": "1",
        "example": "d帮助",
    }
    items = [] if empty else [item, dict(item)]
    modes = (
        []
        if empty
        else [
            {
                "background": source,
                "icon": "",
                "name": f"魔之楔{i}",
                "level": i,
                "side": "left" if i < 4 else "right",
                "position": "left",
            }
            for i in range(8)
        ]
    )
    attributes = (
        []
        if empty
        else [
            {"background": source, "icon": "", "label": f"属性{i}", "value": "10"}
            for i in range(6)
        ]
    )
    weapon = {
        "modes": modes,
        "attributes": attributes,
        "title": "武器详情",
        "name": "武器",
        "level": 80,
        "skill_level": 2,
        "icon": "",
        "weapon_background": source,
        "attribute_background": source,
    }
    sections = (
        []
        if empty
        else [
            {
                "title": title,
                "name": title,
                "background": "",
                "items": items,
                "height": 294,
                "description": "说明",
            }
            for title in ("甲", "乙")
        ]
    )
    grades = (
        []
        if empty
        else [
            {
                "background": source,
                "icon": "",
                "left": i * 64,
                "index": i,
                "unlocked": i < 3,
            }
            for i in range(5)
        ]
    )
    data = {
        "width": 1200,
        "height": 2000,
        "card_height": 2000,
        "header": {"name": "测试玩家", "uid": None, "level": None, "stats": []},
        "achievements": [],
        "sections": sections,
        "categories": sections,
        "hero": {"image": ""},
        "role": {"name": "角色", "level": 80},
        "weapon": weapon,
        "attributes": attributes,
        "grades": grades,
        "skills": [] if empty else [item] * 3,
        "role_modes": modes,
        "weapon_sections": [] if empty else [weapon, weapon],
        "refinement_grades": grades,
        "lines": [],
        "cards": []
        if empty
        else [{"type_name": "密函", "icon": "", "instances": []}] * 3,
    }
    data.update(
        {
            "role_info": {"item_foreground": source},
            "weekly_report": {},
            "role_detail": {"skill_background": source},
            "weapon_detail": {},
            "help": {"cag_background": source},
            "mh_card": {"card_background": source},
        }[template]
    )
    return data


@pytest.mark.parametrize(
    "template",
    ["role_info", "weekly_report", "role_detail", "weapon_detail", "help", "mh_card"],
)
@pytest.mark.parametrize("empty", [False, True])
def test_cards_inline_repeated_decorations_once(template: str, empty: bool) -> None:
    source = "data:image/png;base64," + base64.b64encode(b"x" * 76139).decode("ascii")
    environment = Environment(
        loader=FileSystemLoader(str(Path(__file__).parents[1] / "src/templates")),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    html = environment.get_template(f"cards/{template}.html.j2").render(
        **card_payload(template, source, empty=empty)
    )

    assert html.count(source) <= 1
    if not empty:
        assert html.count(source) == 1
        assert "var(--dna-image-" in html
        text, count = {
            "role_info": ("测试条目", 4),
            "weekly_report": ("测试条目", 4),
            "role_detail": ("魔之楔", 24),
            "weapon_detail": ("魔之楔", 8),
            "help": ("测试条目", 4),
            "mh_card": ("密函", 3),
        }[template]
        assert html.count(text) == count
    assert len(html.encode("utf-8")) < 256 * 1024


@pytest.mark.parametrize("template", ["weekly_report", "role_detail", "weapon_detail"])
def test_cards_keep_distinct_backgrounds(template: str) -> None:
    sources = ["data:image/png;base64,AA==", "data:image/png;base64,aa=="]
    payload = card_payload(template, sources[0])
    if template == "weekly_report":
        payload["categories"][0]["items"][1]["quality"] = sources[1]
    elif template == "role_detail":
        payload["grades"][0]["background"] = sources[1]
    else:
        payload["refinement_grades"][0]["background"] = sources[1]
    environment = Environment(
        loader=FileSystemLoader(str(Path(__file__).parents[1] / "src/templates")),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    html = environment.get_template(f"cards/{template}.html.j2").render(**payload)

    for source in sources:
        assert html.count(source) == 1
    assert "var(--dna-image-0)" in html
    assert "var(--dna-image-1)" in html
