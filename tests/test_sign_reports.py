"""签到全局汇总、本群报告和独立订阅路由契约。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.infrastructure.scheduler import SignPushPayload, SignScheduler
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.checkin import messages
from src.modules.checkin.contracts import AutoSignReport, GroupSignReport


class _StructuredCheckin:
    def __init__(self) -> None:
        self.report_calls = 0

    async def auto_sign_report(self, *, enable_all_users: bool = False) -> AutoSignReport:
        del enable_all_users
        self.report_calls += 1
        return AutoSignReport(
            summary_text="全局汇总：游戏 3，社区 2",
            group_reports={
                "group-a": (
                    GroupSignReport(
                        report_type="game",
                        success=1,
                        failed=0,
                        summary_text="群 A 游戏签到：成功 1，失败 0",
                        detail_text="A-UID: 游戏签到成功",
                    ),
                    GroupSignReport(
                        report_type="community",
                        success=1,
                        failed=1,
                        summary_text="群 A 社区签到：成功 1，失败 1",
                        detail_text="A-UID: 社区签到成功\nA2-UID: 社区签到失败",
                    ),
                ),
                "group-b": (
                    GroupSignReport(
                        report_type="game",
                        success=2,
                        failed=0,
                        summary_text="群 B 游戏签到：成功 2，失败 0",
                        detail_text="B-UID: 游戏签到成功",
                    ),
                ),
            },
        )

    async def clear_sign_records_before(self, record_date: date) -> int:
        del record_date
        return 0


async def _subscriptions(tmp_path: Path) -> SubscriptionStore:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.SIGN_RESULT_SUBSCRIBE,
        origin="platform:group:global",
        group_id="global",
        user_id="owner-global",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.SIGN_GROUP_REPORT_SUBSCRIBE,
        origin="platform:group:group-a",
        group_id="group-a",
        user_id="owner-a",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.SIGN_RESULT_SUBSCRIBE,
        origin="platform:group:both",
        group_id="group-a",
        user_id="owner-both",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.SIGN_GROUP_REPORT_SUBSCRIBE,
        origin="platform:group:both",
        group_id="group-a",
        user_id="owner-both",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.SIGN_GROUP_REPORT_SUBSCRIBE,
        origin="platform:group:group-b",
        group_id="group-b",
        user_id="owner-b",
        bot_id="bot-1",
    )
    return subscriptions


@pytest.mark.asyncio
async def test_sign_scheduler_routes_global_and_group_reports_independently(
    tmp_path: Path,
) -> None:
    pushed: list[tuple[str, SignPushPayload]] = []

    async def push(origin: str, payload: SignPushPayload) -> None:
        pushed.append((origin, payload))

    checkin = _StructuredCheckin()
    scheduler = SignScheduler(checkin, await _subscriptions(tmp_path), push=push)

    text = await scheduler.run_sign_once()

    assert text == "全局汇总：游戏 3，社区 2"
    assert checkin.report_calls == 1
    assert [(origin, payload.text) for origin, payload in pushed] == [
        ("platform:group:global", "全局汇总：游戏 3，社区 2"),
        ("platform:group:both", "全局汇总：游戏 3，社区 2"),
        ("platform:group:group-a", "群 A 游戏签到：成功 1，失败 0\nA-UID: 游戏签到成功"),
        (
            "platform:group:group-a",
            "群 A 社区签到：成功 1，失败 1\nA-UID: 社区签到成功\nA2-UID: 社区签到失败",
        ),
        ("platform:group:both", "群 A 游戏签到：成功 1，失败 0\nA-UID: 游戏签到成功"),
        (
            "platform:group:both",
            "群 A 社区签到：成功 1，失败 1\nA-UID: 社区签到成功\nA2-UID: 社区签到失败",
        ),
        ("platform:group:group-b", "群 B 游戏签到：成功 2，失败 0\nB-UID: 游戏签到成功"),
    ]


@pytest.mark.asyncio
async def test_group_report_never_contains_another_group_detail(tmp_path: Path) -> None:
    pushed: list[tuple[str, SignPushPayload]] = []

    async def push(origin: str, payload: SignPushPayload) -> None:
        pushed.append((origin, payload))

    scheduler = SignScheduler(
        _StructuredCheckin(),
        await _subscriptions(tmp_path),
        push=push,
    )

    await scheduler.run_sign_once()

    group_a_payloads = [payload.text for origin, payload in pushed if origin.endswith(":group-a")]
    group_b_payloads = [payload.text for origin, payload in pushed if origin.endswith(":group-b")]
    assert group_a_payloads
    assert group_b_payloads
    assert all("B-UID" not in text for text in group_a_payloads)
    assert all("A-UID" not in text and "A2-UID" not in text for text in group_b_payloads)


@pytest.mark.asyncio
async def test_sign_scheduler_continues_after_one_report_push_fails(tmp_path: Path) -> None:
    pushed: list[str] = []

    async def push(origin: str, payload: SignPushPayload) -> None:
        if origin.endswith(":group-a"):
            raise ConnectionResetError("network failed")
        pushed.append(f"{origin}:{payload.text}")

    scheduler = SignScheduler(
        _StructuredCheckin(),
        await _subscriptions(tmp_path),
        push=push,
    )

    await scheduler.run_sign_once()

    assert any(item.startswith("platform:group:global:") for item in pushed)
    assert any(item.startswith("platform:group:group-b:") for item in pushed)

@pytest.mark.asyncio
async def test_bootstrap_sign_push_adapts_image_bytes_and_detail_text(tmp_path: Path) -> None:
    """bootstrap 推送适配器使用 AstrBot 原生图片组件承载 bytes。"""

    from astrbot.api.message_components import Plain
    from astrbot.core.message.components import Image as AstrImage

    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    sent: list[tuple[str, object]] = []

    class Context:
        def register_web_api(self, *_args: object) -> None:
            return None

        async def send_message(self, origin: str, message: object) -> None:
            sent.append((origin, message))

    runtime = build_runtime(
        Context(),
        {"sign_in": {"group_report": True, "group_report_image": True}},
        database=AsyncDatabase(tmp_path / "runtime.sqlite3"),
    )
    scheduler = runtime.services["sign_scheduler"]

    await scheduler._push(
        "platform:group:g1",
        SignPushPayload(
            text="群 A 游戏签到汇总",
            image_bytes=b"image-bytes",
            detail_text="uid-a: 游戏签到成功",
        ),
    )

    assert len(sent) == 1
    chain = sent[0][1].chain
    assert isinstance(chain[0], AstrImage)
    assert isinstance(chain[1], Plain)
    assert chain[1].text == "uid-a: 游戏签到成功"

    await scheduler._push(
        "platform:group:g1",
        SignPushPayload(text="群 A 社区签到汇总"),
    )

    assert len(sent) == 2
    text_chain = sent[1][1].chain
    assert isinstance(text_chain[0], Plain)
    assert text_chain[0].text == "群 A 社区签到汇总"
