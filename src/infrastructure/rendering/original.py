"""角色详情原图缓存。

缓存只保存运行期图片路径和平台消息 ID 的关系；它不序列化到数据库，也不把
图片内容或用户凭据写入日志。消息发送层拿到平台返回的消息 ID 后调用
``remember``，原图命令再按引用消息查找。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class OriginalImageCache:
    """按平台消息 ID 保存详情图对应的原始面板图。"""

    def __init__(self) -> None:
        self._paths: dict[str, Path] = {}

    def remember(self, message_ids: Iterable[str], image_path: Path | None) -> None:
        """登记成功发送的消息 ID；缺失原图时不创建伪造映射。"""

        if image_path is None or not image_path.is_file():
            return
        for message_id in message_ids:
            normalized = str(message_id).strip()
            if normalized:
                self._paths[normalized] = image_path

    def get(self, message_id: str | None) -> Path | None:
        """返回仍存在的原图路径；文件被删除时显式视为未找到。"""

        if message_id is None:
            return None
        path = self._paths.get(str(message_id).strip())
        if path is None:
            return None
        return path if path.is_file() else None

    def forget(self, message_id: str | None) -> None:
        """删除单条消息映射，不删除用户文件。"""

        if message_id is not None:
            self._paths.pop(str(message_id).strip(), None)


__all__ = ["OriginalImageCache"]
