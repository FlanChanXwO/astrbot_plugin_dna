from astrbot.api import logger

from ..utils.constants.boardcast import BoardcastTypeEnum
from ..utils.database.models import DNAUser
from ..utils.session import EventContext
from ..utils.subscriptions import gs_subscribe


async def get_signin_config():
    from .dna_config import DNASignConfig

    master = DNASignConfig.get_config("SigninMaster").data
    signin = DNASignConfig.get_config("DNASchedSignin").data
    return master or signin


async def set_config_func(ctx: EventContext, uid: str = "0"):
    config_name = ctx.text
    if "开启" in ctx.command:
        option = ctx.group_id if ctx.group_id else "on"
    else:
        option = "off"

    logger.info(f"uid: {uid}, option: {option}, config_name: {config_name}")

    other_msg = ""
    if config_name == "自动签到":
        if not await get_signin_config():
            return "自动签到功能已禁用!\n"

        # 执行设置
        await DNAUser.update_data_by_uid(
            uid=uid,
            bot_id=ctx.bot_id,
            sign_switch=option,
        )

        if ctx.bot_id == "onebot":
            if option == "off":
                await gs_subscribe.delete_subscribe("single", BoardcastTypeEnum.SIGN_DNA, ctx)
            else:
                await gs_subscribe.add_subscribe("single", BoardcastTypeEnum.SIGN_DNA, ctx)

        if option != "off":
            from .dna_config import DNASignConfig

            SIGN_TIME = DNASignConfig.get_config("SignTime").data
            if isinstance(SIGN_TIME, tuple):
                sign_time_str = f"{SIGN_TIME[0]:02d}:{SIGN_TIME[1]:02d}"
            else:
                sign_time_str = SIGN_TIME
            other_msg = f"😄将于[{sign_time_str}]点自动为您开始{config_name}"

    else:
        return "该配置项不存在!"

    if option == "on":
        succeed_msg = "开启至私聊消息!"
    elif option == "off":
        succeed_msg = "关闭!"
    else:
        succeed_msg = f"开启至群{option}"

    return f"{config_name}已{succeed_msg}\n{other_msg}"
