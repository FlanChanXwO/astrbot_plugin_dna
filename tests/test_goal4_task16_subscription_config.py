"""Goal 4 / Task 16：订阅启用状态与公告配置解耦。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.config.schema import generate_astrbot_schema
from src.infrastructure.config.settings import DnabySettings

# 先加载 notices fixture，避免 rendering/http 包在单文件收集时形成旧有循环导入。
from src.infrastructure.subscriptions import SubscriptionStore


@pytest.mark.asyncio
async def test_legacy_subscription_json_defaults_enabled_and_persists_flag(
    tmp_path: Path,
) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text(
        json.dumps(
            [
                {"type": "ann_subscribe", "unified_msg_origin": "group:old"},
                {
                    "type": "ann_subscribe",
                    "unified_msg_origin": "group:disabled",
                    "enabled": False,
                },
            ]
        ),
        encoding="utf-8",
    )

    store = SubscriptionStore(path)
    await store.load()
    subscriptions = await store.get("ann_subscribe")

    assert [sub.enabled for sub in subscriptions] == [True, False]


def test_legacy_announcement_groups_are_not_imported_into_typed_settings() -> None:
    raw = {"notifications": {"announcement_groups": {"secret-group": True}}}
    settings = DnabySettings.from_config(raw)

    assert not hasattr(settings.notifications, "announcement_groups")
    assert raw["notifications"]["announcement_groups"] == {"secret-group": True}
    assert "announcement_groups" not in generate_astrbot_schema()["notifications"]["items"]
