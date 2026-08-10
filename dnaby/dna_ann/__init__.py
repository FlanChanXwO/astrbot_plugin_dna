from __future__ import annotations

import asyncio
import random

from astrbot.api import logger

from ..dna_config.dna_config import DNAConfig
from ..utils.dna_api import dna_api
from ..utils.msgs.notify import send_dna_notify
from ..utils.session import EventContext, Sender
from ..utils.subscriptions import gs_subscribe
from .ann_card import draw_ann_detail_img, draw_ann_list_img
from .utils import build_index_map, fetch_ann_list, resolve_index

TASK_NAME_ANN = "订阅DNA公告"
ANN_MIN_CHECK: int = DNAConfig.get_config("AnnMinuteCheck").data or 10


async def handle_ann_dna(sender: Sender, ctx: EventContext):
    text = ctx.text.strip().replace("#", "")

    if not text:
        result = await draw_ann_list_img()
        if isinstance(result, str):
            return await send_dna_notify(sender, ctx, result)
        sender.send(result)
        return

    posts = await fetch_ann_list(prefer_cache=True)
    if not posts:
        return await send_dna_notify(sender, ctx, "获取公告列表失败")

    post_id = resolve_index(text, build_index_map(posts))
    if post_id is None:
        return await send_dna_notify(sender, ctx, "公告序号不正确，发送 公告 查看可用列表")

    result = await draw_ann_detail_img(post_id)
    if isinstance(result, str):
        return await send_dna_notify(sender, ctx, result)
    sender.send(result)


async def handle_sub_ann(sender: Sender, ctx: EventContext):
    if not ctx.group_id:
        return await send_dna_notify(sender, ctx, "请在群聊中订阅")
    if not DNAConfig.get_config("DNAAnnOpen").data:
        return await send_dna_notify(sender, ctx, "二重螺旋公告推送功能已关闭")

    data = await gs_subscribe.get_subscribe(TASK_NAME_ANN)
    if data and any(sub.group_id == ctx.group_id for sub in data):
        return await send_dna_notify(sender, ctx, "已经订阅了二重螺旋公告！")

    await gs_subscribe.add_subscribe("session", TASK_NAME_ANN, ctx, extra_message="")
    await send_dna_notify(sender, ctx, "成功订阅二重螺旋公告！")


async def handle_unsub_ann(sender: Sender, ctx: EventContext):
    if not ctx.group_id:
        return await send_dna_notify(sender, ctx, "请在群聊中取消订阅")

    data = await gs_subscribe.get_subscribe(TASK_NAME_ANN)
    if data and any(sub.group_id == ctx.group_id for sub in data):
        await gs_subscribe.delete_subscribe("session", TASK_NAME_ANN, ctx)
        return await send_dna_notify(sender, ctx, "成功取消订阅二重螺旋公告！")

    if not DNAConfig.get_config("DNAAnnOpen").data:
        return await send_dna_notify(sender, ctx, "二重螺旋公告推送功能已关闭")
    return await send_dna_notify(sender, ctx, "未曾订阅二重螺旋公告！")


async def check_dna_ann_state():
    logger.info("[二重螺旋公告] 定时任务: 二重螺旋公告查询..")
    subs = await gs_subscribe.get_subscribe(TASK_NAME_ANN)
    if not subs:
        logger.info("[二重螺旋公告] 暂无群订阅")
        return

    new_ann_list = await dna_api.get_ann_list()
    if not new_ann_list:
        return

    known_ids: list[int] = DNAConfig.get_config("DNAAnnIds").data or []
    fresh_ids = [int(post["postId"]) for post in new_ann_list]

    if not known_ids:
        DNAConfig.set_config("DNAAnnIds", fresh_ids)
        logger.info("[二重螺旋公告] 初始成功, 将在下个轮询中更新.")
        return

    pending = [post_id for post_id in fresh_ids if post_id not in known_ids]
    if not pending:
        logger.info("[二重螺旋公告] 没有最新公告")
        return

    logger.info(f"[二重螺旋公告] 更新公告id: {pending}")
    merged = sorted(set(known_ids) | set(fresh_ids), reverse=True)[:50]
    DNAConfig.set_config("DNAAnnIds", merged)

    for post_id in pending:
        try:
            img = await draw_ann_detail_img(post_id, is_check_time=True)
            if isinstance(img, str):
                continue
            for sub in subs:
                await sub.send(img)  # type: ignore
                await asyncio.sleep(random.uniform(1, 3))
        except Exception as e:  # noqa: BLE001 - 单个订阅失败不能中断其余目标，且会记录日志
            logger.exception(e)

    logger.info("[二重螺旋公告] 推送完毕")


COMMANDS = [
    {
        "key": "ann",
        "group": "公告",
        "name": "公告",
        "desc": "查看二重螺旋公告列表或公告详情",
        "eg": "公告 1",
        "regex": r"^公告(?:\s+(\d+))?$",
        "permission": "user",
        "handler": handle_ann_dna,
    },
    {
        "key": "ann_sub",
        "group": "公告",
        "name": "订阅公告",
        "desc": "订阅二重螺旋公告推送",
        "eg": "订阅公告",
        "regex": r"^订阅公告$",
        "permission": "admin",
        "handler": handle_sub_ann,
    },
    {
        "key": "ann_unsub",
        "group": "公告",
        "name": "取消订阅公告",
        "desc": "取消订阅二重螺旋公告推送",
        "eg": "取消订阅公告",
        "regex": r"^(?:取消订阅公告|取消公告|退订公告)$",
        "permission": "admin",
        "handler": handle_unsub_ann,
    },
]
