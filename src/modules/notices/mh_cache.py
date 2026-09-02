"""密函当前小时快照的完整性缓存。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...infrastructure.cache import CacheManager
from .contracts import (
    MhInstance,
    MhSection,
    MhSnapshot,
    validate_mh_snapshot,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
MH_CACHE_TYPE = "mh"


def _aware(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区")
    return value


def _snapshot_payload(snapshot: MhSnapshot) -> dict[str, Any]:
    validate_mh_snapshot(snapshot)
    return {
        "sections": [
            {
                "mh_type": section.mh_type,
                "type_name": section.type_name,
                "instances": [
                    {"id": item.instance_id, "name": item.name}
                    for item in section.instances
                ],
            }
            for section in snapshot.sections
        ],
    }


def _snapshot_from_payload(raw: object) -> MhSnapshot:
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list):
        raise TypeError("密函缓存缺少 sections")
    sections = []
    for raw_section in raw["sections"]:
        if not isinstance(raw_section, dict):
            raise TypeError("密函缓存分区不是对象")
        raw_instances = raw_section.get("instances")
        if not isinstance(raw_instances, list):
            raise TypeError("密函缓存实例不是列表")
        instances = []
        for raw_instance in raw_instances:
            if not isinstance(raw_instance, dict):
                raise TypeError("密函缓存实例不是对象")
            instance_id = raw_instance.get("id")
            name = raw_instance.get("name")
            if type(instance_id) is not int or not isinstance(name, str):
                raise ValueError("密函缓存实例字段无效")
            instances.append(MhInstance(instance_id=instance_id, name=name))

        mh_type = raw_section.get("mh_type")
        type_name = raw_section.get("type_name")
        if not isinstance(mh_type, str) or not isinstance(type_name, str):
            raise TypeError("密函缓存分区字段无效")
        sections.append(
            MhSection(
                mh_type=mh_type,
                type_name=type_name,
                instances=tuple(instances),
            ),
        )
    return validate_mh_snapshot(MhSnapshot(sections=tuple(sections)))


def snapshot_fingerprint(snapshot: MhSnapshot) -> str:
    """为已校验快照生成稳定摘要，作为缓存内容版本。"""

    content = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class MhSnapshotEnvelope:
    """当前小时缓存所需的快照、窗口、抓取时间和 fingerprint。"""

    snapshot: MhSnapshot
    window_start: datetime
    fetched_at: datetime
    fingerprint: str

    def __post_init__(self) -> None:
        validate_mh_snapshot(self.snapshot)
        window_start = _aware(self.window_start, name="window_start").astimezone(SHANGHAI)
        fetched_at = _aware(self.fetched_at, name="fetched_at")
        if window_start.minute or window_start.second or window_start.microsecond:
            raise ValueError("window_start 必须是整点")
        object.__setattr__(self, "window_start", window_start)
        if fetched_at >= window_start + timedelta(hours=1):
            raise ValueError("fetched_at 不属于 window_start")
        if not isinstance(self.fingerprint, str) or len(self.fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.fingerprint
        ):
            raise ValueError("密函 fingerprint 无效")
        if self.fingerprint != snapshot_fingerprint(self.snapshot):
            raise ValueError("密函 fingerprint 与快照不一致")


def _json_object_validator(content: bytes) -> bool:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict)


class MhSnapshotCache:
    """把已验证的密函快照按本地小时窗口写入统一缓存。"""

    def __init__(self, manager: CacheManager) -> None:
        self.manager = manager

    @staticmethod
    def window_start(now: datetime) -> datetime:
        """将任意带时区时间转换为上海时区的整点窗口。"""

        return _aware(now, name="now").astimezone(SHANGHAI).replace(
            minute=0,
            second=0,
            microsecond=0,
        )

    @staticmethod
    def cache_key(window_start: datetime) -> str:
        normalized = _aware(window_start, name="window_start").astimezone(SHANGHAI)
        if normalized.minute or normalized.second or normalized.microsecond:
            raise ValueError("window_start 必须是整点")
        return f"mh:{normalized.isoformat()}"

    @staticmethod
    def encode(envelope: MhSnapshotEnvelope) -> bytes:
        return json.dumps(
            {
                "fetched_at": envelope.fetched_at.isoformat(),
                "fingerprint": envelope.fingerprint,
                "snapshot": _snapshot_payload(envelope.snapshot),
                "window_start": envelope.window_start.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def decode(content: bytes) -> MhSnapshotEnvelope:
        raw = json.loads(content.decode("utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("密函缓存不是对象")
        window_start = raw.get("window_start")
        fetched_at = raw.get("fetched_at")
        fingerprint = raw.get("fingerprint")
        if not isinstance(window_start, str) or not isinstance(fetched_at, str):
            raise TypeError("密函缓存时间字段无效")
        if not isinstance(fingerprint, str):
            raise TypeError("密函缓存 fingerprint 字段无效")
        envelope = MhSnapshotEnvelope(
            snapshot=_snapshot_from_payload(raw.get("snapshot")),
            window_start=datetime.fromisoformat(window_start),
            fetched_at=datetime.fromisoformat(fetched_at),
            fingerprint=fingerprint,
        )
        return envelope

    async def get(
        self,
        window_start: datetime,
        *,
        now: datetime | None = None,
    ) -> MhSnapshotEnvelope | None:
        key = self.cache_key(window_start)
        lookup = await self.manager.get(
            MH_CACHE_TYPE,
            key,
            validator=_json_object_validator,
            now=now,
        )
        if lookup.entry is None:
            return None
        try:
            envelope = self.decode(lookup.entry.content)
        except (
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return None
        if self.cache_key(envelope.window_start) != key:
            return None
        return envelope

    async def put(self, envelope: MhSnapshotEnvelope) -> None:
        await self.manager.put(
            MH_CACHE_TYPE,
            self.cache_key(envelope.window_start),
            self.encode(envelope),
            resource_version=envelope.fingerprint,
            tags=("mh", f"window:{envelope.window_start.isoformat()}"),
            validator=_json_object_validator,
            now=envelope.fetched_at,
        )


__all__ = [
    "MH_CACHE_TYPE",
    "MhSnapshotCache",
    "MhSnapshotEnvelope",
    "snapshot_fingerprint",
]
