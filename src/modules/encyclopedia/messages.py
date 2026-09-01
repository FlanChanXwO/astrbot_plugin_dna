"""资料查询的用户可见文案。

文案集中在模块边界，service 不拼接服务端原文；这样网络、状态码和结构变化不会
把 token、URL 或调试细节意外发送到聊天中。
"""

from datetime import datetime

from .contracts import CodeEntry

CONTEXT_UNAVAILABLE = "资料查询需要有效的消息上下文"
SERVICE_UNAVAILABLE = "资料服务暂不可用，请检查插件配置"
UID_INVALID = "尚未登录，请先登录"
PEEK_BLOCKED = "该用户不允许被查询"
CODE_TITLE = "[DNA兑换码]"
CODE_EMPTY = f"{CODE_TITLE} 暂无可用兑换码"


def transport_error(kind: str) -> str:
    """按安全失败类别生成稳定文案。"""

    labels = {
        "network": "网络",
        "status": "服务状态",
        "contract": "数据契约",
        "server": "服务",
        "not_found": "资料",
        "resource": "资源",
    }
    return f"{labels.get(kind, '资料')}服务暂不可用，请稍后重试"


def not_found(resource: str) -> str:
    """生成资源未找到文案，不包含底层路径。"""

    return f"{resource}未找到，请检查名称或资源配置"


def _format_code_datetime(value: datetime) -> str:
    """按兑换码展示约定格式化已由 transport 规范化的时间。"""

    return value.strftime("%Y-%m-%d %H:%M:%S")


def code_entry(entry: CodeEntry | str, expiry: str = "") -> str:
    """渲染兑换码本身及 provider 提供的非空可选字段。"""

    # 保留旧调用形态，避免注入型 fixture 或外部集成在过渡期间失效。
    if isinstance(entry, str):
        return f"{entry}（有效期至：{expiry}）" if expiry else entry

    if (
        entry.expires_at is not None
        and not entry.reward
        and entry.valid_from is None
        and not entry.platforms
        and not entry.servers
    ):
        return f"{entry.code}（有效期至：{_format_code_datetime(entry.expires_at)}）"

    lines = [entry.code]
    if entry.reward:
        lines.append(f"奖励：{entry.reward}")
    if entry.valid_from is not None:
        lines.append(f"生效时间：{_format_code_datetime(entry.valid_from)}")
    if entry.expires_at is not None:
        lines.append(f"有效期至：{_format_code_datetime(entry.expires_at)}")
    if entry.platforms:
        lines.append(f"平台：{'、'.join(entry.platforms)}")
    if entry.servers:
        lines.append(f"区服：{'、'.join(entry.servers)}")
    return "\n".join(lines)


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
