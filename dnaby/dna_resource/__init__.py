import asyncio

from astrbot.api import logger

from ..utils.msgs.notify import send_dna_text
from ..utils.resource.download_all_resource import download_all_resource
from ..utils.session import EventContext, Sender


async def handle_download_resource(sender: Sender, ctx: EventContext):
    """下载全部资源：拉取插件所需全部素材。"""
    await send_dna_text(sender, ctx, "[二重螺旋] 正在开始下载~可能需要较久的时间!")
    await download_all_resource()
    await send_dna_text(sender, ctx, "[二重螺旋] 下载完成！")


async def startup():
    logger.info("[二重螺旋] 资源下载任务已在后台启动")
    asyncio.create_task(download_all_resource())


COMMANDS = [
    {
        "key": "download_resource",
        "group": "bot主人功能",
        "name": "下载全部资源",
        "desc": "下载全部资源",
        "eg": "下载全部资源",
        "regex": r"^下载全部资源$",
        "permission": "owner",
        "handler": handle_download_resource,
    },
]
