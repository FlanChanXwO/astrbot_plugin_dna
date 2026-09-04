"""Goal 3 / Task 23：客户端更新消息品牌前缀。"""

from __future__ import annotations

from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientVersionSnapshot,
    messages,
)


def _snapshot(platform: ClientPlatform, patch_version: int) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
        platform=platform,
        region=ClientRegion.CN,
        version_key=patch_version,
        patch_version=patch_version,
        resource_version_dir=(
            str(patch_version) if platform is ClientPlatform.ANDROID else None
        ),
        major=1,
        minor=5,
        revamp=patch_version % 1000,
        patch_key=1,
    )


def test_client_update_result_messages_start_with_duet_night_abyss_branding() -> None:
    current = _snapshot(ClientPlatform.PC, 1410192)
    change = ClientUpdateChange(
        previous=_snapshot(ClientPlatform.PC, 1410191),
        current=current,
        added_size_bytes=15 * 1024**3,
        region=ClientRegion.CN,
        platform=ClientPlatform.PC,
    )

    current_text = messages.format_current(current)
    no_change_text = messages.format_no_change(current)
    change_text = messages.format_change(change)

    assert current_text.startswith("检测到二重螺旋国服 PC 客户端\n")
    assert no_change_text.startswith("检测到二重螺旋国服 PC 客户端\n")
    assert change_text.startswith("检测到二重螺旋国服 PC 客户端更新\n")
    assert len(no_change_text.splitlines()) == 3
    assert len(change_text.splitlines()) == 3
