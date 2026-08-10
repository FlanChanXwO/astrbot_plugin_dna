from ..utils.constants.constants import PATTERN
from ..utils.session import EventContext, Sender
from .upload_card import (
    compress_role_panel_imgs,
    delete_all_role_panel_imgs,
    delete_original_role_panel_img,
    delete_role_panel_img_by_id,
    list_role_panel_imgs,
    upload_role_panel_img,
)


async def handle_upload_panel_img(sender: Sender, ctx: EventContext):
    char_name = ctx.regex_dict.get("char_name", "")
    await upload_role_panel_img(sender, ctx, char_name)


async def handle_delete_original_panel_img(sender: Sender, ctx: EventContext):
    await delete_original_role_panel_img(sender, ctx)


async def handle_delete_panel_img_by_id(sender: Sender, ctx: EventContext):
    char_name = ctx.regex_dict.get("char_name", "")
    image_id = ctx.regex_dict.get("image_id", "")
    await delete_role_panel_img_by_id(sender, ctx, char_name, image_id)


async def handle_delete_all_panel_imgs(sender: Sender, ctx: EventContext):
    char_name = ctx.regex_dict.get("char_name", "")
    await delete_all_role_panel_imgs(sender, ctx, char_name)


async def handle_list_panel_imgs(sender: Sender, ctx: EventContext):
    char_name = ctx.regex_dict.get("char_name", "")
    await list_role_panel_imgs(sender, ctx, char_name)


async def handle_compress_panel_imgs(sender: Sender, ctx: EventContext):
    await compress_role_panel_imgs(sender, ctx)


COMMANDS = [
    {
        "key": "upload_panel_img",
        "group": "面板图管理",
        "name": "上传面板图",
        "desc": "上传角色自定义面板图",
        "eg": "上传角色面板图",
        "regex": rf"^上传(?P<char_name>{PATTERN})面板图$",
        "permission": "owner",
        "handler": handle_upload_panel_img,
    },
    {
        "key": "list_panel_imgs",
        "group": "面板图管理",
        "name": "面板图列表",
        "desc": "查看角色已上传的面板图",
        "eg": "角色面板图列表",
        "regex": rf"^(?P<char_name>{PATTERN})面板图列表$",
        "permission": "owner",
        "handler": handle_list_panel_imgs,
    },
    {
        "key": "delete_panel_img_by_id",
        "group": "面板图管理",
        "name": "删除面板图",
        "desc": "按 ID 删除角色面板图",
        "eg": "删除角色面板图abc",
        "regex": rf"^删除(?P<char_name>{PATTERN})面板图(?P<image_id>\S+)$",
        "permission": "owner",
        "handler": handle_delete_panel_img_by_id,
    },
    {
        "key": "delete_all_panel_imgs",
        "group": "面板图管理",
        "name": "删除全部面板图",
        "desc": "删除角色全部面板图",
        "eg": "删除角色全部面板图",
        "regex": rf"^删除(?P<char_name>{PATTERN})全部面板图$",
        "permission": "owner",
        "handler": handle_delete_all_panel_imgs,
    },
    {
        "key": "delete_original_panel_img",
        "group": "面板图管理",
        "name": "原图删除",
        "desc": "删除引用的原图",
        "eg": "原图删除",
        "regex": r"^原图删除$",
        "permission": "owner",
        "handler": handle_delete_original_panel_img,
    },
    {
        "key": "compress_panel_imgs",
        "group": "面板图管理",
        "name": "压缩面板图",
        "desc": "压缩全部自定义面板图",
        "eg": "压缩面板图",
        "regex": r"^压缩面板图$",
        "permission": "owner",
        "handler": handle_compress_panel_imgs,
    },
]
