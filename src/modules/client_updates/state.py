"""客户端更新观察基线的 typed JSON 状态边界。

状态文件只保存运行期最近一次成功观察和变化摘要，不接触 AstrBot event 或订阅
对象。所有读写都经过固定 schema 校验；写入先落到同目录临时文件，再替换最终
文件，避免进程在写入中断时留下半份 JSON。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
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

STATE_VERSION = 1


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


class ClientUpdateStateStore:
    """版本化客户端更新状态的读写入口。

    ``path`` 由 bootstrap 根据 ``StarTools.get_data_dir`` 注入；本类不自行决定
    运行期目录。单进程内的写操作通过 asyncio 锁串行化，并在内存和磁盘写入
    失败时恢复原有基线。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._baselines: dict[
            tuple[ClientRegion, ClientPlatform], ClientUpdateBaseline
        ] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        """幂等加载状态文件；缺失文件代表尚未建立任何基线。"""

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
            if type(schema_version) is not int or schema_version != STATE_VERSION:
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
    "ClientUpdateStateError",
    "ClientUpdateStateStore",
]
