from pathlib import Path
from typing import Any

import pytest

from src.rendering import qr as qr_module
from src.utils import image_utils


@pytest.mark.asyncio
async def test_qr_code_uses_boolean_matrix_and_fixed_html_canvas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any], Any]] = []

    class Renderer:
        async def render(self, template: str, data: dict[str, Any], spec: Any) -> bytes:
            calls.append((template, data, spec))
            return b"qr-png"

    monkeypatch.setattr(qr_module, "_RENDERER", Renderer())

    assert await qr_module.render_qr_code("https://localhost/login") == b"qr-png"
    template, data, spec = calls[0]
    assert template == "cards/qr_code.html.j2"
    assert spec.width == 420 and spec.height == 420 and spec.full_page is False
    assert data["modules"] == len(data["matrix"])
    assert all(len(row) == data["modules"] for row in data["matrix"])
    assert {module for row in data["matrix"] for module in row} == {False, True}


@pytest.mark.asyncio
async def test_legacy_qr_helper_delegates_without_writing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def render(data: str) -> bytes:
        seen.append(data)
        return b"html-qr"

    monkeypatch.setattr(qr_module, "render_qr_code", render)
    legacy_path = tmp_path / "legacy.gif"

    result = await image_utils.get_qrcode_base64(
        "https://localhost/login", legacy_path, "bot"
    )

    assert result == b"html-qr"
    assert seen == ["https://localhost/login"]
    assert not legacy_path.exists()
