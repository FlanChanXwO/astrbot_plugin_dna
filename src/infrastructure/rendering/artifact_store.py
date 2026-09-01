"""RenderedArtifact 的受控文件与 sidecar 存储。"""

from __future__ import annotations

import json
import os
import tempfile
from uuid import uuid4
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...entry.response import ImageResponse
from .artifact import RenderedArtifact

_SCHEMA_VERSION = 1


def _safe_root(root: str | Path) -> Path:
    path = Path(root).expanduser().absolute()
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("渲染目录路径不安全")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("渲染目录路径不安全")
    return path


def _safe_prefix(prefix: str) -> str:
    if not prefix or Path(prefix).name != prefix or any(char in prefix for char in "/\\"):
        raise ValueError("渲染文件前缀不安全")
    return prefix


def _sidecar_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + ".json")


def _sidecar_payload(artifact: RenderedArtifact) -> bytes:
    return json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "media_type": artifact.media_type,
            "suffix": artifact.suffix,
            "width": artifact.width,
            "height": artifact.height,
            "sha256": artifact.sha256,
            "metadata": dict(artifact.metadata),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


def _write_temp(root: Path, prefix: str, suffix: str, data: bytes) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=f".{prefix}", suffix=f"{suffix}.tmp", dir=root, delete=False
    ) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def write_rendered_artifact(
    root: str | Path,
    artifact: RenderedArtifact,
    *,
    prefix: str,
) -> "ImageResponse":
    from ...entry.response import ImageResponse
    """在受控目录原子发布图片及配对 sidecar。"""

    directory = _safe_root(root)
    normalized_prefix = _safe_prefix(prefix)
    image_path: Path | None = None
    sidecar_path: Path | None = None
    image_tmp: Path | None = None
    sidecar_tmp: Path | None = None
    try:
        image_path = directory / f"{normalized_prefix}{uuid4().hex}{artifact.suffix}"
        sidecar_path = _sidecar_path(image_path)
        image_tmp = _write_temp(directory, normalized_prefix, artifact.suffix, artifact.data)
        sidecar_tmp = _write_temp(directory, normalized_prefix, ".json", _sidecar_payload(artifact))
        image_tmp.replace(image_path)
        sidecar_tmp.replace(sidecar_path)
        return ImageResponse(
            str(image_path),
            temporary=True,
            sidecar=str(sidecar_path),
        )
    except Exception:
        for path in (image_tmp, sidecar_tmp, image_path, sidecar_path):
            if path is not None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise


def read_rendered_artifact(image: str | Path) -> RenderedArtifact:
    """读取并校验图片与 sidecar；任一不匹配都拒绝使用。"""

    image_path = Path(image).expanduser().absolute()
    sidecar_path = _sidecar_path(image_path)
    try:
        raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
        data = image_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("图片 sidecar 不可读取") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("图片 sidecar schema 无效")
    media_type = raw.get("media_type")
    if media_type not in ("image/jpeg", "image/png"):
        raise ValueError("图片 sidecar media_type 无效")
    artifact = RenderedArtifact.from_bytes(
        data,
        media_type=media_type,  # type: ignore[arg-type]
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )
    if raw.get("suffix") != artifact.suffix or raw.get("width") != artifact.width or raw.get("height") != artifact.height:
        raise ValueError("图片 sidecar 尺寸或后缀不匹配")
    if raw.get("sha256") != artifact.sha256:
        raise ValueError("图片 sidecar SHA256 不匹配")
    return artifact


def artifact_validator(media_type: str):
    """返回可直接交给 ``CacheManager`` 的图片完整性 validator。"""

    def validate(data: bytes) -> bool:
        RenderedArtifact.from_bytes(data, media_type=media_type)  # type: ignore[arg-type]
        return True

    return validate


__all__ = ["artifact_validator", "read_rendered_artifact", "write_rendered_artifact"]
