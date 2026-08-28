"""内置调度任务的统一 registry、运行状态与不可恢复 tombstone。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class SchedulerTaskState(StrEnum):
    """任务当前运行状态。"""

    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class SchedulerStateError(ValueError):
    """调度 registry 操作失败。"""


class SchedulerTaskNotFound(SchedulerStateError):
    """请求的任务不在内置 registry 中。"""


class SchedulerTaskDeleted(SchedulerStateError):
    """请求的任务已经被永久删除。"""


class SchedulerTaskNotDeletable(SchedulerStateError):
    """维护任务不允许永久删除。"""


class SchedulerTaskNotPausable(SchedulerStateError):
    """任务不支持暂停/恢复。"""


class SchedulerTaskUnavailable(SchedulerStateError):
    """任务定义存在，但当前配置没有启用它。"""


@dataclass(frozen=True, slots=True)
class SchedulerTaskDefinition:
    """一个内置任务的静态描述。"""

    id: str
    name: str
    schedule: str
    targets: tuple[str, ...] = ()
    can_pause: bool = True
    can_delete: bool = True

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "schedule"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"任务 {field_name} 不能为空")
        if isinstance(self.targets, str):
            raise TypeError("任务 targets 必须是字符串序列")
        object.__setattr__(
            self, "targets", tuple(str(target) for target in self.targets)
        )


@dataclass(frozen=True, slots=True)
class SchedulerTaskSnapshot:
    """对外可见的任务快照，不暴露异常原文。"""

    id: str
    name: str
    state: SchedulerTaskState
    schedule: str
    next_run_at: datetime | None
    targets: tuple[str, ...]
    can_pause: bool
    can_delete: bool
    last_error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", SchedulerTaskState(self.state))
        if self.next_run_at is not None and self.next_run_at.tzinfo is None:
            raise ValueError("next_run_at 必须带时区")
        object.__setattr__(self, "targets", tuple(self.targets))

    def to_dict(self) -> dict[str, Any]:
        """转换为给管理 API 使用的 JSON 兼容快照。"""

        return {
            "id": self.id,
            "name": self.name,
            "state": self.state.value,
            "schedule": self.schedule,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "targets": list(self.targets),
            "can_pause": self.can_pause,
            "can_delete": self.can_delete,
            "last_error": self.last_error,
        }


class SchedulerStateStore:
    """只持久化永久删除 tombstone，并用临时文件原子替换。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path is not None else None
        self._deleted_tasks: set[str] = set()
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> frozenset[str]:
        """幂等加载状态；损坏状态显式失败，不当作空 tombstone。"""

        async with self._lock:
            await self._load_unlocked()
            return frozenset(self._deleted_tasks)

    async def _load_unlocked(self) -> None:
        if self._loaded:
            return
        if self.path is None or not self.path.exists():
            self._loaded = True
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("scheduler state must be an object")
            deleted = raw.get("deleted_tasks", [])
            if not isinstance(deleted, list) or any(
                not isinstance(task_id, str) or not task_id.strip()
                for task_id in deleted
            ):
                raise TypeError("deleted_tasks must be a list of non-empty strings")
            self._deleted_tasks = set(deleted)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"调度状态文件损坏: {self.path.name} ({type(error).__name__})"
            ) from error
        self._loaded = True

    async def is_deleted(self, task_id: str) -> bool:
        async with self._lock:
            await self._load_unlocked()
            return task_id in self._deleted_tasks

    async def delete(self, task_id: str) -> bool:
        """写入永久删除标记；重复删除保持幂等。"""

        async with self._lock:
            await self._load_unlocked()
            if task_id in self._deleted_tasks:
                return False
            previous = set(self._deleted_tasks)
            self._deleted_tasks.add(task_id)
            try:
                self._save_unlocked()
            except BaseException:
                self._deleted_tasks = previous
                raise
            return True

    def _save_unlocked(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"deleted_tasks": sorted(self._deleted_tasks)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)


