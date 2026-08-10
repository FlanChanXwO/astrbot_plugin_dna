from astrbot.api import logger

from ..dna_resource import startup


async def startup_routine():
    """AstrBot 插件启动钩子：后台启动资源下载。"""
    logger.info("[二重螺旋] 启动中...")
    try:
        await startup()
    except Exception as e:  # noqa: BLE001 - 启动钩子不允许中断
        logger.exception(e)

    logger.info("[二重螺旋] 启动完成")
