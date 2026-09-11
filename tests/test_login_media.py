"""内置登录页动态媒体的解析、路由和 generation lease 测试。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

from src.infrastructure.http.login_media import (
    LOGIN_MEDIA_VIDEO_ROUTE,
    LoginMediaService,
)
from src.infrastructure.http.login_server import LocalLoginServer


class _FakeLease:
    def __init__(self, root: Path) -> None:
        self.snapshot = SimpleNamespace(root=root)
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeResourceSnapshots:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.optional_calls = 0
        self.acquire_calls = 0
        self.leases: list[_FakeLease] = []

    @contextmanager
    def optional_lease(self):
        self.optional_calls += 1
        if self.root is None:
            yield None
            return
        lease = _FakeLease(self.root)
        try:
            yield lease.snapshot
        finally:
            lease.release()

    def acquire(self) -> _FakeLease:
        self.acquire_calls += 1
        if self.root is None:
            from src.infrastructure.resources.generation import ResourceGenerationError

            raise ResourceGenerationError("没有当前资源")
        lease = _FakeLease(self.root)
        self.leases.append(lease)
        return lease


def _write_valid_media(root: Path) -> None:
    video_dir = root / "videos" / "login"
    video_dir.mkdir(parents=True, exist_ok=True)
    # 最小合法媒体头：MP4 的 ftyp box。
    (video_dir / "background.mp4").write_bytes(
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
    )


def test_login_media_resolver_returns_fixed_url_for_valid_video(
    tmp_path: Path,
) -> None:
    _write_valid_media(tmp_path)
    snapshots = _FakeResourceSnapshots(tmp_path)
    service = LoginMediaService(snapshots)

    media = service.resolve(
        "http://localhost:6189/astrbot_plugin_dna",
        enabled=True,
    )

    assert media.video_url == (
        "http://localhost:6189/astrbot_plugin_dna/dna/login/media/background.mp4"
    )
    assert not getattr(media, "audio_url", None)
    assert str(tmp_path) not in (media.video_url or "")
    assert snapshots.optional_calls == 1


def test_login_media_resolver_disables_video_when_asset_is_missing_or_invalid(
    tmp_path: Path,
) -> None:
    service = LoginMediaService(_FakeResourceSnapshots(tmp_path))
    assert service.resolve("http://example.test/astrbot_plugin_dna", enabled=True).is_empty

    _write_valid_media(tmp_path)
    (tmp_path / "videos" / "login" / "background.mp4").write_bytes(b"not-mp4")
    assert service.resolve("http://example.test/astrbot_plugin_dna", enabled=True).is_empty


def test_login_media_disabled_or_missing_snapshot_does_not_touch_media_files(
    tmp_path: Path,
) -> None:
    _write_valid_media(tmp_path)
    snapshots = _FakeResourceSnapshots(tmp_path)
    service = LoginMediaService(snapshots)

    assert service.resolve("http://example.test/astrbot_plugin_dna", enabled=False).is_empty
    assert service.file_response("video", enabled=False).status == 404
    assert service.file_response("audio", enabled=True).status == 404
    assert snapshots.optional_calls == 0

    no_snapshot = _FakeResourceSnapshots(None)
    assert LoginMediaService(no_snapshot).resolve(
        "http://example.test/astrbot_plugin_dna",
        enabled=True,
    ).is_empty


def _media_routes(service: LoginMediaService):
    return [
        (LOGIN_MEDIA_VIDEO_ROUTE, lambda: service.file_response("video"), ["GET"], "视频"),
    ]


@pytest.mark.asyncio
async def test_login_media_routes_support_range_and_release_generation_lease(
    tmp_path: Path,
) -> None:
    _write_valid_media(tmp_path)
    snapshots = _FakeResourceSnapshots(tmp_path)
    service = LoginMediaService(snapshots)
    server = LocalLoginServer(
        _media_routes(service),
        host="127.0.0.1",
        port=0,
        base_path="",
    )

    await server.start()
    try:
        async with aiohttp.ClientSession() as client, client.get(
            f"{server.base_url}{LOGIN_MEDIA_VIDEO_ROUTE}",
            headers={"Range": "bytes=0-7"},
        ) as response:
            body = await response.read()
            assert response.status == 206
            assert response.headers["Content-Type"].startswith("video/mp4")
            assert response.headers["Content-Range"].startswith("bytes 0-7/")
            assert body == (tmp_path / "videos/login/background.mp4").read_bytes()[:8]
    finally:
        await server.stop()

    assert snapshots.acquire_calls == 1
    assert all(lease.released for lease in snapshots.leases)


@pytest.mark.asyncio
async def test_login_media_routes_never_accept_a_caller_supplied_path(
    tmp_path: Path,
) -> None:
    _write_valid_media(tmp_path)
    service = LoginMediaService(_FakeResourceSnapshots(tmp_path))
    server = LocalLoginServer(
        _media_routes(service),
        host="127.0.0.1",
        port=0,
        base_path="",
    )

    await server.start()
    try:
        async with aiohttp.ClientSession() as client, client.get(
            f"{server.base_url}/astrbot_plugin_dna/dna/login/media/other.mp4"
        ) as response:
            assert response.status == 404
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_login_page_exposes_media_only_when_setting_and_snapshot_allow_it(
    tmp_path: Path,
) -> None:
    from src.infrastructure.config.settings import LoginSettings
    from src.modules.account.login_flow import LoginFlowCoordinator

    class AccountTransport:
        async def request_sms_code(self, _mobile: str, _validation: str, _dev_code: str):
            return None

    class AccountService:
        async def login(self, _actor, _attempt):
            raise AssertionError("测试不应提交登录")

    actor = SimpleNamespace(
        user_id="user-1",
        bot_id="bot-1",
        group_id=None,
        unified_msg_origin="private:user-1",
    )

    _write_valid_media(tmp_path)
    snapshots = _FakeResourceSnapshots(tmp_path)
    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(
            transport="local",
            port=0,
        ),
        account_transport=AccountTransport(),
        resource_snapshots=snapshots,
    )
    await flow.start()
    try:
        login_response = await flow.begin(actor)
        async with aiohttp.ClientSession() as client, client.get(
            login_response.text.splitlines()[2].strip()
        ) as response:
            page = await response.text()
        assert 'id="backgroundVideo"' in page
        assert 'id="backgroundAudio"' not in page
        assert 'id="audioToggle"' not in page
        assert 'data-video-src="http://localhost:' in page
        assert "/astrbot_plugin_dna/dna/login/media/background.mp4" in page
        assert snapshots.optional_calls == 1
    finally:
        await flow.stop()

    no_media_snapshots = _FakeResourceSnapshots(tmp_path)
    static_flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(
            transport="local",
            port=0,
            dynamic_background=False,
        ),
        account_transport=AccountTransport(),
        resource_snapshots=no_media_snapshots,
    )
    await static_flow.start()
    try:
        login_response = await static_flow.begin(actor)
        async with aiohttp.ClientSession() as client, client.get(
            login_response.text.splitlines()[2].strip()
        ) as response:
            page = await response.text()
        assert 'id="backgroundVideo"' not in page
        assert "background.mp4" not in page
        assert no_media_snapshots.optional_calls == 0
    finally:
        await static_flow.stop()
