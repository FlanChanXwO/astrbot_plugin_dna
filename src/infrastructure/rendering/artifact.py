"""T2I 原始图片 bytes 的结构化值对象。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Literal

from .image_inspector import MediaType, inspect_image

JSONValue = Any


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    """经过容器校验、但未被 Pillow 重编码的图片 artifact。"""

    data: bytes
    media_type: MediaType
    suffix: Literal[".jpg", ".png"]
    width: int
    height: int
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        """返回原始图片 bytes 的 SHA256，用于 sidecar 配对校验。"""

        return hashlib.sha256(self.data).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: MediaType,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> "RenderedArtifact":
        inspected = inspect_image(data, media_type=media_type)
        return cls(
            data=data,
            media_type=inspected.media_type,
            suffix=inspected.suffix,
            width=inspected.width,
            height=inspected.height,
            metadata={} if metadata is None else dict(metadata),
        )


__all__ = ["RenderedArtifact"]
