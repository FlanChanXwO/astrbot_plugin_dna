"""基本信息卡片不能按条目重复内联大型分区背景。"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape


@pytest.mark.parametrize("counts", [(35, 189, 221), (2, 0, 3), (0, 0, 0)])
def test_role_info_shares_backgrounds_without_losing_items(
    counts: tuple[int, int, int],
) -> None:
    templates = Path(__file__).parents[1] / "src" / "templates"
    environment = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "j2", "jinja", "jinja2"),
            default_for_string=True,
        ),
    )
    sections = [
        {
            "title": title,
            "background": "data:image/png;base64,"
            + base64.b64encode(bytes([index]) * 76139).decode("ascii"),
            "items": [
                {
                    "name": f"{title}{item_index % 3}",
                    "type": "role" if index == 0 else "weapon",
                    "level": item_index % 80,
                    "unlocked": item_index % 7 != 0,
                    "image": "",
                    "element": None,
                    "grade": None,
                }
                for item_index in range(count)
            ],
        }
        for index, (title, count) in enumerate(
            zip(("角色信息", "近战武器", "远程武器"), counts, strict=True)
        )
    ]
    html = environment.get_template("cards/role_info.html.j2").render(
        width=1200,
        height=29810,
        header={"name": "测试玩家", "uid": "0", "stats": [], "level": 80},
        achievements=[],
        sections=sections,
    )

    items = [item for section in sections for item in section["items"]]
    assert html.count('<article class="role-info__item') == sum(counts)
    assert re.findall(r'<p class="role-info__name">(.*?)</p>', html) == [
        item["name"] for item in items
    ]
    assert re.findall(r'<p class="role-info__level">(.*?)</p>', html) == [
        f"Lv.{item['level']}" if item["level"] > 0 else "未解锁" for item in items
    ]
    assert html.count('role-info__item locked"') == sum(
        not item["unlocked"] for item in items
    )
    for section in sections:
        assert html.count(section["background"]) == bool(section["items"])
    assert ("暂无已解锁条目" in html) == (sum(counts) == 0)
    assert len(html.encode("utf-8")) < 1024 * 1024
