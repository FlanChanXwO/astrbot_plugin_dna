"""不依赖 Pillow 的 JPEG/PNG 结构检查与尺寸提取。"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

MediaType = Literal["image/jpeg", "image/png"]


@dataclass(frozen=True, slots=True)
class ImageInspection:
    """已验证图片的媒体类型、扩展名和像素尺寸。"""

    media_type: MediaType
    suffix: Literal[".jpg", ".png"]
    width: int
    height: int


def inspect_image(data: bytes, *, media_type: MediaType) -> ImageInspection:
    """用图片容器结构验证 bytes，并提取尺寸；不会解码像素或调用 Pillow。"""

    if not data:
        raise ValueError("图片 bytes 为空")
    if media_type == "image/png":
        if data[:2] == b"\xff\xd8":
            raise ValueError("图片格式不匹配：实际为 JPEG")
        return _inspect_png(data)
    if media_type == "image/jpeg":
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            raise ValueError("图片格式不匹配：实际为 PNG")
        return _inspect_jpeg(data)
    raise ValueError(f"不支持的图片媒体类型: {media_type}")


def _inspect_png(data: bytes) -> ImageInspection:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG 签名无效")
    offset = 8
    seen_ihdr = False
    seen_iend = False
    width = height = 0
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("PNG chunk 被截断")
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        crc_end = chunk_end + 4
        if crc_end > len(data):
            raise ValueError("PNG chunk 长度越界")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_payload = data[chunk_start:chunk_end]
        expected_crc = struct.unpack_from(">I", data, chunk_end)[0]
        import zlib

        if zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG chunk 校验失败")
        if chunk_type == b"IHDR":
            if seen_ihdr or length != 13:
                raise ValueError("PNG IHDR 无效")
            width, height = struct.unpack_from(">II", chunk_payload)
            if width <= 0 or height <= 0:
                raise ValueError("PNG 尺寸无效")
            seen_ihdr = True
        elif not seen_ihdr:
            raise ValueError("PNG 缺少首个 IHDR")
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("PNG IEND 无效")
            seen_iend = True
            offset = crc_end
            break
        offset = crc_end
    if not seen_ihdr or not seen_iend:
        raise ValueError("PNG 缺少完整 IEND")
    if offset != len(data):
        raise ValueError("PNG IEND 后存在无效数据")
    return ImageInspection("image/png", ".png", width, height)


def _inspect_jpeg(data: bytes) -> ImageInspection:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("JPEG SOI 签名无效")
    offset = 2
    width = height = 0
    saw_sof = False
    saw_eoi = False
    sof_markers = (
        set(range(0xC0, 0xC4))
        | set(range(0xC5, 0xC8))
        | set(range(0xC9, 0xCC))
        | set(range(0xCD, 0xD0))
    )
    while offset < len(data):
        if data[offset] != 0xFF:
            raise ValueError("JPEG marker 无效")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            raise ValueError("JPEG marker 被截断")
        marker = data[offset]
        offset += 1
        if marker == 0xD9:
            saw_eoi = True
            break
        if marker == 0xDA:
            if offset + 2 > len(data):
                raise ValueError("JPEG scan header 被截断")
            segment_length = struct.unpack_from(">H", data, offset)[0]
            if segment_length < 2 or offset + segment_length > len(data):
                raise ValueError("JPEG scan header 长度无效")
            offset += segment_length
            # 熵编码区可能含 FF00 和重启 marker；只需找到真正的 EOI，
            # 同时拒绝没有 EOI 的截断结果。
            eoi = data.find(b"\xff\xd9", offset)
            if eoi < 0:
                raise ValueError("JPEG 缺少完整 EOI")
            saw_eoi = True
            break
        if marker == 0x00 or 0xD8 <= marker <= 0xD9 or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            raise ValueError("JPEG segment 长度被截断")
        segment_length = struct.unpack_from(">H", data, offset)[0]
        if segment_length < 2 or offset + segment_length > len(data):
            raise ValueError("JPEG segment 长度无效")
        if marker in sof_markers:
            if segment_length < 7:
                raise ValueError("JPEG SOF 无效")
            height, width = struct.unpack_from(">HH", data, offset + 3)
            if width <= 0 or height <= 0:
                raise ValueError("JPEG 尺寸无效")
            saw_sof = True
        offset += segment_length
    if not saw_sof or not saw_eoi:
        raise ValueError("JPEG 缺少完整尺寸或结束标记")
    return ImageInspection("image/jpeg", ".jpg", width, height)


__all__ = ["ImageInspection", "MediaType", "inspect_image"]
