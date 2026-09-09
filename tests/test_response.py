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
