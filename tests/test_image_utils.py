"""图片工具测试。"""

import asyncio

from astrbot.api.message_components import Image as AstrBotImage

from dnaby.utils.image_utils import change_ev_image_to_bytes


def test_change_event_image_component_to_bytes(tmp_path):
    """OneBot/AstrBot Image 组件应能转换为上传所需的 bytes。"""
    source = tmp_path / "panel.png"
    source.write_bytes(b"test-image")

    image = AstrBotImage.fromFileSystem(str(source))

    result = asyncio.run(change_ev_image_to_bytes(image))

    assert result == b"test-image"
