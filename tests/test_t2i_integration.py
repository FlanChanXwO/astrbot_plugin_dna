"""可选的真实 AstrBot 全局 T2I 集成测试。

默认不访问网络；设置 ``DNABY_T2I_INTEGRATION=1`` 后才调用本机全局渲染器。
服务不可用时显式 skip，避免把环境缺失伪装成通过。
"""

from __future__ import annotations

import asyncio
import os
from io import BytesIO

import pytest
from PIL import Image

from dnaby.dna_sign.sign import create_sign_info_image
from dnaby.rendering import HtmlRenderError
from dnaby.rendering.qr import render_qr_code
from dnaby.utils.session import EventContext, Sender


def _decode_png(payload: bytes) -> Image.Image:
    image = Image.open(BytesIO(payload))
    image.load()
    assert image.format == "PNG"
    return image


@pytest.mark.skipif(
    os.getenv("DNABY_T2I_INTEGRATION") != "1",
    reason="设置 DNABY_T2I_INTEGRATION=1 才调用真实 AstrBot T2I",
)
def test_global_t2i_renders_representative_cards() -> None:
    """检查真实服务能输出固定尺寸 PNG，且字体/二维码内容已进入渲染链。"""

    async def scenario() -> tuple[bytes, bytes]:
        return (
            await create_sign_info_image("✅[二重螺旋]签到成功！\n字体与消息链路", theme="green"),
            await render_qr_code("https://localhost/login"),
        )

    try:
        sign_png, qr_png = asyncio.run(scenario())
    except HtmlRenderError as exc:
        pytest.skip(f"AstrBot 全局 T2I 服务不可用: {exc}")

    sign_image = _decode_png(sign_png)
    qr_image = _decode_png(qr_png)
    assert sign_image.size == (600, 250)
    assert qr_image.size == (420, 420)
    assert qr_image.getbbox() is not None

    # 代表性 handler 返回的真实 PNG bytes 仍进入原有 AstrBot 图片消息链。
    sender = Sender(EventContext(user_id="integration-user"))
    sender.send(sign_png)
    chains = sender.to_chains()
    assert len(chains) == 1
    assert type(chains[0][0]).__name__ == "Image"
