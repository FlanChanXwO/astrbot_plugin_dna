"""命令主门与分发器测试。"""

import asyncio
import re


def test_master_pattern_matches_examples_with_named_groups():
    from src.entry.commands import load_command_registry

    registry = load_command_registry()
    for command in registry:
        pattern = re.compile(command.pattern)
        for eg in command.examples:
            assert pattern.match(eg), f"{command.id}: {eg}"


def test_registered_commands_require_kk_prefix():
    from src.entry.commands import COMMAND_PREFIX, load_command_registry

    registry = load_command_registry()
    assert COMMAND_PREFIX == "kk"
    assert all(command.pattern.startswith(r"^kk") for command in registry)
    assert registry.match("帮助") is None
    assert registry.match("kk帮助") is not None


def test_login_accepts_kk_prefix_at_command_and_master_gates():
    from src.entry.commands import load_command_registry

    registry = load_command_registry()
    login = next(command for command in registry if command.id == "account_login")
    login_pattern = re.compile(login.pattern)

    for message in ("kk登录", "kk登陆", "kklogin", "kk登录 token"):
        assert login_pattern.match(message), message
    for message in ("登录", "dna登录", "DNA登录"):
        assert login_pattern.match(message) is None, message


def test_dispatch_reparses_command_and_populates_context():
    from src.entry.commands import load_command_registry

    registry = load_command_registry()
    matched = registry.match("kk绑定123456")
    assert matched is not None
    assert matched.command.id == "account_bind"
    assert matched.parameters["uid"] == "123456"


def test_send_dna_text_preserves_plain_text_compatibility(monkeypatch):
    """历史纯文本通知可集中走 notify 适配器并保持原始前缀/提及行为。"""
    from src.utils.msgs.notify import send_dna_text
    from src.utils.session import EventContext, Sender

    async def no_uid_hidden(*args):
        return False

    monkeypatch.setattr("src.utils.msgs.notify.is_uid_hidden", no_uid_hidden)

    async def scenario():
        ctx = EventContext(message_str="测试", group_id="group-1")
        sender = Sender(ctx)
        await send_dna_text(sender, ctx, "测试消息")
        return sender.to_chains()

    chains = asyncio.run(scenario())
    assert chains
    assert chains[0][0].text == "测试消息"
