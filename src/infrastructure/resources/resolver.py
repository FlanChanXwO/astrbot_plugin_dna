"""运行期资源的只读解析边界。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, TypeAlias

AssetSource: TypeAlias = Literal[
    "verified_snapshot",
    "bootstrap",
    "placeholder",
    "none",
]
AssetStatus: TypeAlias = Literal[
    "provided",
    "fallback",
    "placeholder",
    "missing",
]

# 只有明确登记为完整保留的 bootstrap 资源才能不标记为不完整。
_BOOTSTRAP_COMPLETE_KEYS = frozenset({"font.help"})


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """一个逻辑资源 key 的解析结果。"""

    path: Path | None
    source: AssetSource
    status: AssetStatus
    incomplete: bool


class RuntimeAssetResolver:
    """按 verified snapshot、bootstrap allowlist 的固定优先级解析资源。

    解析器只消费调用方显式提供的映射，不扫描目录、不读取 Git checkout 或
    candidate，也不执行下载。snapshot 的实际文件读取应由调用方放在对应 lease 内。
    """

    def __init__(
        self,
        *,
        snapshot_root: Path | None,
        snapshot_assets: Mapping[str, str],
        bootstrap_allowlist: Mapping[str, Path],
    ) -> None:
        self._snapshot_root = (
            None
            if snapshot_root is None
            else Path(snapshot_root).expanduser().absolute()
        )
        self._snapshot_assets = {
            self._validate_logical_key(logical_key): self._validate_snapshot_path(
                relative_path,
            )
            for logical_key, relative_path in snapshot_assets.items()
        }
        self._bootstrap_allowlist = {
            self._validate_logical_key(logical_key): Path(path).expanduser().absolute()
            for logical_key, path in bootstrap_allowlist.items()
        }

    @staticmethod
    def _validate_logical_key(logical_key: str) -> str:
        if not isinstance(logical_key, str) or not logical_key.strip():
            raise ValueError("资源 logical key 必须是非空字符串")
        return logical_key

    @staticmethod
    def _validate_snapshot_path(relative_path: str) -> str:
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError("snapshot 资源路径必须是非空字符串")
        if "\\" in relative_path:
            raise ValueError("snapshot 资源路径必须使用 POSIX 分隔符")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("snapshot 资源路径必须是 generation 内相对路径")
        return path.as_posix()

    @staticmethod
    def _verified_file(root: Path, relative_path: str) -> Path | None:
        """返回 root 内的普通文件；符号链接和越界路径均不接受。"""

        if root.is_symlink() or not root.is_dir():
            return None
        candidate = root / relative_path
        if candidate.is_symlink() or not candidate.is_file():
            return None
        try:
            resolved_root = root.resolve(strict=True)
            resolved_candidate = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if not resolved_candidate.is_relative_to(resolved_root):
            return None
        return candidate

    @staticmethod
    def _bootstrap_file(path: Path) -> Path | None:
        """返回 allowlist 中的普通文件，不对目录做递归发现。"""

        if path.is_symlink() or not path.is_file():
            return None
        try:
            path.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        return path

    def resolve(self, logical_key: str) -> ResolvedAsset:
        """解析一个逻辑资源 key，不命中时返回显式 missing 状态。"""

        logical_key = self._validate_logical_key(logical_key)
        relative_path = self._snapshot_assets.get(logical_key)
        if self._snapshot_root is not None and relative_path is not None:
            snapshot_path = self._verified_file(self._snapshot_root, relative_path)
            if snapshot_path is not None:
                return ResolvedAsset(
                    path=snapshot_path,
                    source="verified_snapshot",
                    status="provided",
                    incomplete=False,
                )

        bootstrap_path = self._bootstrap_allowlist.get(logical_key)
        if bootstrap_path is not None:
            resolved_path = self._bootstrap_file(bootstrap_path)
            if resolved_path is not None:
                return ResolvedAsset(
                    path=resolved_path,
                    source="bootstrap",
                    status="fallback",
                    incomplete=logical_key not in _BOOTSTRAP_COMPLETE_KEYS,
                )

        return ResolvedAsset(
            path=None,
            source="none",
            status="missing",
            incomplete=True,
        )


__all__ = ["ResolvedAsset", "RuntimeAssetResolver"]
