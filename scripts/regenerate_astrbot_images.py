"""重新生成 output/astrbot/ 对比图（当前渲染代码 + fixture 数据，可复现）。

- role_overview：legacy 同源渲染（draw_role_info_card_core）
- stamina / weekly_report_*：encyclopedia renderer
素材缓存（legacy RESOURCE_PATH）由预置 fixture 命中，不依赖网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "output" / "astrbot"


def _preseed_legacy_assets() -> None:
    from dnaby.utils.resource import RESOURCE_PATH

    assets = {
        RESOURCE_PATH.AVATAR_PATH / "avatar_101.png": (180, 60, 60),
        RESOURCE_PATH.AVATAR_PATH / "avatar_102.png": (60, 120, 180),
        RESOURCE_PATH.WEAPON_PATH / "weapon_201.png": (160, 140, 40),
        RESOURCE_PATH.WEAPON_PATH / "weapon_202.png": (80, 160, 80),
        RESOURCE_PATH.ATTR_PATH / "attr_fire.png": (200, 90, 40),
        RESOURCE_PATH.ATTR_PATH / "attr_ice.png": (70, 140, 210),
        RESOURCE_PATH.WEAPON_ATTR_PATH / "attr_close.png": (140, 80, 160),
        RESOURCE_PATH.WEAPON_ATTR_PATH / "attr_ranged.png": (60, 170, 130),
    }
    for path, color in assets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            Image.new("RGBA", (64, 64), color).save(path)


def _overview_fixture():
    from src.modules.player.contracts import (
        RoleAchievement,
        RoleItem,
        RoleOverview,
        WeaponItem,
    )

    return RoleOverview(
        role_id="role-1",
        role_name="测试玩家",
        level=42,
        params=[
            RoleAchievement(param_key="总活跃天数", param_value="99"),
            RoleAchievement(param_key="自定义成就", param_value="完整保留"),
        ],
        achievement_total=3,
        role_chars=[
            RoleItem(char_id=101, char_eid="e1", element_icon="element://fire", icon="role://101", level=80, name="角色甲", grade_level=6, unlocked=True),
            RoleItem(char_id=102, char_eid="e2", element_icon="element://ice", icon="role://102", level=0, name="角色乙", grade_level=0, unlocked=False),
        ],
        close_weapons=[
            WeaponItem(element_icon="weapon-element://close", icon="weapon://201", level=70, name="近战甲", unlocked=True, weapon_eid="w1", weapon_id=201, skill_level=3),
        ],
        ranged_weapons=[
            WeaponItem(element_icon="weapon-element://ranged", icon="weapon://202", level=0, name="远程甲", unlocked=False, weapon_eid="w2", weapon_id=202, skill_level=0),
        ],
    )


def _short_note_fixture():
    from src.modules.encyclopedia.contracts import DraftSnapshot, PlayerShortNote

    return PlayerShortNote(
        rouge_like_reward_count=1,
        rouge_like_reward_total=3,
        current_task_progress=2,
        max_daily_task_progress=6,
        hard_boss_reward_count=1,
        hard_boss_reward_total=2,
        dungeon_reward=1,
        dungeon_reward_total=4,
        drafts=(
            DraftSnapshot(product_name="锻造甲", completed=False),
            DraftSnapshot(product_name="锻造乙", completed=True),
        ),
        role_overview=_overview_fixture(),
    )


def _weekly_fixture(week_type: int):
    from src.modules.encyclopedia.contracts import (
        WeeklyReport,
        WeeklyReportCategory,
        WeeklyReportItem,
    )

    return WeeklyReport(
        week_type=week_type,
        start_date="20260803" if week_type == 2 else "20260810",
        end_date="20260809" if week_type == 2 else "20260816",
        categories=(
            WeeklyReportCategory(
                category_name="资源获取",
                items=(
                    WeeklyReportItem(item_id=1, item_name="经验卡", total_num="12"),
                    WeeklyReportItem(item_id=2, item_name="武器经验", total_num="8"),
                ),
            ),
        ),
        role_overview=_overview_fixture(),
    )


def main() -> int:
    import asyncio

    from src.infrastructure.rendering import (
        EncyclopediaRenderer,
        PlayerRenderer,
        ResourceMap,
    )
    from src.infrastructure.resources import EncyclopediaResourceStore

    OUT.mkdir(parents=True, exist_ok=True)
    _preseed_legacy_assets()
    resources = EncyclopediaResourceStore.from_root(ROOT / "output" / "astrbot" / "resources")

    async def render_all() -> None:
        player = PlayerRenderer(OUT, ResourceMap())
        encyclopedia = EncyclopediaRenderer(OUT, resources)

        overview = await player.render_overview_legacy(
            _overview_fixture(),
            uid="1234567890123",
            uid_hidden=False,
            show_unowned=True,
        )
        stamina = encyclopedia.render_stamina(_short_note_fixture())
        current = encyclopedia.render_weekly_report(_weekly_fixture(1))
        last = encyclopedia.render_weekly_report(_weekly_fixture(2))

        targets = (
            (overview.path, "role_overview.png"),
            (stamina.path, "stamina.png"),
            (current.path, "weekly_report_current.png"),
            (last.path, "weekly_report_last.png"),
        )
        for source, name in targets:
            target = OUT / name
            target.write_bytes(source.read_bytes())
            with Image.open(target) as image:
                print(f"{name}: {image.width} x {image.height}")

    asyncio.run(render_all())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
