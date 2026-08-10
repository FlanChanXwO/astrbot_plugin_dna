"""原生图片工具：替代 gsucore ``image_tools`` / ``download_file`` / ``qrlogin``。

- ``convert_img``：PIL/路径 → PNG bytes
- ``crop_center_img`` / ``tint_image``：纯 PIL 实现
- ``download``：httpx 下载到目录
- ``get_event_avatar``：按用户 id 拉头像（QQ 头像源），失败抛异常由调用方兜底
- ``change_ev_image_to_bytes``：URL/路径/bytes → bytes（上传用）
- ``get_qrcode_base64``：URL → 二维码 PNG bytes
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Protocol

import httpx
from astrbot.api import logger
from PIL import Image

from .session import EventContext

__all__ = [
    "change_ev_image_to_bytes",
    "convert_img",
    "crop_center_img",
    "download",
    "get_event_avatar",
    "get_qrcode_base64",
    "tint_image",
]


async def convert_img(
    img: bytes | str | Path | Image.Image,
    background: str | None = None,
) -> bytes:
    """PIL 图片 / 图片路径 / bytes → PNG bytes。"""
    if isinstance(img, bytes):
        return img
    if isinstance(img, (str, Path)):
        im = Image.open(img)
    else:
        im = img
    im = im.convert("RGBA" if background is None else "RGB")
    if background is not None:
        bg = Image.new("RGB", im.size, background)
        bg.paste(im, mask=im.split()[-1])
        im = bg
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def crop_center_img(img: Image.Image, w: int, h: int) -> Image.Image:
    """中心裁剪并缩放至 (w, h)。"""
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        return img
    ratio = max(w / img.width, h / img.height)
    new_w, new_h = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def tint_image(img: Image.Image, color: tuple) -> Image.Image:
    """将图片整体染成指定颜色（保留 alpha）。"""
    img = img.convert("RGBA")
    alpha = img.split()[-1]
    tinted = Image.new("RGBA", img.size, color)
    out = Image.composite(tinted, img, alpha)
    out.putalpha(alpha)
    return out


async def download(
    url: str,
    path: Path,
    name: str,
    tag: str = "",
) -> Path:
    """下载 url 到 ``path/name``（不存在时）。返回目标路径。"""
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    if target.exists():
        return target
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        target.write_bytes(resp.content)
    logger.info(f"{tag} 下载完成: {name} ({len(resp.content)}B)")
    return target


async def get_event_avatar(
    ev: EventContext,
    avatar_path: Path,
    size: int = 640,
) -> Image.Image:
    """获取事件用户头像（QQ 头像源），缓存到 avatar_path。

    失败时抛异常，由调用方决定兜底（如使用默认立绘）。
    """
    uid = ev.at or ev.user_id
    avatar_path.mkdir(parents=True, exist_ok=True)
    name = f"avatar_{uid}.png"
    target = avatar_path / name
    if not target.exists():
        url = f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s={size}"
        await download(url, avatar_path, name, tag="[DNA-avatar]")
    img = Image.open(target).convert("RGBA")
    return img.resize((size, size), Image.Resampling.LANCZOS)


class _ImageComponent(Protocol):
    """AstrBot 图片组件提供的最小转换接口。"""

    async def convert_to_file_path(self) -> str: ...


async def change_ev_image_to_bytes(
    image_source: _ImageComponent | str | bytes | Path,
) -> bytes:
    """URL / 本地路径 / bytes → bytes（自定义面板图上传用）。"""
    if isinstance(image_source, bytes):
        return image_source
    if isinstance(image_source, Path):
        return image_source.read_bytes()
    if not isinstance(image_source, str):
        image_path = await image_source.convert_to_file_path()
        return Path(image_path).read_bytes()
    s = image_source
    if s.startswith(("http://", "https://")):
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(s)
            resp.raise_for_status()
            return resp.content
    return Path(s).read_bytes()


async def get_qrcode_base64(url: str, path: Path, name: str) -> bytes:
    """生成二维码 PNG bytes（扫码登录用）。"""
    import qrcode

    path.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
