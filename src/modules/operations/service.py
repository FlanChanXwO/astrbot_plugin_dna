"""面板管理与资源状态 use case。"""

from __future__ import annotations

import base64
import hashlib
import io
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ...entry.event import EventActor
from ...entry.response import ChainResponse, ImageResponse, PlainTextResponse
from ...infrastructure.resources import ResourceManifest
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
    """本地自定义面板图与私有资源状态的管理器。

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
    ) -> None:
        self.panel_root = Path(panel_root)
        self.resource_root = Path(resource_root)
        self.resolve_char_id = resolve_char_id
        self.panel_dir_for = panel_dir_for

    def _char_panel_dir(self, char_name: str) -> Path | None:
        """解析角色 canonical 名与 CharId，返回其面板目录。"""

        char_id = self.resolve_char_id(char_name)
        if char_id is None:
            return None
        return self.panel_root / self.panel_dir_for(char_id)

    def _panel_files(self, char_dir: Path) -> list[Path]:
        if not char_dir.is_dir():
            return []
        return sorted(
            path
            for path in char_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
        )

    @staticmethod
    def _image_bytes(source: str) -> bytes:
        """把本地路径、base64 或 URL 载荷解析为图像字节；URL 离线不支持。"""

        if source.startswith("base64://"):
            return base64.b64decode(source[len("base64://") :])
        if source.startswith("http://") or source.startswith("https://"):
            raise ValueError("离线环境不支持 URL 面板图")
        path = Path(source)
        if not path.is_file():
            raise ValueError("面板图文件不存在")
        return path.read_bytes()

    @staticmethod
    def _save_webp(image_bytes: bytes, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(image_bytes)) as image:
            mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            image.convert(mode).save(target, "WEBP", quality=90, method=4)

    async def upload_panel_img(self, request: PanelCommandRequest):
        """保存命令附带的面板图到角色自定义面板目录。"""

        if not request.images:
            return PlainTextResponse(messages.PANEL_IMAGE_REQUIRED)
        char_name = request.parameters.get("char_name", "").strip()
        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return PlainTextResponse(messages.PANEL_CHAR_NOT_FOUND.format(name=char_name))

        saved = 0
        failed = 0
        for source in request.images:
            try:
                image_bytes = self._image_bytes(source)
                image_path = char_dir / f"{hashlib.sha1(image_bytes).hexdigest()[:16]}.webp"
                self._save_webp(image_bytes, image_path)
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
            return PlainTextResponse(messages.PANEL_CHAR_NOT_FOUND.format(name=char_name))
        panel_files = self._panel_files(char_dir)
        if not panel_files:
            return PlainTextResponse(messages.PANEL_EMPTY.format(name=char_name))
        components: list[PlainTextResponse | ImageResponse] = [
            PlainTextResponse(messages.PANEL_LIST_TITLE.format(name=char_name, count=len(panel_files))),
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
            return PlainTextResponse(messages.PANEL_CHAR_NOT_FOUND.format(name=char_name))
        for image_path in self._panel_files(char_dir):
            if image_path.stem != image_id and image_path.name != image_id:
                continue
            image_path.unlink(missing_ok=True)
            if not any(char_dir.iterdir()):
                char_dir.rmdir()
            return PlainTextResponse(
                messages.PANEL_DELETED.format(name=char_name, image_id=image_path.stem),
            )
        return PlainTextResponse(messages.PANEL_DELETED_NOT_FOUND.format(name=char_name, image_id=image_id))

    async def delete_all_panel_imgs(self, request: PanelCommandRequest):
        """删除角色全部面板图。"""

        char_name = request.parameters.get("char_name", "").strip()
        char_dir = self._char_panel_dir(char_name)
        if char_dir is None:
            return PlainTextResponse(messages.PANEL_CHAR_NOT_FOUND.format(name=char_name))
        panel_files = self._panel_files(char_dir)
        if not panel_files:
            return PlainTextResponse(messages.PANEL_DELETED_ALL_EMPTY.format(name=char_name))
        shutil.rmtree(char_dir)
        return PlainTextResponse(
            messages.PANEL_DELETED_ALL.format(name=char_name, count=len(panel_files)),
        )

    async def delete_original_panel_img(self, _request: PanelCommandRequest):
        """公开结果边界无原图引用缓存，显式报告不支持。"""

        return PlainTextResponse(messages.PANEL_ORIGINAL_UNSUPPORTED)

    async def compress_panel_imgs(self, _request: PanelCommandRequest):
        """压缩全部自定义面板图为 WebP。"""

        from dnaby.utils.image import compress_to_webp

        if not self.panel_root.is_dir():
            return PlainTextResponse(messages.PANEL_EMPTY.format(name="全部"))
        all_files = []
        for panel_dir in sorted(self.panel_root.iterdir()):
            if panel_dir.is_dir():
                all_files.extend(self._panel_files(panel_dir))
        if not all_files:
            return PlainTextResponse(messages.PANEL_EMPTY.format(name="全部"))
        compressed = 0
        for image_path in all_files:
            is_compressed, _ = compress_to_webp(image_path)
            if is_compressed:
                compressed += 1
        return PlainTextResponse(
            messages.PANEL_COMPRESS_DONE.format(
                total=len(all_files),
                compressed=compressed,
                skipped=len(all_files) - compressed,
            ),
        )

    async def resource_status(self, _request: PanelCommandRequest):
        """展示私有资源仓库与本地面板数据的状态。"""

        lines = [messages.RESOURCE_STATUS_HEADER]
        lines.append(messages.resource_status_line("资源仓库目录", str(self.resource_root)))
        if self.resource_root.is_dir():
            manifest_path = self.resource_root / "resource_manifest.json"
            if manifest_path.is_file():
                try:
                    manifest = ResourceManifest.load(manifest_path)
                    lines.append(
                        messages.resource_status_line("manifest", f"v{manifest.format_version}")
                    )
                    lines.append(
                        messages.resource_status_line("资源版本", manifest.resource_version)
                    )
                    present = [d for d in manifest.required_dirs if (self.resource_root / d).is_dir()]
                    lines.append(
                        messages.resource_status_line(
                            "必需目录",
                            f"{len(present)}/{len(manifest.required_dirs)} 存在",
                        ),
                    )
                except Exception:  # noqa: BLE001
                    lines.append(messages.resource_status_line("manifest", "损坏或不可读"))
            else:
                lines.append(messages.resource_status_line("manifest", "缺失"))
        else:
            lines.append(messages.RESOURCE_STATUS_EMPTY)
        lines.append(messages.resource_status_line("自定义面板目录", str(self.panel_root)))
        if self.panel_root.is_dir():
            total = sum(len(self._panel_files(d)) for d in self.panel_root.iterdir() if d.is_dir())
            lines.append(messages.resource_status_line("自定义面板数量", str(total)))
        return PlainTextResponse("\n".join(lines))


__all__ = ["PanelCommandRequest", "PanelService"]
