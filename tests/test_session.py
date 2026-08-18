"""session.py：EventContext + Sender 单元测试。"""

import asyncio
from io import BytesIO

from PIL import Image as PILImage

from src.utils.segments import MessageSegment
from src.utils.session import EventContext, Sender


def _img() -> bytes:
    buf = BytesIO()
    PILImage.new("RGB", (4, 4), "red").save(buf, format="PNG")
    return buf.getvalue()


def _names(chain):
    return [type(c).__name__ for c in chain]


def test_event_context_defaults():
    ctx = EventContext()
    assert ctx.user_pm == 6
    assert ctx.user_type == "group"
    assert ctx.regex_dict == {}


def test_sender_text():
    ctx = EventContext(user_id="u1")
    sender = Sender(ctx)
    sender.send("你好")
    chains = sender.to_chains()
    assert len(chains) == 1
    assert _names(chains[0]) == ["Plain"]
    assert chains[0][0].text == "你好"


def test_sender_image_bytes_and_pil():
    ctx = EventContext(user_id="u1")
    sender = Sender(ctx)
    sender.send(_img())
    chains = sender.to_chains()
    assert len(chains) == 1
    assert _names(chains[0]) == ["Image"]

    sender2 = Sender(ctx)
    sender2.send(PILImage.new("RGB", (2, 2), "blue"))
    assert _names(sender2.to_chains()[0]) == ["Image"]


def test_sender_at_sender():
    ctx = EventContext(user_id="u1")
    sender = Sender(ctx)
    sender.send("签到完成", at_sender=True)
    chain = sender.to_chains()[0]
    assert _names(chain) == ["At", "Plain"]
    assert chain[0].qq == "u1"
    assert chain[1].text == "签到完成"


def test_sender_segments():
    ctx = EventContext(user_id="u1")
    sender = Sender(ctx)
    sender.send(
        [
            MessageSegment.text("标题\n"),
            MessageSegment.image(_img()),
        ]
    )
    chain = sender.to_chains()[0]
    assert _names(chain) == ["Plain", "Image"]


def test_sender_forward_node_segments():
    """转发节点内的 segment 也应沿用 Sender 的解析逻辑。"""
    sender = Sender(EventContext(user_id="u1"))
    sender.send(MessageSegment.node([[MessageSegment.text("节点内容")]]))

    chain = sender.to_chains()[0]
    assert _names(chain) == ["Node"]
    assert chain[0].content[0].text == "节点内容"


def test_sender_multiple_sends_separate_results():
    ctx = EventContext(user_id="u1")
    sender = Sender(ctx)
    sender.send("第一段")
    sender.send("第二段")
    assert len(sender.to_chains()) == 2


def test_sender_send_supports_sync_and_awaited_callers():
    """迁移后的同步与异步调用方都应复用同一条入队路径。"""
    ctx = EventContext(user_id="u1")
    sender = Sender(ctx)

    async def send_from_legacy_handler():
        assert await sender.send("异步消息") is None
        assert await sender.send("兼容撤回参数", wait_recall=True) is None

    asyncio.run(send_from_legacy_handler())
    assert len(sender.to_chains()) == 2


def test_sender_send_now_uses_immediate_callback():
    """需要先展示登录地址时，立即发送不应等到 handler 结束。"""
    sent = []

    async def immediate_send(chain):
        sent.append(chain)

    sender = Sender(EventContext(user_id="u1"), immediate_send=immediate_send)

    async def scenario():
        await sender.send_now("登录地址")

    asyncio.run(scenario())

    assert len(sent) == 1
    assert sent[0][0].text == "登录地址"
    assert sender.messages == []
