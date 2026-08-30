"""O12-B 密函缓存时序、失败隔离与订阅窗口契约。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.entry.event import EventActor
from src.entry.response import ImageResponse
from src.infrastructure.cache import CacheManager
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices import messages
from src.modules.notices.contracts import (
    MhSection,
    MhSnapshot,
    NoticesTransportError,
)
from src.modules.notices.mh_cache import (
    MH_CACHE_TYPE,
    MhSnapshotCache,
    MhSnapshotEnvelope,
    snapshot_fingerprint,
)
from src.modules.notices.service import NoticesService
from src.modules.privacy import PrivacyService
from tests.test_notices import FakeNoticesTransport, _mh_snapshot

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


class _FakeRenderer:
    def __init__(self, root: Path) -> None:
        self.path = root / "mh.png"

    async def render_mh(self, _snapshot: MhSnapshot, **_kwargs: object):
        return SimpleNamespace(path=self.path)


async def _database_with_binding(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "notices.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )
    return database


def _request() -> object:
    from src.modules.notices.contracts import NoticeRequest

    return NoticeRequest(
        actor=EventActor(
            "user-1",
            "bot-1",
            "group-1",
            unified_msg_origin="platform:group:g1",
        ),
        target_user_id=None,
        text="密函",
    )


def _service(
    database: AsyncDatabase,
    transport: FakeNoticesTransport,
    tmp_path: Path,
    *,
    now: list[datetime],
    cache: CacheManager,
    subscriptions: SubscriptionStore | None = None,
    pushed: list[tuple[str, object]] | None = None,
) -> NoticesService:
    async def push(origin: str, payload: object) -> None:
        if pushed is not None:
            pushed.append((origin, payload))

    return NoticesService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=True),
        _FakeRenderer(tmp_path),
        subscriptions=subscriptions or SubscriptionStore(tmp_path / "subscriptions.json"),
        push=push,
        cache_manager=cache,
        clock=lambda: now[0],
    )


@pytest.mark.asyncio
async def test_mh_before_half_hour_is_realtime_only_and_push_does_not_fetch(
    tmp_path: Path,
) -> None:
    """整点后半小时前允许实时查询，但不写缓存且不触发自动拉取。"""

    database = await _database_with_binding(tmp_path)
    now = [datetime(2026, 8, 30, 12, 10, tzinfo=SHANGHAI)]
    cache = CacheManager(tmp_path / "cache")
    transport = FakeNoticesTransport()
    service = _service(database, transport, tmp_path, now=now, cache=cache)

    response = await service.mh(_request())

    assert isinstance(response, ImageResponse)
    window_start = MhSnapshotCache.window_start(now[0])
    lookup = await cache.get(MH_CACHE_TYPE, MhSnapshotCache.cache_key(window_start))
    assert lookup.entry is None
    assert await service.push_mh_now() == 0
    assert transport.calls == ["get_mh"]
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_after_half_hour_caches_verified_snapshot_and_never_backfills_previous_hour(
    tmp_path: Path,
) -> None:
    """半小时后只缓存通过结构校验的当前小时快照，换小时不读旧键。"""

    database = await _database_with_binding(tmp_path)
    now = [datetime(2026, 8, 30, 12, 35, tzinfo=SHANGHAI)]
    cache = CacheManager(tmp_path / "cache")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object]] = []
    transport = FakeNoticesTransport()
    service = _service(
        database,
        transport,
        tmp_path,
        now=now,
        cache=cache,
        subscriptions=subscriptions,
        pushed=pushed,
    )
    await subscriptions.add(
        messages.MH_SUBSCRIBE,
        origin="platform:group:g1",
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-1",
        uid="user-1",
        extra_message="角色:扼守",
    )

    assert await service.push_mh_now() == 1
    first_window = MhSnapshotCache.window_start(now[0])
    first = await MhSnapshotCache(cache).get(first_window, now=now[0])
    assert first is not None
    assert first.window_start == first_window
    assert first.fetched_at == now[0]
    assert first.fingerprint
    assert pushed

    pushed.clear()
    now[0] += timedelta(hours=1)
    transport.fail = NoticesTransportError("network", resource="密函数据")

    assert await service.push_mh_now() == 0
    next_window = MhSnapshotCache.window_start(now[0])
    assert next_window != first_window
    assert await MhSnapshotCache(cache).get(next_window, now=now[0]) is None
    assert pushed == []
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_failed_or_empty_snapshot_is_not_cached_and_next_round_retries(
    tmp_path: Path,
) -> None:
    """上游失败或空分区不污染当前小时缓存，后续轮次仍重新尝试。"""

    database = await _database_with_binding(tmp_path)
    now = [datetime(2026, 8, 30, 18, 35, tzinfo=SHANGHAI)]
    cache = CacheManager(tmp_path / "cache")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object]] = []
    transport = FakeNoticesTransport(
        mh=MhSnapshot(
            sections=(
                MhSection(mh_type="role", type_name="角色", instances=()),
            ),
        ),
    )
    service = _service(
        database,
        transport,
        tmp_path,
        now=now,
        cache=cache,
        subscriptions=subscriptions,
        pushed=pushed,
    )
    await subscriptions.add(
        messages.MH_SUBSCRIBE,
        origin="platform:group:g1",
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-1",
        uid="user-1",
        extra_message="角色:扼守",
    )

    assert await service.push_mh_now() == 0
    window_start = MhSnapshotCache.window_start(now[0])
    assert await MhSnapshotCache(cache).get(window_start, now=now[0]) is None

    transport.mh = _mh_snapshot()
    assert await service.push_mh_now() == 1
    assert await MhSnapshotCache(cache).get(window_start, now=now[0]) is not None
    assert len(pushed) == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_subscription_window_filters_name_text_and_picture_targets(
    tmp_path: Path,
) -> None:
    """订阅级时间窗继续支持边界，并作用于名称、文本和图片目标。"""

    database = await _database_with_binding(tmp_path)
    now = [datetime(2026, 8, 30, 8, 35, tzinfo=UTC)]
    cache = CacheManager(tmp_path / "cache")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object]] = []
    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        now=now,
        cache=cache,
        subscriptions=subscriptions,
        pushed=pushed,
    )
    common = {
        "extra_data": "17:23",
        "user_id": "user-1",
        "bot_id": "bot-1",
        "group_id": "group-1",
    }
    await subscriptions.add(
        messages.MH_SUBSCRIBE,
        origin="platform:group:name",
        uid="user-1",
        extra_message="角色:扼守",
        **common,
    )
    await subscriptions.add(
        messages.MH_TEXT_SUBSCRIBE,
        origin="platform:group:text",
        **common,
    )
    await subscriptions.add(
        messages.MH_PIC_SUBSCRIBE,
        origin="platform:group:pic",
        **common,
    )

    assert await service.push_mh_now() == 0
    now[0] += timedelta(hours=1)
    assert await service.push_mh_now() == 3
    assert {origin for origin, _payload in pushed} == {
        "platform:group:name",
        "platform:group:text",
        "platform:group:pic",
    }
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_malformed_typed_section_is_not_cached_or_pushed(tmp_path: Path) -> None:
    """异常 typed 分区必须失败关闭，不能把结构异常写入缓存。"""

    database = await _database_with_binding(tmp_path)
    now = [datetime(2026, 8, 30, 18, 35, tzinfo=SHANGHAI)]
    cache = CacheManager(tmp_path / "cache")
    transport = FakeNoticesTransport(
        mh=MhSnapshot(sections=(object(),)),  # type: ignore[arg-type]
    )
    service = _service(database, transport, tmp_path, now=now, cache=cache)

    assert await service.push_mh_now() == 0
    window_start = MhSnapshotCache.window_start(now[0])
    assert await MhSnapshotCache(cache).get(window_start, now=now[0]) is None
    await database.dispose()


def test_mh_cache_rejects_snapshot_fetched_before_half_hour() -> None:
    """缓存 envelope 不能代表整点后半小时前的上游结果。"""

    window_start = datetime(2026, 8, 30, 12, 0, tzinfo=SHANGHAI)
    snapshot = _mh_snapshot()

    with pytest.raises(ValueError, match="半小时"):
        MhSnapshotEnvelope(
            snapshot=snapshot,
            window_start=window_start,
            fetched_at=window_start + timedelta(minutes=10),
            fingerprint=snapshot_fingerprint(snapshot),
        )


def test_removed_global_mh_config_is_discarded_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    """旧全局推送时间/缓存开关不再进入 typed 配置或生成 schema。"""

    from src.infrastructure.config import (
        generate_astrbot_schema,
        generate_legacy_schema,
    )
    from src.infrastructure.config.settings import DnabySettings, migrate_config_dict

    config = {
        "MHPushSubscribe": "07:08",
        "MHCache": False,
        "DNAUID配置": {"MHPushSubscribe": "06:07", "MHCache": True},
        "notifications": {"secret_push_time": "05:06", "secret_cache": False},
    }
    caplog.set_level("WARNING")

    migrated = migrate_config_dict(config)
    settings = DnabySettings.from_config(config)
    typed_schema = generate_astrbot_schema()
    legacy_schema = generate_legacy_schema()

    assert "secret_push_time" not in migrated["notifications"]
    assert "secret_cache" not in migrated["notifications"]
    assert not hasattr(settings.notifications, "secret_push_time")
    assert not hasattr(settings.notifications, "secret_cache")
    assert "secret_push_time" not in typed_schema["notifications"]["items"]
    assert "secret_cache" not in typed_schema["notifications"]["items"]
    assert "MHPushSubscribe" not in legacy_schema["DNAUID配置"]["items"]
    assert "MHCache" not in legacy_schema["DNAUID配置"]["items"]
    assert "secret_push_time" not in config.get("notifications", {})
    assert "secret_cache" not in config.get("notifications", {})
    assert "丢弃已移除的全局密函配置" in caplog.text


@pytest.mark.asyncio
async def test_mh_scheduler_is_fixed_at_half_hour_and_admin_schedule_is_not_mutable() -> None:
    """密函任务固定 HH:30，管理调度解析不再接受任意时间。"""

    from src.infrastructure.notices_scheduler import NoticesScheduler
    from src.infrastructure.scheduler_state import (
        MH_PUSH_AT,
        MH_PUSH_SCHEDULE,
        parse_scheduler_schedule,
    )

    class Notices:
        async def push_mh_now(self) -> int:
            return 0

        async def poll_ann_now(self) -> int:
            return 0

    scheduler = NoticesScheduler(Notices())
    snapshots = await scheduler.registry.list_snapshots()
    mh_task = next(item for item in snapshots if item.id == "dnaby_mh_push")

    assert scheduler.push_time == MH_PUSH_AT == (30, 0)
    assert mh_task.schedule == MH_PUSH_SCHEDULE == "hourly@30:00"
    assert parse_scheduler_schedule("dnaby_mh_push", MH_PUSH_SCHEDULE) == (
        MH_PUSH_SCHEDULE,
        MH_PUSH_AT,
    )
    with pytest.raises(ValueError):
        parse_scheduler_schedule("dnaby_mh_push", "hourly@07:08")
