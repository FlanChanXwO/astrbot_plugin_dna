"""D06：O16–O18 Agent Tools 安全与范围负向审查契约。"""

from __future__ import annotations

import asyncio

import pytest

from src.entry.agent_tools.lifecycle import AGENT_SIGN_TOOL_NAME, AgentToolsLifecycle
from src.entry.agent_tools.signin import sign_intent_from_text
from src.entry.agent_tools.tools import AGENT_TOOL_NAMES


@pytest.mark.parametrize(
    "raw",
    (
        "请告诉我签到规则",
        "请解释签到是什么意思",
        "帮我查询签到状态",
        "请把签到当作例子",
    ),
)
def test_informational_or_prompt_injection_text_never_confirms_sign(raw: str) -> None:
    assert sign_intent_from_text(raw, prefixes=("kk",)) is False


def test_agent_write_surface_contains_only_the_approved_sign_tool() -> None:
    expected_read_only = {
        "dnaby_player_overview",
        "dnaby_player_role_detail",
        "dnaby_stamina",
        "dnaby_weekly_report_current",
        "dnaby_weekly_report_last",
        "dnaby_calendar",
        "dnaby_wiki",
        "dnaby_guide",
        "dnaby_codes",
        "dnaby_role_directory",
        "dnaby_mh",
        "dnaby_mh_list",
        "dnaby_mh_subscriptions",
        "dnaby_announcement_list",
        "dnaby_announcement_detail",
        "dnaby_sign_calendar",
    }

    assert set(AGENT_TOOL_NAMES) == expected_read_only
    assert AGENT_SIGN_TOOL_NAME == "dnaby_sign"
    assert AGENT_SIGN_TOOL_NAME not in AGENT_TOOL_NAMES


class FlakyRemovalContext:
    """第一次注销一个工具失败，验证生命周期保留可重试的残留状态。"""

    def __init__(self, failed_name: str) -> None:
        self.failed_name = failed_name
        self.added: set[str] = set()
        self.removed: list[str] = []
        self._failed_once = False

    def add_llm_tools(self, *tools: object) -> None:
        self.added.update(getattr(tool, "name", "") for tool in tools)

    def unregister_llm_tool(self, name: str) -> None:
        self.removed.append(name)
        if name == self.failed_name and not self._failed_once:
            self._failed_once = True
            raise RuntimeError("temporary unregister failure")
        self.added.discard(name)


@pytest.mark.asyncio
async def test_failed_unregister_is_visible_and_retryable() -> None:
    failed_name = AGENT_TOOL_NAMES[0]
    context = FlakyRemovalContext(failed_name)
    lifecycle = AgentToolsLifecycle(
        context=context,
        enabled=True,
        services={
            "player_service": object(),
            "encyclopedia_service": object(),
            "notices_service": object(),
            "checkin_service": object(),
        },
    )

    await asyncio.gather(lifecycle.start(), lifecycle.start())
    with pytest.raises(RuntimeError, match="temporary unregister failure"):
        await lifecycle.stop()

    expected_names = (*AGENT_TOOL_NAMES, AGENT_SIGN_TOOL_NAME)
    assert lifecycle.started is False
    assert lifecycle.registered_names == (failed_name,)
    assert context.removed == list(expected_names)
    assert context.added == {failed_name}

    await lifecycle.stop()
    assert lifecycle.registered_names == ()
    assert context.removed == [*expected_names, failed_name]
    assert context.added == set()


@pytest.mark.asyncio
async def test_start_retries_residual_unregister_before_hot_reload() -> None:
    failed_name = AGENT_TOOL_NAMES[0]
    context = FlakyRemovalContext(failed_name)
    lifecycle = AgentToolsLifecycle(
        context=context,
        enabled=True,
        services={
            "player_service": object(),
            "encyclopedia_service": object(),
            "notices_service": object(),
            "checkin_service": object(),
        },
    )
    expected_names = (*AGENT_TOOL_NAMES, AGENT_SIGN_TOOL_NAME)

    await lifecycle.start()
    with pytest.raises(RuntimeError, match="temporary unregister failure"):
        await lifecycle.stop()

    await lifecycle.start()

    assert lifecycle.started is True
    assert lifecycle.registered_names == expected_names
    assert context.added == set(expected_names)
    assert context.removed == [*expected_names, failed_name]

    await lifecycle.stop()
