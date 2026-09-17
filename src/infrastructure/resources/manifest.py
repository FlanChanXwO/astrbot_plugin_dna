"""公共资源仓库 manifest 定义与目录校验。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ResourceManifestError(ValueError):
    """资源 manifest 不可读或不符合插件契约。"""


class ResourceManifest(BaseModel):
    """资源仓库根目录的 ``resource_manifest.json``。"""

    model_config = ConfigDict(extra="forbid")

    format_version: int = Field(description="manifest 格式版本。")
    required_dirs: tuple[str, ...] = Field(
        description="资源仓库必须存在的相对目录。",
    )
    required_files: tuple[str, ...] = Field(
        default=(),
        description="缺失时必须阻断资源 generation 发布的相对文件路径。",
    )
    resource_version: str = Field(description="资源内容版本。")
    file_hashes: dict[str, str] = Field(
        default_factory=dict,
        description="可选的相对文件路径到 SHA-256 摘要映射。",
    )

    @field_validator("format_version")
    @classmethod
    def _check_format_version(cls, value: int) -> int:
        # v1 保留用于滚动升级；v2 将“文件必要性”从 file_hashes 中显式拆出。
        if value not in {1, 2}:
            raise ValueError("仅支持 resource_manifest.json format_version=1 或 2")
        return value

    @field_validator("required_dirs")
    @classmethod
    def _check_required_dirs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("required_dirs 不能为空")
        if len(set(value)) != len(value):
            raise ValueError("required_dirs 不能包含重复目录")
        for relative in value:
            path = Path(relative)
            if (
                not relative
                or relative in {".", ".."}
                or path.is_absolute()
                or "\\" in relative
                or ".." in path.parts
            ):
                raise ValueError(f"required_dirs 含有不安全路径: {relative!r}")
        return value

    @field_validator("required_files")
    @classmethod
    def _check_required_files(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("required_files 不能包含重复文件")
        for relative in value:
            parts = relative.split("/")
            if (
                not relative
                or Path(relative).is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ValueError(f"required_files 含有不安全路径: {relative!r}")
        return value

    @field_validator("resource_version")
    @classmethod
    def _check_resource_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resource_version 不能为空")
        return value

    @field_validator("file_hashes")
    @classmethod
    def _check_file_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        for relative, digest in value.items():
            parts = relative.split("/")
            if (
                not relative
                or Path(relative).is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ValueError(f"file_hashes 含有不安全路径: {relative!r}")
            if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
                raise ValueError(f"file_hashes 摘要不是 SHA-256: {relative!r}")
        return value

    @classmethod
    def load(cls, path: str | Path) -> ResourceManifest:
        """读取并解析 manifest；任何失败都向调用方显露。"""

        manifest_path = Path(path)
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResourceManifestError(
                f"无法读取资源 manifest: {manifest_path}"
            ) from exc
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise ResourceManifestError(
                f"资源 manifest 校验失败: {manifest_path}: {exc}"
            ) from exc

    def validate_root(self, root: str | Path) -> ResourceManifest:
        """确认 manifest 声明的目录存在且没有逃逸出仓库根目录。"""

        root_path = Path(root).resolve()
        for relative in self.required_dirs:
            resource_path = (root_path / relative).resolve()
            try:
                resource_path.relative_to(root_path)
            except ValueError as exc:
                raise ResourceManifestError(
                    f"资源目录逃逸出仓库根目录: {relative!r}"
                ) from exc
            if not resource_path.is_dir():
                raise ResourceManifestError(
                    f"资源 manifest 要求的目录不存在: {relative!r}"
                )
        for relative in self.required_files:
            resource_path = root_path.joinpath(*relative.split("/"))
            if resource_path.is_symlink() or not resource_path.is_file():
                raise ResourceManifestError(
                    f"资源 manifest 必须文件不存在: {relative!r}"
                )
        return self

    def validate_file_hashes(self, root: str | Path) -> ResourceManifest:
        """校验 manifest 声明文件的完整性。

        v1 中 ``file_hashes`` 同时承担存在性与完整性约束。v2 起存在性只由
        ``required_files`` 决定，因此缺失的可选文件不会阻断 generation 发布。
        """

        root_path = Path(root).resolve()
        for relative, expected in self.file_hashes.items():
            resource_path = root_path.joinpath(*relative.split("/"))
            if resource_path.is_symlink():
                raise ResourceManifestError(
                    f"资源 manifest 文件哈希目标不允许符号链接: {relative!r}"
                )
            if not resource_path.is_file():
                if self.format_version == 1:
                    raise ResourceManifestError(
                        f"资源 manifest 文件哈希目标不存在: {relative!r}"
                    )
                continue
            digest = hashlib.sha256()
            with resource_path.open("rb") as file:
                while chunk := file.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest().casefold() != expected.casefold():
                raise ResourceManifestError(
                    f"资源 manifest 文件哈希不匹配: {relative!r}"
                )
        return self

__all__ = [
    "ResourceManifest",
    "ResourceManifestError",
]
