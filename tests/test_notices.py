"""Task 21 密函/公告读取的 fixture、隔离 DB 与渲染契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.entry.response import ImageResponse, PlainTextResponse
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import NoticesRenderer
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.notices import messages
from src.modules.notices.contracts import (
    AnnBlock,
    AnnDetail,
    AnnPost,
    AnnSnapshot,
    MhInstance,
    MhSection,
    MhSnapshot,
    NoticeRequest,
    NoticesFailureKind,
    NoticesTransportError,
)
from src.modules.notices.service import NoticesService
from src.modules.privacy import PrivacyService

UID = "1234567890123"


def _mh_snapshot() -> MhSnapshot:
    return MhSnapshot(
        sections=(
            MhSection(
                mh_type="role",
                type_name="角色",
                instances=(
                    MhInstance(instance_id=601, name="扼守"),
                    MhInstance(instance_id=602, name="拆解"),
                ),
            ),
            MhSection(
                mh_type="weapon",
                type_name="武器",
                instances=(MhInstance(instance_id=621, name="勘探"),),
            ),
        ),
    )


def _ann_snapshot() -> AnnSnapshot:
    return AnnSnapshot(
        posts=(
            AnnPost(post_id="1001", title="版本更新公告", time="2026-08-01", preview="pic://1"),
            AnnPost(post_id="1002", title="活动预告", time="2026-08-02"),
        ),
    )


class FakeNoticesTransport:
    """不触碰网络的密函/公告 transport fixture。"""

    def __init__(
        self,
        *,
        mh: MhSnapshot | None = None,
        ann_list: AnnSnapshot | None = None,
        ann_detail: AnnDetail | None = None,
        fail: NoticesTransportError | None = None,
    ) -> None:
        self.mh = mh if mh is not None else _mh_snapshot()
        self.ann_list = ann_list if ann_list is not None else _ann_snapshot()
        self.ann_detail = ann_detail if ann_detail is not None else _ann_detail_fixture()
        self.fail = fail
        self.calls: list[str] = []

    def _maybe_fail(self, name: str) -> None:
        self.calls.append(name)
        if self.fail is not None:
            raise self.fail

    async def get_mh(self, actor, uid, *, credential_user_id) -> MhSnapshot:
        self._maybe_fail("get_mh")
        assert credential_user_id == "user-1"
        return self.mh

    async def get_mh_any(self) -> MhSnapshot:
        self._maybe_fail("get_mh_any")
        return self.mh

    async def get_ann_list(self) -> AnnSnapshot:
        self._maybe_fail("get_ann_list")
        return self.ann_list

    async def get_ann_detail(self, post_id: str) -> AnnDetail:
        self._maybe_fail("get_ann_detail")
        if post_id == "1001":
            return self.ann_detail
        return AnnDetail(
            post_id=post_id,
            title=f"公告{post_id}",
            blocks=self.ann_detail.blocks,
        )


def _ann_detail_fixture() -> AnnDetail:
    return AnnDetail(
        post_id="1001",
        title="版本更新公告",
        blocks=(
            AnnBlock(kind="text", text="新版本将于今晚更新。"),
            AnnBlock(kind="image", image_url="https://cdn.test/pic.png"),
            AnnBlock(kind="text", text="感谢支持。"),
        ),
    )


async def _database_with_binding(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "notices.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            group_id="group-1",
            is_active=True,
        )
    return database


def _service(
    database: AsyncDatabase,
    transport: FakeNoticesTransport,
    *,
    allow_mention_query: bool = True,
    secret_simple_image: bool = False,
) -> NoticesService:
    return NoticesService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=allow_mention_query),
        NoticesRenderer(
            database.path.parent / "rendered",
            EncyclopediaResourceStore.from_root(database.path.parent / "resources"),
            simple_image=secret_simple_image,
        ),
        secret_simple_image=secret_simple_image,
    )


def _request(
    *,
    actor: EventActor | None = None,
    target_user_id: str | None = None,
    text: str = "密函",
    parameters: dict | None = None,
) -> NoticeRequest:
    return NoticeRequest(
        actor=actor if actor is not None else EventActor("user-1", "bot-1", "group-1"),
        target_user_id=target_user_id,
        text=text,
        parameters=parameters or {},
    )


@pytest.mark.asyncio
async def test_mh_renders_standard_card_by_default(tmp_path: Path) -> None:
    """密函默认渲染 1700×900 标准大图卡片。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport()
    service = _service(database, transport, secret_simple_image=False)

    response = await service.mh(_request())

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    with Image.open(Path(response.image)) as image:
        assert image.width == 1700
        assert image.height == 900
        assert image.convert("RGB").getbbox() == (0, 0, image.width, image.height)
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_renders_simple_card_when_configured(tmp_path: Path) -> None:
    """开启简单密函配置时渲染简洁分栏卡。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport()
    service = _service(database, transport, secret_simple_image=True)

    response = await service.mh(_request())

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    with Image.open(Path(response.image)) as image:
        assert image.width == 700
        assert image.height == 646
        assert image.convert("RGB").getbbox() == (0, 0, image.width, image.height)
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_empty_is_visible_not_found(tmp_path: Path) -> None:
    """密函数据为空时返回显式未找到。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport(mh=MhSnapshot())
    service = _service(database, transport)

    response = await service.mh(_request())

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.MH_NOT_FOUND
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_uid_invalid_when_unbound(tmp_path: Path) -> None:
    """无绑定返回显式 UID 提示。"""

    database = AsyncDatabase(tmp_path / "notices.sqlite3")
    await database.create_schema_for_tests()
    transport = FakeNoticesTransport()
    service = _service(database, transport)

    response = await service.mh(_request())

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.NOTICES_UID_INVALID
    assert transport.calls == []
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_transport_failure_is_visible_and_redacted(tmp_path: Path) -> None:
    """transport 错误只映射稳定文案，不回显上游正文。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport(
        fail=NoticesTransportError(
            NoticesFailureKind.NETWORK,
            resource="密函数据",
            detail="token=secret-mh",
        ),
    )
    service = _service(database, transport)

    response = await service.mh(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.transport_error(NoticesFailureKind.NETWORK) in response.text
    assert "secret-mh" not in response.text
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_list_returns_legacy_names(tmp_path: Path) -> None:
    """密函列表返回 legacy 名称清单，无需账号。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport())

    response = await service.mh_list(_request())

    assert isinstance(response, PlainTextResponse)
    assert "扼守" in response.text
    assert "拆解" in response.text


