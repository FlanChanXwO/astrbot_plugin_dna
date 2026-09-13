"""Response adapter regression coverage."""

from __future__ import annotations

from typing import Any

from src.entry.response import ChainResponse, PlainTextResponse, ResponseFactory


class _CaptureEvent:
    """Capture AstrBot-native chain components for assertions."""

    @staticmethod
    def chain_result(components: Any) -> Any:
        return components


def test_chain_separates_adjacent_plain_text_responses() -> None:
    """Independent text DTOs must not be concatenated by the platform chain."""

    response = ChainResponse(
        (
            PlainTextResponse("[DNA兑换码]"),
            PlainTextResponse("狩月的意义\n奖励：月石*450\n区服：cn"),
            PlainTextResponse("SPECIALLIVE\n奖励：月石*450\n区服：global"),
            PlainTextResponse(
                "DENAABINIJI\n奖励：深红凝珠*200\n"
                "平台：pc、android、ios\n区服：global"
            ),
        )
    )

    components = ResponseFactory().build(_CaptureEvent(), response)

    assert "".join(component.text for component in components) == (
        "[DNA兑换码]\n"
        "狩月的意义\n奖励：月石*450\n区服：cn\n"
        "SPECIALLIVE\n奖励：月石*450\n区服：global\n"
        "DENAABINIJI\n奖励：深红凝珠*200\n"
        "平台：pc、android、ios\n区服：global"
    )


class _GroupEvent:
    """带群聊上下文的最小事件，可探测是否被插入 At。"""

    def __init__(self) -> None:
        self.plain_texts: list[str] = []

    def get_group_id(self) -> str:
        return "group-1"

    def get_sender_id(self) -> str:
        return "user-1"

    def plain_result(self, text: str) -> Any:
        self.plain_texts.append(text)
        return ("plain", text)

    def chain_result(self, components: Any) -> Any:
        return components


def test_plain_response_without_need_at_keeps_plain_result() -> None:
    """普通文本回复必须走 plain_result，不得因群聊上下文自行插入 At。

    AstrBot v4 的 ResultDecorateStage 只对纯 Plain/Image 组成的结果应用
    reply_with_mention / reply_with_quote；DNA 提前插 At 会让平台级
    自动 @ 与引用回复全部失效。
    """

    event = _GroupEvent()

    result = ResponseFactory.plain(event, "订阅成功")

    assert result == ("plain", "订阅成功")
    assert event.plain_texts == ["订阅成功"]


def test_explicit_need_at_still_builds_at_component() -> None:
    """显式 need_at 的业务 At 能力必须保留（登录/主动通知场景）。"""

    event = _GroupEvent()

    components = ResponseFactory.plain(event, "凭证失效", need_at=True)

    assert [type(component).__name__ for component in components] == ["At", "Plain"]
    assert components[0].qq == "user-1"
    assert components[1].text == "凭证失效"
