"""GitHub 资源下载加速前缀与 URL 安全边界。"""

from __future__ import annotations

from typing import Literal, TypeAlias
from urllib.parse import SplitResult, urlsplit, urlunsplit

GithubAccelerationMode: TypeAlias = Literal[
    "off",
    "edgeone",
    "hk",
    "gh_proxy",
    "dpik",
    "custom",
]

GITHUB_ORIGIN_PREFIX = "https://github.com/"

BUILTIN_GITHUB_ACCELERATION_PREFIXES: dict[GithubAccelerationMode, str] = {
    "edgeone": "https://edgeone.gh-proxy.com",
    "hk": "https://hk.gh-proxy.com",
    "gh_proxy": "https://gh-proxy.com",
    "dpik": "https://gh.dpik.top",
}


def _validate_text(value: object, *, empty_message: str) -> str:
    if not isinstance(value, str):
        raise TypeError("URL 必须是文本")
    candidate = value.strip()
    if not candidate:
        raise ValueError(empty_message)
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise ValueError("URL 不能包含控制字符")
    if any(character.isspace() for character in candidate):
        raise ValueError("URL 不能包含空白字符")
    if "\\" in candidate:
        raise ValueError("URL 不能包含反斜杠")
    return candidate


def _normalized_netloc(parsed: SplitResult) -> str:
    # ``SplitResult`` 的属性访问可能因非法端口抛出 ValueError；调用方统一转为
    # 不回显原始值的配置错误。
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL 的主机或端口无效") from exc
    if not hostname:
        raise ValueError("URL 必须包含主机")
    normalized_host = hostname.lower()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return normalized_host if port is None else f"{normalized_host}:{port}"


def normalize_http_base_url(value: str, *, allow_empty: bool = True) -> str:
    """规范化安全的 HTTP(S) 基础 URL，不保留尾部斜杠、query 或 fragment。"""

    if not isinstance(value, str):
        raise TypeError("加速地址必须是文本")
    candidate = value.strip()
    if not candidate:
        if allow_empty:
            return ""
        raise ValueError("加速地址不能为空")
    candidate = _validate_text(candidate, empty_message="加速地址不能为空")
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise ValueError("加速地址格式无效") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("加速地址必须使用 HTTP(S)")
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise ValueError("加速地址不能包含凭据")
    if parsed.query or parsed.fragment:
        raise ValueError("加速地址不能包含 query 或 fragment")
    if any(part in {".", ".."} for part in parsed.path.split("/")):
        raise ValueError("加速地址路径不能包含相对段")
    netloc = _normalized_netloc(parsed)
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def normalize_github_repository_url(value: str) -> str:
    """把仓库地址规范为无凭据、无参数的 ``https://github.com/owner/repo.git``。"""

    candidate = _validate_text(value, empty_message="资源 Git remote 不能为空")
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise ValueError("资源 Git remote 格式无效") from exc
    if parsed.scheme.lower() != "https":
        raise ValueError("资源 Git remote 必须使用 HTTPS")
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise ValueError("资源 Git remote 不能包含凭据")
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("资源 Git remote 的主机或端口无效") from exc
    if hostname is None or hostname.lower() != "github.com" or port is not None:
        raise ValueError("资源 Git remote 必须指向 github.com")
    if parsed.query or parsed.fragment:
        raise ValueError("资源 Git remote 不能包含 query 或 fragment")

    path = parsed.path
    path = path.removesuffix("/")
    if not path.startswith("/") or path.count("/") != 2:
        raise ValueError("资源 Git remote 必须包含 owner/repository")
    owner, repository = path[1:].split("/")
    repository = repository.removesuffix(".git")
    if not owner or not repository or owner in {".", ".."} or repository in {".", ".."}:
        raise ValueError("资源 Git remote 的 owner/repository 无效")
    return f"{GITHUB_ORIGIN_PREFIX}{owner}/{repository}.git"


def resolve_github_acceleration_prefix(
    mode: GithubAccelerationMode | str,
    custom_url: str = "",
) -> str | None:
    """将配置模式解析为加速前缀；``off`` 明确返回 ``None``。"""

    if mode == "off":
        return None
    if mode == "custom":
        normalized = normalize_http_base_url(custom_url, allow_empty=False)
        return normalized
    try:
        return BUILTIN_GITHUB_ACCELERATION_PREFIXES[mode]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError("未知 GitHub 加速模式") from exc


def build_git_instead_of_config(prefix: str) -> str:
    """生成只对当前 Git 子进程生效的 ``url.*.insteadOf`` 配置。"""

    normalized = normalize_http_base_url(prefix, allow_empty=False)
    replacement = f"{normalized}/{GITHUB_ORIGIN_PREFIX}"
    return f"url.{replacement}.insteadOf={GITHUB_ORIGIN_PREFIX}"


def accelerate_github_url(url: str, prefix: str | None) -> str:
    """按 AstrBot 资源 URL 语义把完整原始 URL 放到加速前缀之后。"""

    candidate = _validate_text(url, empty_message="目标 URL 不能为空")
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise ValueError("目标 URL 格式无效") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("目标 URL 必须是 HTTP(S) 地址")
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise ValueError("目标 URL 不能包含凭据")
    if prefix is None:
        return candidate
    normalized_prefix = normalize_http_base_url(prefix, allow_empty=False)
    return f"{normalized_prefix}/{candidate}"


__all__ = [
    "BUILTIN_GITHUB_ACCELERATION_PREFIXES",
    "GITHUB_ORIGIN_PREFIX",
    "GithubAccelerationMode",
    "accelerate_github_url",
    "build_git_instead_of_config",
    "normalize_github_repository_url",
    "normalize_http_base_url",
    "resolve_github_acceleration_prefix",
]
