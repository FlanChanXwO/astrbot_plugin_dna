"""资料查询的用户可见文案。

文案集中在模块边界，service 不拼接服务端原文；这样网络、状态码和结构变化不会
把 token、URL 或调试细节意外发送到聊天中。
"""

CONTEXT_UNAVAILABLE = "资料查询需要有效的消息上下文"
SERVICE_UNAVAILABLE = "资料服务暂不可用，请检查插件配置"
UID_INVALID = "UID 无效，请先绑定账号"
PEEK_BLOCKED = "该用户不允许被查询"
CODE_TITLE = "[DNA兑换码]"
CODE_EMPTY = f"{CODE_TITLE} 暂无可用兑换码"


def transport_error(kind: str) -> str:
    """按安全失败类别生成稳定文案。"""

    labels = {
        "network": "网络",
        "status": "服务状态",
        "server": "服务",
        "not_found": "资料",
        "resource": "资源",
    }
    return f"{labels.get(kind, '资料')}服务暂不可用，请稍后重试"


def not_found(resource: str) -> str:
    """生成资源未找到文案，不包含底层路径。"""

    return f"{resource}未找到，请检查名称或资源配置"


def code_entry(code: str, expiry: str) -> str:
    """在 provider 提供独立截止时间时保留与兑换码的一一对应。"""

    return f"{code}（有效期至：{expiry}）" if expiry else code


__all__ = [
    "CODE_EMPTY",
    "CODE_TITLE",
    "CONTEXT_UNAVAILABLE",
    "PEEK_BLOCKED",
    "SERVICE_UNAVAILABLE",
    "UID_INVALID",
    "code_entry",
    "not_found",
    "transport_error",
]
