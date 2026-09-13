"""公共资源 generation 的候选校验、原子发布和运行期快照 lease。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
from builtins import BaseExceptionGroup
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import copy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from PIL import Image

from .encyclopedia import EncyclopediaResourceStore
from .git import (
    DEFAULT_RESOURCE_REMOTE,
    GitRunner,
    ResourceSyncError,
    ResourceSynchronizer,
    ResourceSyncResult,
    run_git,
)
from .manifest import ResourceManifest, ResourceManifestError
from .paths import (
    RESOURCE_GENERATION_STATE_NAME,
    RESOURCE_LAST_SYNC_STATE_NAME,
    RESOURCE_VALIDATION_STATE_NAME,
)

if TYPE_CHECKING:
    from ..rendering.player import ResourceMap


class ResourceGenerationError(ResourceSyncError):
    """资源候选 generation 不可发布或当前快照不可恢复。"""


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """一个不可变资源视图；完整校验完成前内容哈希可以为空。"""

    commit_sha: str
    root: Path
    manifest: ResourceManifest
    player_resources: ResourceMap
    encyclopedia_resources: EncyclopediaResourceStore
    content_sha256: str = ""

    @property
    def resource_version(self) -> str:
        """返回该 generation 的公开资源版本。"""

        return self.manifest.resource_version


@dataclass(frozen=True, slots=True)
class ResourceSyncStatus:
    """可持久化的最近同步安全摘要，不保存仓库路径或异常原文。"""

    status: str
    action: str = ""
    resource_version: str = ""
    commit_sha: str = ""
    error_type: str = ""

    @classmethod
    def from_result(cls, result: ResourceSyncResult) -> ResourceSyncStatus:
        """从同步结果提取不会携带凭据的摘要。"""

        return cls(
            status="success",
            action=result.action,
            resource_version=result.resource_version,
            commit_sha=result.commit_sha,
        )

    @classmethod
    def from_error(cls, error: BaseException) -> ResourceSyncStatus:
        """只保存异常类型，避免把 Git 或上游错误原文落入运行期状态。"""

        return cls(status="failed", error_type=type(error).__name__)

    def to_dict(self) -> dict[str, str]:
        """返回稳定的 JSON 状态投影。"""

        return {
            "status": self.status,
            "action": self.action,
            "resource_version": self.resource_version,
            "commit_sha": self.commit_sha,
            "error_type": self.error_type,
        }

    @classmethod
    def from_dict(cls, raw: object) -> ResourceSyncStatus:
        """解析并校验最近同步摘要；损坏状态必须显式报告。"""

        if not isinstance(raw, dict):
            raise ResourceGenerationError("最近资源同步状态格式无效")
        values: dict[str, str] = {}
        for field in (
            "status",
            "action",
            "resource_version",
            "commit_sha",
            "error_type",
        ):
            value = raw.get(field, "")
            if not isinstance(value, str):
                raise ResourceGenerationError("最近资源同步状态字段无效")
            values[field] = value
        if values["status"] not in {"success", "failed"}:
            raise ResourceGenerationError("最近资源同步状态结果无效")
        if values["status"] == "failed" and not values["error_type"]:
            raise ResourceGenerationError("最近资源同步状态缺少错误类型")
        return cls(**values)


@dataclass(frozen=True, slots=True)
class ResourceStatusSnapshot:
    """资源状态命令所需的轻量 metadata，不包含资源索引或完整校验结果。"""

    repository: Path
    active_pointer: Path
    generation_id: str | None
    resource_root: Path | None
    manifest: ResourceManifest | None
    manifest_state: str
    last_sync: ResourceSyncStatus | None
    last_sync_error: str | None = None
    current_validation_error: str | None = None


class ResourceLease(AbstractContextManager[ResourceSnapshot]):
    """持有 generation 引用，直到离开上下文或显式 release。"""

    def __init__(
        self, coordinator: ResourceSnapshotCoordinator, snapshot: ResourceSnapshot
    ) -> None:
        self._coordinator = coordinator
        self.snapshot = snapshot
        self._released = False

    @property
    def commit_sha(self) -> str:
        return self.snapshot.commit_sha

    @property
    def root(self) -> Path:
        return self.snapshot.root

    def __enter__(self) -> ResourceSnapshot:
        if self._released:
            raise ResourceGenerationError("资源 generation lease 已释放")
        return self.snapshot

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._coordinator._release(self.snapshot.commit_sha)

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.release()


_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_FONT_SIGNATURES = {
    ".ttf": frozenset({b"\x00\x01\x00\x00", b"true", b"ttcf"}),
    ".otf": frozenset({b"OTTO", b"\x00\x01\x00\x00", b"true", b"ttcf"}),
    ".woff": frozenset({b"wOFF"}),
    ".woff2": frozenset({b"wOF2"}),
}
_ASSET_ROOTS = ("images", "panel", "wiki", "guide", "weekly_item", "calendar")
_ALIAS_FILES = ("char_alias.json", "weapon_alias.json")
_REDEEM_KEYS = frozenset(
    {"code", "reward", "valid_from", "expires_at", "platforms", "servers"}
)
_PLATFORMS = frozenset({"pc", "android", "ios"})
_SERVERS = frozenset({"cn", "global"})


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResourceGenerationError(
            f"资源候选 JSON 不可读: {path.relative_to(path.parents[2])}"
        ) from exc


def _validate_alias_file(path: Path) -> None:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ResourceGenerationError(f"资源候选别名格式错误: {path.name}")
    used: dict[str, str] = {}
    terms: list[tuple[str, str]] = []
    for canonical, aliases in raw.items():
        if (
            not isinstance(canonical, str)
            or not canonical.strip()
            or canonical != canonical.strip()
        ):
            raise ResourceGenerationError(f"资源候选别名名称无效: {path.name}")
        if not isinstance(aliases, list) or not aliases:
            raise ResourceGenerationError(f"资源候选别名列表无效: {path.name}")
        terms.append((canonical, canonical))
        for alias in aliases:
            if (
                not isinstance(alias, str)
                or not alias.strip()
                or alias != alias.strip()
            ):
                raise ResourceGenerationError(f"资源候选别名条目无效: {path.name}")
            previous = used.get(alias)
            if previous is not None and previous == canonical:
                raise ResourceGenerationError(f"资源候选别名重复: {path.name}")
            if previous is not None:
                raise ResourceGenerationError(f"资源候选别名存在歧义: {path.name}")
            used[alias] = canonical
            terms.append((alias, canonical))
    for index, (left, left_owner) in enumerate(terms):
        for right, right_owner in terms[index + 1 :]:
            if left_owner != right_owner and (
                left == right or left in right or right in left
            ):
                raise ResourceGenerationError(f"资源候选别名存在歧义: {path.name}")


def _read_binary_prefix(path: Path, size: int, error_message: str) -> bytes:
    try:
        with path.open("rb") as file:
            return file.read(size)
    except OSError as exc:
        raise ResourceGenerationError(error_message) from exc


def _parse_aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ResourceGenerationError(
            f"兑换码 {field_name} 必须是带时区的 ISO 8601 时间"
        )
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ResourceGenerationError(f"兑换码 {field_name} 不是有效时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResourceGenerationError(f"兑换码 {field_name} 必须包含时区")
    return parsed


def _validate_enum_list(
    value: object, allowed: frozenset[str], field_name: str
) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(item not in allowed for item in value)
    ):
        raise ResourceGenerationError(f"兑换码 {field_name} 枚举值无效")
    if len(set(value)) != len(value):
        raise ResourceGenerationError(f"兑换码 {field_name} 不能重复")


def _validate_redeem_file(path: Path) -> None:
    raw = _read_json(path)
    if (
        not isinstance(raw, dict)
        or raw.get("format_version") != 1
        or not isinstance(raw.get("data"), list)
    ):
        raise ResourceGenerationError("资源候选兑换码文件格式错误")
    codes: set[str] = set()
    for entry in raw["data"]:
        if not isinstance(entry, dict) or not set(entry).issubset(_REDEEM_KEYS):
            raise ResourceGenerationError("资源候选兑换码条目格式错误")
        code = entry.get("code")
        if not isinstance(code, str) or not code or code != code.strip():
            raise ResourceGenerationError("资源候选兑换码 code 无效")
        if code in codes:
            raise ResourceGenerationError("资源候选兑换码 code 重复")
        codes.add(code)
        if "reward" in entry and not isinstance(entry["reward"], str):
            raise ResourceGenerationError("资源候选兑换码 reward 无效")
        start = (
            _parse_aware_datetime(entry["valid_from"], "valid_from")
            if "valid_from" in entry
            else None
        )
        end = (
            _parse_aware_datetime(entry["expires_at"], "expires_at")
            if "expires_at" in entry
            else None
        )
        if start is not None and end is not None and start >= end:
            raise ResourceGenerationError("资源候选兑换码有效期起止顺序无效")
        if "platforms" in entry:
            _validate_enum_list(entry["platforms"], _PLATFORMS, "platforms")
        if "servers" in entry:
            _validate_enum_list(entry["servers"], _SERVERS, "servers")


def _validate_schema_file(path: Path) -> None:
    raw = _read_json(path)
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("$schema"), str)
        or not raw["$schema"].strip()
        or raw.get("type") != "object"
    ):
        raise ResourceGenerationError("资源候选兑换码 schema 格式错误")
    required = raw.get("required")
    if not isinstance(required, list) or set(required) != {"format_version", "data"}:
        raise ResourceGenerationError("资源候选兑换码 schema required 无效")


def _validate_image_header(path: Path) -> None:
    header = _read_binary_prefix(path, 12, f"资源候选图片不可读: {path.name}")
    suffix = path.suffix.lower()
    valid = (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        if suffix == ".png"
        else header.startswith(b"\xff\xd8\xff")
        if suffix in {".jpg", ".jpeg"}
        else header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    )
    if not valid:
        raise ResourceGenerationError(f"资源候选图片文件头无效: {path.name}")


def _validate_image_decodability(path: Path) -> None:
    """用 PIL 实际校验图片结构和像素解码，而不是只信任文件头。"""

    _validate_image_header(path)
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ResourceGenerationError(f"资源候选图片不可解码: {path.name}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _content_sha256(root: Path) -> str:
    """按稳定的相对路径和完整文件内容计算 generation 摘要。"""

    digest = hashlib.sha256()
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _validate_declared_file_hashes(
    root: Path,
    manifest: ResourceManifest,
) -> None:
    for relative, expected in manifest.file_hashes.items():
        path = root.joinpath(*relative.split("/"))
        if path.is_symlink() or not path.is_file():
            raise ResourceGenerationError(f"资源候选文件哈希目标不存在: {relative}")
        actual = _sha256_file(path)
        if actual.casefold() != expected.casefold():
            raise ResourceGenerationError(f"资源候选文件哈希不匹配: {relative}")


def _validate_no_symlinks(root: Path) -> None:
    """拒绝 generation 根及其子项的符号链接，避免校验时读取外部文件。"""

    if root.is_symlink():
        raise ResourceGenerationError("资源候选不允许符号链接")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ResourceGenerationError("资源候选不允许符号链接")


def _validate_asset_headers(root: Path) -> None:
    for relative in _ASSET_ROOTS:
        asset_root = root / relative
        for path in sorted(asset_root.rglob("*")):
            if path.is_symlink():
                raise ResourceGenerationError(f"资源候选不允许符号链接: {relative}")
            if not path.is_file() or path.name == ".keep":
                continue
            if path.suffix.lower() in _IMAGE_SUFFIXES:
                _validate_image_decodability(path)
    font_root = root / "fonts"
    for path in sorted(font_root.rglob("*")):
        if path.is_symlink():
            raise ResourceGenerationError("资源候选不允许字体符号链接")
        if not path.is_file() or path.name == ".keep":
            continue
        signature_set = _FONT_SIGNATURES.get(path.suffix.lower())
        if signature_set is None:
            continue
        signature = _read_binary_prefix(path, 4, f"资源候选字体不可读: {path.name}")
        if signature not in signature_set:
            raise ResourceGenerationError(f"资源候选字体文件头无效: {path.name}")


class ResourceGenerationValidator:
    """验证可发布 generation 的 manifest、数据契约、素材头和运行期索引。"""

    def __init__(
        self,
        *,
        custom_alias_path: str | Path | None = None,
        custom_weapon_alias_path: str | Path | None = None,
    ) -> None:
        """保存运行目录的 custom 别名路径，避免 generation 根目录推导错误。"""

        self.custom_alias_path = (
            None
            if custom_alias_path is None
            else Path(custom_alias_path).expanduser().absolute()
        )
        self.custom_weapon_alias_path = (
            None
            if custom_weapon_alias_path is None
            else Path(custom_weapon_alias_path).expanduser().absolute()
        )

    def validate(self, root: str | Path, commit_sha: str) -> ResourceSnapshot:
        root_input = Path(root).expanduser()
        try:
            _validate_no_symlinks(root_input)
            root_path = root_input.resolve()
            manifest = ResourceManifest.load(
                root_path / "resource_manifest.json"
            ).validate_runtime_layout(root_path)
            _validate_declared_file_hashes(root_path, manifest)
            for filename in _ALIAS_FILES:
                _validate_alias_file(root_path / "alias" / filename)
            _validate_redeem_file(root_path / "data" / "redeem_codes.json")
            _validate_schema_file(root_path / "schemas" / "redeem-codes.v1.schema.json")
            _validate_asset_headers(root_path)
            from ..rendering.player import ResourceMap

            player_resources = ResourceMap.from_root(root_path)
            encyclopedia_resources = EncyclopediaResourceStore.from_root(
                root_path,
                custom_alias_path=self.custom_alias_path,
                custom_weapon_alias_path=self.custom_weapon_alias_path,
            )
            content_sha256 = _content_sha256(root_path)
        except ResourceGenerationError as exc:
            raise ResourceGenerationError(
                f"资源候选 generation 校验失败：{exc}"
            ) from exc
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise ResourceGenerationError("资源候选 generation 校验失败") from exc
        return ResourceSnapshot(
            commit_sha=commit_sha,
            root=root_path,
            manifest=manifest,
            player_resources=player_resources,
            encyclopedia_resources=encyclopedia_resources,
            content_sha256=content_sha256,
        )


def _safe_archive_member(root: Path, name: str, seen: set[str]) -> Path:
    if not name or "\\" in name:
        raise ResourceGenerationError("资源候选 archive 含有不安全路径")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ResourceGenerationError("资源候选 archive 含有路径逃逸")
    normalized = str(relative)
    if normalized in seen:
        raise ResourceGenerationError("资源候选 archive 含有重复路径")
    seen.add(normalized)
    target = (root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ResourceGenerationError("资源候选 archive 含有路径逃逸") from exc
    return target


def _extract_archive(archive_path: Path, destination: Path) -> None:
    seen: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r") as archive:
            for member in archive.getmembers():
                target = _safe_archive_member(destination, member.name, seen)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise ResourceGenerationError(
                        "资源候选 archive 含有不支持的文件类型"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ResourceGenerationError("资源候选 archive 文件不可读取")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except ResourceGenerationError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise ResourceGenerationError("资源候选 archive 不可读取") from exc


SnapshotListener = Callable[[ResourceSnapshot], None]


class ResourceSnapshotCoordinator:
    """管理 cache checkout 与运行期 generation 快照之间的原子边界。"""

    def __init__(
        self,
        repository: str | Path,
        *,
        generations_root: str | Path,
        remote: str = DEFAULT_RESOURCE_REMOTE,
        acceleration_prefix: str | None = None,
        runner: GitRunner = run_git,
        validator: ResourceGenerationValidator | None = None,
        custom_alias_path: str | Path | None = None,
        custom_weapon_alias_path: str | Path | None = None,
    ) -> None:
        # 保留运行期目录的符号链接状态，防止 resolve() 把资源写到边界之外。
        self.repository = Path(repository).expanduser().absolute()
        self.generations_root = Path(generations_root).expanduser().absolute()
        self.state_path = self.generations_root / RESOURCE_GENERATION_STATE_NAME
        self.last_sync_path = self.generations_root / RESOURCE_LAST_SYNC_STATE_NAME
        self.validation_path = self.generations_root / RESOURCE_VALIDATION_STATE_NAME
        self.remote = remote
        self.acceleration_prefix = acceleration_prefix
        self._runner = runner
        self._validator = validator or ResourceGenerationValidator(
            custom_alias_path=custom_alias_path,
            custom_weapon_alias_path=custom_weapon_alias_path,
        )
        self._custom_alias_path = (
            Path(custom_alias_path).expanduser().absolute()
            if custom_alias_path is not None
            else getattr(self._validator, "custom_alias_path", None)
        )
        self._custom_weapon_alias_path = (
            Path(custom_weapon_alias_path).expanduser().absolute()
            if custom_weapon_alias_path is not None
            else getattr(self._validator, "custom_weapon_alias_path", None)
        )
        # state lock 只保护内存状态；Git、归档、候选校验和内容哈希不在锁内执行。
        self._state_lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._validation_lock = threading.Lock()
        # light snapshot 只作为待校验输入保存，current 只允许指向完整校验结果。
        self._loaded_snapshot: ResourceSnapshot | None = None
        self._current: ResourceSnapshot | None = None
        self._expected_content_sha256: str | None = None
        self._last_sync: ResourceSyncStatus | None = None
        self._current_validation_error: str | None = None
        self._leases: dict[str, int] = {}
        # 同 commit 修复期间禁止新 lease，并在替换物理目录前等待旧 lease 释放。
        self._lease_condition = threading.Condition(self._state_lock)
        self._repairing: set[str] = set()
        self._retired: set[str] = set()
        self._listeners: list[SnapshotListener] = []

    def _ensure_storage_roots(self, *, require_repository: bool = False) -> None:
        """确认资源 checkout 与 generation 根目录没有通过符号链接越界。"""

        if self.generations_root.is_symlink():
            raise ResourceGenerationError("资源 generation 根目录不允许符号链接")
        if self.generations_root.exists() and not self.generations_root.is_dir():
            raise ResourceGenerationError("资源 generation 根目录不是目录")
        if self.repository.is_symlink():
            raise ResourceGenerationError("资源仓库目录不允许符号链接")
        if (
            require_repository
            and self.repository.exists()
            and not self.repository.is_dir()
        ):
            raise ResourceGenerationError("资源仓库目录不是目录")

    @property
    def current_snapshot(self) -> ResourceSnapshot | None:
        with self._state_lock:
            return self._current

    def subscribe(self, listener: SnapshotListener) -> Callable[[], None]:
        """注册发布后刷新运行期资源视图的监听器。"""

        with self._state_lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._state_lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _read_generation_pointer(self) -> tuple[str | None, str | None]:
        if self.state_path.is_symlink():
            raise ResourceGenerationError("当前资源 generation 指针不允许符号链接")
        if not self.state_path.exists():
            return None, None
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResourceGenerationError("当前资源 generation 指针不可读") from exc
        generation = raw.get("generation") if isinstance(raw, dict) else None
        if (
            not isinstance(generation, str)
            or re.fullmatch(r"[0-9a-fA-F]+", generation) is None
        ):
            raise ResourceGenerationError("当前资源 generation 指针无效")
        content_sha256 = raw.get("content_sha256") if isinstance(raw, dict) else None
        if content_sha256 is not None and (
            not isinstance(content_sha256, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", content_sha256) is None
        ):
            raise ResourceGenerationError("当前资源 generation 内容哈希指针无效")
        return generation, content_sha256

    def _read_generation_id(self) -> str | None:
        """兼容旧调用方，只返回 active pointer 中的 generation 标识。"""

        generation, _content_sha256 = self._read_generation_pointer()
        return generation

    def _read_last_sync_status(self) -> ResourceSyncStatus | None:
        """读取最近同步摘要；缺失表示尚未执行过同步。"""

        if self.last_sync_path.is_symlink():
            raise ResourceGenerationError("最近资源同步状态不允许符号链接")
        if not self.last_sync_path.exists():
            return None
        try:
            raw = json.loads(self.last_sync_path.read_text(encoding="utf-8"))
            return ResourceSyncStatus.from_dict(raw)
        except ResourceGenerationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResourceGenerationError("最近资源同步状态不可读") from exc

    @property
    def last_sync_status(self) -> ResourceSyncStatus | None:
        """返回当前进程已知的最近同步安全摘要。"""

        with self._state_lock:
            if self._last_sync is None:
                self._last_sync = self._read_last_sync_status()
            return self._last_sync

    def _write_last_sync_status(self, status: ResourceSyncStatus) -> None:
        """以同目录临时文件原子写入最近同步摘要。"""

        self._ensure_storage_roots()
        self.generations_root.mkdir(parents=True, exist_ok=True)
        self._ensure_storage_roots()
        if self.last_sync_path.is_symlink():
            raise ResourceGenerationError("最近资源同步状态不允许符号链接")
        temporary = self.generations_root / f".last-sync-{uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(status.to_dict(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.last_sync_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _read_validation_error(self) -> str | None:
        """读取当前 generation 最近一次完整校验失败的安全摘要。"""

        if self.validation_path.is_symlink():
            raise ResourceGenerationError("当前资源校验状态不允许符号链接")
        if not self.validation_path.exists():
            return None
        try:
            raw = json.loads(self.validation_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResourceGenerationError("当前资源校验状态不可读") from exc
        error_type = raw.get("error_type") if isinstance(raw, dict) else None
        if not isinstance(error_type, str) or not error_type:
            raise ResourceGenerationError("当前资源校验状态格式无效")
        return error_type

    def _write_validation_error(self, error_type: str) -> None:
        """原子保存当前 generation 的校验失败类型，不保存异常原文。"""

        self._ensure_storage_roots()
        self.generations_root.mkdir(parents=True, exist_ok=True)
        self._ensure_storage_roots()
        if self.validation_path.is_symlink():
            raise ResourceGenerationError("当前资源校验状态不允许符号链接")
        temporary = self.generations_root / f".validation-{uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps({"error_type": error_type}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.validation_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def record_validation_failure(self, error: BaseException) -> None:
        """记录 current generation 不可用，但不阻断管理/修复入口。"""

        error_type = type(error).__name__
        with self._state_lock:
            if self._current_validation_error == error_type:
                return
            self._write_validation_error(error_type)
            self._current_validation_error = error_type

    def _clear_validation_failure(self) -> None:
        """在成功发布或验证后清除旧的 current 校验失败摘要。"""

        with self._state_lock:
            if self.validation_path.is_symlink():
                raise ResourceGenerationError("当前资源校验状态不允许符号链接")
            if self.validation_path.exists():
                self.validation_path.unlink()
            self._current_validation_error = None

    def record_sync_result(self, result: ResourceSyncResult) -> None:
        """持久化一次成功或无变化同步的安全摘要。"""

        status = ResourceSyncStatus.from_result(result)
        with self._state_lock:
            if self._last_sync == status:
                return
            self._write_last_sync_status(status)
            self._last_sync = status

    def record_sync_failure(self, error: BaseException) -> None:
        """持久化同步失败的异常类型，不落盘异常原文。"""

        status = ResourceSyncStatus.from_error(error)
        with self._state_lock:
            if self._last_sync == status:
                return
            self._write_last_sync_status(status)
            self._last_sync = status

    @staticmethod
    def _read_status_manifest(
        resource_root: Path | None,
    ) -> tuple[str, ResourceManifest | None]:
        """仅读取状态所需 manifest，不检查目录树、图片或文件哈希。"""

        if resource_root is None:
            return "missing", None
        if resource_root.is_symlink() or not resource_root.is_dir():
            return "unavailable", None
        manifest_path = resource_root / "resource_manifest.json"
        if not manifest_path.is_file():
            return "missing", None
        try:
            return "ready", ResourceManifest.load(manifest_path)
        except (ResourceManifestError, UnicodeError):
            return "corrupt", None

    def read_status(
        self,
        snapshot: ResourceSnapshot | None = None,
    ) -> ResourceStatusSnapshot:
        """读取资源状态 metadata，不触发 Git、完整校验、图片解码或内容哈希。"""

        self._ensure_storage_roots()
        pointer_error: ResourceGenerationError | None = None
        if snapshot is not None:
            generation_id = snapshot.commit_sha
            resource_root = snapshot.root
            manifest = snapshot.manifest
            manifest_state = "ready"
        else:
            try:
                generation_id, _content_sha256 = self._read_generation_pointer()
            except ResourceGenerationError as error:
                # 状态命令必须能展示损坏 pointer，保留同步修复入口；不把仓库缓存
                # 冒充为当前 generation，也不在这里触发完整校验。
                generation_id = None
                pointer_error = error
            resource_root = (
                self._generation_path(generation_id)
                if generation_id is not None
                else None
            )
            manifest_state, manifest = self._read_status_manifest(resource_root)
        last_sync_error: str | None = None
        try:
            last_sync = self._read_last_sync_status()
        except ResourceGenerationError as error:
            last_sync = None
            last_sync_error = str(error)
        with self._state_lock:
            current_validation_error = self._current_validation_error
        if current_validation_error is None and pointer_error is not None:
            current_validation_error = type(pointer_error).__name__
        if current_validation_error is None and generation_id is not None:
            try:
                current_validation_error = self._read_validation_error()
            except ResourceGenerationError as error:
                current_validation_error = type(error).__name__
        return ResourceStatusSnapshot(
            repository=self.repository,
            active_pointer=self.state_path,
            generation_id=generation_id,
            resource_root=resource_root,
            manifest=manifest,
            manifest_state=manifest_state,
            last_sync=last_sync,
            last_sync_error=last_sync_error,
            current_validation_error=current_validation_error,
        )

    def _generation_path(self, commit_sha: str) -> Path:
        if re.fullmatch(r"[0-9a-fA-F]+", commit_sha) is None:
            raise ResourceGenerationError("资源 generation 提交标识无效")
        return self.generations_root / commit_sha

    def _remove_generation(self, path: Path) -> None:
        if path.parent != self.generations_root or path == self.generations_root:
            raise ResourceGenerationError("资源 generation 删除路径越界")
        if path.is_symlink():
            raise ResourceGenerationError("资源 generation 不允许符号链接")
        shutil.rmtree(path)

    def _cleanup_orphans(self, active: str | None) -> None:
        for path in sorted(self.generations_root.iterdir()):
            if path == self.state_path:
                continue
            if path.name.startswith((".candidate-", ".archive-")):
                if path.is_dir() and not path.is_symlink():
                    self._remove_generation(path)
                elif path.is_file():
                    path.unlink()
                continue
            if (
                path.is_dir()
                and re.fullmatch(r"[0-9a-fA-F]+", path.name)
                and path.name != active
            ):
                self._remove_generation(path)

    def _load_light_snapshot(self, generation: str) -> ResourceSnapshot:
        """读取已发布 generation 的 metadata 和运行期索引，不执行完整校验。"""

        root = self._generation_path(generation)
        if root.is_symlink() or not root.is_dir():
            raise ResourceGenerationError("当前资源 generation 目录不存在或不安全")
        try:
            manifest = ResourceManifest.load(root / "resource_manifest.json")
            from ..rendering.player import ResourceMap

            player_resources = ResourceMap.from_root(root)
            encyclopedia_resources = EncyclopediaResourceStore.from_root(
                root,
                custom_alias_path=self._custom_alias_path,
                custom_weapon_alias_path=self._custom_weapon_alias_path,
            )
        except ResourceGenerationError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise ResourceGenerationError(
                "当前资源 generation metadata 不可读"
            ) from exc
        return ResourceSnapshot(
            commit_sha=generation,
            root=root.resolve(),
            manifest=manifest,
            player_resources=player_resources,
            encyclopedia_resources=encyclopedia_resources,
        )

    def load_current(self) -> ResourceSnapshot | None:
        """只读取 current 指针和 generation metadata，供后续完整校验使用。"""

        self._ensure_storage_roots()
        generation, expected_content_sha256 = self._read_generation_pointer()
        if generation is None:
            with self._state_lock:
                self._loaded_snapshot = None
                self._current = None
                self._expected_content_sha256 = None
            self._clear_validation_failure()
            return None
        # metadata/index 读取不应占用保护运行期 current 的状态锁。
        snapshot = self._load_light_snapshot(generation)
        with self._state_lock:
            # 并发发布了新 generation 时，不允许旧的 load 结果覆盖 current。
            if (
                self._current is not None
                and self._current.commit_sha != snapshot.commit_sha
            ):
                return snapshot
            self._loaded_snapshot = snapshot
            # 轻量快照不得通过 current_snapshot/acquire 暴露给业务读取。
            self._current = None
            self._expected_content_sha256 = expected_content_sha256
        return snapshot

    def validate_current(self) -> ResourceSnapshot | None:
        """对已加载的 current generation 执行完整校验；无 current 时返回 ``None``。"""

        with self._validation_lock:
            with self._state_lock:
                snapshot = self._current or self._loaded_snapshot
                expected_content_sha256 = self._expected_content_sha256
                if snapshot is self._current:
                    # 重验现有 current 时暂时撤回暴露，避免校验期间继续读取可能已被
                    # 外部篡改的目录；新远端 generation 的构建不会走这个分支，因此不影响
                    # 已验证旧 generation 在后台同步期间继续服务。
                    self._current = None
            if snapshot is None:
                snapshot = self.load_current()
                with self._state_lock:
                    expected_content_sha256 = self._expected_content_sha256
            if snapshot is None:
                return None

            try:
                # 完整 validator、图片解码和 SHA-256 必须在 state lock 外执行。
                validated = self._validator.validate(snapshot.root, snapshot.commit_sha)
                if (
                    expected_content_sha256 is not None
                    and expected_content_sha256.casefold()
                    != validated.content_sha256.casefold()
                ):
                    raise ResourceGenerationError("当前资源 generation 内容哈希不匹配")
                if expected_content_sha256 is None:
                    self._write_state(validated)
            except Exception as error:
                with self._state_lock:
                    if self._current is snapshot:
                        self._current = None
                    if self._loaded_snapshot is snapshot:
                        self._loaded_snapshot = None
                    owns_failed_state = (
                        self._current is None and self._loaded_snapshot is None
                    )
                    if owns_failed_state:
                        self._expected_content_sha256 = None
                if owns_failed_state:
                    self.record_validation_failure(error)
                raise

            with self._state_lock:
                # 如果另一个受控发布已经替换了 current，不能用旧验证结果回写。
                if self._current is not None and self._current is not snapshot:
                    return self._current
                self._loaded_snapshot = validated
                self._current = validated
                self._expected_content_sha256 = validated.content_sha256
            self._clear_validation_failure()
            return validated

    def initialize(self) -> ResourceSnapshot | None:
        """兼容旧生命周期调用：完整恢复当前 generation 并清理孤立目录。"""

        with self._sync_lock:
            self._ensure_storage_roots()
            self.generations_root.mkdir(parents=True, exist_ok=True)
            self._ensure_storage_roots()
            snapshot = self.load_current()
            if snapshot is None:
                self._cleanup_orphans(None)
                return None
            validated = self.validate_current()
            if validated is not None:
                self._cleanup_orphans(validated.commit_sha)
            return validated

    def acquire(self) -> ResourceLease:
        """为一次资源读取取得当前已验证 generation lease。"""

        with self._lease_condition:
            current = self._current
            if current is None:
                raise ResourceGenerationError("当前没有可用的已验证资源 generation")
            commit_sha = current.commit_sha
            if commit_sha in self._repairing:
                raise ResourceGenerationError("当前资源 generation 正在修复")
            self._leases[commit_sha] = self._leases.get(commit_sha, 0) + 1
            return ResourceLease(self, current)

    @contextmanager
    def optional_lease(self) -> Iterator[ResourceSnapshot | None]:
        """为兼容尚未生成 snapshot 的旧缓存提供可选 lease。"""

        with self._lease_condition:
            current = self._current
            if current is not None and current.commit_sha not in self._repairing:
                commit_sha = current.commit_sha
                self._leases[commit_sha] = self._leases.get(commit_sha, 0) + 1
                lease = ResourceLease(self, current)
            else:
                lease = None
        if lease is None:
            yield None
            return
        with lease as snapshot:
            yield snapshot

    def _begin_generation_repair(self, commit_sha: str) -> None:
        """阻止新 lease，并等待旧 lease 退出后再替换同 commit 目录。

        该等待发生在同步 worker 中；condition 不设固定超时，确保不会在仍有
        读取者时提前替换 generation，也不会把未完成的读取静默判定为失败。
        """

        with self._lease_condition:
            self._repairing.add(commit_sha)
            current = self._current
            if current is not None and current.commit_sha == commit_sha:
                # 即使并发重验恰好重新放回 current，也要在替换同路径前撤回它；
                # 新请求只能等修复完成后重新取得新 snapshot。
                self._current = None
                if self._loaded_snapshot is current:
                    self._loaded_snapshot = None
            while self._leases.get(commit_sha, 0):
                self._lease_condition.wait()

    def _end_generation_repair(self, commit_sha: str) -> None:
        """解除同 commit 修复期间的新 lease 门禁。"""

        with self._lease_condition:
            self._repairing.discard(commit_sha)
            self._lease_condition.notify_all()

    @staticmethod
    def _empty_resource_view(resource_attr: str) -> Any:
        """返回无已验证 generation 时的显式空资源视图。"""

        if resource_attr == "player_resources":
            from ..rendering.player import ResourceMap

            return ResourceMap()
        if resource_attr == "encyclopedia_resources":
            return EncyclopediaResourceStore()
        raise ResourceGenerationError(f"资源 generation 视图字段无效: {resource_attr}")

    @contextmanager
    def bind_resource(self, resource_attr: str) -> Iterator[Any]:
        """在 lease 生命周期内返回指定的不可变资源视图。"""

        with self.optional_lease() as snapshot:
            if snapshot is None:
                yield self._empty_resource_view(resource_attr)
                return
            try:
                resources = getattr(snapshot, resource_attr)
            except AttributeError as exc:
                raise ResourceGenerationError(
                    f"资源 generation 视图字段无效: {resource_attr}"
                ) from exc
            yield resources

    @contextmanager
    def bind_renderer(
        self,
        renderer: Any,
        resource_attr: str,
        *,
        asset_resolver_attr: str | None = None,
    ) -> Iterator[Any]:
        """在同一 generation lease 内绑定资源视图和可选图片 resolver。"""

        from .resolver import AssetResolver

        with self.optional_lease() as snapshot:
            if snapshot is None:
                resources = self._empty_resource_view(resource_attr)
            else:
                try:
                    resources = getattr(snapshot, resource_attr)
                except AttributeError as exc:
                    raise ResourceGenerationError(
                        f"资源 generation 视图字段无效: {resource_attr}"
                    ) from exc

            bound = copy(renderer)
            bound.resources = resources
            if asset_resolver_attr is not None:
                base_resolver = getattr(renderer, asset_resolver_attr, None)
                if base_resolver is not None:
                    dynamic_root = getattr(base_resolver, "dynamic_root", None)
                    if dynamic_root is None:
                        raise ResourceGenerationError(
                            "renderer 的 asset resolver 缺少 dynamic_root: "
                            f"{asset_resolver_attr}"
                        )
                    setattr(
                        bound,
                        asset_resolver_attr,
                        AssetResolver.from_snapshot(
                            snapshot,
                            dynamic_root=dynamic_root,
                            downloader=getattr(base_resolver, "downloader", None),
                        ),
                    )
            yield bound

    def _release(self, commit_sha: str) -> None:
        with self._lease_condition:
            count = self._leases.get(commit_sha)
            if count is None:
                return
            if count == 1:
                del self._leases[commit_sha]
            else:
                self._leases[commit_sha] = count - 1
            self._lease_condition.notify_all()
        self._collect_retired()

    def _collect_retired(self) -> None:
        with self._state_lock:
            ready = tuple(
                commit_sha
                for commit_sha in self._retired
                if not self._leases.get(commit_sha, 0)
            )
            for commit_sha in ready:
                self._retired.remove(commit_sha)
        for commit_sha in ready:
            path = self._generation_path(commit_sha)
            try:
                if path.exists():
                    self._remove_generation(path)
            except BaseException:
                with self._state_lock:
                    self._retired.add(commit_sha)
                raise

    def _write_state(self, snapshot: ResourceSnapshot) -> None:
        self._ensure_storage_roots()
        if self.state_path.is_symlink():
            raise ResourceGenerationError("当前资源 generation 指针不允许符号链接")
        temporary = self.generations_root / f".current-{uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "generation": snapshot.commit_sha,
                        "content_sha256": snapshot.content_sha256,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.state_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _activate(self, snapshot: ResourceSnapshot) -> None:
        # 指针写入不与 state lock 交叠；调用方已由 sync lock 串行化。
        self._write_state(snapshot)
        with self._state_lock:
            previous = self._current or self._loaded_snapshot
            self._loaded_snapshot = snapshot
            self._current = snapshot
            self._expected_content_sha256 = snapshot.content_sha256
            if previous is not None and previous.commit_sha != snapshot.commit_sha:
                self._retired.add(previous.commit_sha)
            listeners = tuple(self._listeners)
        self._clear_validation_failure()
        for listener in listeners:
            listener(snapshot)
        self._collect_retired()

    def _materialize(
        self,
        synchronizer: ResourceSynchronizer,
        commit_sha: str,
        *,
        replace_existing: bool = False,
    ) -> tuple[ResourceSnapshot, bool]:
        self._ensure_storage_roots()
        self.generations_root.mkdir(parents=True, exist_ok=True)
        self._ensure_storage_roots()
        candidate = self.generations_root / f".candidate-{uuid4().hex}"
        archive = self.generations_root / f".archive-{uuid4().hex}.tar"
        final: Path | None = None
        replacement_backup: Path | None = None
        replacement_started = False
        created_final = False
        snapshot: ResourceSnapshot | None = None
        primary_error: BaseException | None = None
        try:
            candidate.mkdir()
            synchronizer.archive_fetch_head(archive)
            _extract_archive(archive, candidate)
            self._validator.validate(candidate, commit_sha)
            final = self._generation_path(commit_sha)
            if final.exists() or final.is_symlink():
                if not final.is_dir() or final.is_symlink():
                    raise ResourceGenerationError("资源 generation 目标不是安全目录")
                should_replace = replace_existing
                if not should_replace:
                    try:
                        snapshot = self._validator.validate(final, commit_sha)
                    except ResourceGenerationError:
                        should_replace = True
                if should_replace:
                    # 同一远端 commit 的旧目录可能已经损坏；候选已先完成完整校验，
                    # 通过临时 archive 目录替换旧目录，失败时恢复旧目录和 current 指针。
                    replacement_backup = (
                        self.generations_root / f".archive-{uuid4().hex}.replacement"
                    )
                    final.rename(replacement_backup)
                    replacement_started = True
                    candidate.rename(final)
                    created_final = True
                    # rename 后重新建立索引，避免 snapshot.root 仍指向 candidate。
                    snapshot = self._validator.validate(final, commit_sha)
            else:
                candidate.rename(final)
                created_final = True
                # 索引中的 Path 必须在 rename 后重新建立，不能继续指向已删除的 candidate。
                snapshot = self._validator.validate(final, commit_sha)
        except BaseException as error:  # noqa: BLE001 - 清理边界必须保留原始失败。
            primary_error = error

        cleanup_errors: list[BaseException] = []

        def cleanup(path: Path, *, generation: bool) -> None:
            if not path.exists() and not path.is_symlink():
                return
            try:
                if generation and path.is_dir() and not path.is_symlink():
                    self._remove_generation(path)
                else:
                    path.unlink()
            except BaseException as error:  # noqa: BLE001 - 必须显式报告清理失败。
                cleanup_errors.append(error)

        cleanup(candidate, generation=True)
        cleanup(archive, generation=False)
        if primary_error is not None and replacement_backup is not None:
            # 替换后的新目录未完成物化/校验时，优先恢复原有目录；清理失败仍需
            # 追加到原始错误，不能伪装成恢复成功。
            if (
                replacement_started
                and final is not None
                and (final.exists() or final.is_symlink())
            ):
                cleanup(final, generation=True)
            if replacement_backup.exists() or replacement_backup.is_symlink():
                try:
                    replacement_backup.rename(final)
                except BaseException as error:  # noqa: BLE001
                    cleanup_errors.append(error)
            created_final = False
        elif primary_error is None and replacement_backup is not None:
            cleanup(replacement_backup, generation=True)

        if (
            created_final
            and (primary_error is not None or cleanup_errors)
            and final is not None
        ):
            cleanup(final, generation=True)

        if primary_error is not None:
            if cleanup_errors:
                raise BaseExceptionGroup(
                    "资源 generation 物化和清理均失败",
                    [primary_error, *cleanup_errors],
                ) from primary_error
            raise primary_error
        if cleanup_errors:
            raise BaseExceptionGroup("资源 generation 临时文件清理失败", cleanup_errors)
        assert snapshot is not None
        return snapshot, created_final

    def _sync_resources(self) -> ResourceSyncResult:
        """执行串行同步，外层负责记录成功或失败摘要。"""

        with self._sync_lock:
            return self._sync_resources_unlocked()

    def _sync_resources_unlocked(self) -> ResourceSyncResult:
        """执行 Git/物化工作；不持有运行期 state lock。"""

        self._ensure_storage_roots(require_repository=True)
        synchronizer = ResourceSynchronizer(
            self.repository,
            remote=self.remote,
            acceleration_prefix=self.acceleration_prefix,
            runner=self._runner,
        )
        if not self.repository.exists():
            # 首次 clone 只建立受限 cache；候选仍统一来自随后写入的 FETCH_HEAD。
            result = synchronizer.sync()
            synchronizer.fetch_main()
        else:
            # 先 fetch，候选校验成功后才更新 cache 的工作树，避免坏提交污染旧快照。
            synchronizer.validate()
            synchronizer.fetch_main()
            result = ResourceSyncResult(
                repository=self.repository,
                action="updated",
                resource_version="",
            )
        commit_sha = synchronizer.fetch_head_revision()

        with self._state_lock:
            current = self._current
            known_validation_error = self._current_validation_error
        force_rebuild = known_validation_error is not None

        if current is not None and current.commit_sha == commit_sha:
            try:
                validated = self.validate_current()
            except ResourceGenerationError:
                validated = None
                force_rebuild = True
            if validated is not None:
                return replace(
                    result,
                    action="unchanged",
                    resource_version=validated.resource_version,
                    commit_sha=commit_sha,
                    generation_root=validated.root,
                    content_sha256=validated.content_sha256,
                )

        if current is None and known_validation_error is None:
            # 重载后的 light snapshot 也必须先完整验证；验证失败则继续走
            # materialize，用同一个远端 commit 重建损坏的 generation。
            try:
                self.load_current()
                validated = self.validate_current()
            except ResourceGenerationError:
                validated = None
                force_rebuild = True
            if validated is not None and validated.commit_sha == commit_sha:
                return replace(
                    result,
                    action="unchanged",
                    resource_version=validated.resource_version,
                    commit_sha=commit_sha,
                    generation_root=validated.root,
                    content_sha256=validated.content_sha256,
                )

        repair_generation = False
        if force_rebuild:
            final_path = self._generation_path(commit_sha)
            repair_generation = final_path.exists() or final_path.is_symlink()
        try:
            if repair_generation:
                # 先建立门禁再等待旧 lease；否则等待期间仍可能有新 lease 指向旧路径，
                # 导致替换后继续读取到不稳定的物理目录。
                self._begin_generation_repair(commit_sha)
            if force_rebuild:
                snapshot, created_final = self._materialize(
                    synchronizer,
                    commit_sha,
                    replace_existing=True,
                )
            else:
                snapshot, created_final = self._materialize(synchronizer, commit_sha)
            try:
                synchronizer.fast_forward_fetch_head()
                synchronizer.validate()
                with self._state_lock:
                    current = self._current
                if current is None or current.commit_sha != commit_sha:
                    self._activate(snapshot)
            except BaseException as error:
                cleanup_errors: list[BaseException] = []
                with self._state_lock:
                    current = self._current
                if created_final and (
                    current is None or current.commit_sha != commit_sha
                ):
                    try:
                        self._remove_generation(snapshot.root)
                    except BaseException as cleanup_error:  # noqa: BLE001
                        cleanup_errors.append(cleanup_error)
                if cleanup_errors:
                    raise BaseExceptionGroup(
                        "资源 generation 发布和清理均失败",
                        [error, *cleanup_errors],
                    ) from error
                raise
            return replace(
                result,
                resource_version=snapshot.resource_version,
                commit_sha=commit_sha,
                generation_root=snapshot.root,
                content_sha256=snapshot.content_sha256,
            )
        finally:
            if repair_generation:
                self._end_generation_repair(commit_sha)

    def sync_resources(self) -> ResourceSyncResult:
        """同步 cache、验证 FETCH_HEAD 候选并原子发布新快照。"""

        try:
            result = self._sync_resources()
        except Exception as error:
            self.record_sync_failure(error)
            raise
        self.record_sync_result(result)
        return result

    def synchronize(self) -> ResourceSyncResult:
        """兼容旧调用方，转发到 ``sync_resources``。"""

        return self.sync_resources()


ResourceGenerationManager = ResourceSnapshotCoordinator


__all__ = [
    "ResourceGenerationError",
    "ResourceGenerationManager",
    "ResourceGenerationValidator",
    "ResourceLease",
    "ResourceSnapshot",
    "ResourceSnapshotCoordinator",
    "ResourceStatusSnapshot",
    "ResourceSyncStatus",
]
