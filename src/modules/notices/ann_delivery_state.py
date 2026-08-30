"""公告按目标持久化投递状态。

``ann_state.json`` 是旧版仅按公告 ID 去重的回滚兼容文件；本模块使用独立的
版本化文件记录首次观察到的目标集合和已经成功发送的目标集合，从而支持单目标
失败后的精确重试。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

STATE_VERSION = 1


@dataclass(frozen=True, slots=True)
class AnnDeliveryRecord:
    """一篇公告的目标投递快照。"""

    observed_targets: frozenset[str] = frozenset()
    delivered_targets: frozenset[str] = frozenset()
    legacy_processed: bool = False

    @property
    def pending_targets(self) -> frozenset[str]:
        """返回已观察但尚未成功的目标。"""

        return self.observed_targets - self.delivered_targets


class AnnDeliveryStateStore:
    """版本化公告投递状态的读写入口。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._records: dict[str, AnnDeliveryRecord] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        """幂等加载状态文件；格式损坏时显式失败。"""

        if self._loaded:
            return
        if not self.path.exists():
            self._loaded = True
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("delivery state must be an object")
            if raw.get("version") != STATE_VERSION:
                raise ValueError(f"unsupported delivery state version: {raw.get('version')!r}")
            raw_records = raw.get("announcements")
            if not isinstance(raw_records, dict):
                raise TypeError("announcements must be an object")
            records = {
                str(post_id): self._parse_record(post_id, value)
                for post_id, value in raw_records.items()
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"公告投递状态文件损坏: {self.path.name} ({type(error).__name__})",
            ) from error
        self._records = records
        self._loaded = True

    @staticmethod
    def _parse_record(post_id: object, value: object) -> AnnDeliveryRecord:
        if not isinstance(post_id, str) or not post_id:
            raise ValueError("announcement ID must be a non-empty string")
        if not isinstance(value, dict):
            raise TypeError("announcement record must be an object")
        observed = AnnDeliveryStateStore._parse_targets(value.get("observed_targets"))
        delivered = AnnDeliveryStateStore._parse_targets(value.get("delivered_targets"))
        if not delivered.issubset(observed):
            raise ValueError("delivered targets must be observed targets")
        legacy_processed = value.get("legacy_processed", False)
        if not isinstance(legacy_processed, bool):
            raise TypeError("legacy_processed must be a boolean")
        return AnnDeliveryRecord(
            observed_targets=observed,
            delivered_targets=delivered,
            legacy_processed=legacy_processed,
        )

    @staticmethod
    def _parse_targets(value: object) -> frozenset[str]:
        if not isinstance(value, list):
            raise TypeError("targets must be a list")
        if any(not isinstance(target, str) or not target for target in value):
            raise ValueError("targets must be non-empty strings")
        return frozenset(value)

    async def migrate_legacy_ids(self, legacy_ids: Iterable[int]) -> None:
        """把旧 ID 视为已处理，且不为历史公告补建任何目标。"""

        async with self._lock:
            await self.load()
            previous = self._records.copy()
            changed = False
            for post_id in legacy_ids:
                key = str(post_id)
                if key in self._records:
                    continue
                self._records[key] = AnnDeliveryRecord(legacy_processed=True)
                changed = True
            if changed:
                try:
                    self._save_unlocked()
                except BaseException:
                    self._records = previous
                    raise

    async def pending_targets(
        self,
        post_id: str,
        observed_targets: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        """建立首次观察目标集合并返回待发送目标。

        已存在的记录不会吸收后续新增订阅者，以免把历史公告补发给新目标。
        """

        key = str(post_id)
        async with self._lock:
            await self.load()
            record = self._records.get(key)
            if record is None:
                targets = frozenset(str(target) for target in (observed_targets or ()))
                if any(not target for target in targets):
                    raise ValueError("公告投递目标不能为空")
                record = AnnDeliveryRecord(observed_targets=targets)
                self._records[key] = record
                try:
                    self._save_unlocked()
                except BaseException:
                    self._records.pop(key, None)
                    raise
            if record.legacy_processed:
                return ()
            return tuple(sorted(record.pending_targets))

    async def mark_delivered(self, post_id: str, target: str) -> bool:
        """记录一个目标已成功发送；目标不在首次观察集合中时拒绝写入。"""

        key = str(post_id)
        target = str(target)
        async with self._lock:
            await self.load()
            record = self._records.get(key)
            if record is None or record.legacy_processed or target not in record.observed_targets:
                return False
            if target in record.delivered_targets:
                return True
            previous = self._records
            self._records[key] = AnnDeliveryRecord(
                observed_targets=record.observed_targets,
                delivered_targets=record.delivered_targets | {target},
                legacy_processed=False,
            )
            try:
                self._save_unlocked()
            except BaseException:
                self._records = previous
                raise
            return True

    async def records(self) -> dict[str, AnnDeliveryRecord]:
        """返回不可变记录快照，供诊断与测试核对。"""

        async with self._lock:
            await self.load()
            return dict(self._records)

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STATE_VERSION,
            "announcements": {
                post_id: {
                    "observed_targets": sorted(record.observed_targets),
                    "delivered_targets": sorted(record.delivered_targets),
                    "legacy_processed": record.legacy_processed,
                }
                for post_id, record in sorted(self._records.items())
            },
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)


__all__ = ["STATE_VERSION", "AnnDeliveryRecord", "AnnDeliveryStateStore"]
