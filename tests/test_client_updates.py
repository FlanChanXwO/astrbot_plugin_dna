"""客户端更新同步命令回复的装饰归属回归。

同步命令回复「刚刚执行命令的人」的 @ / 引用由 AstrBot 平台层决定；
DNA 的 CommandResponse 不得为这类回复自行请求 At。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.commands import CommandRequest
from src.entry.event import EventActor
from src.entry.response import PlainTextResponse
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import messages
from src.modules.client_updates.commands import client_update_subscribe_use_case
from src.modules.client_updates.contracts import ClientUpdateRequest
from src.modules.client_updates.service import ClientUpdateService
from src.modules.client_updates.state import ClientUpdateStateStore

_GROUP_ORIGIN = "aiocqhttp:GroupMessage:group-1"


@pytest.mark.asyncio
async def test_client_update_subscribe_result_does_not_request_self_mention(
    tmp_path: Path,
) -> None:
    """订阅结果回复不自行 @ 调用者，交由 AstrBot 决定回复形态。"""

    service = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "state.json"),
        subscriptions=SubscriptionStore(tmp_path / "subscriptions.json"),
    )
    request = ClientUpdateRequest(
        actor=EventActor(
            "user-1",
            "bot-1",
            "group-1",
            _GROUP_ORIGIN,
        )
    )

    response = await service.subscribe(request)

    assert isinstance(response, PlainTextResponse)
    assert response.text in {
        messages.CLIENT_UPDATE_SUBSCRIBED,
        messages.CLIENT_UPDATE_SUBSCRIBED_RETRY,
        messages.CLIENT_UPDATE_ALREADY_SUBSCRIBED,
    }
    assert response.need_at is False


@pytest.mark.asyncio
async def test_client_update_admin_guard_does_not_request_self_mention() -> None:
    """管理员权限不足提示不自行 @ 调用者。"""

    request = CommandRequest(
        command_id="client_update_subscribe",
        text="订阅客户端更新",
        parameters={},
        actor=EventActor(
            "user-1",
            "bot-1",
            "group-1",
            _GROUP_ORIGIN,
        ),
        permission="user",
    )

    response = await client_update_subscribe_use_case(request, None)

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.CLIENT_UPDATE_ADMIN_ONLY
    assert response.need_at is False
