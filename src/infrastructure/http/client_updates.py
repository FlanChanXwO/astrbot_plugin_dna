"""公开客户端更新 Source 的只读 HTTP transport。

只读取登记 provider 所需的 VersionList、补丁 manifest 或 App Store Lookup JSON；
不下载补丁正文，也不把 URL、服务端原文或响应细节带入领域错误。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Self, cast

import httpx
from astrbot.api import logger

from ...modules.client_updates.contracts import (
    AppStoreVersionMetadata,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateFailureKind,
    ClientUpdateStructureError,
    ClientUpdateTransportError,
    ClientVersionSnapshot,
    ManifestCdnVersionMetadata,
    parse_version_list_entries,
    sum_manifest_patch_file_sizes,
)
from ...modules.client_updates.registry import (
    AppStoreProviderConfig,
    ClientUpdateProviderKind,
    ClientUpdateSource,
    ManifestCdnProviderConfig,
    resolve_client_update_source,
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


_APP_STORE_USER_AGENT = "AstrBot-DNA-Client-Update/1"
SessionFactory = Callable[[], Any]


class ClientUpdateTransport:
    """按 Source provider 获取当前版本与可见历史。"""

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
        source_id: str,
        *,
        baseline: ClientSourceVersion | None = None,
    ) -> ClientSourceObservation:
        """读取一个已登记 Source；baseline 缺口通过 observation 显式表达。"""

        source = resolve_client_update_source(source_id)
        _validate_baseline(source, baseline)
        async with self._session_factory() as session:
            if source.provider_kind is ClientUpdateProviderKind.MANIFEST_CDN:
                config = source.provider_config
                if not isinstance(config, ManifestCdnProviderConfig):
                    raise _server_error("Source", "manifest provider config mismatch")
                return await self._get_manifest_observation(
                    session,
                    source,
                    config,
                    baseline,
                )

            config = source.provider_config
            if not isinstance(config, AppStoreProviderConfig):
                raise _server_error("Source", "app store provider config mismatch")
            return await self._get_app_store_observation(
                session,
                source,
                config,
                baseline,
            )

    async def _get_manifest_observation(
        self,
        session: Any,
        source: ClientUpdateSource,
        config: ManifestCdnProviderConfig,
        baseline: ClientSourceVersion | None,
    ) -> ClientSourceObservation:
        version_payload, version_url = await self._get_json_with_fallback(
            session,
            primary_url=_version_url(config.primary_base_url, config.branch),
            fallback_url=_version_url(config.fallback_base_url, config.branch),
            user_agent=config.user_agent,
            resource="VersionList",
        )
        version_base_url = (
            config.primary_base_url
            if version_url == _version_url(config.primary_base_url, config.branch)
            else config.fallback_base_url
        )
        versions = _parse_manifest_versions(version_payload, source)
        current = versions[-1]
        if baseline is None:
            return ClientSourceObservation(
                current=current,
                observed_versions=versions,
                history_complete=True,
                added_size_bytes=None,
            )

        baseline_index = _find_revision_index(versions, baseline.revision_id)
        if baseline_index is None:
            return ClientSourceObservation(
                current=current,
                observed_versions=versions,
                history_complete=False,
                added_size_bytes=None,
            )

        new_versions = versions[baseline_index + 1 :]
        added_size_bytes = 0
        for version in new_versions:
            added_size_bytes += await self._get_manifest_patch_size(
                session,
                source,
                config,
                version,
                base_url=version_base_url,
            )
        return ClientSourceObservation(
            current=current,
            observed_versions=versions,
            history_complete=True,
            added_size_bytes=added_size_bytes,
        )

    async def _get_manifest_patch_size(
        self,
        session: Any,
        source: ClientUpdateSource,
        config: ManifestCdnProviderConfig,
        version: ClientSourceVersion,
        *,
        base_url: str,
    ) -> int:
        metadata = version.provider_metadata
        if not isinstance(metadata, ManifestCdnVersionMetadata):
            raise _server_error("VersionList", "manifest metadata mismatch")
        directory = _manifest_directory(source, metadata)
        fallback_base_url = (
            config.fallback_base_url
            if base_url == config.primary_base_url
            else config.primary_base_url
        )
        pak_result, res_result = await asyncio.gather(
            self._get_json_with_fallback(
                session,
                primary_url=_manifest_url(
                    base_url, config.branch, directory, "PakFilesInfo.json"
                ),
                fallback_url=_manifest_url(
                    fallback_base_url,
                    config.branch,
                    directory,
                    "PakFilesInfo.json",
                ),
                user_agent=config.user_agent,
                resource="PakFilesInfo",
            ),
            self._get_json_with_fallback(
                session,
                primary_url=_manifest_url(
                    base_url, config.branch, directory, "ResDiscreteInfo.json"
                ),
                fallback_url=_manifest_url(
                    fallback_base_url,
                    config.branch,
                    directory,
                    "ResDiscreteInfo.json",
                ),
                user_agent=config.user_agent,
                resource="ResDiscreteInfo",
            ),
        )
        try:
            return sum_manifest_patch_file_sizes(
                config.pak_manifest_key,
                config.res_manifest_key,
                pak_result[0],
                res_result[0],
            )
        except (ClientUpdateStructureError, TypeError, ValueError) as error:
            raise _contract_error("补丁清单", type(error).__name__) from None

    async def _get_app_store_observation(
        self,
        session: Any,
        source: ClientUpdateSource,
        config: AppStoreProviderConfig,
        baseline: ClientSourceVersion | None,
    ) -> ClientSourceObservation:
        payload = await self._get_json(
            session,
            _app_store_lookup_url(config),
            user_agent=_APP_STORE_USER_AGENT,
            resource="App Store Lookup",
        )
        current = _parse_app_store_version(payload, source, config)
        unchanged = baseline is not None and baseline.revision_id == current.revision_id
        return ClientSourceObservation(
            current=current,
            observed_versions=(current,),
            history_complete=baseline is None or unchanged,
            added_size_bytes=0 if unchanged else None,
        )

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
            logger.warning(
                "客户端更新主端点失败，尝试备用端点 "
                "resource=%s kind=%s status=%s",
                error.resource,
                error.kind.value,
                error.status_code,
            )
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
                        raise _server_error(resource, "response status is invalid")
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
                raise _server_error(resource, type(error).__name__) from None

        if self.request_gate is None:
            return await request()
        return await self.request_gate.run(request, key=("client-update-json", url))


def _validate_baseline(
    source: ClientUpdateSource,
    baseline: ClientSourceVersion | None,
) -> None:
    if baseline is not None and not isinstance(baseline, ClientSourceVersion):
        raise TypeError("baseline 必须是 ClientSourceVersion 或 None")
    if baseline is not None and baseline.source_id != source.source_id:
        raise ValueError("baseline 与 Source 不一致")


def _parse_manifest_versions(
    payload: object,
    source: ClientUpdateSource,
) -> tuple[ClientSourceVersion, ...]:
    try:
        snapshots = parse_version_list_entries(payload, source.platform)
    except (ClientUpdateStructureError, TypeError, ValueError) as error:
        raise _contract_error("VersionList", type(error).__name__) from None
    ordered = sorted(
        snapshots,
        key=lambda snapshot: (snapshot.version_key, snapshot.patch_version),
    )
    return tuple(_source_version_from_snapshot(source.source_id, item) for item in ordered)


def _source_version_from_snapshot(
    source_id: str,
    snapshot: ClientVersionSnapshot,
) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id=source_id,
        version_text=snapshot.version_text,
        revision_id=str(snapshot.version_key),
        order_key=(snapshot.version_key, snapshot.patch_version),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=snapshot.version_key,
            patch_version=snapshot.patch_version,
            resource_version_dir=snapshot.resource_version_dir,
        ),
    )


def _find_revision_index(
    versions: tuple[ClientSourceVersion, ...],
    revision_id: str,
) -> int | None:
    for index, version in enumerate(versions):
        if version.revision_id == revision_id:
            return index
    return None


def _manifest_directory(
    source: ClientUpdateSource,
    metadata: ManifestCdnVersionMetadata,
) -> str:
    if source.platform is ClientPlatform.ANDROID:
        if metadata.resource_version_dir is None:
            raise _contract_error(
                "VersionList",
                "Android resource directory is missing",
            )
        return metadata.resource_version_dir
    return str(metadata.patch_version)


def _parse_app_store_version(
    payload: object,
    source: ClientUpdateSource,
    config: AppStoreProviderConfig,
) -> ClientSourceVersion:
    try:
        root = _require_mapping(payload, "App Store Lookup")
        result_count = root.get("resultCount")
        results = root.get("results")
        if type(result_count) is not int or result_count != 1:
            raise ClientUpdateStructureError("App Store resultCount must be 1")
        if not isinstance(results, list) or len(results) != 1:
            raise ClientUpdateStructureError("App Store results must contain one item")
        result = _require_mapping(results[0], "App Store result")
        track_id = result.get("trackId")
        version = result.get("version")
        release_date = result.get("currentVersionReleaseDate")
        if track_id != config.track_id:
            raise ClientUpdateStructureError("App Store trackId mismatch")
        if not isinstance(version, str) or not version.strip():
            raise ClientUpdateStructureError("App Store version must be non-empty")
        if release_date is not None and (
            not isinstance(release_date, str) or not release_date.strip()
        ):
            raise ClientUpdateStructureError("App Store release date is invalid")
    except (ClientUpdateStructureError, TypeError, ValueError) as error:
        raise _contract_error("App Store Lookup", type(error).__name__) from None
    return ClientSourceVersion(
        source_id=source.source_id,
        version_text=version,
        revision_id=f"{config.track_id}:{version}",
        order_key=None,
        provider_metadata=AppStoreVersionMetadata(
            track_id=config.track_id,
            country=config.country,
            release_date=cast(str | None, release_date),
        ),
    )


def _require_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ClientUpdateStructureError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _version_url(base_url: str, branch: str) -> str:
    return f"{base_url}/{branch}/VersionList.json"


def _manifest_url(base_url: str, branch: str, directory: str, name: str) -> str:
    return f"{base_url}/{branch}/{directory}/{name}"


def _app_store_lookup_url(config: AppStoreProviderConfig) -> str:
    return f"https://itunes.apple.com/lookup?id={config.track_id}&country={config.country}"


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


def _server_error(resource: str, detail: str) -> ClientUpdateTransportError:
    return ClientUpdateTransportError(
        ClientUpdateFailureKind.SERVER,
        resource=resource,
        detail=detail,
    )


__all__ = [
    "ClientUpdateTransport",
]
