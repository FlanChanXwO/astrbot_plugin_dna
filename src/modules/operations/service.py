"""面板管理与资源状态 use case。"""

from __future__ import annotations

import base64
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ...entry.event import EventActor
from ...entry.response import ChainResponse, ImageResponse, PlainTextResponse
from ...infrastructure.resources import ResourceManifest, ResourceSnapshotCoordinator
from . import messages

ResolveCharId = Callable[[str], str | None]
PanelDirFor = Callable[[str], str]

_IMAGE_SUFFIXES = frozenset(Image.registered_extensions())


@dataclass(frozen=True, slots=True)
class PanelCommandRequest:
    """面板管理命令的框架无关输入。"""

    actor: EventActor
    parameters: dict[str, str]
    text: str = ""
    images: tuple[str, ...] = ()


class PanelService:
    """本地自定义面板图与公共资源状态的管理器。

    写操作（上传/删除/压缩）只操作运行期数据目录下的 ``panel_custom/``，不触碰插件
    源码、参考区或真实账户；测试使用隔离目录 fixture 验证。
    """

    def __init__(
        self,
        panel_root: str | Path,
        *,
        resource_root: str | Path,
        resolve_char_id: ResolveCharId,
        panel_dir_for: PanelDirFor,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
    ) -> None:
        self.panel_root = Path(panel_root)
        self.resource_root = Path(resource_root)
        self.resolve_char_id = resolve_char_id
        self.panel_dir_for = panel_dir_for
        self.resource_snapshots = resource_snapshots

    def _char_panel_dir(self, char_name: str) -> Path | None:
        """解析角色 canonical 名与 CharId，返回其面板目录（限定在 panel_root 内）。"""

        char_id = self.resolve_char_id(char_name)
        if char_id is None:
            return None
        root = self.panel_root.resolve()
        resolved = (self.panel_root / self.panel_dir_for(char_id)).resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            return None
        if not relative.parts:
            # 角色目录必须是 panel_root 下的子目录，不能把根目录当作某个角色目录。
            return None
        return resolved

    def resolve_panel_dir(self, char_name: str) -> Path | None:
        """返回角色面板目录；调用方只能获得受 ``panel_root`` 约束的路径。"""

        return self._char_panel_dir(char_name)

    def _panel_files(self, char_dir: Path) -> list[Path]:
        if not char_dir.is_dir():
            return []
        root = self.panel_root.resolve()
        files: list[Path] = []
        for path in char_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            try:
                path.resolve().relative_to(root)
            except ValueError:
                # 不读取通过符号链接逃出运行期面板目录的文件。
                continue
            files.append(path)
        return sorted(
            files,
        )

    def list_panel_files(self, char_name: str) -> tuple[Path, ...] | None:
        """列出角色面板文件；未知角色或越界目录返回 ``None``。"""

        char_dir = self._char_panel_dir(char_name)
        return None if char_dir is None else tuple(self._panel_files(char_dir))

    def find_panel_file(self, char_name: str, image_id: str) -> Path | None:
        """按稳定 ID 查找面板图，绝不按用户提供的路径直接拼接。"""

        for image_path in self.list_panel_files(char_name) or ():
            if image_path.stem == image_id or image_path.name == image_id:
                return image_path
        return None

    def save_panel_bytes(self, char_name: str, image_bytes: bytes) -> Path | None:
        """把已读取的图片字节保存到角色自定义目录并返回内部路径。"""

        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return None
        image_path = char_dir / f"{hashlib.sha1(image_bytes).hexdigest()[:16]}.webp"
        self._save_webp(image_bytes, image_path)
        return image_path

    def remove_panel_file(self, char_name: str, image_id: str) -> Path | None:
        """删除一张已解析的面板图，并在目录为空时移除角色目录。"""

        image_path = self.find_panel_file(char_name, image_id)
        if image_path is None:
            return None
        image_path.unlink()
        char_dir = image_path.parent
        if char_dir.is_dir() and not any(char_dir.iterdir()):
            char_dir.rmdir()
        return image_path

    def remove_all_panel_files(self, char_name: str) -> int | None:
        """删除角色目录下的全部面板图，返回删除数量。"""

        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return None
        panel_files = self._panel_files(char_dir)
        if panel_files:
            self._remove_panel_files(panel_files)
        return len(panel_files)

    @staticmethod
    def _remove_panel_files(panel_files: list[Path]) -> None:
        """只删除已识别的图片，保留角色目录中的其他运维文件。"""

        for image_path in panel_files:
            image_path.unlink()
        char_dir = panel_files[0].parent
        if char_dir.is_dir() and not any(char_dir.iterdir()):
            char_dir.rmdir()

    def compress_all_panel_files(self) -> tuple[int, int]:
        """压缩全部角色面板图并返回 ``(总数, 成功压缩数)``。"""

        from ...utils.image import compress_to_webp

        if not self.panel_root.is_dir():
            return 0, 0
        all_files: list[Path] = []
        for panel_dir in sorted(self.panel_root.iterdir()):
            if panel_dir.is_dir() and not panel_dir.is_symlink():
                all_files.extend(self._panel_files(panel_dir))
        compressed = 0
        for image_path in all_files:
            is_compressed, _ = compress_to_webp(image_path)
            if is_compressed:
                compressed += 1
        return len(all_files), compressed

    @staticmethod
    def _image_bytes(source: str) -> bytes:
        """把本地路径、base64 或 URL 载荷解析为图像字节；URL 离线不支持。"""

        if source.startswith("base64://"):
            return base64.b64decode(source[len("base64://") :])
        if source.startswith(("http://", "https://")):
            raise ValueError("离线环境不支持 URL 面板图")
        path = Path(source)
        if not path.is_file():
            raise ValueError("面板图文件不存在")
        return path.read_bytes()

    @staticmethod
    def _save_webp(image_bytes: bytes, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(image_bytes)) as image:
            mode = (
                "RGBA"
                if "A" in image.getbands() or "transparency" in image.info
                else "RGB"
            )
            image.convert(mode).save(target, "WEBP", quality=90, method=4)

    async def upload_panel_img(self, request: PanelCommandRequest):
        """保存命令附带的面板图到角色自定义面板目录。"""

        if not request.images:
            return PlainTextResponse(messages.PANEL_IMAGE_REQUIRED)
        char_name = request.parameters.get("char_name", "").strip()
        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return PlainTextResponse(
                messages.PANEL_CHAR_NOT_FOUND.format(name=char_name)
            )

        saved = 0
        failed = 0
        for source in request.images:
            try:
                image_bytes = self._image_bytes(source)
                self.save_panel_bytes(char_name, image_bytes)
                saved += 1
            except (OSError, ValueError, TypeError):
                failed += 1
        if saved == 0:
            return PlainTextResponse(messages.PANEL_UPLOAD_FAILED)
        text = messages.PANEL_UPLOADED.format(name=char_name, count=saved)
        if failed:
            text += f"，失败{failed}张"
        return PlainTextResponse(text)

    async def list_panel_imgs(self, request: PanelCommandRequest):
        """列出角色已上传的面板图。"""

        char_name = request.parameters.get("char_name", "").strip()
        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return PlainTextResponse(
                messages.PANEL_CHAR_NOT_FOUND.format(name=char_name)
            )
        panel_files = self._panel_files(char_dir)
        if not panel_files:
            return PlainTextResponse(messages.PANEL_EMPTY.format(name=char_name))
        components: list[PlainTextResponse | ImageResponse] = [
            PlainTextResponse(
                messages.PANEL_LIST_TITLE.format(name=char_name, count=len(panel_files))
            ),
        ]
        for image_path in panel_files:
            components.append(PlainTextResponse(f"\nID：{image_path.stem}\n"))
            components.append(ImageResponse(str(image_path)))
        return ChainResponse(tuple(components))

    async def delete_panel_img_by_id(self, request: PanelCommandRequest):
        """按 ID 删除一张角色面板图。"""

        char_name = request.parameters.get("char_name", "").strip()
        image_id = request.parameters.get("image_id", "").strip()
        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return PlainTextResponse(
                messages.PANEL_CHAR_NOT_FOUND.format(name=char_name)
            )
        for image_path in self._panel_files(char_dir):
            if image_path.stem != image_id and image_path.name != image_id:
                continue
            image_path.unlink(missing_ok=True)
            if not any(char_dir.iterdir()):
                char_dir.rmdir()
            return PlainTextResponse(
                messages.PANEL_DELETED.format(name=char_name, image_id=image_path.stem),
            )
        return PlainTextResponse(
            messages.PANEL_DELETED_NOT_FOUND.format(name=char_name, image_id=image_id)
        )

    async def delete_all_panel_imgs(self, request: PanelCommandRequest):
        """删除角色全部面板图。"""

        char_name = request.parameters.get("char_name", "").strip()
        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return PlainTextResponse(
                messages.PANEL_CHAR_NOT_FOUND.format(name=char_name)
            )
        panel_files = self._panel_files(char_dir)
        if not panel_files:
            return PlainTextResponse(
                messages.PANEL_DELETED_ALL_EMPTY.format(name=char_name)
            )
        self._remove_panel_files(panel_files)
        return PlainTextResponse(
            messages.PANEL_DELETED_ALL.format(name=char_name, count=len(panel_files)),
        )

    async def delete_original_panel_img(self, _request: PanelCommandRequest):
        """公开结果边界无原图引用缓存，显式报告不支持。"""

        return PlainTextResponse(messages.PANEL_ORIGINAL_UNSUPPORTED)

    async def compress_panel_imgs(self, _request: PanelCommandRequest):
        """压缩全部自定义面板图为 WebP。"""

        total, compressed = self.compress_all_panel_files()
        if not total:
            return PlainTextResponse(messages.PANEL_EMPTY.format(name="全部"))
        return PlainTextResponse(
            messages.PANEL_COMPRESS_DONE.format(
                total=total,
                compressed=compressed,
                skipped=total - compressed,
            ),
        )

    async def resource_status(self, _request: PanelCommandRequest):
        """展示公共资源仓库与本地面板数据的状态。"""

        if self.resource_snapshots is None:
            return self._resource_status_response(self.resource_root)
        with self.resource_snapshots.optional_lease() as snapshot:
            resource_root = snapshot.root if snapshot is not None else self.resource_root
            return self._resource_status_response(resource_root)

    def _resource_status_response(self, resource_root: Path) -> PlainTextResponse:
        """在调用方持有的 generation lease 内生成资源状态响应。"""

        lines = [messages.RESOURCE_STATUS_HEADER]
        lines.append(messages.resource_status_line("资源仓库目录", str(resource_root)))
        if resource_root.is_dir():
            manifest_path = resource_root / "resource_manifest.json"
            if manifest_path.is_file():
                try:
                    manifest = ResourceManifest.load(manifest_path)
                    lines.append(
                        messages.resource_status_line(
                            "manifest", f"v{manifest.format_version}"
                        )
                    )
                    lines.append(
                        messages.resource_status_line(
                            "资源版本", manifest.resource_version
                        )
                    )
                    present = [d for d in manifest.required_dirs if (resource_root / d).is_dir()]
                    lines.append(
                        messages.resource_status_line(
                            "必需目录",
                            f"{len(present)}/{len(manifest.required_dirs)} 存在",
                        ),
                    )
                except Exception:  # noqa: BLE001
                    lines.append(
                        messages.resource_status_line("manifest", "损坏或不可读")
                    )
            else:
                lines.append(messages.resource_status_line("manifest", "缺失"))
        else:
            lines.append(messages.RESOURCE_STATUS_EMPTY)
        lines.append(
            messages.resource_status_line("自定义面板目录", str(self.panel_root))
        )
        if self.panel_root.is_dir():
            total = sum(
                len(self._panel_files(d))
                for d in self.panel_root.iterdir()
                if d.is_dir()
            )
            lines.append(messages.resource_status_line("自定义面板数量", str(total)))
        return PlainTextResponse("\n".join(lines))


__all__ = ["PanelCommandRequest", "PanelService"]
