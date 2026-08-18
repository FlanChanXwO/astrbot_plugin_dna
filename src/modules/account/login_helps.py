import hashlib
import hmac
import re
import secrets

_LOGIN_AUTH_SECRET = secrets.token_bytes(32)


def is_valid_chinese_phone_number(phone_number):
    # 正则表达式匹配中国大陆的手机号
    pattern = re.compile(r"^1[3-9]\d{9}$")
    return pattern.match(phone_number) is not None


def is_validate_code(code):
    # 正则表达式匹配4位数字
    pattern = re.compile(r"^\d{4}$")
    return pattern.match(code) is not None


def get_token(userId: str) -> str:
    """为登录会话生成进程内稳定但不可由 user_id 反推的标识。"""
    return hmac.new(_LOGIN_AUTH_SECRET, userId.encode(), hashlib.sha256).hexdigest()
