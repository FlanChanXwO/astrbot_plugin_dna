"""公告轮询的已知 ID 状态（运行期 JSON，不入 Git）。

框架无关：只负责保存/读取已推送过的公告 postId 列表，损坏文件显式失败。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

_KNOWN_LIMIT = 50


class AnnStateStore:
    """已知公告 ID 的读写入口；写操作在进程内锁内完成并原子落盘。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._ids: list[int] = []
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        if self._loaded:
            return
        if not self.path.exists():
            self._loaded = True
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise TypeError("announcement state file must be a list")
            ids = [int(item) for item in raw]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"公告状态文件损坏: {self.path.name} ({type(error).__name__})"
            ) from error
        self._ids = ids
        self._loaded = True

    async def known_ids(self) -> list[int]:
        await self.load()
        return list(self._ids)

    async def merge(self, fresh_ids: list[int]) -> list[int]:
        """合并新 id 并保留最近 50 条，返回尚未推送过的 id。"""
        async with self._lock:
            await self.load()
            pending = [post_id for post_id in fresh_ids if post_id not in self._ids]
            if pending or not self._ids:
                merged = sorted(set(self._ids) | set(fresh_ids), reverse=True)[
                    :_KNOWN_LIMIT
                ]
                self._ids = merged
                self._save_unlocked()
            return pending

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._ids), encoding="utf-8")
        tmp.replace(self.path)


__all__ = ["AnnStateStore"]
