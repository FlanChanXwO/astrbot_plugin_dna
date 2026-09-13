"""帮助菜单中的订阅/取消订阅展示契约。"""

from __future__ import annotations

from main import COMMAND_REGISTRY
from src.infrastructure.rendering.help import _load_help_data, _registry_help_sections


def _help_items(permission: str) -> dict[str, str]:
    sections = _registry_help_sections(
        COMMAND_REGISTRY,
        permission,  # type: ignore[arg-type]
        "dna",
        _load_help_data(),
    )
    return {
        str(item["name"]): str(item["example"])
        for section in sections
        for item in section["items"]
    }


def test_user_help_shows_unsubscribe_examples_for_bidirectional_subscriptions() -> None:
    items = _help_items("user")

    assert items["订阅/取消订阅密函"] == (
        "dna订阅拆解密函 / dna取消订阅全部密函"
    )
    assert items["订阅密函图片"] == (
        "dna订阅密函图片 / dna取消订阅密函图片"
    )
    assert items["订阅密函文本"] == (
        "dna订阅密函文本 / dna取消订阅密函文本"
    )
    assert items["设置密函推送时间"] == "dna订阅密函时间17:23"
    assert "订阅密函时间" not in items


def test_admin_help_shows_unsubscribe_examples_for_checkin_subscriptions() -> None:
    items = _help_items("admin")

    assert items["订阅签到结果"] == (
        "dna订阅签到结果 / dna取消订阅签到结果"
    )
    assert items["订阅本群签到报告"] == (
        "dna订阅本群签到报告 / dna取消订阅本群签到报告"
    )
    assert items["订阅客户端更新"] == "dna订阅客户端更新"
    assert items["取消订阅客户端更新"] == "dna取消订阅客户端更新"
    assert items["订阅公告"] == "dna订阅公告"
    assert items["取消订阅公告"] == "dna取消订阅公告"