@pytest.mark.asyncio
async def test_ann_renders_list_image(tmp_path: Path) -> None:
    """公告无序号时渲染列表图，保留标题与时间。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport()
    service = _service(database, transport)

    response = await service.ann(_request(text="公告"))

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    with Image.open(Path(response.image)) as image:
        text = image.info["dnaby.text"]
        resources = json.loads(image.info["dnaby.resources"])
    assert "1. 版本更新公告" in text
    assert "2. 活动预告" in text
    assert any(item["kind"] == "ann_preview" and item["status"] == "provided" for item in resources)
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_detail_image_failure_returns_fixed_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公告详情图片失败时不生成占位图，只返回固定失败文案。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport()
    service = _service(database, transport)

    from src.infrastructure.rendering import notices as notices_rendering

    async def fail_image(*_: object) -> Image.Image:
        raise OSError("image unavailable")

    async def no_qr(*_: object) -> None:
        return None

    monkeypatch.setattr(notices_rendering, "_load_detail_image", fail_image)
    monkeypatch.setattr(notices_rendering, "load_qr_code", no_qr)

    response = await service.ann(_request(text="公告 1", parameters={"index": "1"}))

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.ANN_DETAIL_FAILED
    assert response.need_at is True
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_index_invalid_is_visible(tmp_path: Path) -> None:
    """公告序号不正确时返回显式提示。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport()
    service = _service(database, transport)

    response = await service.ann(_request(text="公告 99", parameters={"index": "99"}))

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.ANN_INDEX_INVALID
    assert transport.calls == ["get_ann_list"]
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_empty_list_is_visible(tmp_path: Path) -> None:
    """公告列表为空返回显式失败。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeNoticesTransport(ann_list=AnnSnapshot())
    service = _service(database, transport)

    response = await service.ann(_request(text="公告"))

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.ANN_LIST_FAILED
    await database.dispose()
