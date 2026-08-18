"""AstrBot legacy 配置兼容层与 schema 生成器。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

DNA_PREFIX = "[二重螺旋]"

CONFIG_DEFAULT = {
    "DNAUID配置": {
        "description": "二重螺旋插件配置",
        "type": "object",
        "items": {
            "MaxBindNum": {
                "description": "未登录用户最大绑定UID数量",
                "type": "int",
                "default": 2,
                "hint": "未登录用户最大绑定UID数量",
            },
            "DNALoginUrl": {
                "description": "dna-login 服务端地址",
                "type": "string",
                "default": "",
                "hint": "部署了 dna-login 的服务地址",
            },
            "DNALoginBindHost": {
                "description": "local 模式下登录页监听地址",
                "type": "string",
                "default": "127.0.0.1",
                "hint": "local 模式下登录页监听地址",
            },
            "DNALoginPort": {
                "description": "local 模式下登录页监听端口",
                "type": "int",
                "default": 6189,
                "hint": "0 表示由系统分配临时端口",
            },
            "DNALoginTransport": {
                "description": "登录页接入方式",
                "type": "string",
                "default": "local",
                "options": ["local", "http_poll", "sse", "ws"],
            },
            "DNALoginSecret": {
                "description": "外置登录服务共享密钥",
                "type": "string",
                "default": "",
            },
            "DNATencentWord": {
                "description": "腾讯文档登录辅助",
                "type": "bool",
                "default": False,
            },
            "DNAQRLogin": {
                "description": "二维码登录",
                "type": "bool",
                "default": False,
            },
            "DNALoginForward": {
                "description": "登录转发消息",
                "type": "bool",
                "default": False,
            },
            "DNAPaint": {
                "description": "角色立绘作者",
                "type": "string",
                "default": "all",
                "options": ["all", "狩月庭攻略组", "猫冬"],
            },
            "DNAPaintShowNone": {
                "description": "角色总览卡显示未拥有角色",
                "type": "bool",
                "default": True,
            },
            "DNAAt": {
                "description": "允许通过 @ 查询他人信息",
                "type": "bool",
                "default": True,
            },
            "DNAAnnState": {
                "description": "公告推送状态",
                "type": "bool",
                "default": True,
            },
            "DNAAnnGroups": {
                "description": "公告推送群组列表",
                "type": "object",
                "items": {},
                "default": {},
            },
            "DNAAnnIds": {
                "description": "已推送的公告ID",
                "type": "list",
                "default": [],
            },
            "AnnMinuteCheck": {
                "description": "公告检查间隔(分钟)",
                "type": "int",
                "default": 10,
            },
            "MHSubscribe": {
                "description": "密函订阅类型",
                "type": "list",
                "default": ["group"],
            },
            "MHPushSubscribe": {
                "description": "密函推送时间 (分:秒)",
                "type": "string",
                "default": "00:30",
            },
            "MHCache": {
                "description": "密函数据缓存",
                "type": "bool",
                "default": True,
            },
            "MHSimplePic": {
                "description": "简易密函图片",
                "type": "bool",
                "default": False,
            },
            "MHPushTask": {
                "description": "密函推送开关",
                "type": "bool",
                "default": True,
            },
        },
    },
    "DNAUID签到配置": {
        "description": "二重螺旋签到配置",
        "type": "object",
        "items": {
            "DNASignin": {
                "description": "自动签到开关",
                "type": "bool",
                "default": False,
            },
            "SignTime": {
                "description": "每日签到时间 (时:分)",
                "type": "string",
                "default": "00:05",
            },
            "SignAllUser": {
                "description": "为所有已绑定用户自动签到",
                "type": "bool",
                "default": True,
            },
            "DNABBSLink": {
                "description": "社区任务项",
                "type": "list",
                "default": [
                    "bbs_sign",
                    "bbs_detail",
                    "bbs_like",
                    "bbs_share",
                    "bbs_reply",
                ],
            },
            "SignRandomTime": {
                "description": "签到随机延迟间隔",
                "type": "list",
                "default": [3, 5],
            },
            "PrivateSignReport": {
                "description": "私聊签到报告",
                "type": "bool",
                "default": False,
            },
            "GroupSignReport": {
                "description": "群聊签到报告",
                "type": "bool",
                "default": False,
            },
            "GroupSignReportPic": {
                "description": "群聊签到报告以图片形式发送",
                "type": "bool",
                "default": False,
            },
        },
    },
}


def generate_astrbot_schema() -> dict[str, Any]:
    return copy.deepcopy(CONFIG_DEFAULT)


@dataclass
class ConfigEntry:
    data: Any


class _ConfigNamespace:
    def __init__(self, section: str) -> None:
        self._section = section
        self._store: dict[str, Any] | None = None

    def bind(self, store: dict[str, Any] | None) -> None:
        self._store = store

    def get_config(self, key: str) -> ConfigEntry:
        schema = CONFIG_DEFAULT.get(self._section, {}).get("items", {})
        if key not in schema:
            raise KeyError(f"未知配置项: {key}")

        default_val = schema[key].get("default")
        if self._store is not None:
            section_data = self._store.get(self._section)
            if isinstance(section_data, dict) and key in section_data:
                return ConfigEntry(data=section_data[key])
        return ConfigEntry(data=default_val)

    def set_config(self, key: str, value: Any) -> None:
        schema = CONFIG_DEFAULT.get(self._section, {}).get("items", {})
        if key not in schema:
            raise KeyError(f"未知配置项: {key}")
        if self._store is not None:
            self._store.setdefault(self._section, {})[key] = value


DNAConfig = _ConfigNamespace("DNAUID配置")
DNASignConfig = _ConfigNamespace("DNAUID签到配置")


__all__ = [
    "CONFIG_DEFAULT",
    "DNAConfig",
    "DNASignConfig",
    "DNA_PREFIX",
    "generate_astrbot_schema",
]
