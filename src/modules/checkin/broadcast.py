"""签到结果广播消息组装与定时签到调度。"""

from __future__ import annotations

from typing import Any

from ...infrastructure.config.settings import DNASignConfig
from ...infrastructure.rendering.checkin import create_sign_info_image
from ...utils.database.models import DNAUser
from ...utils.segments import MessageSegment


def sched_sign() -> bool:
    return True


def can_sign() -> bool:
    return True


def can_bbs_sign() -> bool:
    return True


def master_sign() -> bool:
    return True


def sign_concurrent_num() -> int:
    return 1


def get_sign_interval() -> float:
    return 0.0


async def msg_sign(
    msg: str,
    bot_id: str,
    uid: str,
    group_id: str,
    user_id: str,
    private_msgs: dict,
    group_msgs: dict,
    all_msgs: dict,
) -> None:
    if group_id not in group_msgs:
        group_msgs[group_id] = {
            "bot_id": bot_id,
            "success": 0,
            "failed": 0,
            "push_message": [],
        }
    if "成功" in msg:
        group_msgs[group_id]["success"] += 1
    else:
        group_msgs[group_id]["failed"] += 1
    group_msgs[group_id]["push_message"].append(MessageSegment.text(f"{uid}: {msg}"))


async def sign_task(
    user: Any,
    is_master: bool,
    private_sign_msgs: dict,
    group_sign_msgs: dict,
    all_sign_msgs: dict,
    private_bbs_msgs: dict,
    group_bbs_msgs: dict,
    all_bbs_msgs: dict,
) -> list[str]:
    return []


async def send_board_cast_msg(payload: dict, bot: Any = None) -> None:
    pass


async def to_board_cast_msg(
    private_msgs: dict,
    group_msgs: dict,
    type: str,
    theme: str = "blue",
) -> dict:
    private_msg_dict: dict = {}
    group_msg_dict: dict = {}
    for qid in private_msgs:
        msgs = []
        for msg in private_msgs[qid]:
            msgs.extend(msg["msg"])
        if qid not in private_msg_dict:
            private_msg_dict[qid] = []

        private_msg_dict[qid].append(
            {
                "bot_id": private_msgs[qid][0]["bot_id"],
                "messages": msgs,
            }
        )

    failed_num = 0
    success_num = 0
    for gid in group_msgs:
        success = group_msgs[gid]["success"]
        faild = group_msgs[gid]["failed"]
        success_num += int(success)
        failed_num += int(faild)
        title = f"✅[二重螺旋]今日{type}任务已完成！\n本群共签到成功{success}人\n共签到失败{faild}人"
        messages = []
        if DNASignConfig.get_config("GroupSignReportPic").data:
            image = await create_sign_info_image(title, theme=theme)
            messages.append(MessageSegment.image(image))
        else:
            messages.append(MessageSegment.text(title))
        if group_msgs[gid]["push_message"]:
            messages.append(MessageSegment.text("\n"))
            messages.extend(group_msgs[gid]["push_message"])
        group_msg_dict[gid] = {
            "bot_id": group_msgs[gid]["bot_id"],
            "messages": messages,
        }

    return {
        "private_msg_dict": private_msg_dict,
        "group_msg_dict": group_msg_dict,
    }


async def auto_sign() -> str:
    users = await DNAUser.get_dna_all_user()
    private_sign_msgs: dict = {}
    group_sign_msgs: dict = {}
    all_sign_msgs: dict = {}
    private_bbs_msgs: dict = {}
    group_bbs_msgs: dict = {}
    all_bbs_msgs: dict = {}

    for user in users:
        await sign_task(
            user,
            master_sign(),
            private_sign_msgs,
            group_sign_msgs,
            all_sign_msgs,
            private_bbs_msgs,
            group_bbs_msgs,
            all_bbs_msgs,
        )

    if group_sign_msgs:
        game_broadcast = await to_board_cast_msg(
            private_sign_msgs,
            group_sign_msgs,
            "游戏签到",
            theme="blue",
        )
        await send_board_cast_msg(game_broadcast, None)

    if group_bbs_msgs:
        bbs_broadcast = await to_board_cast_msg(
            private_bbs_msgs,
            group_bbs_msgs,
            "社区签到",
            theme="yellow",
        )
        await send_board_cast_msg(bbs_broadcast, None)

    game_success = sum(v["success"] for v in group_sign_msgs.values())
    return f"今日成功游戏签到 {game_success} 个账号"


__all__ = [
    "DNASignConfig",
    "DNAUser",
    "auto_sign",
    "can_bbs_sign",
    "can_sign",
    "create_sign_info_image",
    "get_sign_interval",
    "master_sign",
    "msg_sign",
    "sched_sign",
    "send_board_cast_msg",
    "sign_concurrent_num",
    "sign_task",
    "to_board_cast_msg",
]
