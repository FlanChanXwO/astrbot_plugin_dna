import datetime
import json

import aiohttp
from astrbot.api import logger

from ..utils.msgs.notify import send_dna_text
from ..utils.segments import MessageSegment
from ..utils.session import EventContext, Sender


async def get_dna_code_info(sender: Sender, ctx: EventContext):
    JSON_URL = "https://raw.gitcode.com/m0_69204072/dna/raw/main/dna_codes.json"

    try:
        async with aiohttp.ClientSession() as session, session.get(JSON_URL) as resp:
            text = await resp.text()
            data = json.loads(text)

        tz = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(tz)

        valid_codes = []
        end_time_str = ""

        for item in data.get("data", []):
            ts = item["end_at"]
            end_time = datetime.datetime.fromtimestamp(ts, tz=tz)

            if end_time > now:
                valid_codes.append(item["code"])
                if not end_time_str:
                    end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        if not valid_codes:
            await send_dna_text(sender, ctx, "[DNA兑换码] 暂无可用兑换码")
            return

        node_list = [MessageSegment.text("[DNA兑换码]")]
        for code in valid_codes:
            node_list.append(MessageSegment.text(code))
        node_list.append(MessageSegment.text(f"有效期至：{end_time_str}"))

        forward_msg = MessageSegment.node(node_list)
        sender.send(forward_msg)

    except (aiohttp.ClientError, json.JSONDecodeError, KeyError, TypeError, UnicodeError) as e:
        logger.error(f"错误: {e}")
        await send_dna_text(sender, ctx, "[DNA兑换码] 获取失败")
