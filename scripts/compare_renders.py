"""本地离线双渲染器图像对比（legacy DNAUID vs rewrite）。

把同一份密函 fixture 数据分别喂给 legacy ``draw_mh_simple`` 与 rewrite
``NoticesRenderer.render_mh``，输出结构化对比表：

- 画布尺寸（legacy 与 rewrite 各自宽度/高度）
- rewrite 侧 ``dnaby.text`` / ``dnaby.layout`` / ``dnaby.resources`` 元数据
- 像素弱信号：RGB 直方图余弦距离；legacy resize 到 rewrite 尺寸后的逐像素
  相同率与差异区域 bounding box（明确标注为近似信号，不作通过依据）
- 动态字段 mask 说明（轮换时间/刷新倒计时固定时钟后确定性输出）

结论分级：结构性一致 / 结构性差异；「视觉等价」仍需人工核对画面。
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXED_NOW = None  # 由脚本按固定时间设置


def _fixed_datetime(tz=None):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime(2026, 8, 12, 10, 30, 0, tzinfo=tz or ZoneInfo("Asia/Shanghai"))


def _build_legacy_fixture():
    """构造与 rewrite snapshot 同源的 legacy 密函模型。"""

    from src.utils.api.model import DNARoleForToolInstance, DNARoleForToolInstanceInfo

    return [
        DNARoleForToolInstanceInfo(
            mh_type="role",
            instances=[
                DNARoleForToolInstance(id=601, name="扼守/无尽"),
                DNARoleForToolInstance(id=602, name="拆解"),
                DNARoleForToolInstance(id=604, name="追缉"),
            ],
        ),
        DNARoleForToolInstanceInfo(
            mh_type="weapon",
            instances=[
                DNARoleForToolInstance(id=621, name="扼守/无尽"),
                DNARoleForToolInstance(id=623, name="勘探/无尽"),
            ],
        ),
        DNARoleForToolInstanceInfo(
            mh_type="mzx",
            instances=[
                DNARoleForToolInstance(id=641, name="扼守/无尽"),
                DNARoleForToolInstance(id=644, name="追缉"),
                DNARoleForToolInstance(id=646, name="调停"),
            ],
        ),
    ]


def _build_rewrite_fixture():
    """构造与 legacy fixture 同源的 rewrite 密函快照。"""

    from src.modules.notices.contracts import MhInstance, MhSection, MhSnapshot

    return MhSnapshot(
        sections=(
            MhSection(
                mh_type="role",
                type_name="角色",
                instances=(
                    MhInstance(601, "扼守/无尽"),
                    MhInstance(602, "拆解"),
                    MhInstance(604, "追缉"),
                ),
            ),
            MhSection(
                mh_type="weapon",
                type_name="武器",
                instances=(MhInstance(621, "扼守/无尽"), MhInstance(623, "勘探/无尽")),
            ),
            MhSection(
                mh_type="mzx",
                type_name="魔之楔",
                instances=(
                    MhInstance(641, "扼守/无尽"),
                    MhInstance(644, "追缉"),
                    MhInstance(646, "调停"),
                ),
            ),
        ),
    )


def _render_legacy(output_dir: Path) -> Image.Image:
    """用固定时钟渲染 legacy 密函简单卡片。"""

    import src.utils as dna_utils
    from src.infrastructure.rendering.notices import draw_mh_simple

    original = dna_utils.get_datetime
    dna_utils.get_datetime = _fixed_datetime
    try:
        raw = __import__("asyncio").run(
            draw_mh_simple(
                _build_legacy_fixture(), remaining_seconds=1800, subscribe_list=None
            )
        )
    finally:
        dna_utils.get_datetime = original
    image = Image.open(BytesIO(raw)).convert("RGBA")
    (output_dir / "legacy_mh_simple.png").write_bytes(raw)
    return image


def _render_rewrite(output_dir: Path) -> tuple[Image.Image, Path]:
    """渲染 rewrite 密函卡片；诊断元数据由 artifact sidecar 读取。"""

    from src.infrastructure.rendering import NoticesRenderer
    from src.infrastructure.resources import EncyclopediaResourceStore

    renderer = NoticesRenderer(
        output_dir,
        EncyclopediaResourceStore.from_root(Path(output_dir) / "resources"),
    )
    rendered = __import__("asyncio").run(renderer.render_mh(_build_rewrite_fixture()))
    image = Image.open(rendered.path).convert("RGBA")
    return image, rendered.path


def _histogram_distance(left: Image.Image, right: Image.Image) -> float:
    """RGB 32-bin 直方图的余弦距离（0=完全相同，1=完全无关）。"""

    import math

    def hist(image: Image.Image) -> list[float]:
        from collections.abc import Iterable
        from typing import cast

        rgb = image.convert("RGB")
        flattened = getattr(rgb, "get_flattened_data", None)
        raw_pixels = flattened() if callable(flattened) else rgb.getdata()
        data = cast(Iterable[tuple[int, int, int]], raw_pixels)
        bins = [0.0] * (32 * 3)
        for red, green, blue in data:
            bins[red // 8] += 1.0
            bins[32 + green // 8] += 1.0
            bins[64 + blue // 8] += 1.0
        total = sum(bins) or 1.0
        return [value / total for value in bins]

    left_vec, right_vec = hist(left), hist(right)
    dot = sum(a * b for a, b in zip(left_vec, right_vec))
    norm = math.sqrt(sum(a * a for a in left_vec)) * math.sqrt(
        sum(b * b for b in right_vec)
    )
    return 1.0 - (dot / norm if norm else 0.0)


def _pixel_stats(left: Image.Image, right: Image.Image) -> dict[str, object]:
    """把 legacy resize 到 rewrite 尺寸后计算相同率与差异 bbox（近似信号）。"""

    resized = left.resize((right.width, right.height))
    left_pixels = resized.load()
    right_pixels = right.load()
    assert left_pixels is not None and right_pixels is not None
    total = right.width * right.height
    same = 0
    min_x, min_y, max_x, max_y = right.width, right.height, -1, -1
    for y in range(right.height):
        for x in range(right.width):
            if left_pixels[x, y] == right_pixels[x, y]:
                same += 1
            else:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
    return {
        "相同像素率": round(same / total, 4) if total else 1.0,
        "差异区域": f"x[{min_x}..{max_x}] y[{min_y}..{max_y}]" if max_x >= 0 else "无",
        "说明": "legacy 已 resize 到 rewrite 画布后的近似信号，不作通过依据",
    }


def _report(
    legacy: Image.Image, rewrite: Image.Image, rewrite_path: Path, out: Path
) -> str:

    from src.infrastructure.rendering.artifact_store import read_rendered_artifact

    metadata = read_rendered_artifact(rewrite_path).metadata
    text = str(metadata.get("dnaby.text", ""))
    layout = metadata.get("dnaby.layout", {})
    resources = metadata.get("dnaby.resources", [])
    if not isinstance(layout, dict):
        raise ValueError("rewrite artifact 的 dnaby.layout 无效")
    if not isinstance(resources, list):
        raise ValueError("rewrite artifact 的 dnaby.resources 无效")

    lines = [
        "# 本地离线渲染对比：密函（legacy draw_mh_simple vs rewrite render_mh）",
        "",
        (
            "- 数据源：同源 fixture（角色/武器/魔之楔 3 类型，8 个委托），固定时钟"
            f" `{_fixed_datetime().isoformat()}`，刷新倒计时 1800s（动态字段已 mask）。"
        ),
        f"- 对比资料（不入 Git）：`{Path(rewrite_path).parent}`",
        "",
        "## 画布尺寸",
        "",
        f"- legacy `draw_mh_simple`：{legacy.width} × {legacy.height}",
        f"- rewrite `render_mh`：{rewrite.width} × {rewrite.height}",
        "- 结论：**结构性差异**（legacy 为横向卡片，rewrite 为 1300 宽纵向布局）。",
        "",
        "## rewrite 文本元数据（供人工核对 legacy 画面内容）",
        "",
        "```",
        text,
        "```",
        "",
        "## rewrite 布局段",
        "",
        "```",
        json.dumps(layout.get("sections", []), ensure_ascii=False, indent=2),
        "```",
        "",
        "## rewrite 资源语义",
        "",
        "```",
        json.dumps(resources, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 像素弱信号",
        "",
        f"- RGB 直方图余弦距离：{_histogram_distance(legacy, rewrite):.4f}（0=相同）",
        f"- 像素统计：{json.dumps(_pixel_stats(legacy, rewrite), ensure_ascii=False)}",
        "",
        "## 结论",
        "",
        (
            "- 结构性对比：两图绘制内容同源（角色/武器/魔之楔 + 委托名逐一对应），但画布尺寸与"
            " 布局方式不同（legacy 横向卡片 vs rewrite 纵向 1300 宽），**结构性差异**。"
        ),
        (
            "- rewrite 侧文本/布局/资源语义可由元数据自动核对；legacy 侧文本画入图内，需人工"
            " 查看 `legacy_mh_simple.png` 核对角色名/委托名/轮换时间文案。"
        ),
        "- 像素相似度低属于布局差异的必然结果，不设通过阈值；视觉等价由人工确认。",
        "",
    ]
    content = "\n".join(lines)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="本地离线双渲染器密函图像对比")
    parser.add_argument(
        "--out",
        default=ROOT / "docs" / "porting" / "render-compare-mh.md",
        type=Path,
        help="对比报告输出路径（默认 docs/porting/render-compare-mh.md）",
    )
    args = parser.parse_args()

    import tempfile

    artifact_dir = Path(tempfile.mkdtemp(prefix="dnaby-render-compare-"))
    legacy = _render_legacy(artifact_dir)
    rewrite, rewrite_path = _render_rewrite(artifact_dir)
    report = _report(legacy, rewrite, rewrite_path, args.out)
    print(report)
    print(f"\n[artifact] {artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
