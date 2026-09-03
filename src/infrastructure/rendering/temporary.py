"""运行期合成图片的受控目录、租约和过期清理。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

DEFAULT_RENDERED_PREFIXES = (
    "player-",
    "player-cache-",
    "encyclopedia-",
    "notices-",
    "checkin-",
    "dnaby-help-",
    "dnaby-resource-",
)

# 内容缓存 TTL 与 rendered 临时文件生命周期相互独立。
DEFAULT_RENDERED_RETENTION_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RenderedCleanupReport:
    """一次 rendered 扫描的可观测结果。"""

    removed: int = 0
    skipped_active: int = 0
    skipped_invalid: int = 0


class RenderedFileStore:
    """管理运行期生成图片，并在租约存在时保护发送中的文件。

    renderer 仍可直接生成文件，但只有已知的临时文件名前缀会进入清理范围；
    ``panel_custom``、资源和其它持久数据不会因一次清理被误删。
    """

    def __init__(
        self,
        root: str | Path,
        *,
        retention_seconds: float,
        prefixes: tuple[str, ...] = DEFAULT_RENDERED_PREFIXES,
    ) -> None:
        if retention_seconds <= 0:
            raise ValueError("rendered 文件保留时间必须大于零")
        if not prefixes or any(not prefix for prefix in prefixes):
            raise ValueError("rendered 临时文件前缀不能为空")
        self.root = self._absolute(Path(root).expanduser())
        self.retention_seconds = float(retention_seconds)
        self.prefixes = tuple(dict.fromkeys(prefixes))
        self._leases: dict[Path, int] = {}
        self._lock = RLock()

    @staticmethod
    def _absolute(path: Path) -> Path:
        """规范化点段但不解析符号链接，保留后续链接边界检查。"""

        return Path(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _normalize_now(now: datetime | None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("rendered 清理时间必须带时区")
        return value.astimezone(timezone.utc)

    def _safe_path(self, path: str | Path) -> Path:
        candidate = self._absolute(Path(path).expanduser())
        if self.root.is_symlink() or not candidate.is_relative_to(self.root):
            raise ValueError("rendered 文件不在受控目录中")
        current = candidate
        while current != self.root:
            if current.is_symlink():
                raise ValueError("rendered 文件路径不能是符号链接")
            current = current.parent
        return candidate

    def register(self, path: str | Path) -> None:
        """登记一个正在交给 AstrBot 发送的临时文件。"""

        safe_path = self._safe_path(path)
        with self._lock:
            self._leases[safe_path] = self._leases.get(safe_path, 0) + 1

    def release(self, path: str | Path) -> None:
        """释放一次文件租约；不存在的登记按幂等操作处理。"""

        safe_path = self._safe_path(path)
        with self._lock:
            count = self._leases.get(safe_path, 0)
            if count <= 1:
                self._leases.pop(safe_path, None)
            else:
                self._leases[safe_path] = count - 1

    @property
    def active_lease_count(self) -> int:
        """返回当前进程中仍登记的文件租约数量。"""

        with self._lock:
            return sum(self._leases.values())

    def _is_managed_name(self, path: Path) -> bool:
        return any(path.name.startswith(prefix) for prefix in self.prefixes)

    def cleanup(self, *, now: datetime | None = None) -> RenderedCleanupReport:
        """清理超过保留期的孤儿文件，并跳过活动租约和不安全路径。"""

        normalized_now = self._normalize_now(now)
        with self._lock:
            if self.root.is_symlink() or not self.root.is_dir():
                return RenderedCleanupReport()
            removed = 0
            skipped_active = 0
            skipped_invalid = 0
            candidates = sorted(self.root.rglob("*"))
            seen: set[Path] = set()
            for path in candidates:
                if path in seen or not self._is_managed_name(path):
                    continue
                # 图片、sidecar 和 manifest 作为一个逻辑 pair 清理，避免半发布残留和重复计数。
                if path.name.endswith(".manifest.json"):
                    image_path = path.with_name(
                        path.name.removesuffix(".manifest.json")
                    )
                    if image_path.exists():
                        continue
                    sidecar = image_path.with_name(image_path.name + ".json")
                    pair = tuple(item for item in (path, sidecar) if item.exists())
                elif path.name.endswith(".json"):
                    image_path = path.with_name(path.name.removesuffix(".json"))
                    if (
                        image_path.exists()
                        or image_path.with_name(
                            image_path.name + ".manifest.json"
                        ).exists()
                    ):
                        continue
                    pair = (path,)
                else:
                    image_path = path
                    sidecar = path.with_name(path.name + ".json")
                    manifest = path.with_name(path.name + ".manifest.json")
                    pair = tuple(
                        item for item in (path, sidecar, manifest) if item.exists()
                    )
                seen.update(pair)
                if any(
                    item.is_symlink() or item.parent.is_symlink() or not item.is_file()
                    for item in pair
                ):
                    skipped_invalid += 1
                    continue
                try:
                    safe_pair = tuple(self._safe_path(item) for item in pair)
                    modified_at = max(
                        datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                        for item in safe_pair
                    )
                except (OSError, ValueError):
                    skipped_invalid += 1
                    continue
                age_seconds = max(0.0, (normalized_now - modified_at).total_seconds())
                if age_seconds < self.retention_seconds:
                    continue
                if any(self._leases.get(item, 0) > 0 for item in safe_pair):
                    skipped_active += 1
                    continue
                try:
                    for item in safe_pair:
                        item.unlink()
                except OSError:
                    skipped_invalid += 1
                else:
                    removed += 1
            self._leases = {
                path: count for path, count in self._leases.items() if path.exists()
            }
            return RenderedCleanupReport(
                removed=removed,
                skipped_active=skipped_active,
                skipped_invalid=skipped_invalid,
            )


__all__ = [
    "DEFAULT_RENDERED_PREFIXES",
    "DEFAULT_RENDERED_RETENTION_SECONDS",
    "RenderedCleanupReport",
    "RenderedFileStore",
]
