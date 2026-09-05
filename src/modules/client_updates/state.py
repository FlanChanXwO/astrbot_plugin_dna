"""客户端更新基线与待投递事件的 typed JSON 状态边界。

状态文件只保存运行期最近一次成功观察、变化摘要和未完成的投递事件，不接触
AstrBot event 或订阅对象。所有读写都经过固定 schema 校验；写入先落到同目录
临时文件，再替换最终文件，避免进程在写入中断时留下半份 JSON。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientVersionSnapshot,
)

STATE_VERSION = 3
_LEGACY_STATE_VERSION = 1
_V2_STATE_VERSION = 2
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
        self._baselines: dict[tuple[ClientRegion, str], ClientUpdateBaseline] = {}
        self._pending_events: dict[str, ClientUpdatePendingEvent] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    @property
    def migration_backup_path(self) -> Path:
        """返回 State v2→v3 迁移保留的原始字节备份路径。"""

        return self.path.with_name(f"{self.path.name}.v2.bak")

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
        """读取一个区服/平台或固定渠道基线，未建立时返回 ``None``。"""

        candidates = _baseline_lookup_keys(region, platform)
        await self.load()
        for key in candidates:
            baseline = self._baselines.get(key)
            if baseline is not None:
                return baseline
        return None

    async def pending_events(self) -> tuple[ClientUpdatePendingEvent, ...]:
        """按首次生成顺序返回仍未完成的投递事件。"""

        await self.load()
        return tuple(self._pending_events.values())

    async def save_baseline(self, baseline: ClientUpdateBaseline) -> None:
        """保存基线并原子替换状态文件。"""

        if not isinstance(baseline, ClientUpdateBaseline):
            raise TypeError("baseline 必须是 ClientUpdateBaseline")
        key = _snapshot_baseline_key(baseline.snapshot)

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

    async def save_baseline_with_pending_event(
        self,
        baseline: ClientUpdateBaseline,
        change: ClientUpdateChange,
        targets: Iterable[ClientUpdatePendingTarget],
    ) -> ClientUpdatePendingEvent | None:
        """原子保存新基线和变化事件，避免基线先推进后丢失事件。

        ``targets`` 只在事件首次生成时生效；已有同键事件继续保留其固定目标。
        没有匹配目标时仍保存基线，但不会创建事件。
        """

        if not isinstance(baseline, ClientUpdateBaseline):
            raise TypeError("baseline 必须是 ClientUpdateBaseline")
        if not isinstance(change, ClientUpdateChange):
            raise TypeError("change 必须是 ClientUpdateChange")
        if baseline.last_change != change:
            raise ValueError("baseline.last_change 必须等于 change")
        key = _snapshot_baseline_key(baseline.snapshot)
        event = ClientUpdatePendingEvent(change, tuple(targets))
        if event.targets and not event.pending_targets:
            raise ValueError("新建事件至少需要一个 pending 目标")

        async with self._lock:
            self._load_unlocked()
            existing = self._pending_events.get(event.event_key)
            if existing is not None and existing.change != event.change:
                raise ClientUpdateStateError("event key maps to different change")

            previous_baselines = self._baselines.copy()
            previous_pending_events = self._pending_events.copy()
            self._baselines[key] = baseline
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
            raw_bytes = self.path.read_bytes()
            raw = json.loads(raw_bytes.decode("utf-8"))
            root = _require_mapping(raw, "state")
            schema_version = _required(root, "schema_version", "state")
            if type(schema_version) is not int or schema_version not in (
                _LEGACY_STATE_VERSION,
                _V2_STATE_VERSION,
                STATE_VERSION,
            ):
                raise ValueError("unsupported state schema version")
            raw_baselines = _required(root, "baselines", "state")
            if not isinstance(raw_baselines, Mapping):
                raise TypeError("state.baselines must be an object")

            baselines: dict[tuple[ClientRegion, str], ClientUpdateBaseline] = {}
            for raw_key, raw_baseline in raw_baselines.items():
                region, channel_id = _parse_state_baseline_key(
                    raw_key,
                    schema_version=schema_version,
                )
                baseline = _parse_baseline(
                    raw_baseline,
                    f"state.baselines[{raw_key!r}]",
                    channel_id=channel_id,
                    canonicalize=schema_version != STATE_VERSION,
                )
                key = (region, channel_id)
                if key in baselines:
                    raise ValueError("duplicate baseline channel key")
                baselines[key] = baseline

            if schema_version == _LEGACY_STATE_VERSION:
                raw_pending_events: object = []
            else:
                raw_pending_events = _required(root, "pending_events", "state")
            pending_events = _parse_pending_events(
                raw_pending_events,
                schema_version=schema_version,
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

        if schema_version != STATE_VERSION:
            previous_baselines = self._baselines
            previous_pending_events = self._pending_events
            self._baselines = baselines
            self._pending_events = pending_events
            try:
                self._preserve_legacy_state_unlocked(raw_bytes)
                self._save_unlocked()
            except OSError as error:
                self._baselines = previous_baselines
                self._pending_events = previous_pending_events
                raise ClientUpdateStateError(
                    "state migration could not be committed"
                ) from error
            except BaseException:
                self._baselines = previous_baselines
                self._pending_events = previous_pending_events
                raise

        self._baselines = baselines
        self._pending_events = pending_events
        self._loaded = True

    def _preserve_legacy_state_unlocked(self, raw_bytes: bytes) -> None:
        """迁移前保留原始字节；已有相同备份时保持幂等，不覆盖它。"""

        backup_path = self.migration_backup_path
        if backup_path.exists():
            if backup_path.read_bytes() != raw_bytes:
                raise OSError("legacy state backup does not match source")
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = backup_path.with_name(f".{backup_path.name}.tmp")
        try:
            temporary_path.write_bytes(raw_bytes)
            temporary_path.replace(backup_path)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass

    def _save_unlocked(self) -> None:
        payload = {
            "schema_version": STATE_VERSION,
            "baselines": {
                _format_baseline_key(region, channel_or_platform): _baseline_to_json(
                    baseline
                )
                for (region, channel_or_platform), baseline in sorted(
                    self._baselines.items(),
                    key=lambda item: (item[0][0].value, item[0][1]),
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
    platform_or_channel: ClientPlatform | str,
) -> tuple[ClientRegion, str]:
    try:
        normalized_region = ClientRegion(region)
    except (TypeError, ValueError) as error:
        raise ValueError("不支持的客户端区服") from error

    try:
        return normalized_region, ClientPlatform(platform_or_channel).value
    except (TypeError, ValueError):
        channel = _resolve_channel(platform_or_channel)
        if channel.region is not normalized_region:
            raise ValueError("客户端更新渠道与区服不一致")
        return normalized_region, channel.channel_id


def _baseline_lookup_keys(
    region: ClientRegion | str,
    platform_or_channel: ClientPlatform | str,
) -> tuple[tuple[ClientRegion, str], ...]:
    normalized_region = ClientRegion(region)
    if isinstance(platform_or_channel, str):
        try:
            platform = ClientPlatform(platform_or_channel)
        except ValueError:
            return (_baseline_key(normalized_region, platform_or_channel),)
        channel_id = _default_channel_id(platform)
        return (
            (normalized_region, channel_id),
            (normalized_region, platform.value),
        )
    platform = ClientPlatform(platform_or_channel)
    channel_id = _default_channel_id(platform)
    return (
        (normalized_region, channel_id),
        (normalized_region, platform.value),
    )


def _snapshot_baseline_key(
    snapshot: ClientVersionSnapshot,
) -> tuple[ClientRegion, str]:
    if snapshot.channel_id is None:
        channel_id = _canonical_channel_id_for_identity(
            snapshot.region,
            snapshot.platform.value,
        )
        return snapshot.region, channel_id
    channel = _resolve_channel(snapshot.channel_id)
    if (
        channel.region is not snapshot.region
        or channel.platform is not snapshot.platform
    ):
        raise ValueError("snapshot channel identity differs")
    return snapshot.region, channel.channel_id


def _format_baseline_key(region: ClientRegion, channel_or_platform: str) -> str:
    return f"{region.value}:{channel_or_platform}"


def _format_event_key(
    region: ClientRegion,
    channel_id: str,
    previous_patch_version: int,
    current_patch_version: int,
) -> str:
    return (
        f"{region.value}:{channel_id}:{previous_patch_version}:{current_patch_version}"
    )


def _parse_baseline_key(value: object) -> tuple[ClientRegion, str]:
    if not isinstance(value, str):
        raise TypeError("baseline key must be a string")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("baseline key must contain region and platform")
    return _baseline_key(parts[0], parts[1])


def _parse_state_baseline_key(
    value: object,
    *,
    schema_version: int,
) -> tuple[ClientRegion, str]:
    """读取状态 key，并在 v1/v2 中映射旧 platform 身份。"""

    region, identity = _parse_baseline_key(value)
    if schema_version == STATE_VERSION:
        if not _is_registered_channel_id(identity):
            raise ValueError("state v3 baseline key must use a channel ID")
        channel = _resolve_channel(identity)
        if channel.region is not region:
            raise ValueError("baseline channel and region differ")
        return region, channel.channel_id
    return region, _canonical_channel_id_for_identity(region, identity)


def _canonical_channel_id_for_identity(
    region: ClientRegion,
    identity: str,
) -> str:
    """把旧 platform 或固定 channel 身份归一化为 v3 channel ID。"""

    try:
        platform = ClientPlatform(identity)
    except (TypeError, ValueError):
        channel = _resolve_channel(identity)
        if channel.region is not region:
            raise ValueError("客户端更新渠道与区服不一致")
        return channel.channel_id

    channel_id = _default_channel_id(platform)
    channel = _resolve_channel(channel_id)
    if channel.region is not region:
        raise ValueError("客户端平台与区服不一致")
    return channel.channel_id


def _default_channel_id(platform: ClientPlatform) -> str:
    from .channels import default_channel_id_for_platform

    return default_channel_id_for_platform(platform)


def _resolve_channel(channel_id: str):
    from .channels import resolve_client_update_channel

    return resolve_client_update_channel(channel_id)


def _is_registered_channel_id(value: str) -> bool:
    from .channels import CLIENT_UPDATE_CHANNELS

    return value in CLIENT_UPDATE_CHANNELS


def _platform_for_identity(channel_or_platform: str) -> ClientPlatform:
    try:
        return ClientPlatform(channel_or_platform)
    except ValueError:
        return _resolve_channel(channel_or_platform).platform


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
    payload: dict[str, Any] = {
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
    if snapshot.channel_id is not None:
        payload["channel_id"] = snapshot.channel_id
    return payload


def _change_to_json(change: ClientUpdateChange) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "region": change.region.value,
        "platform": change.platform.value,
        "previous": _snapshot_to_json(change.previous),
        "current": _snapshot_to_json(change.current),
        "added_size_bytes": change.added_size_bytes,
    }
    if change.channel_id != change.platform.value:
        payload["channel_id"] = change.channel_id
    return payload


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


def _parse_baseline(
    value: object,
    context: str,
    *,
    channel_id: str,
    canonicalize: bool,
) -> ClientUpdateBaseline:
    entry = _require_mapping(value, context)
    snapshot = _align_snapshot_to_channel(
        _parse_snapshot(_required(entry, "snapshot", context), f"{context}.snapshot"),
        channel_id,
        f"{context}.snapshot",
        canonicalize=canonicalize,
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
    if last_change is not None:
        last_change = _align_change_to_channel(
            last_change,
            channel_id,
            f"{context}.last_change",
            canonicalize=canonicalize,
        )
    return ClientUpdateBaseline(
        snapshot=snapshot,
        observed_at=observed_at,
        last_change=last_change,
    )


def _align_snapshot_to_channel(
    snapshot: ClientVersionSnapshot,
    channel_id: str,
    context: str,
    *,
    canonicalize: bool,
) -> ClientVersionSnapshot:
    channel = _resolve_channel(channel_id)
    if snapshot.region is not channel.region:
        raise ValueError(f"{context}.region does not match channel")
    if snapshot.platform is not channel.platform:
        raise ValueError(f"{context}.platform does not match channel")
    if snapshot.channel_id is not None:
        if canonicalize:
            snapshot_channel_id = _canonical_channel_id_for_identity(
                snapshot.region,
                snapshot.channel_id,
            )
            if snapshot_channel_id != channel_id:
                raise ValueError(f"{context}.channel_id does not match channel")
        elif snapshot.channel_id != channel_id:
            raise ValueError(f"{context}.channel_id does not match channel")
    if canonicalize:
        return replace(snapshot, channel_id=channel_id)
    return snapshot


def _align_change_to_channel(
    change: ClientUpdateChange,
    channel_id: str,
    context: str,
    *,
    canonicalize: bool,
) -> ClientUpdateChange:
    channel = _resolve_channel(channel_id)
    if change.region is not channel.region:
        raise ValueError(f"{context}.region does not match channel")
    if change.platform is not channel.platform:
        raise ValueError(f"{context}.platform does not match channel")
    previous = _align_snapshot_to_channel(
        change.previous,
        channel_id,
        f"{context}.previous",
        canonicalize=canonicalize,
    )
    current = _align_snapshot_to_channel(
        change.current,
        channel_id,
        f"{context}.current",
        canonicalize=canonicalize,
    )
    if canonicalize:
        return ClientUpdateChange(
            previous=previous,
            current=current,
            added_size_bytes=change.added_size_bytes,
            region=channel.region,
            platform=channel.platform,
            channel_id=channel_id,
        )
    if change.channel_id not in (channel_id, channel.platform.value):
        raise ValueError(f"{context}.channel_id does not match channel")
    return change


def _parse_pending_events(
    value: object,
    *,
    schema_version: int,
) -> dict[str, ClientUpdatePendingEvent]:
    if not isinstance(value, list):
        raise TypeError("state.pending_events must be a list")
    events: dict[str, ClientUpdatePendingEvent] = {}
    for index, raw_event in enumerate(value):
        event = _parse_pending_event(
            raw_event,
            f"state.pending_events[{index}]",
            schema_version=schema_version,
        )
        if event.event_key in events:
            raise ValueError("duplicate pending event key")
        events[event.event_key] = event
    return events


def _parse_pending_event(
    value: object,
    context: str,
    *,
    schema_version: int,
) -> ClientUpdatePendingEvent:
    entry = _require_mapping(value, context)
    raw_event_key = _required(entry, "event_key", context)
    if not isinstance(raw_event_key, str) or not raw_event_key:
        raise ValueError(f"{context}.event_key must be a non-empty string")
    (
        region,
        identity,
        previous_patch_version,
        current_patch_version,
    ) = _parse_event_key(raw_event_key, context, schema_version=schema_version)
    raw_change = _parse_change(_required(entry, "change", context), f"{context}.change")
    if raw_change is None:
        raise ValueError(f"{context}.change must be an object")
    channel_id = _canonical_channel_id_for_identity(region, identity)
    change = _align_change_to_channel(
        raw_change,
        channel_id,
        f"{context}.change",
        canonicalize=(
            schema_version != STATE_VERSION or _is_registered_channel_id(identity)
        ),
    )
    if change.previous.patch_version != previous_patch_version:
        raise ValueError(f"{context}.event_key previous patch does not match change")
    if change.current.patch_version != current_patch_version:
        raise ValueError(f"{context}.event_key current patch does not match change")
    raw_targets = _required(entry, "targets", context)
    if not isinstance(raw_targets, list):
        raise TypeError(f"{context}.targets must be a list")
    event = ClientUpdatePendingEvent(
        change,
        tuple(
            _parse_pending_target(target, f"{context}.targets[{index}]")
            for index, target in enumerate(raw_targets)
        ),
    )
    expected_event_key = (
        event.event_key
        if schema_version == STATE_VERSION
        else _format_event_key(
            region,
            channel_id,
            previous_patch_version,
            current_patch_version,
        )
    )
    if event.event_key != expected_event_key or (
        schema_version == STATE_VERSION and raw_event_key != expected_event_key
    ):
        raise ValueError(f"{context}.event_key does not match change")
    if not event.targets or not event.pending_targets:
        raise ValueError(f"{context} must contain a pending target")
    return event


def _parse_event_key(
    value: str,
    context: str,
    *,
    schema_version: int,
) -> tuple[ClientRegion, str, int, int]:
    parts = value.split(":")
    if len(parts) != 4 or not all(parts[:2]):
        raise ValueError(f"{context}.event_key has invalid shape")
    try:
        region = ClientRegion(parts[0])
    except ValueError as error:
        raise ValueError(f"{context}.event_key region is invalid") from error
    identity = parts[1]
    try:
        previous_patch_version = int(parts[2])
        current_patch_version = int(parts[3])
    except ValueError as error:
        raise ValueError(f"{context}.event_key patch version is invalid") from error
    if previous_patch_version < 0 or current_patch_version <= previous_patch_version:
        raise ValueError(f"{context}.event_key patch range is invalid")

    if schema_version == STATE_VERSION and not _is_registered_channel_id(identity):
        try:
            ClientPlatform(identity)
        except ValueError:
            _resolve_channel(identity)
    return region, identity, previous_patch_version, current_patch_version


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
        channel_id=cast(str | None, entry.get("channel_id")),
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
        channel_id=cast(str | None, entry.get("channel_id")),
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
