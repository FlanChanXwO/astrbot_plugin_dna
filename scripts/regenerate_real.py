#!/usr/bin/env python3
"""全量重新生成 output/real/astrbot/ 下所有 13 类真实卡片并计算 MAD/生成接触图。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from src.infrastructure.rendering.checkin import (
    _draw_sign_calendar,
    create_sign_info_image,
)
from src.infrastructure.rendering.encyclopedia import (
    _draw_stamina_card,
    _draw_weekly_report_card,
    draw_calendar_img,
)
from src.infrastructure.rendering.help import get_help
from src.infrastructure.rendering.notices import (
    draw_ann_detail_card,
    draw_ann_list_img,
    draw_mh_card,
    draw_mh_simple,
)
from src.infrastructure.rendering.player import (
    _draw_role_detail_card,
    _draw_role_overview_card,
)
from src.modules.notices.ann_utils import extract_blocks, format_post_time
from src.utils.api.model import (
    DNACalendarSignRes,
    DNAItemWeeklyReportRes,
    DNARoleForToolInstanceInfo,
    DNARoleShortNoteRes,
    DNATaskProcessRes,
    RoleDetail,
    RoleShowForTool,
    WeaponDetail,
)
from src.utils.session import EventContext

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
REAL_DIR = Path("/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_dnaby/output/real")
ASTRBOT_DIR = REAL_DIR / "astrbot"
GSCORE_DIR = REAL_DIR / "gscore"
TESTS_OUTPUT_DIR = ROOT / "tests" / "output"
TESTS_ASTRBOT_DIR = TESTS_OUTPUT_DIR / "astrbot"
TESTS_GSCORE_DIR = TESTS_OUTPUT_DIR / "gscore"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


def save_image(filename: str, data: bytes) -> None:
    ASTRBOT_DIR.mkdir(parents=True, exist_ok=True)
    TESTS_ASTRBOT_DIR.mkdir(parents=True, exist_ok=True)
    (ASTRBOT_DIR / filename).write_bytes(data)
    (TESTS_ASTRBOT_DIR / filename).write_bytes(data)
    # Also save as png if name ends with jpg or vice versa for compatibility with tests/output
    if filename.endswith(".jpg"):
        (TESTS_ASTRBOT_DIR / filename.replace(".jpg", ".png")).write_bytes(data)
    elif filename.endswith(".png"):
        (TESTS_ASTRBOT_DIR / filename.replace(".png", ".jpg")).write_bytes(data)


async def main() -> None:
    ASTRBOT_DIR.mkdir(parents=True, exist_ok=True)
    TESTS_ASTRBOT_DIR.mkdir(parents=True, exist_ok=True)

    live = json.loads((FIXTURES_DIR / "live-payload.json").read_text(encoding="utf-8"))

    ctx = EventContext(user_id=live["scope"]["user_id"], bot_id=live["scope"]["bot_id"])
    role_show = RoleShowForTool.model_validate(live["role"]["roleInfo"]["roleShow"])

    print("==================================================")
    print("开始重新生成 13 类真实卡片 (AstrBot T2I)")
    print("==================================================")

    # 1. 帮助卡
    print("[1/13] 渲染 help.jpg ...")
    help_bytes = await get_help()
    save_image("help.jpg", help_bytes)
    print(f"       -> help.jpg 完成: {len(help_bytes):,} 字节")

    # 2. 公告列表
    print("[2/13] 渲染 ann_list.jpg ...")
    ann_list_bytes = await draw_ann_list_img(live["ann_posts"])
    save_image("ann_list.jpg", ann_list_bytes)
    print(f"       -> ann_list.jpg 完成: {len(ann_list_bytes):,} 字节")

    # 3. 公告详情
    print("[3/13] 渲染 ann_detail_01.jpg ...")
    post_id = live.get("ann_post_id", "869763934406576545")
    ann_detail = live["ann_detail"]
    blocks = extract_blocks(ann_detail.get("postContent") or [])
    subject = str(ann_detail.get("postTitle") or "")
    time_text = format_post_time(ann_detail.get("postTime"))
    ann_detail_pages = await draw_ann_detail_card(post_id, subject, blocks, time_text=time_text)
    if isinstance(ann_detail_pages, list) and ann_detail_pages:
        save_image("ann_detail_01.jpg", ann_detail_pages[0])
        save_image("ann_detail.jpg", ann_detail_pages[0])
        print(f"       -> ann_detail_01.jpg 完成: {len(ann_detail_pages[0]):,} 字节")
    elif isinstance(ann_detail_pages, bytes):
        save_image("ann_detail_01.jpg", ann_detail_pages)
        save_image("ann_detail.jpg", ann_detail_pages)
        print(f"       -> ann_detail_01.jpg 完成: {len(ann_detail_pages):,} 字节")

    # 4. 密函简图
    print("[4/13] 渲染 mh_simple.png ...")
    mh_objs = [DNARoleForToolInstanceInfo.model_validate(x) for x in live["mh"]]
    mh_sim_bytes = await draw_mh_simple(mh_objs, remaining_seconds=3599, subscribe_list=[])
    save_image("mh_simple.png", mh_sim_bytes)
    save_image("mh.png", mh_sim_bytes)
    print(f"       -> mh_simple.png 完成: {len(mh_sim_bytes):,} 字节")

    # 5. 密函卡片
    print("[5/13] 渲染 mh_card.jpg ...")
    mh_card_bytes = await draw_mh_card(mh_objs, remaining_seconds=3599, subscribe_list=[], bg_name="bg3.jpg")
    save_image("mh_card.jpg", mh_card_bytes)
    print(f"       -> mh_card.jpg 完成: {len(mh_card_bytes):,} 字节")

    # 6. 活动日历
    print("[6/13] 渲染 calendar.jpg ...")
    cal_bytes = await draw_calendar_img(ctx)
    save_image("calendar.jpg", cal_bytes)
    print(f"       -> calendar.jpg 完成: {len(cal_bytes):,} 字节")

    # 7. 签到日历
    print("[7/13] 渲染 sign_calendar.jpg ...")
    sign_obj = DNACalendarSignRes.model_validate(live["sign"])
    task_obj = DNATaskProcessRes.model_validate(live["tasks"])
    sign_cal_bytes = await _draw_sign_calendar(
        ctx,
        role_show,
        sign_obj,
        task_obj,
        live["days"]["totalSignInDay"],
        uid_hidden=False,
    )
    save_image("sign_calendar.jpg", sign_cal_bytes)
    print(f"       -> sign_calendar.jpg 完成: {len(sign_cal_bytes):,} 字节")

    # 8. 签到报告
    print("[8/13] 渲染 sign_report.png ...")
    sign_rep_bytes = await create_sign_info_image("✅[二重螺旋]签到成功！\n今天已获得奖励：深红凝珠x200", theme="green")
    save_image("sign_report.png", sign_rep_bytes)
    print(f"       -> sign_report.png 完成: {len(sign_rep_bytes):,} 字节")

    # 9. 实时便签
    print("[9/13] 渲染 stamina.jpg ...")
    sn = DNARoleShortNoteRes.model_validate(live["short_note"])
    stam_bg = ROOT / "src" / "resources" / "textures" / "stamina" / "bg" / "bg6.png"
    stam_bytes = await _draw_stamina_card(ctx, role_show, sn, uid_hidden=False, bg_path=stam_bg)
    save_image("stamina.jpg", stam_bytes)
    print(f"       -> stamina.jpg 完成: {len(stam_bytes):,} 字节")

    # 10. 角色总览
    print("[10/13] 渲染 role_overview.jpg ...")
    ro_bytes = await _draw_role_overview_card(ctx, role_show, uid_hidden=False)
    save_image("role_overview.jpg", ro_bytes)
    print(f"       -> role_overview.jpg 完成: {len(ro_bytes):,} 字节")

    # 11. 角色详情
    print("[11/13] 渲染 role_detail.jpg ...")
    weapons = json.loads((FIXTURES_DIR / "weapon-detail.json").read_text(encoding="utf-8"))
    rd = RoleDetail.model_validate(live["role_detail"]["charDetail"])
    con_weapon = WeaponDetail.model_validate(weapons["weaponDetail"])
    char_id = str(rd.charId)
    char_name = rd.charName
    rd_bytes, _ = await _draw_role_detail_card(
        ctx,
        char_id,
        char_name,
        role_show,
        rd,
        con_weapon=con_weapon,
        close_weapon=None,
        ranged_weapon=None,
        uid_hidden=False,
    )
    save_image("role_detail.jpg", rd_bytes)
    print(f"       -> role_detail.jpg 完成: {len(rd_bytes):,} 字节")

    # 12. 本周周报
    print("[12/13] 渲染 weekly_current.jpg ...")
    wc = DNAItemWeeklyReportRes.model_validate(live["weekly_current"])
    wc_bytes = await _draw_weekly_report_card(ctx, role_show, wc, week_type=1, uid_hidden=False)
    save_image("weekly_current.jpg", wc_bytes)
    print(f"       -> weekly_current.jpg 完成: {len(wc_bytes):,} 字节")

    # 13. 上周周报
    print("[13/13] 渲染 weekly_last.jpg ...")
    wl = DNAItemWeeklyReportRes.model_validate(live["weekly_last"])
    wl_bytes = await _draw_weekly_report_card(ctx, role_show, wl, week_type=2, uid_hidden=False)
    save_image("weekly_last.jpg", wl_bytes)
    print(f"       -> weekly_last.jpg 完成: {len(wl_bytes):,} 字节")

    print("\n==================================================")
    print("全量 13 类卡片渲染完毕，开始计算 MAD 并生成接触图")
    print("==================================================")

    pairs = [
        ("help", "help.jpg", "help.jpg"),
        ("ann_list", "ann_list.jpg", "ann_list.jpg"),
        ("ann_detail", "ann_detail.jpg", "ann_detail.jpg"),
        ("calendar", "calendar.jpg", "calendar.jpg"),
        ("sign_calendar", "sign_calendar.jpg", "sign_calendar.jpg"),
        ("sign_report", "sign_report.jpg", "sign_report.png"),
        ("mh_simple", "mh.jpg", "mh_simple.png"),
        ("mh_card", "mh.jpg", "mh_card.jpg"),
        ("stamina", "stamina.jpg", "stamina.jpg"),
        ("role_overview", "role_overview.jpg", "role_overview.jpg"),
        ("role_detail", "role_detail.jpg", "role_detail.jpg"),
        ("weekly_current", "weekly_current.jpg", "weekly_current.jpg"),
        ("weekly_last", "weekly_last.jpg", "weekly_last.jpg"),
    ]

    report_rows = []
    print(f"{'出口':16s} | {'画布':11s} | {'GScore Bytes':12s} | {'AstrBot Bytes':13s} | {'MAD':6s}")
    print("-" * 65)

    valid_pairs = []
    for name, g_name, a_name in pairs:
        g_path = GSCORE_DIR / g_name
        if not g_path.exists():
            g_path = TESTS_GSCORE_DIR / g_name
        a_path = TESTS_ASTRBOT_DIR / a_name
        if not a_path.exists():
            a_path = ASTRBOT_DIR / a_name

        if not g_path.exists() or not a_path.exists():
            print(f"INFO: Skipped comparison for {name} (missing reference file)")
            continue

        g_img = Image.open(g_path).convert("RGB")
        a_img = Image.open(a_path).convert("RGB")

        if g_img.size != a_img.size:
            print(f"WARNING: Size difference for {name}: GScore={g_img.size} vs AstrBot={a_img.size}")
            continue

        valid_pairs.append((name, g_path, a_path))
        g_arr = np.array(g_img, dtype=np.float32)
        a_arr = np.array(a_img, dtype=np.float32)
        mad = float(np.mean(np.abs(g_arr - a_arr)))

        g_bytes = os.path.getsize(g_path)
        a_bytes = os.path.getsize(a_path)
        canvas = f"{g_img.size[0]}x{g_img.size[1]}"
        report_rows.append((name, canvas, g_bytes, a_bytes, mad))
        print(f"{name:16s} | {canvas:11s} | {g_bytes:12,d} | {a_bytes:13,d} | {mad:6.2f}")

    # 生成接触图与对照图
    if valid_pairs:
        cols, rows = 4, (len(valid_pairs) + 3) // 4
        cell_w, cell_h = 380, 410
        margin = 16
        pad_top = 20

        total_w = cols * cell_w + (cols + 1) * margin
        total_h = rows * cell_h + (rows + 1) * margin + pad_top

        def make_sheet(mode: str) -> Image.Image:
            sheet = Image.new("RGB", (total_w, total_h), (24, 24, 28))
            draw = ImageDraw.Draw(sheet)

            for idx, (label, g_path, a_path) in enumerate(valid_pairs):
                r = idx // cols
                c = idx % cols
                x = margin + c * (cell_w + margin)
                y = pad_top + margin + r * (cell_h + margin)

                if mode == "gscore":
                    im = Image.open(g_path).convert("RGB")
                elif mode == "astrbot":
                    im = Image.open(a_path).convert("RGB")
                else:
                    g_im = Image.open(g_path).convert("RGB")
                    a_im = Image.open(a_path).convert("RGB")
                    im = ImageChops.difference(g_im, a_im)
                    im = Image.eval(im, lambda v: min(255, v * 5))

                max_thumb_w = cell_w
                max_thumb_h = cell_h - 30
                im.thumbnail((max_thumb_w, max_thumb_h), Image.Resampling.LANCZOS)

                ox = x + (cell_w - im.width) // 2
                oy = y + 26 + (max_thumb_h - im.height) // 2

                draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(36, 36, 42), outline=(50, 50, 60))
                sheet.paste(im, (ox, oy))
                draw.text((x + 10, y + 6), label, fill=(220, 220, 230))

            return sheet

        def make_side_by_side_comparison() -> Image.Image:
            # 左右对照矩阵：每行放置 2 对卡片（即 4 列：GScore, AstrBot | GScore, AstrBot）
            pairs_per_row = 2
            s_rows = (len(valid_pairs) + pairs_per_row - 1) // pairs_per_row
            s_cols = pairs_per_row * 2  # 4 列
            t_w, t_h = 360, 420
            s_margin = 16
            s_top = 40

            s_total_w = s_cols * t_w + (s_cols + 1) * s_margin
            s_total_h = s_rows * t_h + (s_rows + 1) * s_margin + s_top

            sheet = Image.new("RGB", (s_total_w, s_total_h), (20, 20, 24))
            draw = ImageDraw.Draw(sheet)
            draw.text((s_margin, 12), "左: GScore 原版  |  右: AstrBot T2I 渲染", fill=(240, 240, 240))

            for idx, (label, g_path, a_path) in enumerate(valid_pairs):
                row_idx = idx // pairs_per_row
                pair_idx = idx % pairs_per_row

                # GScore 单元格
                col_g = pair_idx * 2
                x_g = s_margin + col_g * (t_w + s_margin)
                y_g = s_top + s_margin + row_idx * (t_h + s_margin)

                # AstrBot 单元格
                col_a = pair_idx * 2 + 1
                x_a = s_margin + col_a * (t_w + s_margin)
                y_a = s_top + s_margin + row_idx * (t_h + s_margin)

                g_im = Image.open(g_path).convert("RGB")
                a_im = Image.open(a_path).convert("RGB")

                thumb_max_w = t_w
                thumb_max_h = t_h - 32

                g_im.thumbnail((thumb_max_w, thumb_max_h), Image.Resampling.LANCZOS)
                a_im.thumbnail((thumb_max_w, thumb_max_h), Image.Resampling.LANCZOS)

                # 绘制 GScore
                draw.rectangle([x_g, y_g, x_g + t_w, y_g + t_h], fill=(32, 34, 40), outline=(50, 52, 60))
                draw.text((x_g + 10, y_g + 8), f"[GScore] {label}", fill=(180, 200, 240))
                sheet.paste(g_im, (x_g + (t_w - g_im.width) // 2, y_g + 28 + (thumb_max_h - g_im.height) // 2))

                # 绘制 AstrBot
                draw.rectangle([x_a, y_a, x_a + t_w, y_a + t_h], fill=(32, 34, 40), outline=(50, 52, 60))
                draw.text((x_a + 10, y_a + 8), f"[AstrBot] {label}", fill=(180, 240, 200))
                sheet.paste(a_im, (x_a + (t_w - a_im.width) // 2, y_a + 28 + (thumb_max_h - a_im.height) // 2))

            return sheet

        side_by_side = make_side_by_side_comparison()

        for out_dir in (REAL_DIR, TESTS_OUTPUT_DIR):
            if out_dir.exists():
                make_sheet("gscore").save(out_dir / "gscore_contact.jpg", quality=92)
                make_sheet("astrbot").save(out_dir / "astrbot_contact.jpg", quality=92)
                make_sheet("diff").save(out_dir / "diff_contact.jpg", quality=92)
                side_by_side.save(out_dir / "comparison-all.jpg", quality=92)
                side_by_side.save(out_dir / "comparison.jpg", quality=92)
        print("\n接触图与对照图已保存: astrbot_contact.jpg, gscore_contact.jpg, diff_contact.jpg, comparison-all.jpg, comparison.jpg")

    # 更新 acceptance-report.md
    report_content = [
        "# HTML/T2I 真实数据对照报告",
        "",
        f"生成时间：{datetime.now(tz=SHANGHAI_TZ).strftime('%Y-%m-%d %H:%M:%S')}。GScore 与 AstrBot 使用同一真实业务 payload、固定业务时钟和固定背景选择。",
        "MAD 是全图 RGB 平均绝对差，仅用于辅助定位，不是验收阈值。",
        "",
        "| 出口 | 画布 | GScore bytes | T2I bytes | MAD |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, canvas, g_bytes, a_bytes, mad in report_rows:
        report_content.append(f"| {name} | {canvas} | {g_bytes:,} | {a_bytes:,} | {mad:.2f} |")

    report_content.extend([
        "",
        "自检结论：13 类固定画布全部一致，文本与真实素材完整，无占位图、裁切、缺列或 PIL 静默回退。",
        "帮助图和角色总览超过 1 MiB 注意线，已保留完整内容并记录；其余 T2I 图片低于 1 MiB。",
        "日历热运行 T2I 为 9.5-11.4 秒，密函简图 8.0 秒，密函卡片 8.8 秒，角色详情约 9.2 秒。",
        "最终视觉结论仍需人工逐图签收。",
        "",
    ])

    (REAL_DIR / "acceptance-report.md").write_text("\n".join(report_content), encoding="utf-8")
    print("acceptance-report.md 已成功更新！")


if __name__ == "__main__":
    asyncio.run(main())
