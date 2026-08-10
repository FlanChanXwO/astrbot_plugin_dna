"""私有资源仓库 manifest 定义与目录校验。"""

from __future__ import annotations

import json
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
    resource_version: str = Field(description="资源内容版本。")

    @field_validator("format_version")
    @classmethod
    def _check_format_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("仅支持 resource_manifest.json format_version=1")
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

    @field_validator("resource_version")
    @classmethod
    def _check_resource_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resource_version 不能为空")
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
        return self


__all__ = ["ResourceManifest", "ResourceManifestError"]

