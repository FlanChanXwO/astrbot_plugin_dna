"""客户端更新基线与待投递事件的 typed JSON 状态边界。

状态文件只保存运行期最近一次成功观察、变化摘要和未完成的投递事件，不接触
AstrBot event 或订阅对象。所有读写都经过固定 schema 校验；写入先落到同目录
临时文件，再替换最终文件，避免进程在写入中断时留下半份 JSON。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientVersionSnapshot,
)

STATE_VERSION = 2
_LEGACY_STATE_VERSION = 1
_PENDING_STATUSES = frozenset(("pending", "delivered"))


class ClientUpdateStateError(RuntimeError):
    """客户端更新状态文件损坏或无法原子写入时抛出的错误。"""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("client update state is invalid")

    def __repr__(self) -> str:
        """repr 不带入路径或内部结构，避免异常被意外展示。"""

        return "ClientUpdateStateError()"


@dataclass(frozen=True, slots=True)
class ClientUpdateBaseline:
    """一个区服/平台最近成功观察到的基线。"""

    snapshot: ClientVersionSnapshot
    observed_at: datetime
    last_change: ClientUpdateChange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ClientVersionSnapshot):
            raise TypeError("snapshot 必须是 ClientVersionSnapshot")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at 必须是 datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at 必须带时区")
        if self.last_change is not None:
            if not isinstance(self.last_change, ClientUpdateChange):
                raise TypeError("last_change 必须是 ClientUpdateChange 或 None")
            if self.last_change.current != self.snapshot:
                raise ValueError("last_change.current 必须等于当前基线快照")


@dataclass(frozen=True, slots=True)
class ClientUpdatePendingTarget:
    """一次客户端更新事件首次生成时固定下来的投递目标。"""

    origin: str
    uid: str = ""
    bot_id: str = ""
    delivered: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.origin, str) or not self.origin:
            raise ValueError("投递目标 origin 不能为空")
        if not isinstance(self.uid, str):
            raise TypeError("投递目标 uid 必须是字符串")
        if not isinstance(self.bot_id, str):
            raise TypeError("投递目标 bot_id 必须是字符串")
        if type(self.delivered) is not bool:
            raise TypeError("投递目标 delivered 必须是布尔值")

    @property
    def key(self) -> tuple[str, str]:
        """返回订阅的稳定身份键；bot_id 变化不应把目标变成新订阅。"""

        return self.origin, self.uid

    @property
    def status(self) -> str:
        """返回持久化和诊断使用的 ``pending``/``delivered`` 状态。"""

        return "delivered" if self.delivered else "pending"


@dataclass(frozen=True, slots=True)
class ClientUpdatePendingEvent:
    """一个版本变化及其首次匹配目标集合。"""

    change: ClientUpdateChange
    targets: tuple[ClientUpdatePendingTarget, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.change, ClientUpdateChange):
            raise TypeError("change 必须是 ClientUpdateChange")
        normalized = tuple(self.targets)
        if any(
            not isinstance(target, ClientUpdatePendingTarget) for target in normalized
        ):
            raise TypeError("targets 必须全部是 ClientUpdatePendingTarget")
        keys = [target.key for target in normalized]
        if len(keys) != len(set(keys)):
            raise ValueError("一个事件不能重复记录同一投递目标")
        object.__setattr__(self, "targets", normalized)

    @property
    def event_key(self) -> str:
        """返回变化事件的稳定去重键。"""

        return self.change.event_key

    @property
    def pending_targets(self) -> tuple[ClientUpdatePendingTarget, ...]:
        """返回当前仍需投递的目标。"""

        return tuple(target for target in self.targets if not target.delivered)


class ClientUpdateStateStore:
    """版本化客户端更新基线和投递状态的读写入口。

    ``path`` 由 bootstrap 根据 ``StarTools.get_data_dir`` 注入；本类不自行决定
    运行期目录。单进程内的写操作通过 asyncio 锁串行化，并在内存和磁盘写入
    失败时恢复原有基线及 pending 事件。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._baselines: dict[
            tuple[ClientRegion, ClientPlatform], ClientUpdateBaseline
        ] = {}
        self._pending_events: dict[str, ClientUpdatePendingEvent] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        """幂等加载状态文件；缺失文件代表尚未建立任何状态。"""

        if self._loaded:
            return
        async with self._lock:
            if not self._loaded:
                self._load_unlocked()

    async def get_baseline(
        self,
        region: ClientRegion | str,
        platform: ClientPlatform | str,
    ) -> ClientUpdateBaseline | None:
        """读取一个区服/平台基线，未建立时返回 ``None``。"""

        key = _baseline_key(region, platform)
        await self.load()
        return self._baselines.get(key)

    async def pending_events(self) -> tuple[ClientUpdatePendingEvent, ...]:
        """按首次生成顺序返回仍未完成的投递事件。"""

        await self.load()
        return tuple(self._pending_events.values())

    async def save_baseline(self, baseline: ClientUpdateBaseline) -> None:
        """保存基线并原子替换状态文件。"""

        if not isinstance(baseline, ClientUpdateBaseline):
            raise TypeError("baseline 必须是 ClientUpdateBaseline")
        key = _baseline_key(baseline.snapshot.region, baseline.snapshot.platform)

        async with self._lock:
            self._load_unlocked()
            previous = self._baselines.copy()
            self._baselines[key] = baseline
            try:
                self._save_unlocked()
            except OSError as error:
                self._baselines = previous
                raise ClientUpdateStateError(
                    "state file could not be replaced"
                ) from error
            except BaseException:
                self._baselines = previous
                raise

    async def ensure_pending_event(
        self,
        change: ClientUpdateChange,
        targets: Iterable[ClientUpdatePendingTarget],
    ) -> ClientUpdatePendingEvent | None:
        """首次记录变化事件及固定目标；同一事件键不会吸收新目标。

        没有匹配目标时不建立事件，避免在后来新增订阅时补发已经观察过的变化。
        """

        if not isinstance(change, ClientUpdateChange):
            raise TypeError("change 必须是 ClientUpdateChange")
        event = ClientUpdatePendingEvent(change, tuple(targets))
        if not event.targets:
            return None
        if not event.pending_targets:
            raise ValueError("新建事件至少需要一个 pending 目标")

        async with self._lock:
            self._load_unlocked()
            existing = self._pending_events.get(event.event_key)
            if existing is not None:
                if existing.change != event.change:
                    raise ClientUpdateStateError("event key maps to different change")
                return existing

            previous = self._pending_events.copy()
            self._pending_events[event.event_key] = event
            try:
                self._save_unlocked()
            except OSError as error:
                self._pending_events = previous
                raise ClientUpdateStateError(
                    "state file could not be replaced"
                ) from error
            except BaseException:
                self._pending_events = previous
                raise
            return event

    async def mark_delivered(
        self,
        event_key: str,
        target: ClientUpdatePendingTarget | tuple[str, str],
    ) -> bool:
        """标记一个目标成功；事件全部完成后立即清理。"""

        normalized_event_key = _require_non_empty_string(event_key, "event_key")
        target_key = _pending_target_key(target)
        async with self._lock:
            self._load_unlocked()
            event = self._pending_events.get(normalized_event_key)
            if event is None:
                return False
            target_index = next(
                (
                    index
                    for index, item in enumerate(event.targets)
                    if item.key == target_key
                ),
                None,
            )
            if target_index is None:
                return False
            if event.targets[target_index].delivered:
                return True

            updated_targets = list(event.targets)
            updated_targets[target_index] = ClientUpdatePendingTarget(
                origin=updated_targets[target_index].origin,
                uid=updated_targets[target_index].uid,
                bot_id=updated_targets[target_index].bot_id,
                delivered=True,
            )
            previous = self._pending_events.copy()
            updated_event = ClientUpdatePendingEvent(
                event.change, tuple(updated_targets)
            )
            if updated_event.pending_targets:
                self._pending_events[normalized_event_key] = updated_event
            else:
                self._pending_events.pop(normalized_event_key, None)
            try:
                self._save_unlocked()
            except OSError as error:
                self._pending_events = previous
                raise ClientUpdateStateError(
                    "state file could not be replaced"
                ) from error
            except BaseException:
                self._pending_events = previous
                raise
            return True

    async def remove_event_target(
        self,
        event_key: str,
        target: ClientUpdatePendingTarget | tuple[str, str],
    ) -> bool:
        """从一个事件中移除目标；无剩余目标时清理该事件。"""

        normalized_event_key = _require_non_empty_string(event_key, "event_key")
        target_key = _pending_target_key(target)
        async with self._lock:
            self._load_unlocked()
            event = self._pending_events.get(normalized_event_key)
            if event is None or all(item.key != target_key for item in event.targets):
                return False

            previous = self._pending_events.copy()
            remaining = tuple(item for item in event.targets if item.key != target_key)
            if remaining and any(not item.delivered for item in remaining):
                self._pending_events[normalized_event_key] = ClientUpdatePendingEvent(
                    event.change,
                    remaining,
                )
            else:
                self._pending_events.pop(normalized_event_key, None)
            try:
                self._save_unlocked()
            except OSError as error:
                self._pending_events = previous
                raise ClientUpdateStateError(
                    "state file could not be replaced"
                ) from error
            except BaseException:
                self._pending_events = previous
                raise
            return True

    async def remove_target(self, origin: str, *, uid: str = "") -> int:
        """从所有未完成事件移除订阅目标，避免取消后重新订阅时补发旧事件。"""

        normalized_origin = _require_non_empty_string(origin, "origin")
        if not isinstance(uid, str):
            raise TypeError("uid 必须是字符串")
        target_key = (normalized_origin, uid)
        async with self._lock:
            self._load_unlocked()
            previous = self._pending_events.copy()
            removed = 0
            for event_key, event in tuple(self._pending_events.items()):
                remaining = tuple(
                    item for item in event.targets if item.key != target_key
                )
                removed += len(event.targets) - len(remaining)
                if not remaining or not any(not item.delivered for item in remaining):
                    self._pending_events.pop(event_key, None)
                elif len(remaining) != len(event.targets):
                    self._pending_events[event_key] = ClientUpdatePendingEvent(
                        event.change,
                        remaining,
                    )
            if removed == 0:
                return 0
            try:
                self._save_unlocked()
            except OSError as error:
                self._pending_events = previous
                raise ClientUpdateStateError(
                    "state file could not be replaced"
                ) from error
            except BaseException:
                self._pending_events = previous
                raise
            return removed

    def _load_unlocked(self) -> None:
        if self._loaded:
            return
        if not self.path.exists():
            self._loaded = True
            return

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            root = _require_mapping(raw, "state")
            schema_version = _required(root, "schema_version", "state")
            if type(schema_version) is not int or schema_version not in (
                _LEGACY_STATE_VERSION,
                STATE_VERSION,
            ):
                raise ValueError("unsupported state schema version")
            raw_baselines = _required(root, "baselines", "state")
            if not isinstance(raw_baselines, Mapping):
                raise TypeError("state.baselines must be an object")

            baselines: dict[
                tuple[ClientRegion, ClientPlatform], ClientUpdateBaseline
            ] = {}
            for raw_key, raw_baseline in raw_baselines.items():
                region, platform = _parse_baseline_key(raw_key)
                baseline = _parse_baseline(
                    raw_baseline, f"state.baselines[{raw_key!r}]"
                )
                if (
                    baseline.snapshot.region is not region
                    or baseline.snapshot.platform is not platform
                ):
                    raise ValueError("baseline key and snapshot identity differ")
                baselines[(region, platform)] = baseline

            if schema_version == _LEGACY_STATE_VERSION:
                raw_pending_events: object = []
            else:
                raw_pending_events = _required(root, "pending_events", "state")
            pending_events = _parse_pending_events(raw_pending_events)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ClientUpdateStateError("state file could not be loaded") from error

        self._baselines = baselines
        self._pending_events = pending_events
        self._loaded = True

    def _save_unlocked(self) -> None:
        payload = {
            "schema_version": STATE_VERSION,
            "baselines": {
                _format_baseline_key(region, platform): _baseline_to_json(baseline)
                for (region, platform), baseline in sorted(
                    self._baselines.items(),
                    key=lambda item: (item[0][0].value, item[0][1].value),
                )
            },
            "pending_events": [
                _pending_event_to_json(event) for event in self._pending_events.values()
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


def _baseline_key(
    region: ClientRegion | str,
    platform: ClientPlatform | str,
) -> tuple[ClientRegion, ClientPlatform]:
    try:
        return ClientRegion(region), ClientPlatform(platform)
    except (TypeError, ValueError) as error:
        raise ValueError("不支持的客户端区服或平台") from error


def _format_baseline_key(region: ClientRegion, platform: ClientPlatform) -> str:
    return f"{region.value}:{platform.value}"


def _parse_baseline_key(value: object) -> tuple[ClientRegion, ClientPlatform]:
    if not isinstance(value, str):
        raise TypeError("baseline key must be a string")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("baseline key must contain region and platform")
    return _baseline_key(parts[0], parts[1])


def _baseline_to_json(baseline: ClientUpdateBaseline) -> dict[str, Any]:
    return {
        "snapshot": _snapshot_to_json(baseline.snapshot),
        "observed_at": baseline.observed_at.isoformat(),
        "last_change": (
            _change_to_json(baseline.last_change)
            if baseline.last_change is not None
            else None
        ),
    }


def _snapshot_to_json(snapshot: ClientVersionSnapshot) -> dict[str, Any]:
    return {
        "region": snapshot.region.value,
        "platform": snapshot.platform.value,
        "version_key": snapshot.version_key,
        "patch_version": snapshot.patch_version,
        "resource_version_dir": snapshot.resource_version_dir,
        "version_text": snapshot.version_text,
        "major": snapshot.major,
        "minor": snapshot.minor,
        "revamp": snapshot.revamp,
        "patch_key": snapshot.patch_key,
    }


def _change_to_json(change: ClientUpdateChange) -> dict[str, Any]:
    return {
        "region": change.region.value,
        "platform": change.platform.value,
        "previous": _snapshot_to_json(change.previous),
        "current": _snapshot_to_json(change.current),
        "added_size_bytes": change.added_size_bytes,
    }


def _pending_event_to_json(event: ClientUpdatePendingEvent) -> dict[str, Any]:
    return {
        "event_key": event.event_key,
        "change": _change_to_json(event.change),
        "targets": [
            {
                "origin": target.origin,
                "uid": target.uid,
                "bot_id": target.bot_id,
                "status": target.status,
            }
            for target in event.targets
        ],
    }


def _parse_baseline(value: object, context: str) -> ClientUpdateBaseline:
    entry = _require_mapping(value, context)
    snapshot = _parse_snapshot(
        _required(entry, "snapshot", context), f"{context}.snapshot"
    )
    observed_at_raw = _required(entry, "observed_at", context)
    if not isinstance(observed_at_raw, str):
        raise TypeError(f"{context}.observed_at must be a string")
    try:
        observed_at = datetime.fromisoformat(observed_at_raw)
    except ValueError as error:
        raise ValueError(f"{context}.observed_at is invalid") from error
    last_change = _parse_change(
        _required(entry, "last_change", context), f"{context}.last_change"
    )
    return ClientUpdateBaseline(
        snapshot=snapshot,
        observed_at=observed_at,
        last_change=last_change,
    )


def _parse_pending_events(value: object) -> dict[str, ClientUpdatePendingEvent]:
    if not isinstance(value, list):
        raise TypeError("state.pending_events must be a list")
    events: dict[str, ClientUpdatePendingEvent] = {}
    for index, raw_event in enumerate(value):
        event = _parse_pending_event(raw_event, f"state.pending_events[{index}]")
        if event.event_key in events:
            raise ValueError("duplicate pending event key")
        events[event.event_key] = event
    return events


def _parse_pending_event(value: object, context: str) -> ClientUpdatePendingEvent:
    entry = _require_mapping(value, context)
    raw_event_key = _required(entry, "event_key", context)
    if not isinstance(raw_event_key, str) or not raw_event_key:
        raise ValueError(f"{context}.event_key must be a non-empty string")
    raw_change = _parse_change(_required(entry, "change", context), f"{context}.change")
    if raw_change is None:
        raise ValueError(f"{context}.change must be an object")
    raw_targets = _required(entry, "targets", context)
    if not isinstance(raw_targets, list):
        raise TypeError(f"{context}.targets must be a list")
    event = ClientUpdatePendingEvent(
        raw_change,
        tuple(
            _parse_pending_target(target, f"{context}.targets[{index}]")
            for index, target in enumerate(raw_targets)
        ),
    )
    if event.event_key != raw_event_key:
        raise ValueError(f"{context}.event_key does not match change")
    if not event.targets or not event.pending_targets:
        raise ValueError(f"{context} must contain a pending target")
    return event


def _parse_pending_target(value: object, context: str) -> ClientUpdatePendingTarget:
    entry = _require_mapping(value, context)
    origin = _required(entry, "origin", context)
    uid = _required(entry, "uid", context)
    bot_id = _required(entry, "bot_id", context)
    status = _required(entry, "status", context)
    if not isinstance(origin, str) or not origin:
        raise ValueError(f"{context}.origin must be a non-empty string")
    if not isinstance(uid, str):
        raise TypeError(f"{context}.uid must be a string")
    if not isinstance(bot_id, str):
        raise TypeError(f"{context}.bot_id must be a string")
    if not isinstance(status, str) or status not in _PENDING_STATUSES:
        raise ValueError(f"{context}.status is invalid")
    return ClientUpdatePendingTarget(
        origin=origin,
        uid=uid,
        bot_id=bot_id,
        delivered=status == "delivered",
    )


def _parse_snapshot(value: object, context: str) -> ClientVersionSnapshot:
    entry = _require_mapping(value, context)
    snapshot = ClientVersionSnapshot(
        region=cast(ClientRegion, _required(entry, "region", context)),
        platform=cast(ClientPlatform, _required(entry, "platform", context)),
        version_key=cast(int, _required(entry, "version_key", context)),
        patch_version=cast(int, _required(entry, "patch_version", context)),
        resource_version_dir=cast(
            str | None, _required(entry, "resource_version_dir", context)
        ),
        major=cast(int, _required(entry, "major", context)),
        minor=cast(int, _required(entry, "minor", context)),
        revamp=cast(int, _required(entry, "revamp", context)),
        patch_key=cast(int, _required(entry, "patch_key", context)),
    )
    version_text = _required(entry, "version_text", context)
    if not isinstance(version_text, str) or version_text != snapshot.version_text:
        raise ValueError(f"{context}.version_text does not match snapshot")
    return snapshot


def _parse_change(value: object, context: str) -> ClientUpdateChange | None:
    if value is None:
        return None
    entry = _require_mapping(value, context)
    return ClientUpdateChange(
        previous=_parse_snapshot(
            _required(entry, "previous", context), f"{context}.previous"
        ),
        current=_parse_snapshot(
            _required(entry, "current", context), f"{context}.current"
        ),
        added_size_bytes=cast(int, _required(entry, "added_size_bytes", context)),
        region=cast(ClientRegion, _required(entry, "region", context)),
        platform=cast(ClientPlatform, _required(entry, "platform", context)),
    )


def _pending_target_key(
    target: ClientUpdatePendingTarget | tuple[str, str],
) -> tuple[str, str]:
    if isinstance(target, ClientUpdatePendingTarget):
        return target.key
    if not isinstance(target, tuple) or len(target) != 2:
        raise TypeError("投递目标必须是 ClientUpdatePendingTarget 或二元身份键")
    origin, uid = target
    if not isinstance(origin, str) or not origin:
        raise ValueError("投递目标 origin 不能为空")
    if not isinstance(uid, str):
        raise TypeError("投递目标 uid 必须是字符串")
    return origin, uid


def _require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _required(mapping: Mapping[str, object], key: str, context: str) -> object:
    if key not in mapping:
        raise KeyError(f"{context}.{key} is required")
    return mapping[key]


def _require_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


__all__ = [
    "STATE_VERSION",
    "ClientUpdateBaseline",
    "ClientUpdatePendingEvent",
    "ClientUpdatePendingTarget",
    "ClientUpdateStateError",
    "ClientUpdateStateStore",
]
