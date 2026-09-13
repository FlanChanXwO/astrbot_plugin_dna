"""公开客户端更新 Source 的只读 HTTP transport。

只读取登记 provider 所需的 VersionList、补丁 manifest、Apple Lookup、B 站游戏
中心或好游快爆详情页数据；不下载补丁正文，也不把 URL、服务端原文或响应细节
带入领域错误。每个发行渠道的协议细节都封装在本模块的 Adapter 内，上层
Module 不感知具体渠道。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Self, cast

import httpx
from astrbot.api import logger

from ...modules.client_updates.contracts import (
    AppStoreVersionMetadata,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceProviderMetadata,
    ClientSourceVersion,
    ClientUpdateFailureKind,
    ClientUpdateStructureError,
    ClientUpdateTransportError,
    ClientVersionOrderKey,
    ClientVersionSnapshot,
    ManifestCdnVersionMetadata,
    parse_version_list_entries,
    sum_manifest_patch_file_sizes,
)
from ...modules.client_updates.registry import (
    CLIENT_UPDATE_REGISTRY,
    AppStoreProviderConfig,
    BilibiliGameCenterProviderConfig,
    ClientUpdateProviderKind,
    ClientUpdateRegistry,
    ClientUpdateSource,
    HykbProviderConfig,
    ManifestCdnProviderConfig,
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

    async def json(self, **_kwargs: object) -> object:
        return self._response.json()

    async def text(self, **_kwargs: object) -> str:
        return self._response.text


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
_BILIBILI_GAMEINFO_URL = "https://line1-h5-pc-api.biligame.com/game/detail/gameinfo"
_BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HYKB_DETAIL_URL = "https://m.3839.com/a/{0:d}.htm"
_HYKB_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Mobile/15E148"
)
_HYKB_DOWN_INFO_RE = re.compile(r"var downInfo = (\{.*?\}),", re.DOTALL)
_HYKB_VERSION_RE = re.compile(r'<p class="sp2">\s*([^<\s][^<]*?)\s*</p>')
_MD5_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
_BILIBILI_ANDROID_PACKAGE = "com.hero.dna.bilibili"
# Bilibili 渠道包下载文件名内嵌四段版本号（ezlx_1.6.186.1_...apk）；提取不到
# 时不伪造版本号，version_text 保持 None。
_BILIBILI_VERSION_RE = re.compile(r"_(\d+\.\d+\.\d+\.\d+)_")
SessionFactory = Callable[[], Any]


class ClientUpdateTransport:
    """按 Source provider 获取当前版本与可见历史。"""

    def __init__(
        self,
        *,
        request_gate: RequestConcurrencyGate | None = None,
        session_factory: SessionFactory | None = None,
        registry: ClientUpdateRegistry = CLIENT_UPDATE_REGISTRY,
    ) -> None:
        if not isinstance(registry, ClientUpdateRegistry):
            raise TypeError("registry 必须是 ClientUpdateRegistry")
        self.request_gate = request_gate
        self.registry = registry
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

        source = self.registry.resolve_source(source_id)
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

            if source.provider_kind is ClientUpdateProviderKind.APP_STORE:
                config = source.provider_config
                if not isinstance(config, AppStoreProviderConfig):
                    raise _server_error("Source", "app store provider config mismatch")
                return await self._get_app_store_observation(
                    session,
                    source,
                    config,
                    baseline,
                )

            if source.provider_kind is ClientUpdateProviderKind.BILIBILI_GAME_CENTER:
                config = source.provider_config
                if not isinstance(config, BilibiliGameCenterProviderConfig):
                    raise _server_error("Source", "bilibili provider config mismatch")
                return await self._get_bilibili_observation(
                    session,
                    source,
                    config,
                    baseline,
                )

            config = source.provider_config
            if not isinstance(config, HykbProviderConfig):
                raise _server_error("Source", "hykb provider config mismatch")
            return await self._get_hykb_observation(session, source, config, baseline)

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
            fallback_url=(
                _version_url(config.fallback_base_url, config.branch)
                if config.fallback_base_url is not None
                else None
            ),
            user_agent=config.user_agent,
            resource="VersionList",
        )
        version_base_url = (
            config.fallback_base_url
            if config.fallback_base_url is not None
            and version_url == _version_url(config.fallback_base_url, config.branch)
            else config.primary_base_url
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
                fallback_url=(
                    _manifest_url(
                        fallback_base_url,
                        config.branch,
                        directory,
                        "PakFilesInfo.json",
                    )
                    if fallback_base_url is not None and fallback_base_url != base_url
                    else None
                ),
                user_agent=config.user_agent,
                resource="PakFilesInfo",
            ),
            self._get_json_with_fallback(
                session,
                primary_url=_manifest_url(
                    base_url, config.branch, directory, "ResDiscreteInfo.json"
                ),
                fallback_url=(
                    _manifest_url(
                        fallback_base_url,
                        config.branch,
                        directory,
                        "ResDiscreteInfo.json",
                    )
                    if fallback_base_url is not None and fallback_base_url != base_url
                    else None
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
            accept_nonstandard_json_content_type=True,
        )
        current = _parse_app_store_version(payload, source, config)
        return _single_revision_observation(current, baseline)

    async def _get_bilibili_observation(
        self,
        session: Any,
        source: ClientUpdateSource,
        config: BilibiliGameCenterProviderConfig,
        baseline: ClientSourceVersion | None,
    ) -> ClientSourceObservation:
        payload = await self._get_json(
            session,
            f"{_BILIBILI_GAMEINFO_URL}?game_base_id={config.game_base_id}",
            user_agent=_BILIBILI_USER_AGENT,
            resource="Bilibili 游戏中心",
        )
        current = _parse_bilibili_gameinfo(payload, source)
        return _single_revision_observation(current, baseline)

    async def _get_hykb_observation(
        self,
        session: Any,
        source: ClientUpdateSource,
        config: HykbProviderConfig,
        baseline: ClientSourceVersion | None,
    ) -> ClientSourceObservation:
        page = await self._get_text(
            session,
            _HYKB_DETAIL_URL.format(config.game_id),
            user_agent=_HYKB_USER_AGENT,
            resource="好游快爆页面",
        )
        current = _parse_hykb_detail(page, source, config)
        return _single_revision_observation(current, baseline)

    async def _get_json_with_fallback(
        self,
        session: Any,
        *,
        primary_url: str,
        fallback_url: str | None,
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
            # 没有登记可信 fallback 时直接暴露 primary 的真实错误，不做无谓重试。
            if fallback_url is None or not _can_fallback(error):
                raise
            logger.warning(
                "客户端更新端点失败 endpoint_role=primary next_role=fallback "
                "resource=%s kind=%s status=%s",
                error.resource,
                error.kind.value,
                error.status_code,
            )
            try:
                fallback_payload = await self._get_json(
                    session,
                    fallback_url,
                    user_agent=user_agent,
                    resource=resource,
                )
            except ClientUpdateTransportError as fallback_error:
                logger.warning(
                    "客户端更新端点失败 endpoint_role=fallback "
                    "resource=%s kind=%s status=%s",
                    fallback_error.resource,
                    fallback_error.kind.value,
                    fallback_error.status_code,
                )
                raise
            return fallback_payload, fallback_url

    async def _get_json(
        self,
        session: Any,
        url: str,
        *,
        user_agent: str,
        resource: str,
        accept_nonstandard_json_content_type: bool = False,
    ) -> object:
        async def decode(response: Any) -> object:
            try:
                if accept_nonstandard_json_content_type:
                    # Apple Lookup 当前合法 JSON 使用 text/javascript；只跳过
                    # MIME 门禁，后续 typed contract 仍严格校验响应结构。
                    return await response.json(content_type=None)
                return await response.json()
            except (TypeError, ValueError, UnicodeError) as error:
                raise _contract_error(resource, type(error).__name__) from None

        return await self._request(session, url, user_agent, resource, decode)

    async def _get_text(
        self,
        session: Any,
        url: str,
        *,
        user_agent: str,
        resource: str,
    ) -> str:
        async def decode(response: Any) -> str:
            try:
                text = await response.text()
            except (TypeError, ValueError, UnicodeError) as error:
                raise _contract_error(resource, type(error).__name__) from None
            if not isinstance(text, str):
                raise _contract_error(resource, "response text is not a string")
            return text

        result = await self._request(session, url, user_agent, resource, decode)
        return cast(str, result)

    async def _request(
        self,
        session: Any,
        url: str,
        user_agent: str,
        resource: str,
        decode: Callable[[Any], Awaitable[object]],
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
                    return await decode(response)
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
    return tuple(
        _source_version_from_snapshot(source.source_id, item) for item in ordered
    )


def _source_version_from_snapshot(
    source_id: str,
    snapshot: ClientVersionSnapshot,
) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id=source_id,
        version_text=snapshot.version_text,
        revision_id=_manifest_revision_id(snapshot),
        order_key=(snapshot.version_key, snapshot.patch_version),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=snapshot.version_key,
            patch_version=snapshot.patch_version,
            resource_version_dir=snapshot.resource_version_dir,
        ),
    )


def _manifest_revision_id(snapshot: ClientVersionSnapshot) -> str:
    """返回同时区分 VersionList key 与补丁目录的 manifest 身份。"""

    return f"{snapshot.version_key}:{snapshot.patch_version}"


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
    return (
        f"https://itunes.apple.com/lookup?id={config.track_id}&country={config.country}"
    )


def _single_revision_observation(
    current: ClientSourceVersion,
    baseline: ClientSourceVersion | None,
) -> ClientSourceObservation:
    """单 revision 发行渠道的 observation：历史始终只有当前一条。

    变化发生时该渠道无法提供逐版本历史，因此标记 history gap、不提供更新大小。
    """

    unchanged = baseline is not None and baseline.revision_id == current.revision_id
    return ClientSourceObservation(
        current=current,
        observed_versions=(current,),
        history_complete=baseline is None or unchanged,
        added_size_bytes=0 if unchanged else None,
    )


def _parse_bilibili_gameinfo(
    payload: object,
    source: ClientUpdateSource,
) -> ClientSourceVersion:
    """把 B 站游戏中心 gameinfo 响应归一化为 Source 版本。"""

    try:
        root = _require_mapping(payload, "Bilibili 游戏中心")
        if root.get("code") != 0:
            raise ClientUpdateStructureError("Bilibili gameinfo code must be 0")
        data = _require_mapping(root.get("data"), "Bilibili data")
        if source.platform is ClientPlatform.ANDROID:
            download_url = _required_text(data.get("android_download_link"))
            signature = _required_text(data.get("android_sign"))
            package = _required_text(data.get("android_pkg_name"))
            pkg_ver = data.get("android_pkg_ver")
            if _MD5_HEX_RE.fullmatch(signature) is None:
                raise ClientUpdateStructureError("Bilibili android_sign must be an MD5")
            if type(pkg_ver) is not int or pkg_ver < 0:
                raise ClientUpdateStructureError(
                    "Bilibili android_pkg_ver must be a non-negative integer"
                )
            revision_id = signature
            order_key: ClientVersionOrderKey | None = pkg_ver
            metadata: ClientSourceProviderMetadata | None = None
            if package != _BILIBILI_ANDROID_PACKAGE:
                raise ClientUpdateStructureError("Bilibili package mismatch")
        else:
            download_url = _required_text(data.get("pc_download_link"))
            # PC 安装器没有稳定的公开版本号；文件名本身已包含构建时间与哈希，
            # 足以作为发行 revision。
            revision_id = _installer_revision(download_url)
            order_key = None
            metadata = None
        version_match = _BILIBILI_VERSION_RE.search(download_url)
    except (ClientUpdateStructureError, TypeError, ValueError) as error:
        raise _contract_error("Bilibili 游戏中心", type(error).__name__) from None
    return ClientSourceVersion(
        source_id=source.source_id,
        version_text=version_match.group(1) if version_match is not None else None,
        revision_id=revision_id,
        order_key=order_key,
        provider_metadata=metadata,
    )


def _installer_revision(download_url: str) -> str:
    """从下载 URL 提取稳定的安装器名称作为 revision。"""

    name = download_url.rsplit("/", 1)[-1]
    if not name or not name.endswith((".exe", ".apk", ".zip")):
        raise ClientUpdateStructureError("installer URL must end with a file name")
    return name


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClientUpdateStructureError("required text field is empty")
    return value


def _parse_hykb_detail(
    page: str,
    source: ClientUpdateSource,
    config: HykbProviderConfig,
) -> ClientSourceVersion:
    """把好游快爆详情页的 downInfo 与版本文本归一化为 Source 版本。"""

    try:
        info_match = _HYKB_DOWN_INFO_RE.search(page)
        if info_match is None:
            raise ClientUpdateStructureError("HYKB downInfo block is missing")
        try:
            info = json.loads(info_match.group(1))
        except (TypeError, ValueError) as error:
            raise ClientUpdateStructureError(
                "HYKB downInfo is not valid JSON"
            ) from error
        entry = _require_mapping(info, "HYKB downInfo")
        kb_id = _required_text(entry.get("kb_id"))
        package = _required_text(entry.get("package"))
        md5 = _required_text(entry.get("md5"))
        _ = _required_text(entry.get("apkurl"))
        if kb_id != str(config.game_id):
            raise ClientUpdateStructureError("HYKB kb_id mismatch")
        if package != config.expected_package:
            raise ClientUpdateStructureError("HYKB package mismatch")
        if _MD5_HEX_RE.fullmatch(md5) is None:
            raise ClientUpdateStructureError("HYKB md5 must be hexadecimal MD5")
        version_match = _HYKB_VERSION_RE.search(page)
        version_text = version_match.group(1) if version_match else None
    except (ClientUpdateStructureError, TypeError, ValueError) as error:
        raise _contract_error("好游快爆页面", type(error).__name__) from None
    return ClientSourceVersion(
        source_id=source.source_id,
        version_text=version_text,
        revision_id=md5,
        order_key=None,
        provider_metadata=None,
    )


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
