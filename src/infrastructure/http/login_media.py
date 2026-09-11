"""内置登录页媒体资源的安全解析与 generation lease 适配。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from ..resources.generation import (
    ResourceGenerationError,
    ResourceLease,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
)

LOGIN_MEDIA_VIDEO_PATH = "/dna/login/media/background.mp4"
LOGIN_MEDIA_VIDEO_ROUTE = f"/astrbot_plugin_dna{LOGIN_MEDIA_VIDEO_PATH}"

_VIDEO_RELATIVE_PATH = Path("videos/login/background.mp4")
_MEDIA_DEFINITIONS: dict[str, tuple[Path, str]] = {
    "video": (_VIDEO_RELATIVE_PATH, "video/mp4"),
}


@dataclass(frozen=True, slots=True)
class LoginMedia:
    """登录页可公开使用的媒体 URL；不包含资源 generation 的本地路径。"""

    video_url: str | None = None

    @property
    def is_empty(self) -> bool:
        """返回是否没有可用的完整媒体包。"""

        return self.video_url is None


class _LeasedFileResponse(web.FileResponse):
    """在 aiohttp 完成文件响应后释放资源 generation lease。"""

    def __init__(
        self,
        path: Path,
        lease: ResourceLease,
        *,
        content_type: str,
    ) -> None:
        super().__init__(path, headers={"Content-Type": content_type})
        self._lease = lease

    async def prepare(self, request: web.BaseRequest):
        try:
            # FileResponse.prepare 会完成 Range 处理及文件发送；返回后可以安全释放
            # generation，避免同步切换时删除仍在读取的文件。
            return await super().prepare(request)
        finally:
            self._lease.release()


class LoginMediaService:
    """解析登录媒体并提供固定路由所需的文件响应。"""

    def __init__(
        self,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
    ) -> None:
        self.resource_snapshots = resource_snapshots

    def resolve(self, base_url: str, *, enabled: bool) -> LoginMedia:
        """在资源快照有效时返回固定媒体 URL，否则返回完整静态回退。"""

        if not enabled or self.resource_snapshots is None:
            return LoginMedia()

        with self.resource_snapshots.optional_lease() as snapshot:
            if snapshot is None or self._media_paths(snapshot) is None:
                return LoginMedia()

        base = base_url.rstrip("/")
        return LoginMedia(
            video_url=f"{base}{LOGIN_MEDIA_VIDEO_PATH}",
        )

    def file_response(
        self,
        media_kind: str,
        *,
        enabled: bool = True,
    ) -> web.StreamResponse:
        """返回固定媒体文件响应；关闭动态背景时媒体路由不可用。"""

        if not enabled:
            return web.Response(status=404)

        definition = _MEDIA_DEFINITIONS.get(media_kind)
        if definition is None or self.resource_snapshots is None:
            return web.Response(status=404)

        try:
            lease = self.resource_snapshots.acquire()
        except ResourceGenerationError:
            return web.Response(status=404)

        snapshot = lease.snapshot
        paths = self._media_paths(snapshot)
        if paths is None:
            lease.release()
            return web.Response(status=404)

        _relative_path, content_type = definition
        path = paths[media_kind]
        return _LeasedFileResponse(path, lease, content_type=content_type)

    @staticmethod
    def _media_paths(snapshot: ResourceSnapshot) -> dict[str, Path] | None:
        """校验媒体存在、文件头合法且路径仍在 generation 根目录内。"""

        root = snapshot.root.resolve()
        paths: dict[str, Path] = {}
        for media_kind, (relative_path, _content_type) in _MEDIA_DEFINITIONS.items():
            candidate = (root / relative_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return None
            if not candidate.is_file() or not _valid_media_header(media_kind, candidate):
                return None
            paths[media_kind] = candidate
        return paths


def _valid_media_header(media_kind: str, path: Path) -> bool:
    """只读取固定大小的文件头，拒绝明显错误或截断的媒体文件。"""

    try:
        with path.open("rb") as file:
            prefix = file.read(32)
    except OSError:
        return False

    if media_kind == "video":
        # ISO BMFF/MP4 的 ftyp box 位于文件偏移 4，后面必须有主 brand。
        box_size = int.from_bytes(prefix[:4], "big") if len(prefix) >= 4 else 0
        brand = prefix[8:12]
        return (
            len(prefix) >= 12
            and 16 <= box_size
            and prefix[4:8] == b"ftyp"
            and len(brand) == 4
            and all(32 <= byte < 127 for byte in brand)
        )
    return False


__all__ = [
    "LOGIN_MEDIA_VIDEO_PATH",
    "LOGIN_MEDIA_VIDEO_ROUTE",
    "LoginMedia",
    "LoginMediaService",
]
