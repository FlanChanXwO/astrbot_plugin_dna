"""O10 玩家数据、角色卡片缓存和资源版本测试。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.entry.event import EventActor
from src.entry.response import ChainResponse, ImageResponse, PlainTextResponse
from src.infrastructure.cache import CacheManager
from src.modules.player import messages
from src.modules.player.cache import PlayerCache
from src.modules.player.contracts import (
    PlayerCommandRequest,
    PlayerFailureKind,
    PlayerTransportError,
)
from src.modules.player.service import PlayerService
from src.modules.privacy import PrivacyService
from tests.test_player import (
    FixturePlayerTransport,
    _database_with_binding,
    _detail_fixture,
    _overview_fixture,
    _weapon_fixture,
)


class CountingTransport(FixturePlayerTransport):
    """记录每类远端请求次数，并允许测试刷新失败。"""

    def __init__(self) -> None:
        super().__init__(_overview_fixture(), _detail_fixture(), _weapon_fixture())
        self.overview_calls = 0
        self.role_detail_calls = 0
        self.weapon_detail_calls = 0
        self.damage_calls = 0
        self.fail_overview = False
        self.fail_role_detail = False

    async def get_overview(self, *args, **kwargs):
        self.overview_calls += 1
        if self.fail_overview:
            raise PlayerTransportError(PlayerFailureKind.SERVER, resource="角色概览")
        return await super().get_overview(*args, **kwargs)

    async def get_role_detail(self, *args, **kwargs):
        self.role_detail_calls += 1
        if self.fail_role_detail:
            raise PlayerTransportError(PlayerFailureKind.SERVER, resource="角色详情")
        return await super().get_role_detail(*args, **kwargs)

    async def get_weapon_detail(self, *args, **kwargs):
        self.weapon_detail_calls += 1
        return await super().get_weapon_detail(*args, **kwargs)

    async def calculate_damage(self, *args, **kwargs):
        self.damage_calls += 1
        return await super().calculate_damage(*args, **kwargs)


class CountingRenderer:
    """用可比较的 PNG 代替真实大图，保留 renderer 的不完整标记。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.overview_calls = 0
        self.detail_calls = 0
        self.incomplete = False

    def _write(self, prefix: str, text: str):
        call_number = self.overview_calls + self.detail_calls
        path = self.root / f"{prefix}-{call_number}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        info = PngInfo()
        info.add_text("dnaby.text", text)
        Image.new("RGBA", (8, 8), (call_number, 20, 30, 255)).save(
            path,
            format="PNG",
            pnginfo=info,
        )
        return SimpleNamespace(
            path=path,
            width=8,
            height=8,
            text_lines=(text,),
            resources=(),
            sections=(),
            original_image_path=None,
            temporary=True,
            incomplete=self.incomplete,
        )

    async def render_overview(self, overview, **kwargs):
        self.overview_calls += 1
        return self._write("overview", overview.role_name)

    async def render_detail(self, role_detail, *_args, **kwargs):
        self.detail_calls += 1
        return self._write("detail", role_detail.char_name)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


class SnapshotCoordinator:
    def __init__(self, version: str) -> None:
        self.current_snapshot = SimpleNamespace(
            commit_sha=version,
            content_sha256=f"content-{version}",
            resource_version=f"manifest-{version}",
        )

    @contextmanager
    def bind_renderer(self, renderer, _purpose: str):
        yield renderer


def _request(*, detail: bool = False) -> PlayerCommandRequest:
    parameters = {}
    if detail:
        parameters = {"char_name": "角色甲", "weapon_name_1": "近战甲"}
    return PlayerCommandRequest(
        actor=EventActor("user-1", "bot-1", "group-1"),
        target_user_id=None,
        parameters=parameters,
    )


async def _service(tmp_path: Path, clock: MutableClock, *, snapshots=None):
    database = await _database_with_binding(tmp_path)
    transport = CountingTransport()
    renderer = CountingRenderer(tmp_path / "rendered")
    cache = PlayerCache(
        CacheManager(tmp_path / "cache"),
        tmp_path / "rendered",
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        renderer,
        cache=cache,
        clock=clock,
        resource_snapshots=snapshots,
    )
    return database, transport, renderer, cache, service


