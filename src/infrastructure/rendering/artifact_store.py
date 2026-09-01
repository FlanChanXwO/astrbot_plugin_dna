"""RenderedArtifact 的受控文件与 sidecar 存储。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

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
    if (
        not prefix
        or Path(prefix).name != prefix
        or any(char in prefix for char in "/\\")
    ):
        raise ValueError("渲染文件前缀不安全")
    return prefix


def _sidecar_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + ".json")


def _manifest_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + ".manifest.json")


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


def _manifest_payload(
    image_path: Path, sidecar_path: Path, sidecar_data: bytes
) -> bytes:
    return json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "image": image_path.name,
            "sidecar": sidecar_path.name,
            "sidecar_sha256": hashlib.sha256(sidecar_data).hexdigest(),
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
) -> ImageResponse:
    from ...entry.response import ImageResponse

    """在受控目录原子发布图片及配对 sidecar。"""

    directory = _safe_root(root)
    normalized_prefix = _safe_prefix(prefix)
    image_path: Path | None = None
    sidecar_path: Path | None = None
    manifest_path: Path | None = None
    image_tmp: Path | None = None
    sidecar_tmp: Path | None = None
    manifest_tmp: Path | None = None
    try:
        image_path = directory / f"{normalized_prefix}{uuid4().hex}{artifact.suffix}"
        sidecar_path = _sidecar_path(image_path)
        manifest_path = _manifest_path(image_path)
        image_tmp = _write_temp(
            directory, normalized_prefix, artifact.suffix, artifact.data
        )
        sidecar_data = _sidecar_payload(artifact)
        sidecar_tmp = _write_temp(directory, normalized_prefix, ".json", sidecar_data)
        manifest_tmp = _write_temp(
            directory,
            normalized_prefix,
            ".manifest.json",
            _manifest_payload(image_path, sidecar_path, sidecar_data),
        )
        image_tmp.replace(image_path)
        sidecar_tmp.replace(sidecar_path)
        # manifest 最后发布：读者只有看到 manifest 才会把这对文件视为可用。
        manifest_tmp.replace(manifest_path)
        return ImageResponse(
            str(image_path),
            temporary=True,
            sidecar=str(sidecar_path),
            manifest=str(manifest_path),
        )
    except Exception:
        for path in (
            image_tmp,
            sidecar_tmp,
            manifest_tmp,
            image_path,
            sidecar_path,
            manifest_path,
        ):
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
    manifest_path = _manifest_path(image_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("图片发布清单不可读取") from error
    try:
        sidecar_data = sidecar_path.read_bytes()
        raw = json.loads(sidecar_data.decode("utf-8"))
        data = image_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("图片 sidecar 不可读取") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != _SCHEMA_VERSION
        or manifest.get("image") != image_path.name
        or manifest.get("sidecar") != sidecar_path.name
    ):
        raise ValueError("图片发布清单无效")
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
    if (
        raw.get("suffix") != artifact.suffix
        or raw.get("width") != artifact.width
        or raw.get("height") != artifact.height
    ):
        raise ValueError("图片 sidecar 尺寸或后缀不匹配")
    if raw.get("sha256") != artifact.sha256:
        raise ValueError("图片 sidecar SHA256 不匹配")
    if manifest.get("sidecar_sha256") != hashlib.sha256(sidecar_data).hexdigest():
        raise ValueError("图片 sidecar SHA256 与发布清单不匹配")
    return artifact


def export_rendered_artifact(
    image: str | Path,
    destination_stem: str | Path,
) -> ImageResponse:
    """把已发布 artifact 复制为确定性文件名，并重建有效配对清单。"""

    from ...entry.response import ImageResponse

    artifact = read_rendered_artifact(image)
    stem = Path(destination_stem).expanduser().absolute()
    if stem.suffix:
        raise ValueError("artifact 导出目标必须是不含扩展名的文件 stem")
    directory = _safe_root(stem.parent)
    if stem.parent != directory or stem.name in {"", ".", ".."}:
        raise ValueError("artifact 导出目标不安全")
    image_path = stem.with_suffix(artifact.suffix)
    sidecar_path = _sidecar_path(image_path)
    manifest_path = _manifest_path(image_path)
    image_tmp: Path | None = None
    sidecar_tmp: Path | None = None
    manifest_tmp: Path | None = None
    try:
        image_tmp = _write_temp(
            directory, f"{stem.name}-", artifact.suffix, artifact.data
        )
        sidecar_data = _sidecar_payload(artifact)
        sidecar_tmp = _write_temp(directory, f"{stem.name}-", ".json", sidecar_data)
        manifest_tmp = _write_temp(
            directory,
            f"{stem.name}-",
            ".manifest.json",
            _manifest_payload(image_path, sidecar_path, sidecar_data),
        )
        image_tmp.replace(image_path)
        sidecar_tmp.replace(sidecar_path)
        manifest_tmp.replace(manifest_path)
    except Exception:
        for path in (image_tmp, sidecar_tmp, manifest_tmp):
            if path is not None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise
    return ImageResponse(
        str(image_path),
        temporary=False,
        sidecar=str(sidecar_path),
        manifest=str(manifest_path),
    )


def artifact_validator(media_type: str):
    """返回可直接交给 ``CacheManager`` 的图片完整性 validator。"""

    def validate(data: bytes) -> bool:
        RenderedArtifact.from_bytes(data, media_type=media_type)  # type: ignore[arg-type]
        return True

    return validate


__all__ = [
    "artifact_validator",
    "export_rendered_artifact",
    "read_rendered_artifact",
    "write_rendered_artifact",
]
