"""公开客户端更新 API 的 HTTP transport。

本模块只读取契约中明确的 VersionList 和补丁清单 JSON，不下载补丁正文，也不把
URL、服务端原文或响应细节带入领域错误。默认客户端使用项目已有的 ``httpx``
依赖；在支持 aiohttp 的运行时保留同样的 ClientSession seam，便于复用现有
transport fake 和部署环境。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Self

import httpx

from ...modules.client_updates.channels import (
    CLIENT_UPDATE_CHANNELS,
    ClientUpdateChannel,
    default_channel_id_for_platform,
    resolve_client_update_channel,
)
from ...modules.client_updates.contracts import (
    ClientPlatform,
    ClientUpdateFailureKind,
    ClientUpdateObservation,
    ClientUpdateStructureError,
    ClientUpdateTransportError,
    ClientVersionSnapshot,
    parse_version_list_entries,
    sum_channel_patch_file_sizes,
    sum_patch_file_sizes,
)
from .concurrency import RequestConcurrencyGate

try:
    import aiohttp as _aiohttp
except ImportError:
    _aiohttp = None


class _HttpxResponse:
    """把 httpx response 缩小为 transport 所需的 aiohttp-like 形状。"""

    def __init__(self, response: httpx.Response) -> None:
        self.status = response.status_code
        self._response = response

    async def json(self) -> object:
        return self._response.json()


class _HttpxRequestContext:
    """把 httpx 的 awaitable response 包装为异步上下文管理器。"""

    def __init__(self, response: Awaitable[httpx.Response]) -> None:
        self._response_awaitable = response

    async def __aenter__(self) -> _HttpxResponse:
        return _HttpxResponse(await self._response_awaitable)

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None


class _HttpxSession:
    """提供最小 ClientSession seam，避免导入不兼容的旧 aiohttp。"""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        await self._client.aclose()

    def get(self, url: str, **kwargs: Any) -> _HttpxRequestContext:
        return _HttpxRequestContext(self._client.get(url, **kwargs))


class _AiohttpCompat:
    """当前环境无法导入 aiohttp 时暴露兼容的 ClientSession 属性。"""

    ClientSession = _HttpxSession


# 测试和既有 transport 风格都通过这个窄 seam 替换 ClientSession；正常运行时优先
# 使用 aiohttp，当前 Python 3.14 导入失败时则回退到项目已有的 httpx。
aiohttp = _aiohttp if _aiohttp is not None else _AiohttpCompat()


if _aiohttp is not None:
    _NETWORK_ERRORS: tuple[type[BaseException], ...] = (
        _aiohttp.ClientError,
        httpx.HTTPError,
        OSError,
        asyncio.TimeoutError,
    )
else:
    _NETWORK_ERRORS = (httpx.HTTPError, OSError, asyncio.TimeoutError)


# 旧 platform transport 常量继续保留为兼容导出，但协议元数据唯一来自 channel registry。
_PC_CHANNEL = CLIENT_UPDATE_CHANNELS["pc_cn"]
_ANDROID_CHANNEL = CLIENT_UPDATE_CHANNELS["android_astc_cn"]
PC_PRIMARY_BASE_URL = _PC_CHANNEL.primary_base_url
PC_FALLBACK_BASE_URL = _PC_CHANNEL.fallback_base_url
ANDROID_PRIMARY_BASE_URL = _ANDROID_CHANNEL.primary_base_url
ANDROID_FALLBACK_BASE_URL = _ANDROID_CHANNEL.fallback_base_url
PC_BRANCH = _PC_CHANNEL.branch
ANDROID_BRANCH = _ANDROID_CHANNEL.branch
PC_USER_AGENT = _PC_CHANNEL.user_agent
ANDROID_USER_AGENT = _ANDROID_CHANNEL.user_agent


SessionFactory = Callable[[], Any]


class ClientUpdateTransport:
    """读取国服 PC/安卓最新版本及新增补丁清单的 transport。"""

    def __init__(
        self,
        *,
        request_gate: RequestConcurrencyGate | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.request_gate = request_gate
        self._session_factory = (
            aiohttp.ClientSession if session_factory is None else session_factory
        )

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        """读取一个平台或固定渠道的最新版本及新增补丁大小。"""

        normalized_platform, channel, explicit_channel = _resolve_target(platform)
        _validate_previous_patch_version(previous_patch_version)

        async with self._session_factory() as session:
            version_payload, version_url = await self._get_version_payload(
                session,
                channel,
            )
            version_base_url = (
                channel.primary_base_url
                if version_url == _version_url(channel.primary_base_url, channel.branch)
                else channel.fallback_base_url
            )
            entries = _parse_version_entries(
                version_payload,
                normalized_platform,
                channel=channel,
                explicit_channel=explicit_channel,
            )
            latest = max(
                entries,
                key=lambda version: (version.version_key, version.patch_version),
            )
            if (
                previous_patch_version is None
                or previous_patch_version >= latest.patch_version
            ):
                return ClientUpdateObservation(snapshot=latest)

            entries_by_patch = _index_entries(entries)
            patch_sizes: dict[int, int] = {}
            for patch_version in range(
                previous_patch_version + 1,
                latest.patch_version + 1,
            ):
                entry = entries_by_patch.get(patch_version)
                if entry is None:
                    raise _contract_error(
                        "VersionList",
                        "patch version entry is missing",
                    )
                patch_sizes[patch_version] = await self._get_patch_size(
                    session,
                    channel,
                    entry,
                    explicit_channel=explicit_channel,
                    base_url=version_base_url,
                )

            return ClientUpdateObservation(
                snapshot=latest,
                patch_sizes=patch_sizes,
            )

    async def _get_version_payload(
        self,
        session: Any,
        channel: ClientUpdateChannel,
    ) -> tuple[object, str]:
        return await self._get_json_with_fallback(
            session,
            primary_url=_version_url(channel.primary_base_url, channel.branch),
            fallback_url=_version_url(channel.fallback_base_url, channel.branch),
            user_agent=channel.user_agent,
            resource="VersionList",
        )

    async def _get_patch_size(
        self,
        session: Any,
        channel: ClientUpdateChannel,
        entry: ClientVersionSnapshot,
        *,
        explicit_channel: bool,
        base_url: str,
    ) -> int:
        directory = _manifest_directory(channel.platform, entry)
        fallback_base_url = (
            channel.fallback_base_url
            if base_url == channel.primary_base_url
            else channel.primary_base_url
        )
        pak_payload_result, res_payload_result = await asyncio.gather(
            self._get_json_with_fallback(
                session,
                primary_url=_manifest_url(
                    base_url, channel.branch, directory, "PakFilesInfo.json"
                ),
                fallback_url=_manifest_url(
                    fallback_base_url,
                    channel.branch,
                    directory,
                    "PakFilesInfo.json",
                ),
                user_agent=channel.user_agent,
                resource="PakFilesInfo",
            ),
            self._get_json_with_fallback(
                session,
                primary_url=_manifest_url(
                    base_url, channel.branch, directory, "ResDiscreteInfo.json"
                ),
                fallback_url=_manifest_url(
                    fallback_base_url,
                    channel.branch,
                    directory,
                    "ResDiscreteInfo.json",
                ),
                user_agent=channel.user_agent,
                resource="ResDiscreteInfo",
            ),
        )
        pak_payload, _ = pak_payload_result
        res_payload, _ = res_payload_result
        try:
            if explicit_channel:
                return sum_channel_patch_file_sizes(
                    channel.channel_id,
                    pak_payload,
                    res_payload,
                )
            return sum_patch_file_sizes(channel.platform, pak_payload, res_payload)
        except (ClientUpdateStructureError, TypeError, ValueError) as error:
            raise _contract_error("补丁清单", type(error).__name__) from None

    async def _get_json_with_fallback(
        self,
        session: Any,
        *,
        primary_url: str,
        fallback_url: str,
        user_agent: str,
        resource: str,
    ) -> tuple[object, str]:
        try:
            return (
                await self._get_json(
                    session,
                    primary_url,
                    user_agent=user_agent,
                    resource=resource,
                ),
                primary_url,
            )
        except ClientUpdateTransportError as error:
            if not _can_fallback(error):
                raise
            return (
                await self._get_json(
                    session,
                    fallback_url,
                    user_agent=user_agent,
                    resource=resource,
                ),
                fallback_url,
            )

    async def _get_json(
        self,
        session: Any,
        url: str,
        *,
        user_agent: str,
        resource: str,
    ) -> object:
        async def request() -> object:
            try:
                async with session.get(
                    url,
                    headers={"User-Agent": user_agent},
                ) as response:
                    status = getattr(response, "status", None)
                    if type(status) is not int:
                        raise ClientUpdateTransportError(
                            ClientUpdateFailureKind.SERVER,
                            resource=resource,
                            detail="response status is invalid",
                        )
                    if not 200 <= status < 300:
                        raise ClientUpdateTransportError(
                            ClientUpdateFailureKind.STATUS,
                            resource=resource,
                            status_code=status,
                            detail="response status is not successful",
                        )
                    try:
                        return await response.json()
                    except (TypeError, ValueError, UnicodeError) as error:
                        raise _contract_error(resource, type(error).__name__) from None
            except ClientUpdateTransportError:
                raise
            except _NETWORK_ERRORS as error:
                raise ClientUpdateTransportError(
                    ClientUpdateFailureKind.NETWORK,
                    resource=resource,
                    detail=type(error).__name__,
                ) from None
            except (AttributeError, KeyError, TypeError) as error:
                raise ClientUpdateTransportError(
                    ClientUpdateFailureKind.SERVER,
                    resource=resource,
                    detail=type(error).__name__,
                ) from None

        if self.request_gate is None:
            return await request()
        return await self.request_gate.run(request, key=("client-update-json", url))


def _resolve_target(
    target: ClientPlatform | str,
) -> tuple[ClientPlatform, ClientUpdateChannel, bool]:
    try:
        normalized_platform = _coerce_platform(target)
    except ValueError:
        channel = resolve_client_update_channel(target)
        return channel.platform, channel, True
    channel = resolve_client_update_channel(
        default_channel_id_for_platform(normalized_platform)
    )
    return normalized_platform, channel, False


def _parse_version_entries(
    payload: object,
    platform: ClientPlatform,
    *,
    channel: ClientUpdateChannel,
    explicit_channel: bool,
) -> tuple[ClientVersionSnapshot, ...]:
    try:
        if explicit_channel:
            return parse_version_list_entries(payload, channel.channel_id)
        return parse_version_list_entries(payload, platform)
    except (ClientUpdateStructureError, TypeError, ValueError) as error:
        raise _contract_error("VersionList", type(error).__name__) from None


def _index_entries(
    entries: tuple[ClientVersionSnapshot, ...],
) -> dict[int, ClientVersionSnapshot]:
    by_patch_version: dict[int, ClientVersionSnapshot] = {}
    for entry in entries:
        previous = by_patch_version.get(entry.patch_version)
        if previous is not None and previous != entry:
            raise _contract_error(
                "VersionList",
                "duplicate patch version has conflicting entries",
            )
        by_patch_version[entry.patch_version] = entry
    return by_patch_version


def _manifest_directory(platform: ClientPlatform, entry: ClientVersionSnapshot) -> str:
    if platform is ClientPlatform.ANDROID:
        if entry.resource_version_dir is None:
            raise _contract_error(
                "VersionList", "Android resource directory is missing"
            )
        return entry.resource_version_dir
    return str(entry.patch_version)


def _coerce_platform(platform: ClientPlatform | str) -> ClientPlatform:
    try:
        return ClientPlatform(platform)
    except (TypeError, ValueError) as error:
        raise ValueError("不支持的客户端平台") from error


def _validate_previous_patch_version(previous_patch_version: int | None) -> None:
    if previous_patch_version is not None and (
        type(previous_patch_version) is not int or previous_patch_version < 0
    ):
        raise ValueError("previous_patch_version 必须是非负整数或 None")


def _version_url(base_url: str, branch: str) -> str:
    return f"{base_url}/{branch}/VersionList.json"


def _manifest_url(base_url: str, branch: str, directory: str, name: str) -> str:
    return f"{base_url}/{branch}/{directory}/{name}"


def _can_fallback(error: ClientUpdateTransportError) -> bool:
    return error.kind is ClientUpdateFailureKind.NETWORK or (
        error.kind is ClientUpdateFailureKind.STATUS
        and error.status_code is not None
        and error.status_code >= 500
    )


def _contract_error(resource: str, detail: str) -> ClientUpdateTransportError:
    return ClientUpdateTransportError(
        ClientUpdateFailureKind.CONTRACT,
        resource=resource,
        detail=detail,
    )


__all__ = [
    "ANDROID_BRANCH",
    "ANDROID_FALLBACK_BASE_URL",
    "ANDROID_PRIMARY_BASE_URL",
    "ANDROID_USER_AGENT",
    "PC_BRANCH",
    "PC_FALLBACK_BASE_URL",
    "PC_PRIMARY_BASE_URL",
    "PC_USER_AGENT",
    "ClientUpdateTransport",
]
