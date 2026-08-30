"""玩家数据与渲染卡片的缓存适配器。

缓存 key 只在进程内组合用户身份、UID 和查询参数；``CacheManager`` 负责将
其摘要写入磁盘。这样可以复用统一的完整性、租约和 fresh/stale/retention
语义，同时不把用户身份或 UID 直接落到缓存文件名和 metadata 中。
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel

from ...entry.response import ImageResponse, write_temporary_image
from ...infrastructure.cache import CacheLookup, CacheManager

PLAYER_DATA_CACHE_TYPE = "player_data"
PLAYER_CARD_CACHE_TYPE = "player_card"


def _json_object_validator(content: bytes) -> bool:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict)


def _png_validator(content: bytes) -> bool:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (OSError, SyntaxError, ValueError):
        return False
    return True


class PlayerCache:
    """将玩家查询的领域对象映射到统一文件缓存。"""

    def __init__(self, manager: CacheManager, rendered_root: str | Path) -> None:
        self.manager = manager
        self.rendered_root = Path(rendered_root).expanduser().absolute()

    @staticmethod
    def _key(*parts: object) -> str:
        return "\x1f".join(str(part) for part in parts)

    @staticmethod
    def _version(value: str | None) -> str:
        return value if value else "none"

    @classmethod
    def identity_tag(cls, target_user_id: str, uid: str) -> str:
        digest = cls.manager_key_digest(cls._key(target_user_id, uid))
        return f"identity:{digest}"

    @staticmethod
    def manager_key_digest(value: str) -> str:
        """对 metadata tag 使用不可逆摘要，避免落盘敏感身份。"""

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def resource_tag(cls, resource_version: str | None) -> str:
        digest = cls.manager_key_digest(cls._version(resource_version))
        return f"resource:{digest}"

    @classmethod
    def data_tag(cls, data_digest: str) -> str:
        return f"data:{data_digest}"

    @classmethod
    def overview_data_key(cls, target_user_id: str, uid: str) -> str:
        return cls._key("overview-data", target_user_id, uid)

    @classmethod
    def detail_data_key(
        cls,
        target_user_id: str,
        uid: str,
        char_id: int,
        weapon_names: tuple[str, ...],
        overview_digest: str,
    ) -> str:
        return cls._key(
            "detail-data",
            target_user_id,
            uid,
            char_id,
            *weapon_names,
            overview_digest,
        )

    @classmethod
    def overview_card_key(
        cls,
        target_user_id: str,
        uid: str,
        data_digest: str,
        resource_version: str | None,
        uid_hidden: bool,
        show_unowned: bool,
    ) -> str:
        return cls._key(
            "overview-card",
            target_user_id,
            uid,
            data_digest,
            cls._version(resource_version),
            uid_hidden,
            show_unowned,
        )

    @classmethod
    def detail_card_key(
        cls,
        target_user_id: str,
        uid: str,
        char_id: int,
        weapon_names: tuple[str, ...],
        overview_digest: str,
        detail_digest: str,
        resource_version: str | None,
        uid_hidden: bool,
    ) -> str:
        return cls._key(
            "detail-card",
            target_user_id,
            uid,
            char_id,
            *weapon_names,
            overview_digest,
            detail_digest,
            cls._version(resource_version),
            uid_hidden,
        )

    @classmethod
    def overview_card_tags(
        cls,
        target_user_id: str,
        uid: str,
        data_digest: str,
        resource_version: str | None,
    ) -> tuple[str, ...]:
        return (
            "player_card",
            "overview",
            cls.identity_tag(target_user_id, uid),
            cls.data_tag(data_digest),
            cls.resource_tag(resource_version),
        )

    @classmethod
    def detail_data_tags(
        cls,
        target_user_id: str,
        uid: str,
        char_id: int,
        overview_digest: str,
    ) -> tuple[str, ...]:
        return (
            "player_data",
            "detail",
            cls.identity_tag(target_user_id, uid),
            f"role:{char_id}",
            cls.data_tag(overview_digest),
        )

    @classmethod
    def detail_card_tags(
        cls,
        target_user_id: str,
        uid: str,
        char_id: int,
        data_digest: str,
        resource_version: str | None,
    ) -> tuple[str, ...]:
        return (
            "player_card",
            "detail",
            cls.identity_tag(target_user_id, uid),
            f"role:{char_id}",
            f"panel:{char_id}",
            cls.data_tag(data_digest),
            cls.resource_tag(resource_version),
        )

    @staticmethod
    def encode_json(value: object) -> bytes:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json", by_alias=True)
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def decode_json(content: bytes) -> dict[str, Any]:
        value = json.loads(content.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("玩家缓存 JSON 必须是对象")
        return value

    @staticmethod
    def content_digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def read_rendered_card(self, image: object) -> bytes:
        """只读取受控 rendered 根下的普通 PNG，避免把任意路径写入缓存。"""

        root = self.rendered_root
        path = Path(str(image)).expanduser().absolute()
        if root.is_symlink() or not path.is_relative_to(root):
            raise ValueError("渲染图片不在受控目录中")
        current = path
        while current != root:
            if current.is_symlink():
                raise ValueError("渲染图片路径不能是符号链接")
            current = current.parent
        if not path.is_file():
            raise ValueError("渲染图片不是普通文件")
        content = path.read_bytes()
        if not _png_validator(content):
            raise ValueError("渲染图片不是有效 PNG")
        return content

    async def get_data(self, key: str, *, now=None) -> CacheLookup:
        return await self.manager.get(
            PLAYER_DATA_CACHE_TYPE,
            key,
            validator=_json_object_validator,
            now=now,
        )

    async def put_data(
        self,
        key: str,
        value: object,
        *,
        tags: tuple[str, ...],
        now=None,
    ):
        return await self.manager.put(
            PLAYER_DATA_CACHE_TYPE,
            key,
            self.encode_json(value),
            tags=tags,
            now=now,
        )

    async def get_card(self, key: str, *, now=None) -> CacheLookup:
        return await self.manager.get(
            PLAYER_CARD_CACHE_TYPE,
            key,
            validator=_png_validator,
            now=now,
        )

    async def put_card(
        self,
        key: str,
        content: bytes,
        *,
        resource_version: str | None,
        tags: tuple[str, ...],
        now=None,
    ):
        return await self.manager.put(
            PLAYER_CARD_CACHE_TYPE,
            key,
            content,
            resource_version=resource_version,
            tags=tags,
            validator=_png_validator,
            now=now,
        )

    async def card_response(self, key: str, *, now=None) -> ImageResponse:
        """在租约内复制缓存 PNG，避免清理器删除正在发送的内容。"""

        async with self.manager.lease(
            PLAYER_CARD_CACHE_TYPE,
            key,
            validator=_png_validator,
            now=now,
        ) as entry:
            return write_temporary_image(
                self.rendered_root,
                entry.content,
                prefix="player-cache-",
                suffix=".png",
            )


__all__ = [
    "PLAYER_CARD_CACHE_TYPE",
    "PLAYER_DATA_CACHE_TYPE",
    "PlayerCache",
]
