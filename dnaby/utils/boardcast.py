import asyncio
import random

from astrbot.api import logger

from ..utils.constants.boardcast import BoardcastType
from .subscriptions import gs_subscribe

title = "二重螺旋"


async def send_board_cast_msg(msgs: dict, board_cast_type: BoardcastType):
    """按订阅目标推送签到结果等消息（替代 gsucore ``gss.target_send``）。

    ``msgs`` 形如 ``{"private_msg_dict": {qid: [{"bot_id", "messages"}...]},
    "group_msg_dict": {gid: [{"bot_id", "messages"}...]}}``。
    """
    logger.info(f"[「{title}」推送] {board_cast_type} 任务启动...")
    private_msg_list = msgs.get("private_msg_dict", {})
    group_msg_list = msgs.get("group_msg_dict", {})

    subs = await gs_subscribe.get_subscribe(board_cast_type)

    # 私聊推送
    for qid, entries in private_msg_list.items():
        try:
            for single in entries:
                for sub in subs:
                    if sub.user_type != "direct":
                        continue
                    if sub.user_id != str(qid):
                        continue
                    await sub.send(single.get("messages"))
        except Exception as e:  # noqa: BLE001 - 单个目标失败不能中断其余推送，且会记录日志
            logger.exception(f"[「{title}」推送] {qid} 私聊推送失败!错误信息 {e}")
        await asyncio.sleep(0.5 + random.randint(1, 3))
    logger.info(f"[「{title}」推送] {board_cast_type} 私聊推送完成!")

    # 群聊推送
    for gid, entries in group_msg_list.items():
        try:
            if isinstance(entries, list):
                for group in entries:
                    for sub in subs:
                        if sub.user_type != "group":
                            continue
                        if sub.group_id != str(gid):
                            continue
                        await sub.send(group.get("messages"))
            else:
                for sub in subs:
                    if sub.user_type != "group":
                        continue
                    if sub.group_id != str(gid):
                        continue
                    await sub.send(entries.get("messages"))
        except Exception as e:  # noqa: BLE001 - 单个目标失败不能中断其余推送，且会记录日志
            logger.exception(f"[「{title}」推送] 群 {gid} 推送失败!错误信息 {e}")
        await asyncio.sleep(0.5 + random.randint(1, 3))
    logger.info(f"[「{title}」推送] {board_cast_type} 群聊推送完成!")
    logger.info(f"[「{title}」推送] {board_cast_type} 任务结束!")
