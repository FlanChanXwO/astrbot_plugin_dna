"""使用 HTML/T2I 渲染二维码，避免业务层生成用户可见 PIL 图片。"""

from __future__ import annotations

import qrcode

from .renderer import HtmlRenderer
from .spec import RenderSpec

QR_SIZE = 420
_RENDERER = HtmlRenderer()


async def render_qr_code(data: str, *, size: int = QR_SIZE) -> bytes:
    """将二维码矩阵交给全局 T2I 渲染为固定尺寸 PNG。"""

    qr = qrcode.QRCode(border=2)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    return await _RENDERER.render(
        "cards/qr_code.html.j2",
        {
            "matrix": matrix,
            "modules": len(matrix),
            "size": size,
        },
        RenderSpec(width=size, height=size, full_page=False),
    )
