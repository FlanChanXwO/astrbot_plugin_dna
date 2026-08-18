"""图片工具测试。"""

import asyncio
from pathlib import Path

from astrbot.api.message_components import Image as AstrBotImage
from PIL import Image

from src.infrastructure.rendering.update_log import _extract_leading_emojis
from src.utils.image import add_footer
from src.utils.image_utils import change_ev_image_to_bytes


def test_change_event_image_component_to_bytes(tmp_path):
    """OneBot/AstrBot Image 组件应能转换为上传所需的 bytes。"""
    source = tmp_path / "panel.png"
    source.write_bytes(b"test-image")

    image = AstrBotImage.fromFileSystem(str(source))

    result = asyncio.run(change_ev_image_to_bytes(image))

    assert result == b"test-image"


def test_footer_keeps_legacy_card_width() -> None:
    """卡片仍按 legacy 的 600px footer 宽度排版。"""

    card = Image.new("RGBA", (1200, 300), "black")
    rendered = add_footer(card, 600)

    footer = Image.open(Path(__file__).parents[1] / "src/resources/textures/common/footer.png")
    expected_height = int(footer.height * 600 / footer.width)
    expected_left = (card.width - 600) // 2
    expected_top = card.height - expected_height - 20
    assert rendered.crop(
        (expected_left, expected_top, expected_left + 600, expected_top + expected_height),
    ).getbbox() is not None


def test_update_log_accepts_commit_without_emoji() -> None:
    """Conventional Commit 不应因缺少 emoji 被更新记录丢弃。"""

    emojis, text = _extract_leading_emojis("fix: keep update log visible")

    assert emojis == []
    assert text == "fix: keep update log visible"
