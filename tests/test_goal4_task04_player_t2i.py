"""Goal 4 / Task 04：玩家卡片 T2I 原始 bytes 直出契约。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.infrastructure.rendering import player as player_module
from src.infrastructure.rendering.artifact import RenderedArtifact
from src.infrastructure.rendering.artifact_store import (
    read_rendered_artifact,
    write_rendered_artifact,
)
from src.infrastructure.rendering.player import (
    PlayerRenderer,
    RenderedPlayerImage,
    ResourceMap,
)
from src.modules.player.contracts import DamageCalculation
from tests.test_player import (
    UID,
    _damage_fixture,
    _detail_fixture,
    _overview_fixture,
    _weapon_fixture,
)


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (13, 17), "#123456").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["overview", "detail"])
async def test_player_renderer_publishes_t2i_jpeg_bytes_without_pillow_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """玩家卡片应直接发布 T2I JPEG，不能回读后转 RGBA/PNG。"""

    payload = _jpeg_bytes()

    async def fake_overview(*args: object, **kwargs: object) -> bytes:
        return payload

    async def fake_detail(*args: object, **kwargs: object) -> tuple[bytes, None]:
        return payload, None

    monkeypatch.setattr(player_module, "draw_role_info_card_core", fake_overview)
    monkeypatch.setattr(player_module, "_draw_role_detail_card", fake_detail)
    monkeypatch.setattr(
        player_module.RoleShowForTool,
        "model_validate",
        lambda *_args, **_kwargs: pytest.fail(
            "typed 玩家渲染不应回拼完整 legacy RoleShowForTool"
        ),
    )
    monkeypatch.setattr(
        player_module.Image,
        "open",
        lambda *args, **kwargs: pytest.fail(
            "常规玩家 T2I 输出不应调用 Pillow Image.open"
        ),
    )

    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())
    if kind == "overview":
        rendered = await renderer.render_overview(_overview_fixture(), uid=UID)
    else:
        rendered = await renderer.render_detail(
            _detail_fixture(),
            [("近战", _weapon_fixture())],
            DamageCalculation.success(_damage_fixture()),
            uid=UID,
        )

    assert rendered.path.suffix == ".jpg"
    assert rendered.path.read_bytes() == payload
    assert rendered.sidecar is not None
    assert rendered.manifest is not None
    restored = read_rendered_artifact(rendered.path)
    assert restored.data == payload
    assert restored.media_type == "image/jpeg"
    assert restored.metadata["dnaby.text"]
    assert restored.metadata["dnaby.layout"]
    assert restored.metadata["dnaby.resources"]


@pytest.mark.asyncio
async def test_player_cache_preserves_jpeg_bytes_and_suffix(tmp_path: Path) -> None:
    from src.infrastructure.cache import CacheManager
    from src.modules.player.cache import PlayerCache

    payload = _jpeg_bytes()
    cache = PlayerCache(CacheManager(tmp_path / "cache"), tmp_path / "rendered")
    await cache.put_card(
        "player-key", payload, resource_version="v1", tags=("player_card",)
    )

    response = await cache.card_response("player-key")

    assert Path(response.image).suffix == ".jpg"
    assert Path(response.image).read_bytes() == payload
    assert response.sidecar is not None
    assert response.manifest is not None


@pytest.mark.asyncio
async def test_player_cache_rejects_legacy_png_after_jpeg_format_switch(
    tmp_path: Path,
) -> None:
    """格式切换后，旧 PNG 玩家卡片不能继续命中缓存。"""

    from src.infrastructure.cache import CacheManager
    from src.modules.player.cache import PlayerCache

    png_buffer = BytesIO()
    Image.new("RGBA", (1200, 7410), "#123456").save(png_buffer, format="PNG")
    manager = CacheManager(tmp_path / "cache")
    await manager.put(
        "player_card",
        "player-key",
        png_buffer.getvalue(),
        tags=("player_card", "overview"),
    )

    cache = PlayerCache(manager, tmp_path / "rendered")
    lookup = await cache.get_card("player-key")

    assert lookup.status == "miss"
    assert lookup.reason == "invalid_content"


def test_admin_preview_cleans_player_artifact_pair_and_keeps_media_type(
    tmp_path: Path,
) -> None:
    from src.modules.admin.preview import AdminPreviewService

    artifact = RenderedArtifact.from_bytes(_jpeg_bytes(), media_type="image/jpeg")
    stored = write_rendered_artifact(tmp_path / "rendered", artifact, prefix="player-")
    rendered = RenderedPlayerImage(
        path=Path(stored.image),
        width=artifact.width,
        height=artifact.height,
        text_lines=(),
        resources=(),
        sections=(),
        temporary=True,
        sidecar=Path(stored.sidecar) if stored.sidecar is not None else None,
        manifest=Path(stored.manifest) if stored.manifest is not None else None,
        media_type="image/jpeg",
    )

    response = AdminPreviewService._image_response(
        rendered,
        user_id="user-1",
        uid=UID,
        view="overview",
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data.content_type == "image/jpeg"
    assert not rendered.path.exists()
    assert rendered.sidecar is not None and not rendered.sidecar.exists()
    assert rendered.manifest is not None and not rendered.manifest.exists()
