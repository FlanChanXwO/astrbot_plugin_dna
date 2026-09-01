"""Goal 4 / Task 11：网络图片、二维码与公告详情的 single-flight。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.http.concurrency import RequestConcurrencyGate
from src.infrastructure.http.notices import DnaApiNoticesTransport
from src.infrastructure.rendering import notices


@pytest.mark.asyncio
async def test_source_image_same_url_shares_one_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RequestConcurrencyGate(4)
    calls = 0
    release = asyncio.Event()

    async def fake_download(
        _url: str, target: Path, _name: str, **_kwargs: object
    ) -> Path:
        nonlocal calls
        calls += 1
        await release.wait()
        result = target / _name
        result.write_bytes(b"image-bytes")
        return result

    monkeypatch.setattr(notices, "download", fake_download)
    tasks = [
        asyncio.create_task(
            notices._fetch_image_bytes("https://img.test/a.png", request_gate=gate)
        )
        for _ in range(5)
    ]
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(*tasks) == [b"image-bytes"] * 5
    assert calls == 1


@pytest.mark.asyncio
async def test_qr_same_url_shares_one_image_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RequestConcurrencyGate(4)
    calls = 0
    image = Image.new("RGBA", (220, 220), "white")

    async def fake_fetch(_path: Path, _url: str, **_kwargs: object) -> Image.Image:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return image

    monkeypatch.setattr(notices, "_fetch_image", fake_fetch)
    results = await asyncio.gather(
        *(
            notices._load_qr_code("https://qr.test/a", request_gate=gate)
            for _ in range(4)
        )
    )
    assert len(results) == 4
    assert calls == 1


@pytest.mark.asyncio
async def test_announcement_detail_same_post_shares_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RequestConcurrencyGate(4)
    calls = 0

    async def fake_detail(_post_id: str):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return SimpleNamespace(
            is_success=True,
            data={
                "postDetail": {
                    "postId": "p1",
                    "postTitle": "公告",
                    "postContent": [{"contentType": 1, "content": "正文"}],
                }
            },
        )

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_post_detail", fake_detail)
    transport = DnaApiNoticesTransport(None, request_gate=gate)  # type: ignore[arg-type]
    results = await asyncio.gather(*(transport.get_ann_detail("p1") for _ in range(4)))
    assert [item.post_id for item in results] == ["p1"] * 4
    assert calls == 1


@pytest.mark.asyncio
async def test_source_image_failure_cleans_singleflight_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RequestConcurrencyGate(2)
    calls = 0

    async def fake_download(
        _url: str, target: Path, _name: str, **_kwargs: object
    ) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary")
        result = target / _name
        result.write_bytes(b"ok")
        return result

    monkeypatch.setattr(notices, "download", fake_download)
    with pytest.raises(OSError, match="temporary"):
        await notices._fetch_image_bytes(
            "https://img.test/retry.png", request_gate=gate
        )
    assert (
        await notices._fetch_image_bytes(
            "https://img.test/retry.png", request_gate=gate
        )
        == b"ok"
    )
    assert calls == 2


@pytest.mark.asyncio
async def test_source_image_different_urls_remain_parallel_under_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RequestConcurrencyGate(2)
    active = 0
    peak = 0

    async def fake_download(
        _url: str, target: Path, name: str, **_kwargs: object
    ) -> Path:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        result = target / name
        result.write_bytes(b"ok")
        active -= 1
        return result

    monkeypatch.setattr(notices, "download", fake_download)
    await asyncio.gather(
        notices._fetch_image_bytes("https://img.test/a.png", request_gate=gate),
        notices._fetch_image_bytes("https://img.test/b.png", request_gate=gate),
    )
    assert peak == 2
