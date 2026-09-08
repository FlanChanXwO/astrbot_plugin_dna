"""跨 transport 复用的凭据失效判定。"""

from __future__ import annotations

import re
from typing import Any


_AUTH_FAILURE_MARKERS = (
    "token无效",
    "token失效",
    "token已失效",
    "token过期",
    "token已过期",
    "登录失效",
    "登录已失效",
    "登录过期",
    "凭据无效",
    "凭据失效",
    "credentialinvalid",
    "credentialexpired",
    "tokeninvalid",
    "tokenexpired",
    "unauthorized",
    "authenticationfailed",
    "用户身份校验失败",
    "身份校验失败",
)


def is_credential_failure(response: Any) -> bool:
    """判断响应是否明确表示凭据失效，不把普通失败误判为认证失败。"""

    code = getattr(response, "code", None)
    if code == -999:
        return False
    if code in (401, 403):
        return True

    message = str(getattr(response, "msg", "") or "").casefold()
    normalized = re.sub(r"[\s:：，,。.!！?？_\-]+", "", message)
    return any(marker in normalized for marker in _AUTH_FAILURE_MARKERS)


__all__ = ["is_credential_failure"]
