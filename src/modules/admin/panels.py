"""面板图管理的框架无关 Admin API 适配器。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import UnidentifiedImageError

from ..operations.service import PanelService
from .contracts import AdminApiResponse, AdminError, AdminErrorCode


def _failure(code: AdminErrorCode, message: str) -> AdminApiResponse[Any]:
    """建立不暴露本地路径或底层异常的管理失败响应。"""

    return AdminApiResponse.failure(AdminError(code, message))


def _role_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _image_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or ".." in normalized
    ):
        return None
    return normalized


@dataclass(frozen=True, slots=True)
class PanelImageMetadata:
    """管理页可展示的面板图元数据；不携带服务器绝对路径。"""

    role_name: str
    char_id: str
    image_id: str
    filename: str
    size: int
    media_type: str

    @property
    def id(self) -> str:
        """稳定的面板图标识。"""

        return self.image_id

    @property
    def role(self) -> str:
        """角色名的 API 友好别名。"""

        return self.role_name

    @property
    def content_type(self) -> str:
        """HTTP 内容类型别名。"""

        return self.media_type

    def to_dict(self) -> dict[str, object]:
        """导出不包含本地文件路径的 JSON 视图。"""

        return {
            "role_name": self.role_name,
            "char_id": self.char_id,
            "id": self.image_id,
            "filename": self.filename,
            "size": self.size,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class PanelImage:
    """按需读取的图片载荷。"""

    metadata: PanelImageMetadata
    data: bytes
    media_type: str

    @property
    def content(self) -> bytes:
        """图片字节的语义别名。"""

        return self.data

    @property
    def payload(self) -> bytes:
        """图片字节的 API 友好别名。"""

        return self.data

    @property
    def image_id(self) -> str:
        """返回关联元数据的稳定 ID。"""

        return self.metadata.image_id

    def to_dict(self) -> dict[str, object]:
        """导出 JSON 兼容载荷，避免把绝对路径放进响应。"""

        return {
            "metadata": self.metadata.to_dict(),
            "data": base64.b64encode(self.data).decode("ascii"),
            "media_type": self.media_type,
        }

    def __repr__(self) -> str:
        """诊断表示只显示大小，不展开图片内容。"""

        return (
            "PanelImage("
            f"metadata={self.metadata!r}, byte_length={len(self.data)}, "
            f"media_type={self.media_type!r})"
        )


@dataclass(frozen=True, slots=True)
class PanelDeletionResult:
    """面板图删除结果。"""

    role_name: str
    image_id: str | None
    count: int

    @property
    def deleted_count(self) -> int:
        """删除数量别名。"""

        return self.count

    def to_dict(self) -> dict[str, object]:
        return {
            "role_name": self.role_name,
            "image_id": self.image_id,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class PanelCompressionResult:
    """全量面板图压缩结果。"""

    total: int
    compressed: int
    skipped: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "compressed": self.compressed,
            "skipped": self.skipped,
        }


def _media_type(path: Path) -> str:
    return {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")


class AdminPanelService:
    """把安全的 ``PanelService`` 存储操作映射为 Admin response。"""

    def __init__(self, panel_service: PanelService) -> None:
        self.panel_service = panel_service

    def _metadata(self, role_name: str, path: Path) -> PanelImageMetadata:
        char_id = self.panel_service.resolve_char_id(role_name)
        if char_id is None:
            raise ValueError("角色不存在")
        return PanelImageMetadata(
            role_name=role_name,
            char_id=str(char_id),
            image_id=path.stem,
            filename=path.name,
            size=path.stat().st_size,
            media_type=_media_type(path),
        )

    async def list_panel_images(
        self,
        role_name: str,
    ) -> AdminApiResponse[tuple[PanelImageMetadata, ...]]:
        """列出角色面板图元数据。"""

        normalized = _role_name(role_name)
        if normalized is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称不能为空")
        try:
            paths = self.panel_service.list_panel_files(normalized)
            if paths is None:
                return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
            return AdminApiResponse.success(
                tuple(self._metadata(normalized, path) for path in paths),
            )
        except (OSError, ValueError):
            return _failure(AdminErrorCode.INTERNAL, "读取面板图元数据失败")

    async def get_panel_image(
        self,
        role_name: str,
        image_id: str,
    ) -> AdminApiResponse[PanelImage]:
        """按需读取图片字节，不向响应暴露本地路径。"""

        normalized_role = _role_name(role_name)
        normalized_id = _image_id(image_id)
        if normalized_role is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称不能为空")
        if normalized_id is None:
            return _failure(AdminErrorCode.VALIDATION, "面板图 ID 无效")
        try:
            paths = self.panel_service.list_panel_files(normalized_role)
            if paths is None:
                return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
            path = self.panel_service.find_panel_file(normalized_role, normalized_id)
            if path is None:
                return _failure(AdminErrorCode.NOT_FOUND, "面板图不存在")
            metadata = self._metadata(normalized_role, path)
            return AdminApiResponse.success(
                PanelImage(
                    metadata=metadata,
                    data=path.read_bytes(),
                    media_type=metadata.media_type,
                ),
            )
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "读取面板图失败")

    async def upload_panel_image(
        self,
        role_name: str,
        image: bytes | bytearray | memoryview,
    ) -> AdminApiResponse[PanelImageMetadata]:
        """上传一张图片并返回新文件元数据。"""

        normalized = _role_name(role_name)
        if normalized is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称不能为空")
        if not isinstance(image, bytes | bytearray | memoryview) or not image:
            return _failure(AdminErrorCode.VALIDATION, "图片内容不能为空")
        try:
            path = self.panel_service.save_panel_bytes(normalized, bytes(image))
            if path is None:
                return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
            return AdminApiResponse.success(self._metadata(normalized, path))
        except UnidentifiedImageError:
            return _failure(AdminErrorCode.VALIDATION, "图片内容无效")
        except ValueError:
            return _failure(AdminErrorCode.VALIDATION, "图片内容无效")
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "保存面板图失败")

    async def delete_panel_image(
        self,
        role_name: str,
        image_id: str,
    ) -> AdminApiResponse[PanelDeletionResult]:
        """删除角色的一张自定义面板图。"""

        normalized_role = _role_name(role_name)
        normalized_id = _image_id(image_id)
        if normalized_role is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称不能为空")
        if normalized_id is None:
            return _failure(AdminErrorCode.VALIDATION, "面板图 ID 无效")
        if self.panel_service.resolve_panel_dir(normalized_role) is None:
            return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
        if self.panel_service.find_panel_file(normalized_role, normalized_id) is None:
            return _failure(AdminErrorCode.NOT_FOUND, "面板图不存在")
        try:
            deleted = self.panel_service.remove_panel_file(
                normalized_role, normalized_id
            )
            if deleted is None:
                return _failure(AdminErrorCode.NOT_FOUND, "面板图不存在")
            return AdminApiResponse.success(
                PanelDeletionResult(normalized_role, deleted.stem, 1),
            )
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "删除面板图失败")

    async def delete_all_panel_images(
        self,
        role_name: str,
        *,
        confirmed: bool = False,
    ) -> AdminApiResponse[PanelDeletionResult]:
        """删除角色全部面板图；管理端必须显式传入二次确认。"""

        normalized = _role_name(role_name)
        if normalized is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称不能为空")
        if confirmed is not True:
            return _failure(AdminErrorCode.VALIDATION, "删除全部面板图需要二次确认")
        if self.panel_service.resolve_panel_dir(normalized) is None:
            return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
        try:
            count = self.panel_service.remove_all_panel_files(normalized)
            if count is None:
                return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
            return AdminApiResponse.success(
                PanelDeletionResult(normalized, None, count)
            )
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "删除角色面板图失败")

    async def compress_panel_images(self) -> AdminApiResponse[PanelCompressionResult]:
        """压缩全部角色面板图。"""

        try:
            total, compressed = self.panel_service.compress_all_panel_files()
            return AdminApiResponse.success(
                PanelCompressionResult(total, compressed, total - compressed),
            )
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "压缩面板图失败")

    # 以下别名保持 adapter 命名可读，同时不增加另一套业务实现。
    list_images = list_panel_images
    get_image = get_panel_image
    upload = upload_panel_image
    delete_image = delete_panel_image
    delete_all = delete_all_panel_images
    compress = compress_panel_images


PanelAdminService = AdminPanelService
PanelImagePayload = PanelImage
PanelImageInfo = PanelImageMetadata


__all__ = [
    "AdminPanelService",
    "PanelAdminService",
    "PanelCompressionResult",
    "PanelDeletionResult",
    "PanelImage",
    "PanelImageInfo",
    "PanelImageMetadata",
    "PanelImagePayload",
]
