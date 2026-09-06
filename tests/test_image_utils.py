"""图片工具测试。"""

import asyncio
from pathlib import Path

from astrbot.api.message_components import Image as AstrBotImage
from PIL import Image

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

    footer = Image.open(
        Path(__file__).parents[1] / "src/resources/textures/common/footer.png"
    )
    expected_height = int(footer.height * 600 / footer.width)
    expected_left = (card.width - 600) // 2
    expected_top = card.height - expected_height - 20
    assert (
        rendered.crop(
            (
                expected_left,
                expected_top,
                expected_left + 600,
                expected_top + expected_height,
            ),
        ).getbbox()
        is not None
    )
