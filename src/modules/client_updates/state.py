"""客户端更新 Source 基线与待投递事件的 v4 typed JSON 状态边界。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .contracts import (
    AppStoreVersionMetadata,
    ClientSourceProviderMetadata,
    ClientSourceVersion,
    ClientUpdateChange,
    ManifestCdnVersionMetadata,
)
from .registry import (
    CLIENT_UPDATE_REGISTRY,
    ClientUpdateRegistry,
    ClientUpdateProviderKind,
)

logger = logging.getLogger(__name__)

STATE_VERSION = 4
_IGNORED_STATE_VERSIONS = frozenset((1, 2, 3))
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
    """一个 Source 最近成功观察到的版本基线。"""

    version: ClientSourceVersion
    observed_at: datetime
    last_change: ClientUpdateChange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.version, ClientSourceVersion):
            raise TypeError("version 必须是 ClientSourceVersion")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at 必须是 datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at 必须带时区")
        if self.last_change is not None:
            if not isinstance(self.last_change, ClientUpdateChange):
                raise TypeError("last_change 必须是 ClientUpdateChange 或 None")
            if self.last_change.current != self.version:
                raise ValueError("last_change.current 必须等于当前基线版本")

    @property
    def source_id(self) -> str:
        """返回基线所属 Source。"""

        return self.version.source_id


@dataclass(frozen=True, slots=True)
class ClientUpdatePendingTarget:
    """事件创建时固定的消息目的地和其实际覆盖 Target。"""

    origin: str
    target_ids: tuple[str, ...]
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
        normalized_target_ids = _normalize_target_id_values(self.target_ids)
        if not normalized_target_ids:
            raise ValueError("投递目标必须包含至少一个 Target ID")
        if type(self.delivered) is not bool:
            raise TypeError("投递目标 delivered 必须是布尔值")
        object.__setattr__(self, "target_ids", normalized_target_ids)

    @property
    def key(self) -> tuple[str, str]:
        """返回订阅的稳定身份键；bot_id 变化不产生新订阅。"""

        return self.origin, self.uid

    @property
    def status(self) -> str:
        """返回持久化和诊断使用的 pending/delivered 状态。"""

        return "delivered" if self.delivered else "pending"


@dataclass(frozen=True, slots=True)
class ClientUpdatePendingEvent:
    """一个 Source 变化及其首次匹配的固定投递目标集合。"""

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
        expected_target_ids = self.change.target_ids
        if any(target.target_ids != expected_target_ids for target in normalized):
            raise ValueError("投递目标覆盖的 Target 必须与变化快照一致")
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
    """串行、原子地读写客户端更新 state v4。"""

    def __init__(
        self,
        path: str | Path,
        *,
        registry: ClientUpdateRegistry = CLIENT_UPDATE_REGISTRY,
    ) -> None:
        if not isinstance(registry, ClientUpdateRegistry):
            raise TypeError("registry 必须是 ClientUpdateRegistry")
        self.path = Path(path).expanduser().resolve()
        self.registry = registry
        self._baselines: dict[str, ClientUpdateBaseline] = {}
        self._pending_events: dict[str, ClientUpdatePendingEvent] = {}
        self._lock = asyncio.Lock()
        # 外部消息发送无法由 state 文件事务回滚；投递与取消必须共享这把进程内锁，
        # 保证“读取 pending → 发送 → 确认”和取消清理之间具有明确先后顺序。
        self._delivery_coordination_lock = asyncio.Lock()
        self._loaded = False

    @property
    def delivery_coordination_lock(self) -> asyncio.Lock:
        """返回投递与取消订阅共享的进程内协调锁。"""

        return self._delivery_coordination_lock

    async def load(self) -> None:
        """幂等加载；缺失文件或已识别旧 schema 均视为空状态。"""

        if self._loaded:
            return
        async with self._lock:
            if not self._loaded:
                self._load_unlocked()

    async def get_baseline(self, source_id: str) -> ClientUpdateBaseline | None:
        """读取一个已登记 Source 的基线。"""

        normalized_source_id = _registered_source_id(source_id, self.registry)
        await self.load()
        return self._baselines.get(normalized_source_id)

    async def pending_events(self) -> tuple[ClientUpdatePendingEvent, ...]:
        """按首次生成顺序返回仍未完成的投递事件。"""

        await self.load()
        return tuple(self._pending_events.values())

    async def save_baseline(self, baseline: ClientUpdateBaseline) -> None:
        """保存 Source 基线并原子替换状态文件。"""

        normalized = _canonicalize_baseline(baseline, self.registry)
        async with self._lock:
            self._load_unlocked()
            previous = self._baselines.copy()
            self._baselines[normalized.source_id] = normalized
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

    async def save_baseline_with_pending_event(
        self,
        baseline: ClientUpdateBaseline,
        change: ClientUpdateChange,
        targets: Iterable[ClientUpdatePendingTarget],
    ) -> ClientUpdatePendingEvent | None:
        """原子保存基线和首次事件；无消息目的地时仅推进基线。"""

        normalized_baseline = _canonicalize_baseline(baseline, self.registry)
        normalized_change = canonicalize_client_update_change(
            change,
            registry=self.registry,
        )
        if normalized_baseline.last_change != normalized_change:
            raise ValueError("baseline.last_change 必须等于 change")
        event = ClientUpdatePendingEvent(normalized_change, tuple(targets))
        if event.targets and not event.pending_targets:
            raise ValueError("新建事件至少需要一个 pending 目标")

        async with self._lock:
            self._load_unlocked()
            existing = self._pending_events.get(event.event_key)
            if existing is not None and existing.change != event.change:
                raise ClientUpdateStateError("event key maps to different change")

            previous_baselines = self._baselines.copy()
            previous_pending_events = self._pending_events.copy()
            self._baselines[normalized_baseline.source_id] = normalized_baseline
            if existing is None and event.targets:
                self._pending_events[event.event_key] = event
                stored_event = event
            else:
                stored_event = existing
            try:
                self._save_unlocked()
            except OSError as error:
                self._baselines = previous_baselines
                self._pending_events = previous_pending_events
                raise ClientUpdateStateError(
                    "state file could not be replaced"
                ) from error
            except BaseException:
                self._baselines = previous_baselines
                self._pending_events = previous_pending_events
                raise
            return stored_event

    async def ensure_pending_event(
        self,
        change: ClientUpdateChange,
        targets: Iterable[ClientUpdatePendingTarget],
    ) -> ClientUpdatePendingEvent | None:
        """首次记录变化事件；同一事件键不会吸收后来出现的目标。"""

        normalized_change = canonicalize_client_update_change(
            change,
            registry=self.registry,
        )
        event = ClientUpdatePendingEvent(normalized_change, tuple(targets))
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
        """标记一个目的地成功；事件全部完成后立即清理。"""

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
            item = updated_targets[target_index]
            updated_targets[target_index] = ClientUpdatePendingTarget(
                origin=item.origin,
                uid=item.uid,
                bot_id=item.bot_id,
                target_ids=item.target_ids,
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
        """从一个事件中移除目的地；无剩余目标时清理事件。"""

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
        """从所有未完成事件移除一个订阅目的地。"""

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
            if type(schema_version) is not int:
                raise TypeError("state.schema_version must be an integer")
            if schema_version in _IGNORED_STATE_VERSIONS:
                logger.warning(
                    "[dnaby][client_update] 忽略不兼容的客户端更新 state v%s，按空状态启动",
                    schema_version,
                )
                self._baselines = {}
                self._pending_events = {}
                self._loaded = True
                return
            if schema_version != STATE_VERSION:
                raise ValueError("unsupported state schema version")

            raw_baselines = _require_mapping(
                _required(root, "baselines", "state"), "state.baselines"
            )
            baselines: dict[str, ClientUpdateBaseline] = {}
            for raw_source_id, raw_baseline in raw_baselines.items():
                source_id = _registered_source_id(raw_source_id, self.registry)
                baseline = _parse_baseline(
                    raw_baseline,
                    f"state.baselines[{raw_source_id!r}]",
                    self.registry,
                )
                if baseline.source_id != source_id:
                    raise ValueError("baseline key does not match version source")
                baselines[source_id] = baseline

            pending_events = _parse_pending_events(
                _required(root, "pending_events", "state"),
                self.registry,
            )
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
                source_id: _baseline_to_json(baseline)
                for source_id, baseline in sorted(self._baselines.items())
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
            temporary_path.unlink(missing_ok=True)


def canonicalize_client_update_change(
    change: ClientUpdateChange,
    *,
    registry: ClientUpdateRegistry = CLIENT_UPDATE_REGISTRY,
) -> ClientUpdateChange:
    """验证变化引用的 Source 与 Target 均来自 registry 且关系一致。"""

    if not isinstance(change, ClientUpdateChange):
        raise TypeError("change 必须是 ClientUpdateChange")
    if not isinstance(registry, ClientUpdateRegistry):
        raise TypeError("registry 必须是 ClientUpdateRegistry")
    source_id = _registered_source_id(change.source_id, registry)
    for target_id in change.target_ids:
        target = registry.resolve_target(target_id)
        if target.source_id != source_id:
            raise ValueError("变化 Target 与 Source 不一致")
    return change


def _canonicalize_baseline(
    baseline: ClientUpdateBaseline,
    registry: ClientUpdateRegistry,
) -> ClientUpdateBaseline:
    if not isinstance(baseline, ClientUpdateBaseline):
        raise TypeError("baseline 必须是 ClientUpdateBaseline")
    source_id = _registered_source_id(baseline.source_id, registry)
    if baseline.last_change is not None:
        change = canonicalize_client_update_change(
            baseline.last_change,
            registry=registry,
        )
        if change.source_id != source_id:
            raise ValueError("baseline.last_change 与基线 Source 不一致")
    return baseline


def _registered_source_id(value: object, registry: ClientUpdateRegistry) -> str:
    if not isinstance(value, str):
        raise TypeError("source_id 必须是字符串")
    return registry.resolve_source(value).source_id


def _normalize_target_id_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError("target_ids 必须是 Target ID 序列")
    try:
        target_ids = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("target_ids 必须是 Target ID 序列") from error
    if any(not isinstance(target_id, str) for target_id in target_ids):
        raise TypeError("target_ids 必须全部是字符串")
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("target_ids 不能重复")
    return cast(tuple[str, ...], target_ids)


def _normalize_target_ids(
    value: object,
    registry: ClientUpdateRegistry,
) -> tuple[str, ...]:
    target_ids = _normalize_target_id_values(value)
    for target_id in target_ids:
        registry.resolve_target(target_id)
    return target_ids


def _baseline_to_json(baseline: ClientUpdateBaseline) -> dict[str, Any]:
    return {
        "version": _version_to_json(baseline.version),
        "observed_at": baseline.observed_at.isoformat(),
        "last_change": (
            _change_to_json(baseline.last_change)
            if baseline.last_change is not None
            else None
        ),
    }


def _version_to_json(version: ClientSourceVersion) -> dict[str, Any]:
    return {
        "source_id": version.source_id,
        "version_text": version.version_text,
        "revision_id": version.revision_id,
        "order_key": (
            list(version.order_key)
            if isinstance(version.order_key, tuple)
            else version.order_key
        ),
        "provider_metadata": _provider_metadata_to_json(version.provider_metadata),
    }


def _provider_metadata_to_json(
    metadata: ClientSourceProviderMetadata | None,
) -> dict[str, Any] | None:
    if metadata is None:
        return None
    if isinstance(metadata, ManifestCdnVersionMetadata):
        return {
            "kind": ClientUpdateProviderKind.MANIFEST_CDN.value,
            "version_key": metadata.version_key,
            "patch_version": metadata.patch_version,
            "resource_version_dir": metadata.resource_version_dir,
        }
    if isinstance(metadata, AppStoreVersionMetadata):
        return {
            "kind": ClientUpdateProviderKind.APP_STORE.value,
            "track_id": metadata.track_id,
            "country": metadata.country,
            "release_date": metadata.release_date,
        }
    raise TypeError("不支持的 provider metadata")


def _change_to_json(change: ClientUpdateChange) -> dict[str, Any]:
    return {
        "previous": _version_to_json(change.previous),
        "current": _version_to_json(change.current),
        "history_complete": change.history_complete,
        "added_size_bytes": change.added_size_bytes,
        "target_ids": list(change.target_ids),
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
                "target_ids": list(target.target_ids),
                "status": target.status,
            }
            for target in event.targets
        ],
    }


def _parse_baseline(
    value: object,
    context: str,
    registry: ClientUpdateRegistry,
) -> ClientUpdateBaseline:
    entry = _require_mapping(value, context)
    observed_at_raw = _required(entry, "observed_at", context)
    if not isinstance(observed_at_raw, str):
        raise TypeError(f"{context}.observed_at must be a string")
    try:
        observed_at = datetime.fromisoformat(observed_at_raw)
    except ValueError as error:
        raise ValueError(f"{context}.observed_at is invalid") from error
    return ClientUpdateBaseline(
        version=_parse_version(
            _required(entry, "version", context),
            f"{context}.version",
            registry,
        ),
        observed_at=observed_at,
        last_change=_parse_change(
            _required(entry, "last_change", context),
            f"{context}.last_change",
            registry,
        ),
    )


def _parse_version(
    value: object,
    context: str,
    registry: ClientUpdateRegistry,
) -> ClientSourceVersion:
    entry = _require_mapping(value, context)
    source_id = _registered_source_id(
        _required(entry, "source_id", context),
        registry,
    )
    order_key = _parse_order_key(_required(entry, "order_key", context), context)
    metadata = _parse_provider_metadata(
        _required(entry, "provider_metadata", context),
        source_id,
        context,
        registry,
    )
    return ClientSourceVersion(
        source_id=source_id,
        version_text=cast(str, _required(entry, "version_text", context)),
        revision_id=cast(str, _required(entry, "revision_id", context)),
        order_key=order_key,
        provider_metadata=metadata,
    )


def _parse_order_key(value: object, context: str):
    if isinstance(value, list):
        if any(type(item) is not int for item in value):
            raise TypeError(f"{context}.order_key items must be integers")
        return tuple(cast(list[int], value))
    if value is None or type(value) is int or isinstance(value, str):
        return value
    raise TypeError(f"{context}.order_key is invalid")


def _parse_provider_metadata(
    value: object,
    source_id: str,
    context: str,
    registry: ClientUpdateRegistry,
) -> ClientSourceProviderMetadata | None:
    if value is None:
        return None
    entry = _require_mapping(value, f"{context}.provider_metadata")
    kind = _required(entry, "kind", f"{context}.provider_metadata")
    source = registry.resolve_source(source_id)
    if kind != source.provider_kind.value:
        raise ValueError(f"{context}.provider_metadata kind does not match Source")
    if source.provider_kind is ClientUpdateProviderKind.MANIFEST_CDN:
        return ManifestCdnVersionMetadata(
            version_key=cast(int, _required(entry, "version_key", context)),
            patch_version=cast(int, _required(entry, "patch_version", context)),
            resource_version_dir=cast(
                str | None, _required(entry, "resource_version_dir", context)
            ),
        )
    return AppStoreVersionMetadata(
        track_id=cast(int, _required(entry, "track_id", context)),
        country=cast(str, _required(entry, "country", context)),
        release_date=cast(str | None, _required(entry, "release_date", context)),
    )


def _parse_change(
    value: object,
    context: str,
    registry: ClientUpdateRegistry,
) -> ClientUpdateChange | None:
    if value is None:
        return None
    entry = _require_mapping(value, context)
    change = ClientUpdateChange(
        previous=_parse_version(
            _required(entry, "previous", context),
            f"{context}.previous",
            registry,
        ),
        current=_parse_version(
            _required(entry, "current", context),
            f"{context}.current",
            registry,
        ),
        history_complete=cast(bool, _required(entry, "history_complete", context)),
        added_size_bytes=cast(
            int | None, _required(entry, "added_size_bytes", context)
        ),
        target_ids=_normalize_target_ids(
            _required(entry, "target_ids", context),
            registry,
        ),
    )
    return canonicalize_client_update_change(change, registry=registry)


def _parse_pending_events(
    value: object,
    registry: ClientUpdateRegistry,
) -> dict[str, ClientUpdatePendingEvent]:
    if not isinstance(value, list):
        raise TypeError("state.pending_events must be a list")
    events: dict[str, ClientUpdatePendingEvent] = {}
    for index, raw_event in enumerate(value):
        context = f"state.pending_events[{index}]"
        entry = _require_mapping(raw_event, context)
        raw_event_key = _require_non_empty_string(
            _required(entry, "event_key", context), f"{context}.event_key"
        )
        change = _parse_change(
            _required(entry, "change", context),
            f"{context}.change",
            registry,
        )
        if change is None:
            raise ValueError(f"{context}.change must be an object")
        raw_targets = _required(entry, "targets", context)
        if not isinstance(raw_targets, list):
            raise TypeError(f"{context}.targets must be a list")
        event = ClientUpdatePendingEvent(
            change=change,
            targets=tuple(
                _parse_pending_target(
                    item,
                    f"{context}.targets[{target_index}]",
                    registry,
                )
                for target_index, item in enumerate(raw_targets)
            ),
        )
        if raw_event_key != event.event_key:
            raise ValueError(f"{context}.event_key does not match change")
        if event.event_key in events:
            raise ValueError("duplicate pending event key")
        events[event.event_key] = event
    return events


def _parse_pending_target(
    value: object,
    context: str,
    registry: ClientUpdateRegistry,
) -> ClientUpdatePendingTarget:
    entry = _require_mapping(value, context)
    status = _required(entry, "status", context)
    if not isinstance(status, str) or status not in _PENDING_STATUSES:
        raise ValueError(f"{context}.status is invalid")
    return ClientUpdatePendingTarget(
        origin=cast(str, _required(entry, "origin", context)),
        uid=cast(str, _required(entry, "uid", context)),
        bot_id=cast(str, _required(entry, "bot_id", context)),
        target_ids=_normalize_target_ids(
            _required(entry, "target_ids", context),
            registry,
        ),
        delivered=status == "delivered",
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
    "canonicalize_client_update_change",
]
