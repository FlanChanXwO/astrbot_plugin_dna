from types import SimpleNamespace

import pytest

import src.modules.checkin.broadcast as sign_module
from src.rendering import T2IRenderError
from src.utils.segments import ImageSegment


class _SignConfig:
    @staticmethod
    def get_config(_: str) -> SimpleNamespace:
        return SimpleNamespace(data=True)


@pytest.mark.asyncio
async def test_sign_report_html_bytes_enter_group_broadcast(monkeypatch: pytest.MonkeyPatch) -> None:
    themes: list[str] = []

    async def render_report(_: str, theme: str = "blue") -> bytes:
        themes.append(theme)
        return f"png:{theme}".encode()

    monkeypatch.setattr(sign_module, "DNASignConfig", _SignConfig)
    monkeypatch.setattr(sign_module, "create_sign_info_image", render_report)

    result = await sign_module.to_board_cast_msg(
        {},
        {
            "group-1": {
                "bot_id": "bot-1",
                "success": 2,
                "failed": 1,
                "push_message": [],
            }
        },
        "游戏签到",
        theme="blue",
    )

    segment = result["group_msg_dict"]["group-1"]["messages"][0]
    assert isinstance(segment, ImageSegment)
    assert segment.value == b"png:blue"
    assert themes == ["blue"]


@pytest.mark.asyncio
async def test_auto_sign_pushes_game_and_community_html_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    class _DNAUser:
        @staticmethod
        async def get_dna_all_user() -> list[object]:
            return [object()]

    async def fake_sign_task(
        _: object,
        __: bool,
        private_sign_msgs: dict,
        group_sign_msgs: dict,
        all_sign_msgs: dict,
        private_bbs_msgs: dict,
        group_bbs_msgs: dict,
        all_bbs_msgs: dict,
    ) -> list[str]:
        await sign_module.msg_sign(
            "游戏签到成功",
            "bot",
            "uid",
            "group-1",
            "user-1",
            private_sign_msgs,
            group_sign_msgs,
            all_sign_msgs,
        )
        await sign_module.msg_sign(
            "社区签到成功",
            "bot",
            "uid",
            "group-1",
            "user-1",
            private_bbs_msgs,
            group_bbs_msgs,
            all_bbs_msgs,
        )
        return []

    async def render_report(_: str, theme: str = "blue") -> bytes:
        return theme.encode()

    async def capture_broadcast(payload: dict, _: object) -> None:
        sent.append(payload)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(sign_module, "DNAUser", _DNAUser)
    monkeypatch.setattr(sign_module, "DNASignConfig", _SignConfig)
    monkeypatch.setattr(sign_module, "sched_sign", lambda: True)
    monkeypatch.setattr(sign_module, "can_sign", lambda: True)
    monkeypatch.setattr(sign_module, "can_bbs_sign", lambda: True)
    monkeypatch.setattr(sign_module, "master_sign", lambda: True)
    monkeypatch.setattr(sign_module, "sign_concurrent_num", lambda: 1)
    monkeypatch.setattr(sign_module, "get_sign_interval", lambda: 0.0)
    monkeypatch.setattr(sign_module, "sign_task", fake_sign_task)
    monkeypatch.setattr(sign_module, "create_sign_info_image", render_report)
    monkeypatch.setattr(sign_module, "send_board_cast_msg", capture_broadcast)
    monkeypatch.setattr(sign_module.asyncio, "sleep", no_sleep)

    summary = await sign_module.auto_sign()

    assert "今日成功游戏签到 1 个账号" in summary
    assert len(sent) == 2
    game_image = sent[0]["group_msg_dict"]["group-1"]["messages"][0]
    community_image = sent[1]["group_msg_dict"]["group-1"]["messages"][0]
    assert isinstance(game_image, ImageSegment) and game_image.value == b"blue"
    assert isinstance(community_image, ImageSegment) and community_image.value == b"yellow"


@pytest.mark.asyncio
async def test_sign_report_render_error_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_render(_: str, theme: str = "blue") -> bytes:
        raise T2IRenderError(f"T2I unavailable: {theme}")

    monkeypatch.setattr(sign_module, "DNASignConfig", _SignConfig)
    monkeypatch.setattr(sign_module, "create_sign_info_image", fail_render)

    with pytest.raises(T2IRenderError, match="T2I unavailable"):
        await sign_module.to_board_cast_msg(
            {},
            {
                "group-1": {
                    "bot_id": "bot-1",
                    "success": 1,
                    "failed": 0,
                    "push_message": [],
                }
            },
            "社区签到",
            theme="yellow",
        )
