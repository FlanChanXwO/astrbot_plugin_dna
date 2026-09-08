"""公共资源 generation 的候选校验、原子发布和运行期快照 lease。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import copy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, TypeVar
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
from .manifest import ResourceManifest

if TYPE_CHECKING:
    from ..rendering.player import ResourceMap


class ResourceGenerationError(ResourceSyncError):
    """资源候选 generation 不可发布或当前快照不可恢复。"""


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """一个经过完整校验、可供运行期读取的不可变资源视图。"""

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


class ResourceLease(AbstractContextManager[ResourceSnapshot]):
    """持有 generation 引用，直到离开上下文或显式 release。"""

    def __init__(self, coordinator: ResourceSnapshotCoordinator, snapshot: ResourceSnapshot) -> None:
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
        raise ResourceGenerationError(f"资源候选 JSON 不可读: {path.relative_to(path.parents[2])}") from exc


def _validate_alias_file(path: Path) -> None:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ResourceGenerationError(f"资源候选别名格式错误: {path.name}")
    used: dict[str, str] = {}
    terms: list[tuple[str, str]] = []
    for canonical, aliases in raw.items():
        if not isinstance(canonical, str) or not canonical.strip() or canonical != canonical.strip():
            raise ResourceGenerationError(f"资源候选别名名称无效: {path.name}")
        if not isinstance(aliases, list) or not aliases:
            raise ResourceGenerationError(f"资源候选别名列表无效: {path.name}")
        terms.append((canonical, canonical))
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip() or alias != alias.strip():
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
        raise ResourceGenerationError(f"兑换码 {field_name} 必须是带时区的 ISO 8601 时间")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ResourceGenerationError(f"兑换码 {field_name} 不是有效时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResourceGenerationError(f"兑换码 {field_name} 必须包含时区")
    return parsed


def _validate_enum_list(value: object, allowed: frozenset[str], field_name: str) -> None:
    if not isinstance(value, list) or not value or any(item not in allowed for item in value):
        raise ResourceGenerationError(f"兑换码 {field_name} 枚举值无效")
    if len(set(value)) != len(value):
        raise ResourceGenerationError(f"兑换码 {field_name} 不能重复")


def _validate_redeem_file(path: Path) -> None:
    raw = _read_json(path)
    if not isinstance(raw, dict) or raw.get("format_version") != 1 or not isinstance(raw.get("data"), list):
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
        start = _parse_aware_datetime(entry["valid_from"], "valid_from") if "valid_from" in entry else None
        end = _parse_aware_datetime(entry["expires_at"], "expires_at") if "expires_at" in entry else None
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
    except (OSError, SyntaxError, ValueError) as exc:
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
            manifest = ResourceManifest.load(root_path / "resource_manifest.json").validate_runtime_layout(root_path)
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
            raise ResourceGenerationError(f"资源候选 generation 校验失败：{exc}") from exc
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
                    raise ResourceGenerationError("资源候选 archive 含有不支持的文件类型")
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
_ResolverBinding = TypeVar("_ResolverBinding")


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
        self.state_path = self.generations_root / "current.json"
        self.remote = remote
        self.acceleration_prefix = acceleration_prefix
        self._runner = runner
        self._validator = validator or ResourceGenerationValidator(
            custom_alias_path=custom_alias_path,
            custom_weapon_alias_path=custom_weapon_alias_path,
        )
        self._lock = threading.RLock()
        self._current: ResourceSnapshot | None = None
        self._leases: dict[str, int] = {}
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
        if require_repository and self.repository.exists() and not self.repository.is_dir():
            raise ResourceGenerationError("资源仓库目录不是目录")

    @property
    def current_snapshot(self) -> ResourceSnapshot | None:
        with self._lock:
            return self._current

    def subscribe(self, listener: SnapshotListener) -> Callable[[], None]:
        """注册发布后刷新运行期资源视图的监听器。"""

        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
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
        if not isinstance(generation, str) or re.fullmatch(r"[0-9a-fA-F]+", generation) is None:
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
            if path.is_dir() and re.fullmatch(r"[0-9a-fA-F]+", path.name) and path.name != active:
                self._remove_generation(path)

    def initialize(self) -> ResourceSnapshot | None:
        """读取当前指针并清理重启后没有 lease 的孤立 generation。"""

        with self._lock:
            self._ensure_storage_roots()
            self.generations_root.mkdir(parents=True, exist_ok=True)
            self._ensure_storage_roots()
            generation, expected_content_sha256 = self._read_generation_pointer()
            if generation is None:
                self._current = None
                self._cleanup_orphans(None)
                return None
            root = self._generation_path(generation)
            snapshot = self._validator.validate(root, generation)
            if (
                expected_content_sha256 is not None
                and expected_content_sha256.casefold() != snapshot.content_sha256.casefold()
            ):
                raise ResourceGenerationError("当前资源 generation 内容哈希不匹配")
            self._current = snapshot
            if expected_content_sha256 is None:
                self._write_state(snapshot)
            self._cleanup_orphans(generation)
            return snapshot

    def acquire(self) -> ResourceLease:
        """为一次资源读取取得当前 generation lease。"""

        with self._lock:
            if self._current is None:
                raise ResourceGenerationError("当前没有可用的已验证资源 generation")
            commit_sha = self._current.commit_sha
            self._leases[commit_sha] = self._leases.get(commit_sha, 0) + 1
            return ResourceLease(self, self._current)

    @contextmanager
    def optional_lease(self) -> Iterator[ResourceSnapshot | None]:
        """为兼容尚未生成 snapshot 的旧缓存提供可选 lease。"""

        if self.current_snapshot is None:
            yield None
            return
        with self.acquire() as snapshot:
            yield snapshot

    @contextmanager
    def bind_resource(self, resource_attr: str) -> Iterator[Any | None]:
        """在 lease 生命周期内返回指定的不可变资源视图。"""

        with self.optional_lease() as snapshot:
            if snapshot is None:
                yield None
                return
            try:
                resources = getattr(snapshot, resource_attr)
            except AttributeError as exc:
                raise ResourceGenerationError(
                    f"资源 generation 视图字段无效: {resource_attr}"
                ) from exc
            yield resources

    @contextmanager
    def bind_resolver(
        self,
        factory: Callable[[ResourceSnapshot | None], _ResolverBinding],
    ) -> Iterator[_ResolverBinding]:
        """在当前 generation lease 内创建请求级资源解析器。"""

        with self.optional_lease() as snapshot:
            yield factory(snapshot)

    @contextmanager
    def bind_renderer(self, renderer: Any, resource_attr: str) -> Iterator[Any]:
        """复制 renderer 并绑定一个持有 generation lease 的资源视图。"""

        with self.bind_resource(resource_attr) as resources:
            if resources is None:
                yield renderer
                return
            bound = copy(renderer)
            bound.resources = resources
            yield bound

    def _release(self, commit_sha: str) -> None:
        with self._lock:
            count = self._leases.get(commit_sha)
            if count is None:
                return
            if count == 1:
                del self._leases[commit_sha]
            else:
                self._leases[commit_sha] = count - 1
            self._collect_retired()

    def _collect_retired(self) -> None:
        for commit_sha in tuple(self._retired):
            if self._leases.get(commit_sha, 0):
                continue
            path = self._generation_path(commit_sha)
            if path.exists():
                self._remove_generation(path)
            self._retired.remove(commit_sha)

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
        previous = self._current
        self._write_state(snapshot)
        self._current = snapshot
        if previous is not None and previous.commit_sha != snapshot.commit_sha:
            self._retired.add(previous.commit_sha)
        try:
            for listener in tuple(self._listeners):
                listener(snapshot)
        finally:
            self._collect_retired()

    def _materialize(self, synchronizer: ResourceSynchronizer, commit_sha: str) -> ResourceSnapshot:
        self._ensure_storage_roots()
        self.generations_root.mkdir(parents=True, exist_ok=True)
        self._ensure_storage_roots()
        candidate = self.generations_root / f".candidate-{uuid4().hex}"
        archive = self.generations_root / f".archive-{uuid4().hex}.tar"
        try:
            candidate.mkdir()
            synchronizer.archive_fetch_head(archive)
            _extract_archive(archive, candidate)
            self._validator.validate(candidate, commit_sha)
            final = self._generation_path(commit_sha)
            if final.exists():
                if not final.is_dir() or final.is_symlink():
                    raise ResourceGenerationError("资源 generation 目标不是安全目录")
                existing = self._validator.validate(final, commit_sha)
                return existing
            candidate.rename(final)
            # 索引中的 Path 必须在 rename 后重新建立，不能继续指向已删除的 candidate。
            return self._validator.validate(final, commit_sha)
        finally:
            if candidate.exists():
                if candidate.is_dir() and not candidate.is_symlink():
                    self._remove_generation(candidate)
                else:
                    candidate.unlink()
            if archive.exists():
                archive.unlink()

    def synchronize(self) -> ResourceSyncResult:
        """同步 cache、验证 FETCH_HEAD 候选并原子发布新快照。"""

        with self._lock:
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
            snapshot = self._materialize(synchronizer, commit_sha)
            synchronizer.fast_forward_fetch_head()
            synchronizer.validate()
            if self._current is None or self._current.commit_sha != commit_sha:
                self._activate(snapshot)
            return replace(
                result,
                resource_version=snapshot.resource_version,
                commit_sha=commit_sha,
                generation_root=snapshot.root,
                content_sha256=snapshot.content_sha256,
            )


ResourceGenerationManager = ResourceSnapshotCoordinator


__all__ = [
    "ResourceGenerationError",
    "ResourceGenerationManager",
    "ResourceGenerationValidator",
    "ResourceLease",
    "ResourceSnapshot",
    "ResourceSnapshotCoordinator",
]
