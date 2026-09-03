"""带完整性元数据的运行期文件缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ..config.settings import CacheSettings

logger = logging.getLogger(__name__)

CacheState = Literal["fresh", "miss"]
ContentValidator = Callable[[bytes], bool | None | Awaitable[bool | None]]


class CacheContentError(ValueError):
    """缓存内容为空或未通过调用方完整性校验。"""


class CacheMetadataError(ValueError):
    """缓存 sidecar 无法解析，拒绝在不明租约状态下覆盖。"""


class CacheMissError(LookupError):
    """请求租约的缓存条目不存在、已过期或完整性校验失败。"""


@dataclass(frozen=True, slots=True)
class CacheMetadata:
    """缓存条目的 sidecar 元数据；``key`` 只保存不可逆摘要。"""

    cache_type: str
    key: str
    content_sha256: str
    created_at: datetime
    last_accessed_at: datetime
    resource_version: str | None = None
    integrity: str = "complete"
    tags: tuple[str, ...] = ()
    lease_count: int = 0

    def to_dict(self) -> dict[str, object]:
        """转换为 sidecar JSON 的稳定表示。"""

        return {
            "cache_type": self.cache_type,
            "key": self.key,
            "content_sha256": self.content_sha256,
            "created_at": self.created_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "resource_version": self.resource_version,
            "integrity": self.integrity,
            "tags": list(self.tags),
            "lease_count": self.lease_count,
        }

    @classmethod
    def from_dict(cls, raw: object) -> CacheMetadata:
        """从 sidecar 读取并校验必要字段。"""

        if not isinstance(raw, dict):
            raise TypeError("缓存 metadata 必须是对象")
        tags = raw.get("tags", [])
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) or not tag for tag in tags
        ):
            raise ValueError("缓存 metadata tags 无效")
        lease_count = raw.get("lease_count", 0)
        if not isinstance(lease_count, int) or lease_count < 0:
            raise ValueError("缓存 metadata lease_count 无效")
        created_at = _parse_datetime(raw.get("created_at"))
        last_accessed_at = _parse_datetime(raw.get("last_accessed_at"))
        cache_type = raw.get("cache_type")
        key = raw.get("key")
        content_sha256 = raw.get("content_sha256")
        integrity = raw.get("integrity")
        resource_version = raw.get("resource_version")
        if not isinstance(cache_type, str) or not cache_type:
            raise ValueError("缓存 metadata cache_type 无效")
        if not isinstance(key, str) or not key:
            raise ValueError("缓存 metadata key 无效")
        if (
            not isinstance(content_sha256, str)
            or len(content_sha256) != 64
            or any(char not in "0123456789abcdef" for char in content_sha256)
        ):
            raise ValueError("缓存 metadata content_sha256 无效")
        if not isinstance(integrity, str) or not integrity:
            raise ValueError("缓存 metadata integrity 无效")
        if resource_version is not None and not isinstance(resource_version, str):
            raise ValueError("缓存 metadata resource_version 无效")
        return cls(
            cache_type=cache_type,
            key=key,
            content_sha256=content_sha256,
            created_at=created_at,
            last_accessed_at=last_accessed_at,
            resource_version=resource_version,
            integrity=integrity,
            tags=tuple(dict.fromkeys(tags)),
            lease_count=lease_count,
        )


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """一次缓存读取得到的内容及其元数据。"""

    content: bytes
    metadata: CacheMetadata


@dataclass(frozen=True, slots=True)
class CacheLookup:
    """缓存查询结果；miss 时 ``entry`` 为空且保留可观测原因。"""

    status: CacheState
    entry: CacheEntry | None = None
    reason: str | None = None


class CacheManager:
    """在一个运行期目录中管理带 sidecar 的完整文件缓存。"""

    def __init__(
        self,
        root: str | Path,
        settings: CacheSettings | None = None,
    ) -> None:
        # 保留根目录自身的符号链接状态，避免 resolve() 把写入边界解析到缓存根目录之外。
        self.root = Path(root).expanduser().absolute()
        self.settings = settings or CacheSettings()
        self._lock = asyncio.Lock()

    @staticmethod
    def key_digest(key: str) -> str:
        """返回不把原始 key 写入路径或 metadata 的 SHA-256 摘要。"""

        if not isinstance(key, str) or not key:
            raise ValueError("缓存 key 必须是非空字符串")
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_cache_type(cache_type: str) -> str:
        if (
            not isinstance(cache_type, str)
            or not cache_type
            or cache_type != cache_type.strip()
            or cache_type in {".", ".."}
            or "/" in cache_type
            or "\\" in cache_type
            or "\x00" in cache_type
        ):
            raise ValueError("缓存类型必须是安全的单级名称")
        return cache_type

    def _paths(self, cache_type: str, key: str) -> tuple[Path, Path]:
        cache_type = self._validate_cache_type(cache_type)
        digest = self.key_digest(key)
        directory = self.root / cache_type
        return directory / f"{digest}.data", directory / f"{digest}.meta.json"

    def _entry_path_is_unsafe(
        self,
        data_path: Path,
        metadata_path: Path,
    ) -> bool:
        """拒绝沿缓存根、类型目录或条目文件的符号链接读写。"""

        return any(
            path.is_symlink()
            for path in (
                self.root,
                data_path.parent,
                data_path,
                metadata_path,
            )
        )

    def _ensure_cache_directory(self, directory: Path) -> None:
        """创建缓存目录，并在写入前确认目录没有越过运行期根目录。"""

        if self.root.is_symlink() or (
            self.root.exists() and not self.root.is_dir()
        ):
            raise CacheMetadataError("缓存目录路径不安全")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise CacheMetadataError("缓存目录路径不安全")
        if directory.is_symlink() or (
            directory.exists() and not directory.is_dir()
        ):
            raise CacheMetadataError("缓存目录路径不安全")
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise CacheMetadataError("缓存目录路径不安全")

    @staticmethod
    def _normalize_now(now: datetime | None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("缓存时间必须带时区")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_tags(tags: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        if any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("缓存 tags 必须是非空字符串")
        return tuple(dict.fromkeys(tags))

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    async def _validate_content(
        content: bytes,
        validator: ContentValidator | None,
    ) -> None:
        if not content:
            raise CacheContentError("缓存内容不能为空")
        if validator is None:
            return
        try:
            result = validator(content)
            if inspect.isawaitable(result):
                result = await result
        except CacheContentError:
            raise
        except Exception as error:
            raise CacheContentError("缓存内容校验失败") from error
        if result is False:
            raise CacheContentError("缓存内容校验失败")

    @staticmethod
    def _read_metadata(path: Path) -> CacheMetadata:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CacheMetadata.from_dict(raw)

    def _ttl_seconds(self) -> float:
        """返回统一内容缓存 TTL；-1 为永久，0 为禁用持久缓存。"""

        if self.settings.ttl_hours == -1:
            return float("inf")
        return float(self.settings.ttl_hours * 60 * 60)

    async def put(
        self,
        cache_type: str,
        key: str,
        content: bytes,
        *,
        resource_version: str | None = None,
        tags: tuple[str, ...] | list[str] | set[str] = (),
        validator: ContentValidator | None = None,
        now: datetime | None = None,
    ) -> CacheMetadata:
        """校验并写入内容；TTL 为 0 时仅返回内存 metadata，不触碰磁盘。"""

        if not isinstance(content, bytes):
            raise TypeError("缓存内容必须是 bytes")
        await self._validate_content(content, validator)
        if resource_version is not None and not isinstance(resource_version, str):
            raise TypeError("resource_version 必须是字符串或 None")
        normalized_now = self._normalize_now(now)
        normalized_tags = self._normalize_tags(tags)
        normalized_type = self._validate_cache_type(cache_type)
        key_digest = self.key_digest(key)
        metadata = CacheMetadata(
            cache_type=normalized_type,
            key=key_digest,
            content_sha256=hashlib.sha256(content).hexdigest(),
            created_at=normalized_now,
            last_accessed_at=normalized_now,
            resource_version=resource_version,
            tags=normalized_tags,
        )
        if self.settings.ttl_hours == 0:
            return metadata

        data_path, metadata_path = self._paths(normalized_type, key)
        async with self._lock:
            self._ensure_cache_directory(data_path.parent)
            if data_path.is_symlink() or metadata_path.is_symlink():
                raise CacheMetadataError("已有缓存路径不安全")
            lease_count = 0
            if metadata_path.exists():
                try:
                    lease_count = self._read_metadata(metadata_path).lease_count
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:
                    raise CacheMetadataError(
                        "已有缓存 metadata 无法读取，拒绝覆盖"
                    ) from error
            metadata = replace(metadata, lease_count=lease_count)
            self._atomic_write(data_path, content)
            self._atomic_write(
                metadata_path,
                json.dumps(
                    metadata.to_dict(), ensure_ascii=False, sort_keys=True
                ).encode("utf-8"),
            )
            return metadata

    async def get(
        self,
        cache_type: str,
        key: str,
        *,
        validator: ContentValidator | None = None,
        now: datetime | None = None,
    ) -> CacheLookup:
        """读取统一 TTL 下的 fresh 条目；未命中时只返回 miss 及原因。"""

        normalized_now = self._normalize_now(now)
        normalized_type = self._validate_cache_type(cache_type)
        key_digest = self.key_digest(key)
        if self.settings.ttl_hours == 0:
            return CacheLookup("miss", reason="disabled")

        data_path, metadata_path = self._paths(normalized_type, key)
        async with self._lock:
            if self._entry_path_is_unsafe(data_path, metadata_path):
                return CacheLookup("miss", reason="unsafe_path")
            if not data_path.is_file() or not metadata_path.is_file():
                return CacheLookup("miss", reason="not_found")
            try:
                metadata = self._read_metadata(metadata_path)
                content = data_path.read_bytes()
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                return CacheLookup("miss", reason="invalid_metadata")
            if metadata.cache_type != normalized_type or metadata.key != key_digest:
                return CacheLookup("miss", reason="invalid_metadata")
            if metadata.integrity != "complete":
                return CacheLookup("miss", reason="invalid_integrity")
            if not content:
                return CacheLookup("miss", reason="empty_content")
            if hashlib.sha256(content).hexdigest() != metadata.content_sha256:
                return CacheLookup("miss", reason="content_hash_mismatch")
            try:
                await self._validate_content(content, validator)
            except CacheContentError:
                return CacheLookup("miss", reason="invalid_content")
            age_seconds = max(
                0.0, (normalized_now - metadata.created_at).total_seconds()
            )
            if age_seconds >= self._ttl_seconds():
                return CacheLookup("miss", reason="ttl_expired")
            accessed = replace(metadata, last_accessed_at=normalized_now)
            self._atomic_write(
                metadata_path,
                json.dumps(
                    accessed.to_dict(), ensure_ascii=False, sort_keys=True
                ).encode("utf-8"),
            )
            return CacheLookup("fresh", CacheEntry(content, accessed))

    @asynccontextmanager
    async def lease(
        self,
        cache_type: str,
        key: str,
        *,
        validator: ContentValidator | None = None,
        now: datetime | None = None,
    ) -> AsyncIterator[CacheEntry]:
        """持有一条缓存租约，避免清理器删除正在使用的条目。"""

        normalized_now = self._normalize_now(now)
        normalized_type = self._validate_cache_type(cache_type)
        key_digest = self.key_digest(key)
        if self.settings.ttl_hours == 0:
            raise CacheMissError("缓存已禁用")
        data_path, metadata_path = self._paths(normalized_type, key)
        async with self._lock:
            if self._entry_path_is_unsafe(data_path, metadata_path):
                raise CacheMissError("缓存条目路径不安全")
            if not data_path.is_file() or not metadata_path.is_file():
                raise CacheMissError("缓存条目不存在")
            try:
                metadata = self._read_metadata(metadata_path)
                content = data_path.read_bytes()
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                raise CacheMissError("缓存条目 metadata 无效") from error
            if metadata.cache_type != normalized_type or metadata.key != key_digest:
                raise CacheMissError("缓存条目 metadata 身份不匹配")
            if metadata.integrity != "complete":
                raise CacheMissError("缓存条目完整性不是 complete")
            if not content:
                raise CacheMissError("缓存条目内容为空")
            if hashlib.sha256(content).hexdigest() != metadata.content_sha256:
                raise CacheMissError("缓存条目内容校验失败")
            try:
                await self._validate_content(content, validator)
            except CacheContentError as error:
                raise CacheMissError("缓存条目内容校验失败") from error
            age_seconds = max(
                0.0, (normalized_now - metadata.created_at).total_seconds()
            )
            if age_seconds >= self._ttl_seconds():
                raise CacheMissError("缓存条目已过期")
            leased_metadata = replace(
                metadata,
                last_accessed_at=normalized_now,
                lease_count=metadata.lease_count + 1,
            )
            self._atomic_write(
                metadata_path,
                json.dumps(
                    leased_metadata.to_dict(), ensure_ascii=False, sort_keys=True
                ).encode("utf-8"),
            )
            entry = CacheEntry(content, leased_metadata)

        try:
            yield entry
        finally:
            async with self._lock:
                if (
                    not self._entry_path_is_unsafe(data_path, metadata_path)
                    and metadata_path.is_file()
                ):
                    try:
                        current = self._read_metadata(metadata_path)
                        if current.lease_count > 0:
                            self._atomic_write(
                                metadata_path,
                                json.dumps(
                                    replace(
                                        current, lease_count=current.lease_count - 1
                                    ).to_dict(),
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ).encode("utf-8"),
                            )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        KeyError,
                        TypeError,
                        ValueError,
                    ) as error:
                        # 释放阶段不能覆盖调用方异常；损坏 sidecar 保留现场交给维护任务。
                        logger.warning(
                            "缓存租约释放失败，保留条目等待维护: %s",
                            type(error).__name__,
                        )

    async def cleanup(self, *, now: datetime | None = None) -> int:
        """删除超过统一 TTL 且没有活动租约的条目，并清理孤儿 payload。"""

        normalized_now = self._normalize_now(now)
        async with self._lock:
            if self.root.is_symlink() or not self.root.is_dir():
                return 0
            removed = 0
            metadata_paths = sorted(self.root.rglob("*.meta.json"))
            for metadata_path in metadata_paths:
                data_path = metadata_path.with_name(
                    f"{metadata_path.name.removesuffix('.meta.json')}.data"
                )
                if (
                    metadata_path.is_symlink()
                    or data_path.is_symlink()
                    or metadata_path.parent.is_symlink()
                ):
                    continue
                try:
                    metadata = self._read_metadata(metadata_path)
                except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    # 损坏 sidecar 不能成为成功缓存；保留现场交给后续修复/观测，
                    # 避免清理器在无法确认租约时误删正在使用的内容。
                    continue
                age_seconds = max(
                    0.0, (normalized_now - metadata.created_at).total_seconds()
                )
                if (
                    age_seconds >= self._ttl_seconds()
                    and metadata.lease_count == 0
                ):
                    if data_path.exists() or data_path.is_symlink():
                        data_path.unlink()
                    if metadata_path.exists() or metadata_path.is_symlink():
                        metadata_path.unlink()
                    removed += 1

            for data_path in sorted(self.root.rglob("*.data")):
                metadata_path = data_path.with_name(
                    f"{data_path.name.removesuffix('.data')}.meta.json"
                )
                if data_path.is_symlink() or data_path.parent.is_symlink():
                    continue
                if not metadata_path.exists() and (
                    data_path.exists() or data_path.is_symlink()
                ):
                    data_path.unlink()
                    removed += 1
            return removed

    async def invalidate(
        self,
        cache_type: str | None = None,
        *,
        key: str | None = None,
        tags: tuple[str, ...] | list[str] | set[str] = (),
        resource_version: str | None = None,
    ) -> int:
        """按 cache type、key、tags 和素材版本精准删除无租约条目。

        至少提供一个筛选条件，避免调用方误把整个运行期缓存当作无条件
        清理目标；有活动租约的条目保留到发送完成后再由后续失效调用处理。
        损坏 sidecar 或非普通文件也保留现场，避免失效操作掩盖安全问题。
        """

        normalized_type = (
            None
            if cache_type is None
            else self._validate_cache_type(cache_type)
        )
        key_digest = None if key is None else self.key_digest(key)
        normalized_tags = self._normalize_tags(tags)
        if (
            normalized_type is None
            and key_digest is None
            and not normalized_tags
            and resource_version is None
        ):
            raise ValueError("缓存失效至少需要一个筛选条件")
        if resource_version is not None and not isinstance(resource_version, str):
            raise TypeError("resource_version 必须是字符串或 None")

        async with self._lock:
            if self.root.is_symlink() or not self.root.is_dir():
                return 0
            removed = 0
            for metadata_path in sorted(self.root.rglob("*.meta.json")):
                data_path = metadata_path.with_name(
                    f"{metadata_path.name.removesuffix('.meta.json')}.data"
                )
                if (
                    metadata_path.is_symlink()
                    or data_path.is_symlink()
                    or metadata_path.parent.is_symlink()
                    or not metadata_path.is_file()
                    or (data_path.exists() and not data_path.is_file())
                ):
                    continue
                try:
                    metadata = self._read_metadata(metadata_path)
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue
                if normalized_type is not None and metadata.cache_type != normalized_type:
                    continue
                if key_digest is not None and metadata.key != key_digest:
                    continue
                if normalized_tags and not set(normalized_tags).issubset(metadata.tags):
                    continue
                if (
                    resource_version is not None
                    and metadata.resource_version != resource_version
                ):
                    continue
                if metadata.lease_count != 0:
                    continue
                if data_path.exists():
                    data_path.unlink()
                if metadata_path.exists():
                    metadata_path.unlink()
                removed += 1
            return removed


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("缓存 metadata 时间无效")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("缓存 metadata 时间必须带时区")
    return parsed.astimezone(timezone.utc)
