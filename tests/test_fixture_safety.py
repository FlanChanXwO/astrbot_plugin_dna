"""测试 fixture 只包含结构保持的合成标识，不携带生产签名链接。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


FIXTURE = Path(__file__).parent / "fixtures" / "live-payload.json"

IDENTITY_KEYS = {
    "charEid",
    "conWeaponEid",
    "postId",
    "postUserId",
    "roleBoundId",
    "roleId",
    "uid",
    "userId",
    "user_id",
    "videoId",
    "weaponEid",
}


def _walk(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_live_payload_uses_synthetic_identity_and_urls() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert "auth_key=" not in text
    assert not re.search(r"herobox|dnabbs-vod|yingxiong", text, re.IGNORECASE)
    assert "https://example.invalid" in text

    for key, value in _walk(payload):
        if key in IDENTITY_KEYS:
            assert isinstance(value, str) and value.startswith("synthetic-"), (key, value)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            assert urlsplit(value).hostname == "example.invalid", (key, value)

    assert payload["scope"]["user_id"] == "synthetic-user-1"
    assert payload["scope"]["uid"] == "synthetic-uid-1"
    assert all(item["postId"] == "synthetic-post-1" for item in payload["ann_posts"])
