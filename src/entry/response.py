"""框架无关响应 DTO 到 AstrBot 原生结果的转换边界。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api.message_components import Image as AstrImage
from astrbot.api.message_components import Node as AstrNode
from astrbot.api.message_components import Nodes as AstrNodes
from astrbot.api.message_components import Plain as AstrPlain

if TYPE_CHECKING:
    from ..infrastructure.rendering.temporary import RenderedFileStore


@dataclass(frozen=True, slots=True)
class PlainTextResponse:
    """纯文本 use case 响应。"""

    text: str
    need_at: bool = False


@dataclass(frozen=True, slots=True)
class LoginResponse:
    """登录入口的组合响应，承载二维码和合并转发选项。"""

    text: str
    qr_bytes: bytes | None = None
    forward: bool = False
    need_at: bool = False


@dataclass(frozen=True, slots=True)
class ChainResponse:
    """消息链 use case 响应。"""

    components: Any


@dataclass(frozen=True, slots=True)
class ImageResponse:
    """图片 use case 响应。"""

    image: Any
    temporary: bool = False
    """仅限本次事件结束后可删除的合成文件。"""
    original_image_path: Path | None = None
    """与本次详情响应关联的原图；没有公开发送 ID 时不得据此登记缓存。"""
    incomplete: bool = False
    """素材缺失时允许本次发送，但不应作为完整卡片缓存。"""
    sidecar: Any | None = None
    """与图片 bytes 配对的 artifact sidecar 路径。"""
    manifest: Any | None = None
    """声明图片与 sidecar 已完整发布的配对清单路径。"""


@dataclass(frozen=True, slots=True)
class MultiImageResponse:
    """需要在同一条消息中连续发送的多页图片响应。"""

    images: tuple[ImageResponse, ...]

    def __post_init__(self) -> None:
        if not self.images:
            raise ValueError("多图响应至少需要一张图片")
        if any(not isinstance(image, ImageResponse) for image in self.images):
            raise TypeError("多图响应只能包含 ImageResponse")


@dataclass(frozen=True, slots=True)
class MultiTextResponse:
    """按 channel 顺序承载多条文本的框架无关响应。"""

    texts: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(self.texts)
        if not normalized:
            raise ValueError("多文本响应至少需要一条文本")
        if any(not isinstance(text, str) for text in normalized):
            raise TypeError("多文本响应只能包含字符串")
        object.__setattr__(self, "texts", normalized)


CommandResponse = (
    PlainTextResponse
    | LoginResponse
    | ChainResponse
    | ImageResponse
    | MultiImageResponse
    | MultiTextResponse
)


def write_temporary_image(
    rendered_root: str | Path,
    payload: bytes,
    *,
    prefix: str,
    suffix: str,
) -> ImageResponse:
    """把合成图片写入受控渲染根，交由事件生命周期清理。"""

    root = Path(rendered_root).expanduser().absolute()
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("渲染目录路径不安全")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("渲染目录路径不安全")
    with tempfile.NamedTemporaryFile(
        prefix=prefix,
        suffix=suffix,
        dir=root,
        delete=False,
    ) as file:
        file.write(payload)
        return ImageResponse(file.name, temporary=True)


_ONEBOT_PLATFORM_NAMES = frozenset(("aiocqhttp", "onebot"))


def _is_onebot_event(event: Any) -> bool:
    """按 AstrBot 平台名或统一消息来源识别 OneBot 事件。"""

    get_platform_name = getattr(event, "get_platform_name", None)
    if callable(get_platform_name):
        platform_name = get_platform_name()
        if isinstance(platform_name, str):
            return platform_name in _ONEBOT_PLATFORM_NAMES

    origin = getattr(event, "unified_msg_origin", None)
    return isinstance(origin, str) and origin.split(":", 1)[0] in _ONEBOT_PLATFORM_NAMES


class ResponseFactory:
    """集中调用 AstrBot 事件的原生结果构造方法。

    业务 use case 不应直接依赖 ``plain_result``/``chain_result``；后续命令层
    只把框架无关 DTO 交给此类转换。
    """

    def __init__(
        self,
        *,
        temporary_roots: tuple[str | Path, ...] = (),
        rendered_store: RenderedFileStore | None = None,
    ) -> None:
        """限定可交给事件清理的合成文件根目录。"""

        self._temporary_roots = tuple(
            Path(root).expanduser().resolve() for root in temporary_roots
        )
        self._rendered_store = rendered_store

    @staticmethod
    def plain(event: Any, text: str, *, need_at: bool = False) -> Any:
        """构造 AstrBot 原生纯文本结果。"""

        if need_at:
            get_group_id = getattr(event, "get_group_id", None)
            get_sender_id = getattr(event, "get_sender_id", None)
            group_id = get_group_id() if callable(get_group_id) else None
            user_id = get_sender_id() if callable(get_sender_id) else None
            chain_result = getattr(event, "chain_result", None)
            if group_id and user_id and callable(chain_result):
                from astrbot.api.message_components import At, Plain

                return chain_result([At(qq=str(user_id)), Plain(text)])
        return event.plain_result(text)

    @staticmethod
    def multi_text(event: Any, texts: tuple[str, ...]) -> Any:
        """将有序多 channel 文本适配为平台原生消息。"""

        if len(texts) == 1:
            return ResponseFactory.plain(event, texts[0])
        if not _is_onebot_event(event):
            return event.plain_result("\n\n".join(texts))

        nodes = [
            AstrNode(
                content=[AstrPlain(text)],
                name="二重螺旋客户端更新",
                uin="0",
            )
            for text in texts
        ]
        return event.chain_result(AstrNodes(nodes))

    @staticmethod
    def chain(event: Any, components: Any) -> Any:
        """构造 AstrBot 原生消息链结果。"""

        if isinstance(components, (list, tuple)):
            converted: list[Any] = []
            changed = False
            previous_plain_response = False
            for component in components:
                if isinstance(component, PlainTextResponse):
                    text = ("\n" if previous_plain_response else "") + component.text
                    converted.append(AstrPlain(text))
                    changed = True
                    previous_plain_response = True
                elif isinstance(component, ImageResponse):
                    converted.append(AstrImage.fromFileSystem(str(component.image)))
                    changed = True
                    previous_plain_response = False
                else:
                    converted.append(component)
                    previous_plain_response = False
            if changed:
                components = converted
        return event.chain_result(components)

    @staticmethod
    def image(event: Any, image: Any) -> Any:
        """构造 AstrBot 原生图片结果。"""
        image_result = getattr(event, "image_result", None)
        if callable(image_result):
            return image_result(image)
        # 最小测试事件可能只公开 plain_result；真实 AstrBot event 总会提供 image_result。
        return event.plain_result(str(image))

    def _temporary_path(self, image: Any) -> Path:
        """验证临时图片是已存在且位于受控渲染目录中的普通文件。"""

        try:
            path = Path(str(image)).resolve(strict=True)
        except OSError as error:
            raise ValueError("临时图片路径不可用") from error
        if not path.is_file():
            raise ValueError("临时图片路径不是文件")
        if not any(path.is_relative_to(root) for root in self._temporary_roots):
            raise ValueError("临时图片不在受控渲染目录中")
        return path

    def _track_one_temporary_image(
        self, event: Any, response: ImageResponse, tracker: Any
    ) -> None:
        """登记单个临时图片及其可选 sidecar，供复合响应复用。"""

        if not response.temporary:
            return
        path = self._temporary_path(response.image)
        tracker(str(path))
        if self._rendered_store is not None:
            self._rendered_store.register(path)
        for companion in (response.sidecar, response.manifest):
            if companion is None:
                continue
            companion_path = self._temporary_path(companion)
            tracker(str(companion_path))
            if self._rendered_store is not None:
                self._rendered_store.register(companion_path)

    def _track_temporary_images(self, event: Any, response: CommandResponse) -> None:
        """将明确标记的合成图片交给 AstrBot 事件生命周期清理。"""

        tracker = getattr(event, "track_temporary_local_file", None)
        if not callable(tracker):
            # 单元测试中的最小 event 只验证 result 构造；真实 AstrBot event 提供该公开方法。
            return
        if isinstance(response, ImageResponse):
            self._track_one_temporary_image(event, response, tracker)
            return
        if isinstance(response, MultiImageResponse):
            for image in response.images:
                self._track_one_temporary_image(event, image, tracker)
            return
        if isinstance(response, ChainResponse) and isinstance(
            response.components, (list, tuple)
        ):
            for component in response.components:
                if isinstance(component, ImageResponse):
                    self._track_one_temporary_image(event, component, tracker)

    def build(self, event: Any, response: CommandResponse) -> Any:
        """将框架无关 DTO 转换为 AstrBot 原生结果。"""

        self._track_temporary_images(event, response)
        if isinstance(response, PlainTextResponse):
            return self.plain(event, response.text, need_at=response.need_at)
        if isinstance(response, LoginResponse):
            components: list[Any] = []
            if response.need_at:
                get_group_id = getattr(event, "get_group_id", None)
                get_sender_id = getattr(event, "get_sender_id", None)
                group_id = get_group_id() if callable(get_group_id) else None
                user_id = get_sender_id() if callable(get_sender_id) else None
                if group_id and user_id:
                    from astrbot.api.message_components import At

                    components.append(At(qq=str(user_id)))
            components.append(AstrPlain(response.text))
            if response.qr_bytes is not None:
                components.append(AstrImage.fromBytes(response.qr_bytes))
            if response.forward:
                return event.chain_result(
                    AstrNodes([AstrNode(content=components, name="二重螺旋登录")])
                )
            return event.chain_result(components)
        if isinstance(response, ChainResponse):
            return self.chain(event, response.components)
        if isinstance(response, ImageResponse):
            return self.image(event, response.image)
        if isinstance(response, MultiImageResponse):
            return self.chain(event, response.images)
        if isinstance(response, MultiTextResponse):
            return self.multi_text(event, response.texts)
        raise TypeError(f"未知命令响应类型: {type(response).__name__}")


__all__ = [
    "ChainResponse",
    "CommandResponse",
    "ImageResponse",
    "LoginResponse",
    "MultiImageResponse",
    "MultiTextResponse",
    "PlainTextResponse",
    "ResponseFactory",
    "write_temporary_image",
]
