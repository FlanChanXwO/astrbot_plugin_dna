"""Goal 6 T12：资源命令公开名称、service 语义与 manifest 投影 Red 契约。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.entry.commands import load_command_registry, manifest_records
from src.entry.response import PlainTextResponse
from src.modules.operations.commands import (
    resource_download_use_case,
    resource_status_use_case,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_resource_sync_command_uses_public_name_and_stable_id() -> None:
    """公开文本切换为“同步资源”，内部 ID 保持兼容。"""

    registry = load_command_registry()
    spec = registry.get("download_resource")

    assert spec.id == "download_resource"
    assert spec.pattern == r"^kk同步资源$"
    assert spec.name == "同步资源"
    assert spec.description == "同步全部公共资源"
    assert spec.examples == ("kk同步资源",)
    assert registry.match("kk同步资源") is not None
    assert registry.match("kk下载全部资源") is None


@pytest.mark.asyncio
async def test_resource_sync_use_case_calls_canonical_service_method() -> None:
    """命令 use case 必须调用 canonical ``sync_resources``，不依赖旧别名。"""

    calls: list[object] = []

    class Service:
        async def sync_resources(self, request: object) -> PlainTextResponse:
            calls.append(request)
            return PlainTextResponse("同步完成")

    request = SimpleNamespace(
        actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1"),
        services={"resource_update_service": Service()},
    )

    generator = resource_download_use_case(request, load_command_registry())
    response = await anext(generator)

    assert response == PlainTextResponse("开始同步公共资源，请稍候，完成后会发送结果")
    response = await anext(generator)
    assert response == PlainTextResponse("同步完成")
    assert calls == [None]


@pytest.mark.asyncio
async def test_resource_status_use_case_remains_read_only() -> None:
    """状态命令只调用 status，不误触发同步入口。"""

    calls: list[str] = []

    class Service:
        async def status(self) -> PlainTextResponse:
            calls.append("status")
            return PlainTextResponse("状态")

        async def sync_resources(self, _request: object) -> PlainTextResponse:
            calls.append("sync")
            return PlainTextResponse("不应调用")

    request = SimpleNamespace(
        actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1"),
        services={"resource_update_service": Service()},
    )

    response = await resource_status_use_case(request, load_command_registry())

    assert isinstance(response, PlainTextResponse)
    assert response.text == "状态"
    assert calls == ["status"]


def test_commands_json_is_generated_from_current_registry() -> None:
    """提交的 commands.json 必须与代码 registry 投影逐项一致。"""

    manifest = json.loads((ROOT / "commands.json").read_text(encoding="utf-8"))

    assert manifest == manifest_records(load_command_registry())
