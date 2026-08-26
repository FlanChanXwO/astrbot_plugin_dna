import asyncio
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astrbot.api.star import StarTools

from src.bootstrap import build_runtime
from src.entry.commands import (
    CommandRequest,
    execute_use_case,
    load_command_registry,
)
from src.entry.event import EventActor
from src.entry.response import ChainResponse, ImageResponse, PlainTextResponse
from src.infrastructure.persistence.database import AsyncDatabase


class MockContext:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def send_message(self, *args: object, **kwargs: object) -> None:
        self.sent_messages.append((args, kwargs))


def _save_reports(output_dir: Path, report_data: dict[str, object], markdown_text: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = output_dir / "live_test_report.json"
    report_md_path = output_dir / "live_test_report.md"

    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    return report_json_path, report_md_path


async def run() -> None:
    print("========================================")
    print("Initializing Plugin Runtime with live DB")
    print("========================================")

    prod_data_dir = Path("/AstrBot/data/plugin_data/astrbot_plugin_dnaby")
    if (prod_data_dir / "dnaby.sqlite3").exists():
        data_dir = prod_data_dir
    else:
        data_dir = Path(StarTools.get_data_dir("astrbot_plugin_dnaby"))

    db = AsyncDatabase.from_data_dir(data_dir)
    await db.create_schema_for_tests()
    print(f"Database: {db.path}")

    registry = load_command_registry()
    ctx = MockContext()
    runtime = build_runtime(ctx, None, command_registry=registry, database=db)
    services = runtime.services

    # Test user: 308597424 (QQ) with active UID 1002631141868 (江上月)
    user_id = "308597424"
    bot_id = "onebot"
    group_id = "1007417650"

    actor = EventActor(
        user_id=user_id,
        bot_id=bot_id,
        group_id=group_id,
        unified_msg_origin=f"onebot:{group_id}:{user_id}",
    )

    test_commands = [
        # 0. 帮助
        ("kk帮助", "kk帮助", "帮助菜单卡片渲染"),

        # 1. 账号与隐私控制
        ("kk查看UID", "kk查看UID", "查看绑定UID"),
        ("kk获取ck", "kk获取ck", "查看凭据状态"),
        ("kk开偷窥", "kk开偷窥", "开启个人偷窥"),
        ("kk防偷窥", "kk防偷窥", "关闭个人偷窥"),
        ("kk隐藏UID", "kk隐藏UID", "开启隐藏UID"),
        ("kk显示UID", "kk显示UID", "关闭隐藏UID"),
        ("kk切换1002631141868", "kk切换1002631141868", "切换当前激活UID"),
        ("kk指定隐藏UID", "kk指定隐藏UID", "管理员指定隐藏UID"),
        ("kk指定显示UID", "kk指定显示UID", "管理员指定显示UID"),
        ("kk全体隐藏UID", "kk全体隐藏UID", "管理员全体隐藏UID"),
        ("kk全体显示UID", "kk全体显示UID", "管理员全体显示UID"),
        ("kk取消全体UID隐藏", "kk取消全体UID隐藏", "管理员取消全体UID隐藏"),
        ("kk全体开偷窥", "kk全体开偷窥", "管理员全体开偷窥"),
        ("kk全体防偷窥", "kk全体防偷窥", "管理员全体防偷窥"),
        ("kk取消全体偷窥", "kk取消全体偷窥", "管理员取消全体偷窥"),

        # 2. 玩家卡片与详情
        ("kk卡片", "kk卡片", "玩家总览卡片T2I渲染"),
        ("kk菲娜详情", "kk菲娜详情", "角色属性与武器详情卡T2I渲染"),
        ("kk菲娜详情+暗月+暗月", "kk菲娜详情+暗月+暗月", "角色与自定义武器面板详情"),
        ("kk原图", "kk原图", "角色原图查询（提示暂不支持）"),

        # 3. 百科、周报与便签模块
        ("kk便签", "kk便签", "实时便签与体力卡片T2I渲染"),
        ("kk周报", "kk周报", "本周周报数据统计T2I渲染"),
        ("kk本周周报", "kk本周周报", "本周周报别名触发"),
        ("kk上周周报", "kk上周周报", "上周周报历史数据统计T2I渲染"),
        ("kk日历", "kk日历", "活动与卡池日历卡片T2I渲染"),
        ("kk兑换码", "kk兑换码", "可用兑换码查询"),
        ("kk菲娜别名", "kk菲娜别名", "角色别名查询"),
        ("kk角色列表", "kk角色列表", "全角色清单查询"),
        ("kk武器列表", "kk武器列表", "全武器清单查询"),
        ("kk菲娜图鉴", "kk菲娜图鉴", "角色图鉴查询"),
        ("kk菲娜攻略", "kk菲娜攻略", "角色攻略查询"),

        # 4. 签到模块
        ("kk签到", "kk签到", "手动执行签到任务"),
        ("kk签到日历", "kk签到日历", "当月签到记录日历T2I渲染"),
        ("kk全部签到", "kk全部签到", "执行全部用户签到"),
        ("kk订阅签到结果", "kk订阅签到结果", "订阅签到广播"),
        ("kk取消订阅签到结果", "kk取消订阅签到结果", "取消订阅签到广播"),

        # 5. 密函与公告模块
        ("kk密函", "kk密函", "密函卡片T2I渲染"),
        ("kk密函列表", "kk密函列表", "可订阅密函类型列表"),
        ("kk订阅扼守密函", "kk订阅扼守密函", "订阅指定密函并@用户"),
        ("kk我的密函", "kk我的密函", "查看当前订阅密函状态"),
        ("kk订阅密函时间17:23", "kk订阅密函时间17:23", "设置密函推送时间范围"),
        ("kk订阅密函图片", "kk订阅密函图片", "开启密函图片推送"),
        ("kk取消订阅密函图片", "kk取消订阅密函图片", "关闭密函图片推送"),
        ("kk订阅密函文本", "kk订阅密函文本", "开启密函文本推送"),
        ("kk取消订阅密函文本", "kk取消订阅密函文本", "关闭密函文本推送"),
        ("kk密函测试", "kk密函测试", "密函推送测试"),
        ("kk取消订阅扼守密函", "kk取消订阅扼守密函", "取消订阅指定密函"),
        ("kk公告", "kk公告", "最新公告列表T2I渲染"),
        ("kk公告 1", "kk公告 1", "指定序号公告详情查询"),
        ("kk订阅公告", "kk订阅公告", "群聊订阅游戏公告"),
        ("kk取消订阅公告", "kk取消订阅公告", "群聊退订游戏公告"),

        # 6. 运维与别名管理
        ("kk资源状态", "kk资源状态", "公共资源目录健康检查"),
        ("kk更新记录", "kk更新记录", "Git更新日志查询"),
        ("kk恢复别名", "kk恢复别名", "恢复内置角色别名映射"),
        ("kk添加角色辛西娅别名小辛", "kk添加角色辛西娅别名小辛", "添加自定义角色别名"),
        ("kk删除角色辛西娅别名小辛", "kk删除角色辛西娅别名小辛", "删除自定义角色别名"),
        ("kk菲娜面板图列表", "kk菲娜面板图列表", "查询自定义面板图"),
        ("kk压缩面板图", "kk压缩面板图", "压缩自定义面板图"),
    ]

    results: list[dict[str, object]] = []
    output_dir = Path(__file__).resolve().parents[1] / "scripts" / "output"

    for test_id, msg_text, desc in test_commands:
        print(f"\n>>> Testing command: {test_id} ({msg_text}) [{desc}]")
        matched_spec = None
        matched_params = {}
        for spec in registry:
            m = re.match(spec.pattern, msg_text)
            if m is not None:
                matched_spec = spec
                matched_params = m.groupdict()
                break

        if not matched_spec:
            print(f"❌ No matching command spec for: {msg_text}")
            results.append({
                "test_id": test_id,
                "command": msg_text,
                "description": desc,
                "status": "NO_SPEC_MATCH",
            })
            continue

        req = CommandRequest(
            command_id=matched_spec.id,
            text=msg_text,
            parameters=matched_params,
            actor=actor,
            target_user_id=None,
            reply_id=None,
            services=services,
            images=(),
        )

        try:
            responses = []
            async for resp in execute_use_case(matched_spec, req, registry):
                responses.append(resp)

            print(f"   Count of responses: {len(responses)}")
            resp_summary = []
            for i, r in enumerate(responses):
                if isinstance(r, PlainTextResponse):
                    text_sample = r.text.replace("\n", " \n ")
                    print(f"   [{i}] PlainText(need_at={r.need_at}): {text_sample[:150]}")
                    resp_summary.append({
                        "type": "PlainText",
                        "need_at": r.need_at,
                        "text": r.text,
                    })
                elif isinstance(r, ImageResponse):
                    img_path = r.image
                    img_info: dict[str, object] = {"type": "Image"}
                    if isinstance(img_path, (str, Path)) and os.path.exists(str(img_path)):
                        size_bytes = os.path.getsize(str(img_path))
                        try:
                            with Image.open(str(img_path)) as im:
                                w, h = im.size
                                fmt = im.format
                                print(f"   [{i}] Image: path={img_path}, size={size_bytes:,}B, res={w}x{h}, fmt={fmt}")
                                img_info.update({
                                    "path": str(img_path),
                                    "size_bytes": size_bytes,
                                    "resolution": f"{w}x{h}",
                                    "format": fmt,
                                })
                        except (OSError, ValueError) as e:
                            print(f"   [{i}] Image: path={img_path}, size={size_bytes:,}B, error: {e}")
                            img_info.update({"path": str(img_path), "size_bytes": size_bytes, "error": str(e)})
                    elif isinstance(img_path, bytes):
                        print(f"   [{i}] Image: raw_bytes, size={len(img_path):,}B")
                        img_info.update({"size_bytes": len(img_path), "raw": True})
                    else:
                        print(f"   [{i}] Image: path={img_path} (NOT FOUND ON DISK)")
                        img_info.update({"path": str(img_path), "missing": True})
                    resp_summary.append(img_info)
                elif isinstance(r, ChainResponse):
                    print(f"   [{i}] ChainResponse: {r.components}")
                    resp_summary.append({
                        "type": "ChainResponse",
                        "components": str(r.components),
                    })
                else:
                    print(f"   [{i}] Other response: {type(r).__name__} -> {r}")
                    resp_summary.append({
                        "type": type(r).__name__,
                        "value": str(r),
                    })
            results.append({
                "test_id": test_id,
                "command": msg_text,
                "description": desc,
                "status": "OK",
                "responses": resp_summary,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"❌ Error executing {test_id}: {exc}")
            traceback.print_exc()
            results.append({
                "test_id": test_id,
                "command": msg_text,
                "description": desc,
                "status": "ERROR",
                "error": str(exc),
            })

    # Output report files
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    md_lines = [
        "# 二重螺旋插件 (dnaby) 全量指令测试报告\n\n",
        f"- **测试时间**: {timestamp}\n",
        f"- **测试账号**: QQ `{user_id}` (UID: `1002631141868` / 角色: 江上月)\n",
        f"- **测试命令总数**: {len(results)}\n\n",
        "| 序号 | 测试指令 | 功能描述 | 执行状态 | 输出摘要 |\n",
        "| :--- | :--- | :--- | :--- | :--- |\n",
    ]

    for i, item in enumerate(results, 1):
        status = item["status"]
        status_badge = "✅ OK" if status == "OK" else f"❌ {status}"
        responses = item.get("responses", [])
        summary_parts = []
        if isinstance(responses, list):
            for r in responses:
                if isinstance(r, dict):
                    t = r.get("type")
                    if t == "PlainText":
                        summary_parts.append(f"文本: `{str(r.get('text', '')).replace(chr(10), ' ')[:60]}`")
                    elif t == "Image":
                        res = r.get("resolution", "N/A")
                        sz = r.get("size_bytes", 0)
                        summary_parts.append(f"图片: `{res}` ({sz:,}B)")
                    else:
                        summary_parts.append(f"{t}")
        summary_str = "<br>".join(summary_parts) if summary_parts else (str(item.get("error", "无返回"))[:60])
        md_lines.append(f"| {i} | `{item['command']}` | {item['description']} | {status_badge} | {summary_str} |\n")

    report_json_path, report_md_path = _save_reports(
        output_dir,
        {
            "generated_at": timestamp,
            "user_id": user_id,
            "total_tested": len(results),
            "results": results,
        },
        "".join(md_lines),
    )

    print("\n========================================")
    print("SUMMARY OF ALL TESTED COMMANDS")
    print("========================================")
    for item in results:
        print(f"{item['command']!s:<30} : {item['status']}")
    print(f"\nSaved test reports to:\n - {report_json_path}\n - {report_md_path}")


if __name__ == "__main__":
    asyncio.run(run())
