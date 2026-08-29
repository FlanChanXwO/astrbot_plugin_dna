"""Goal 2 D03：跨存储失败后的可重试边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.subscriptions import SubscriptionStore


@pytest.mark.asyncio
async def test_subscription_store_retries_after_corrupt_file_is_repaired(
    tmp_path: Path,
) -> None:
    """首次解析失败后，修复文件必须可被同一实例重新加载。"""

    path = tmp_path / "subscriptions.json"
    path.write_text("{ not json", encoding="utf-8")
    store = SubscriptionStore(path)

    with pytest.raises(RuntimeError):
        await store.load()

    path.write_text(
        json.dumps(
            [
                {
                    "type": "mh",
                    "unified_msg_origin": "origin-1",
                    "user_id": "user-1",
                    "uid": "user-1",
                }
            ]
        ),
        encoding="utf-8",
    )

    subscriptions = await store.get("mh")

    assert len(subscriptions) == 1
    assert subscriptions[0].user_id == "user-1"