@pytest.mark.asyncio
async def test_overview_fresh_cache_reuses_data_and_card(tmp_path: Path) -> None:
    clock = MutableClock()
    database, transport, renderer, _cache, service = await _service(tmp_path, clock)
    try:
        first = await service.role_overview(_request())
        clock.value += timedelta(minutes=29)
        second = await service.role_overview(_request())

        assert isinstance(first, ImageResponse)
        assert isinstance(second, ImageResponse)
        assert second.incomplete is False
        assert transport.overview_calls == 1
        assert renderer.overview_calls == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_overview_stale_data_refreshes_and_replaces_card(tmp_path: Path) -> None:
    clock = MutableClock()
    database, transport, renderer, _cache, service = await _service(tmp_path, clock)
    try:
        await service.role_overview(_request())
        transport.overview = transport.overview.model_copy(update={"role_name": "刷新后的玩家"})
        clock.value += timedelta(minutes=31)

        response = await service.role_overview(_request())

        assert isinstance(response, ImageResponse)
        assert transport.overview_calls == 2
        assert renderer.overview_calls == 2
        assert "刷新后的玩家" in Image.open(response.image).info["dnaby.text"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_overview_stale_refresh_failure_uses_complete_old_card(tmp_path: Path) -> None:
    clock = MutableClock()
    database, transport, renderer, _cache, service = await _service(tmp_path, clock)
    try:
        first = await service.role_overview(_request())
        old_bytes = Path(first.image).read_bytes()
        clock.value += timedelta(minutes=31)
        transport.fail_overview = True

        response = await service.role_overview(_request())

        assert isinstance(response, ChainResponse)
        warning, image = response.components
        assert isinstance(warning, PlainTextResponse)
        assert warning.text == messages.PLAYER_CACHE_STALE
        assert isinstance(image, ImageResponse)
        assert Path(image.image).read_bytes() == old_bytes
        assert transport.overview_calls == 2
        assert renderer.overview_calls == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_incomplete_card_is_sent_but_never_cached(tmp_path: Path) -> None:
    clock = MutableClock()
    database, _transport, renderer, _cache, service = await _service(tmp_path, clock)
    try:
        renderer.incomplete = True
        first = await service.role_overview(_request())
        assert isinstance(first, ImageResponse)
        assert first.incomplete is True

        renderer.incomplete = False
        second = await service.role_overview(_request())
        third = await service.role_overview(_request())

        assert isinstance(second, ImageResponse)
        assert second.incomplete is False
        assert isinstance(third, ImageResponse)
        assert third.incomplete is False
        assert renderer.overview_calls == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_detail_fresh_cache_reuses_full_bundle_and_card(tmp_path: Path) -> None:
    clock = MutableClock()
    database, transport, renderer, _cache, service = await _service(tmp_path, clock)
    try:
        await service.role_detail(_request(detail=True))
        clock.value += timedelta(minutes=29)
        response = await service.role_detail(_request(detail=True))

        assert isinstance(response, ImageResponse)
        assert transport.overview_calls == 1
        assert transport.role_detail_calls == 1
        assert transport.weapon_detail_calls == 2
        assert transport.damage_calls == 1
        assert renderer.detail_calls == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_detail_stale_refresh_failure_uses_complete_old_card(tmp_path: Path) -> None:
    clock = MutableClock()
    database, transport, renderer, _cache, service = await _service(tmp_path, clock)
    try:
        first = await service.role_detail(_request(detail=True))
        old_bytes = Path(first.image).read_bytes()
        clock.value += timedelta(minutes=31)
        transport.fail_role_detail = True

        response = await service.role_detail(_request(detail=True))

        assert isinstance(response, ChainResponse)
        warning, image = response.components
        assert isinstance(warning, PlainTextResponse)
        assert warning.text == messages.PLAYER_CACHE_STALE
        assert isinstance(image, ImageResponse)
        assert Path(image.image).read_bytes() == old_bytes
        assert renderer.detail_calls == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_resource_version_change_only_rerenders_card(tmp_path: Path) -> None:
    clock = MutableClock()
    snapshots = SnapshotCoordinator("v1")
    database, transport, renderer, _cache, service = await _service(
        tmp_path,
        clock,
        snapshots=snapshots,
    )
    try:
        await service.role_overview(_request())
        snapshots.current_snapshot = SimpleNamespace(
            commit_sha="v2",
            content_sha256="content-v2",
            resource_version="manifest-v2",
        )
        response = await service.role_overview(_request())

        assert isinstance(response, ImageResponse)
        assert transport.overview_calls == 1
        assert renderer.overview_calls == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_cache_invalidate_matches_all_filters_without_touching_other_entries(
    tmp_path: Path,
) -> None:
    manager = CacheManager(tmp_path / "cache")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await manager.put(
        "player_card",
        "a",
        b"a",
        resource_version="v1",
        tags=("identity:a", "role:101"),
        now=now,
    )
    await manager.put(
        "player_card",
        "b",
        b"b",
        resource_version="v1",
        tags=("identity:b", "role:101"),
        now=now,
    )
    await manager.put(
        "player_card",
        "c",
        b"c",
        resource_version="v1",
        tags=("identity:a", "role:102"),
        now=now,
    )

    assert await manager.invalidate(
        "player_card",
        tags=("identity:a", "role:101"),
        resource_version="v1",
    ) == 1
    assert (await manager.get("player_card", "a", now=now)).status == "miss"
    assert (await manager.get("player_card", "b", now=now)).status == "fresh"
    assert (await manager.get("player_card", "c", now=now)).status == "fresh"
