"""命令主门与分发器测试。"""

import asyncio
import re


def test_master_pattern_matches_examples_with_named_groups():
    from dnaby.dispatch import ALL_COMMANDS, MASTER_PATTERN

    master = re.compile(MASTER_PATTERN)
    for command in ALL_COMMANDS:
        assert master.match(command["eg"]), command["key"]


def test_login_accepts_dna_prefix_at_command_and_master_gates():
    from dnaby.dispatch import ALL_COMMANDS, MASTER_PATTERN

    login = next(command for command in ALL_COMMANDS if command["key"] == "user_login")
    login_pattern = re.compile(login["regex"])
    master = re.compile(MASTER_PATTERN)

    for message in ("登录", "dna登录", "DNA登录", "dna登录 token"):
        assert login_pattern.match(message), message
        assert master.match(message), message


def test_dispatch_reparses_command_and_populates_context(monkeypatch):
    from dnaby.dispatch import ALL_COMMANDS, dispatch
    from dnaby.utils.session import EventContext, Sender

    command = next(item for item in ALL_COMMANDS if item["key"] == "user_bind")
    seen = {}

    async def fake_handler(sender, ctx):
        seen["command"] = ctx.command
        seen["text"] = ctx.text
        seen["regex_dict"] = ctx.regex_dict

    monkeypatch.setitem(command, "handler", fake_handler)

    async def scenario():
        ctx = EventContext(message_str="绑定123456")
        sender = Sender(ctx)
        assert await dispatch(object(), sender, ctx)

    asyncio.run(scenario())
    assert seen == {
        "command": "绑定123456",
        "text": "123456",
        "regex_dict": {"arg": "123456"},
    }


def test_send_dna_text_preserves_plain_text_compatibility(monkeypatch):
    """历史纯文本通知可集中走 notify 适配器并保持原始前缀/提及行为。"""
    from dnaby.utils.msgs.notify import send_dna_text
    from dnaby.utils.session import EventContext, Sender

    async def no_uid_hidden(*args):
        return False

    monkeypatch.setattr("dnaby.utils.msgs.notify.is_uid_hidden", no_uid_hidden)

    async def scenario():
        ctx = EventContext(message_str="测试", group_id="group-1")
        sender = Sender(ctx)
        await send_dna_text(sender, ctx, "测试消息")
        return sender.to_chains()

    chains = asyncio.run(scenario())
    assert chains
    assert chains[0][0].text == "测试消息"
