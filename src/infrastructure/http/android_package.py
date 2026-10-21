"""只读取 APK 的 ZIP 元数据及 AndroidManifest，不下载游戏正文。"""

import io
import struct
import zipfile
import zlib
from collections.abc import Awaitable, Callable


async def read_official_android_package(
    read_range: Callable[[int, int | None], Awaitable[tuple[bytes, int]]],
) -> tuple[str, int, int]:
    tail, total = await read_range(-65557, None)  # ZIP EOCD + 最大 comment 长度。
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or end + 22 > len(tail):
        raise ValueError("APK ZIP end record missing")
    fields = struct.unpack_from("<4s4H2IH", tail, end)
    _, disk, central_disk, entries, count, size, offset, comment = fields
    if (
        disk
        or central_disk
        or entries != count
        or count == 65535
        or size == 0xFFFFFFFF
        or offset == 0xFFFFFFFF
        or end + 22 + comment != len(tail)
        or offset + size != total - len(tail) + end
    ):
        raise ValueError("unsupported APK ZIP directory")
    central, next_total = await read_range(offset, offset + size - 1)
    if next_total != total:
        raise ValueError("APK changed during metadata read")
    # 将中央目录放到小型内存 ZIP 中，保留条目原始 offset；不建立整包副本。
    eocd = bytearray(tail[end:])
    struct.pack_into("<I", eocd, 16, 0)
    with zipfile.ZipFile(io.BytesIO(central + eocd)) as archive:
        info = archive.getinfo("AndroidManifest.xml")
        if info.flag_bits & 1 or info.compress_type not in (0, 8):
            raise ValueError("unsupported APK manifest encoding")
        header, next_total = await read_range(
            info.header_offset, info.header_offset + 29
        )
        if next_total != total:
            raise ValueError("APK changed during metadata read")
        values = struct.unpack("<I5H3I2H", header)
        if values[0] != 0x04034B50:
            raise ValueError("APK manifest local header missing")
        start = info.header_offset + 30 + values[-2] + values[-1]
        if info.compress_size <= 0 or start + info.compress_size > offset:
            raise ValueError("invalid APK manifest bounds")
        body, next_total = await read_range(start, start + info.compress_size - 1)
        if next_total != total:
            raise ValueError("APK changed during metadata read")
        if info.compress_type == 8:
            decoder = zlib.decompressobj(-15)
            body = decoder.decompress(body, info.file_size + 1)
            if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError("invalid APK manifest compression")
        if len(body) != info.file_size or zlib.crc32(body) != info.CRC:
            raise ValueError("APK manifest integrity mismatch")
    name, code = parse_official_android_manifest(body)
    return name, code, total


def parse_official_android_manifest(data: bytes) -> tuple[str, int]:
    def uint16(offset: int) -> int:
        return struct.unpack_from("<H", data, offset)[0]

    def uint32(offset: int) -> int:
        return struct.unpack_from("<I", data, offset)[0]

    def length(offset: int, utf8: bool) -> tuple[int, int]:
        step, mask = (1, 0x80) if utf8 else (2, 0x8000)
        first = data[offset] if utf8 else uint16(offset)
        if first & mask:
            second = data[offset + step] if utf8 else uint16(offset + step)
            return ((first & (mask - 1)) << (step * 8)) | second, offset + 2 * step
        return first, offset + step

    if struct.unpack_from("<HHI", data) != (3, 8, len(data)):
        raise ValueError("invalid binary AndroidManifest")
    strings: list[str] = []
    offset = 8
    while offset < len(data):
        kind, header, size = struct.unpack_from("<HHI", data, offset)
        if header < 8 or size < header or offset + size > len(data):
            raise ValueError("invalid AndroidManifest chunk")
        if kind == 1:
            if header < 28:
                raise ValueError("invalid AndroidManifest string pool")
            count, flags, start = (
                uint32(offset + 8),
                uint32(offset + 16),
                uint32(offset + 20),
            )
            if header + count * 4 > start or start >= size:
                raise ValueError("invalid AndroidManifest string offsets")
            for index in range(count):
                pos = offset + start + uint32(offset + header + index * 4)
                if not offset + start <= pos < offset + size:
                    raise ValueError("invalid AndroidManifest string offset")
                utf8 = bool(flags & 256)
                count_chars, pos = length(pos, utf8)
                if utf8:
                    count_chars, pos = length(pos, True)
                end = pos + count_chars * (1 if utf8 else 2)
                if end + (1 if utf8 else 2) > offset + size:
                    raise ValueError("truncated AndroidManifest string")
                strings.append(data[pos:end].decode("utf-8" if utf8 else "utf-16le"))
        elif kind == 0x102:
            ext = offset + header
            if ext + 20 > offset + size:
                raise ValueError("invalid AndroidManifest element")
            if strings[uint32(ext + 4)] == "manifest":
                start, stride, count = (
                    uint16(ext + 8),
                    uint16(ext + 10),
                    uint16(ext + 12),
                )
                if (
                    start < 20
                    or stride < 20
                    or ext + start + stride * count > offset + size
                ):
                    raise ValueError("invalid AndroidManifest attributes")
                attributes: dict[str, str | int] = {}
                for index in range(count):
                    pos = ext + start + index * stride
                    key = strings[uint32(pos + 4)]
                    if key not in {"package", "versionName", "versionCode"}:
                        continue
                    if key in attributes:
                        raise ValueError("duplicate AndroidManifest attribute")
                    raw, value = uint32(pos + 8), uint32(pos + 16)
                    if raw != 0xFFFFFFFF:
                        attributes[key] = strings[raw]
                    elif data[pos + 15] == 3:
                        attributes[key] = strings[value]
                    elif data[pos + 15] == 0x10:
                        attributes[key] = value
                    else:
                        raise ValueError("invalid AndroidManifest value type")
                name, code = attributes["versionName"], attributes["versionCode"]
                if (
                    attributes["package"] != "com.hero.dna.gf"
                    or not isinstance(name, str)
                    or type(code) is not int
                    or code <= 0
                ):
                    raise ValueError("unexpected official APK identity")
                return name, code
        offset += size
    raise ValueError("AndroidManifest identity missing")