class SchedulerRegistry:
    """跨签到/通知 scheduler 共享的四任务 registry。"""

    def __init__(self, state: SchedulerStateStore | str | Path | None = None) -> None:
        if isinstance(state, SchedulerStateStore):
            self.state_store = state
        else:
            self.state_store = SchedulerStateStore(state)
        self._definitions: dict[str, SchedulerTaskDefinition] = {}
        self._enabled: dict[str, bool] = {}
        self._snapshots: dict[str, SchedulerTaskSnapshot] = {}
        self._deleted_tasks: set[str] = set()
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def state_path(self) -> Path | None:
        """返回 tombstone 文件路径；内存测试 registry 返回 ``None``。"""

        return self.state_store.path

    def register(
        self,
        definition: SchedulerTaskDefinition,
        *,
        enabled: bool = True,
    ) -> None:
        """注册内置任务；重复注册相同定义是幂等的。"""

        existing = self._definitions.get(definition.id)
        if existing is not None:
            if existing != definition or self._enabled[definition.id] != enabled:
                raise ValueError(f"任务定义冲突: {definition.id}")
            return
        self._definitions[definition.id] = definition
        self._enabled[definition.id] = enabled
        self._snapshots[definition.id] = SchedulerTaskSnapshot(
            id=definition.id,
            name=definition.name,
            state=SchedulerTaskState.PAUSED,
            schedule=definition.schedule,
            next_run_at=None,
            targets=definition.targets,
            can_pause=definition.can_pause,
            can_delete=definition.can_delete,
        )

    async def initialize(self) -> None:
        """加载 tombstone；多 scheduler 并发初始化保持幂等。"""

        async with self._lock:
            if self._initialized:
                return
            self._deleted_tasks = set(await self.state_store.load())
            self._initialized = True

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    def _require_locked(self, task_id: str) -> SchedulerTaskSnapshot:
        snapshot = self._snapshots.get(task_id)
        if snapshot is None:
            raise SchedulerTaskNotFound(task_id)
        if task_id in self._deleted_tasks:
            raise SchedulerTaskDeleted(task_id)
        return snapshot

    async def list_snapshots(self) -> tuple[SchedulerTaskSnapshot, ...]:
        await self._ensure_initialized()
        async with self._lock:
            return tuple(
                snapshot
                for task_id, snapshot in self._snapshots.items()
                if task_id not in self._deleted_tasks
            )

    async def get_snapshot(self, task_id: str) -> SchedulerTaskSnapshot | None:
        await self._ensure_initialized()
        async with self._lock:
            if task_id in self._deleted_tasks:
                return None
            return self._snapshots.get(task_id)

    async def is_deleted(self, task_id: str) -> bool:
        await self._ensure_initialized()
        async with self._lock:
            return task_id in self._deleted_tasks

    async def is_enabled(self, task_id: str) -> bool:
        await self._ensure_initialized()
        async with self._lock:
            if task_id not in self._definitions:
                raise SchedulerTaskNotFound(task_id)
            return self._enabled[task_id]

    async def activate(self, task_id: str) -> None:
        """标记 scheduler 已创建该任务。"""

        await self._ensure_initialized()
        async with self._lock:
            self._require_locked(task_id)
            if not self._enabled[task_id]:
                raise SchedulerTaskUnavailable(task_id)
            current = self._snapshots[task_id]
            self._snapshots[task_id] = replace(
                current,
                state=SchedulerTaskState.RUNNING,
                last_error=None,
            )

    async def deactivate(self, task_id: str) -> None:
        """标记 scheduler 已停止该任务，不写入永久状态。"""

        await self._ensure_initialized()
        async with self._lock:
            if task_id in self._deleted_tasks:
                return
            current = self._snapshots.get(task_id)
            if current is None:
                return
            self._snapshots[task_id] = replace(
                current,
                state=SchedulerTaskState.PAUSED,
                next_run_at=None,
            )

    async def pause(self, task_id: str) -> None:
        await self._ensure_initialized()
        async with self._lock:
            current = self._require_locked(task_id)
            if not current.can_pause:
                raise SchedulerTaskNotPausable(task_id)
            self._snapshots[task_id] = replace(
                current,
                state=SchedulerTaskState.PAUSED,
                next_run_at=None,
                last_error=None,
            )

    async def resume(self, task_id: str) -> None:
        await self._ensure_initialized()
        async with self._lock:
            current = self._require_locked(task_id)
            if not current.can_pause:
                raise SchedulerTaskNotPausable(task_id)
            if not self._enabled[task_id]:
                raise SchedulerTaskUnavailable(task_id)
            self._snapshots[task_id] = replace(
                current,
                state=SchedulerTaskState.RUNNING,
                next_run_at=None,
                last_error=None,
            )

    async def delete(self, task_id: str) -> None:
        """永久删除任务并原子写入 tombstone；不提供恢复操作。"""

        await self._ensure_initialized()
        async with self._lock:
            current = self._require_locked(task_id)
            if not current.can_delete:
                raise SchedulerTaskNotDeletable(task_id)
            await self.state_store.delete(task_id)
            self._deleted_tasks.add(task_id)

    async def set_next_run(self, task_id: str, next_run_at: datetime) -> None:
        """登记带时区的下一次运行时间。"""

        if next_run_at.tzinfo is None or next_run_at.utcoffset() is None:
            raise ValueError("next_run_at 必须带时区")
        await self._ensure_initialized()
        async with self._lock:
            current = self._require_locked(task_id)
            if current.state is SchedulerTaskState.PAUSED:
                return
            self._snapshots[task_id] = replace(current, next_run_at=next_run_at)

    async def mark_running(self, task_id: str) -> None:
        await self._ensure_initialized()
        async with self._lock:
            current = self._require_locked(task_id)
            if current.state is SchedulerTaskState.PAUSED:
                return
            self._snapshots[task_id] = replace(
                current,
                state=SchedulerTaskState.RUNNING,
                last_error=None,
            )

    async def mark_error(self, task_id: str) -> None:
        """记录安全的固定错误状态，不保存异常原文。"""

        await self._ensure_initialized()
        async with self._lock:
            current = self._require_locked(task_id)
            if current.state is SchedulerTaskState.PAUSED:
                return
            self._snapshots[task_id] = replace(
                current,
                state=SchedulerTaskState.ERROR,
                last_error="task execution failed",
            )


__all__ = [
    "SchedulerRegistry",
    "SchedulerStateError",
    "SchedulerStateStore",
    "SchedulerTaskDefinition",
    "SchedulerTaskDeleted",
    "SchedulerTaskNotDeletable",
    "SchedulerTaskNotFound",
    "SchedulerTaskNotPausable",
    "SchedulerTaskSnapshot",
    "SchedulerTaskState",
    "SchedulerTaskUnavailable",
]
