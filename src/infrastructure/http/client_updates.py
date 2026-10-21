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
import struct
import zipfile
import zlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any, Self, cast

import httpx

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
from ...modules.client_updates.downloads import (
    hdiff_download_size,
    manifest_download_plan,
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
from ..logger import logger
from .android_package import read_official_android_package
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
        self.headers = response.headers

    async def json(self, **_kwargs: object) -> object:
        await self._response.aread()
        return self._response.json()

    async def text(self, **_kwargs: object) -> str:
        await self._response.aread()
        return self._response.text

    async def read(self) -> bytes:
        return await self._response.aread()


class _HttpxRequestContext:
    """把 httpx 的 awaitable response 包装为异步上下文管理器。"""

    def __init__(self, response: Awaitable[httpx.Response]) -> None:
        self._response_awaitable = response

    async def __aenter__(self) -> _HttpxResponse:
        self._response = await self._response_awaitable
        return _HttpxResponse(self._response)

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        await self._response.aclose()


class _HttpxSession:
    """提供最小 ClientSession seam，避免导入不兼容的旧 aiohttp。"""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        await self._client.aclose()

    def get(self, url: str, **kwargs: Any) -> _HttpxRequestContext:
        return _HttpxRequestContext(
            self._client.send(
                self._client.build_request("GET", url, **kwargs), stream=True
            )
        )


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
        capture_package_version: bool = False,
    ) -> ClientSourceObservation:
        """读取一个已登记 Source；baseline 缺口通过 observation 显式表达。"""

        source = self.registry.resolve_source(source_id)
        _validate_baseline(source, baseline)
        async with self._session_factory() as session:
            if source.provider_kind is ClientUpdateProviderKind.MANIFEST_CDN:
                config = source.provider_config
                if not isinstance(config, ManifestCdnProviderConfig):
                    raise _server_error("Source", "manifest provider config mismatch")
                try:
                    return await self._get_manifest_observation(
                        session,
                        source,
                        config,
                        baseline,
                        capture_package_version=capture_package_version,
                    )
                except ClientUpdateStructureError as error:
                    raise _contract_error("下载计划", type(error).__name__) from None

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
        *,
        capture_package_version: bool = False,
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
        alternate_base_url = (
            config.fallback_base_url
            if version_base_url == config.primary_base_url
            else config.primary_base_url
        )
        versions = _parse_manifest_versions(version_payload, source)
        current = versions[-1]
        if baseline is None and not capture_package_version:
            return ClientSourceObservation(
                current=current,
                observed_versions=versions,
                history_complete=True,
                added_size_bytes=None,
            )
        package_release: tuple[int, str, int] | None = None
        if config.package_branch is not None:
            package_info, _ = await self._get_json_with_fallback(
                session,
                primary_url=f"{version_base_url}/{config.package_branch}/VersionManifest.json",
                fallback_url=(
                    f"{alternate_base_url}/{config.package_branch}/VersionManifest.json"
                    if alternate_base_url is not None
                    else None
                ),
                user_agent=config.user_agent,
                resource="VersionManifest",
            )
            try:
                if not isinstance(package_info, Mapping):
                    raise TypeError("invalid package manifest")
                for key in ("latest_version", "min_supported_version"):
                    if not isinstance(package_info[key], str) or not re.fullmatch(
                        r"[1-9][0-9]*", package_info[key]
                    ):
                        raise ValueError("invalid package version")
                package_version = int(package_info["latest_version"])
                package_series = package_info["latest_version_number"]
                minimum = int(package_info["min_supported_version"])
                if (
                    not isinstance(package_series, str)
                    or not re.fullmatch(r"\d+\.\d+", package_series)
                    or package_series
                    != ".".join(cast(str, current.version_text).split(".")[:2])
                    or not 0 < minimum <= package_version
                ):
                    raise ValueError("inconsistent base package version")
                current = replace(
                    current,
                    provider_metadata=replace(
                        cast(ManifestCdnVersionMetadata, current.provider_metadata),
                        package_version=package_version,
                    ),
                )
                versions = (*versions[:-1], current)
                package_release = (package_version, package_series, minimum)
            except (KeyError, TypeError, ValueError):
                raise _contract_error(
                    "VersionManifest", "invalid package version"
                ) from None

        if baseline is None:
            return ClientSourceObservation(
                current=current,
                observed_versions=versions,
                history_complete=True,
                added_size_bytes=None,
            )
        baseline_index = _find_revision_index(versions, baseline.revision_id)
        new_versions = (
            versions if baseline_index is None else versions[baseline_index + 1 :]
        )
        plan_versions = new_versions
        manifests = []
        for version in new_versions:
            manifests.append(
                await self._get_manifest_patch_manifests(
                    session,
                    source,
                    config,
                    version,
                    base_url=version_base_url,
                )
            )
        added_size_bytes = (
            sum(
                sum_manifest_patch_file_sizes(
                    config.pak_manifest_key, config.res_manifest_key, pak, res
                )
                for pak, res in manifests
            )
            if baseline_index is not None
            else None
        )
        android_base_change = (
            source.source_id == "cn-official-android-astc-manifest"
            and baseline.version_text is not None
            and baseline.version_text.startswith("1.6.")
            and cast(str, current.version_text).startswith("1.7.")
        )
        if android_base_change:
            # shortcut: 只核验过官服 APK 19 的内置边界；新基包需先核验再扩展。
            selected = tuple(
                v for v in versions if cast(str, v.version_text).startswith("1.7.")
            )
            old_metadata = baseline.provider_metadata
            if (
                not isinstance(old_metadata, ManifestCdnVersionMetadata)
                or not 1_400_000 <= old_metadata.patch_version < 1_500_000
                or selected[0].revision_id != "1510205:1510205"
            ):
                raise _contract_error("下载计划", "unverified Android base boundary")
            jumps, _ = await self._get_json_with_fallback(
                session,
                primary_url=f"{version_base_url}/PakJumpUrl/PakJumpUrl.json",
                fallback_url=f"{alternate_base_url}/PakJumpUrl/PakJumpUrl.json"
                if alternate_base_url
                else None,
                user_agent=config.user_agent,
                resource="PakJumpUrl",
                accept_nonstandard_json_content_type=True,
            )
            if not isinstance(jumps, Mapping) or not isinstance(
                jumps.get("2.0"), Mapping
            ):
                raise _contract_error("PakJumpUrl", "missing official APK")
            jump = jumps["2.0"]
            apk_url = "https://cdn-dna.yingxiong.com/dna/Android_dna.apk"
            if jump.get("ChannelId") != 18 or jump.get("JumpUrl") != apk_url:
                raise _contract_error("PakJumpUrl", "unverified official APK source")
            apk_name, apk_code, apk_size = await self._get_android_package(
                session, apk_url, config.user_agent
            )
            if (apk_name, apk_code) != ("1.7.204.1", 19):
                raise _contract_error(
                    "Android APK", "unverified embedded resource boundary"
                )
            examine, _ = await self._get_json_with_fallback(
                session,
                primary_url=f"{version_base_url}/{config.branch}/ExamineFile.json",
                fallback_url=f"{alternate_base_url}/{config.branch}/ExamineFile.json"
                if alternate_base_url
                else None,
                user_agent=config.user_agent,
                resource="ExamineFile",
            )
            if examine != [{}]:
                raise _contract_error("ExamineFile", "unverified cross-path file reuse")
            cached = {
                v.revision_id: pair
                for v, pair in zip(new_versions, manifests, strict=True)
            }
            files = []
            resource_tags: set[str] = set()
            for version in selected:
                metadata = cast(ManifestCdnVersionMetadata, version.provider_metadata)
                row = cast(dict[str, Any], version_payload)["versionList"][
                    str(metadata.version_key)
                ]
                if (
                    not 1_500_000 <= metadata.patch_version < 1_600_000
                    or row.get("patchKey") != 1
                    or row.get("bOptional") is not False
                ):
                    raise _contract_error(
                        "下载计划", "mixed or optional Android base patches"
                    )
                pak, res = (
                    cached[version.revision_id]
                    if version.revision_id in cached
                    else await self._get_manifest_patch_manifests(
                        session, source, config, version, base_url=version_base_url
                    )
                )
                for payload, key in (
                    (pak, config.pak_manifest_key),
                    (res, config.res_manifest_key),
                ):
                    for file in cast(dict[str, Any], payload)["pakFilesMap"][key][
                        "pakFileInfos"
                    ]:
                        tag = file.get("pakOptionalSign", "")
                        if not isinstance(tag, str):
                            raise _contract_error(
                                "下载计划", "invalid Android resource option"
                            )
                        resource_tags.add(tag)
                        if not re.fullmatch(
                            r"1\.7\.[0-9]+\.1_.+_Android_ASTC_"
                            + str(metadata.patch_version)
                            + r"_P\.(pak|sig)",
                            file["fileName"],
                        ) or not re.fullmatch(
                            r"[0-9a-fA-F]{32}", str(file.get("hash", ""))
                        ):
                            raise _contract_error(
                                "下载计划", "unverified Android file identity"
                            )
                files.append((_manifest_directory(source, metadata), pak, res))
            if resource_tags != {
                "",
                "Patch_East",
                "Patch_Icelake",
                "VoiceCN",
                "VoiceEN",
                "VoiceJP",
                "VoiceKR",
            }:
                raise _contract_error(
                    "下载计划", "incomplete or unknown Android resource options"
                )
            # APK 19 不内置这些独立 pak/sig；原生按目录路径匹配，旧 14 目录不能命中新 15 路径。
            plan = manifest_download_plan(
                files,
                config.pak_manifest_key,
                config.res_manifest_key,
                basis="apk_and_patch",
                package_size=apk_size,
                package_to=apk_code,
            )
            return ClientSourceObservation(
                current=current,
                observed_versions=versions,
                history_complete=baseline_index is not None,
                added_size_bytes=added_size_bytes,
                download_plan=plan,
            )

        package_size = 0
        package_from = None
        package_to = None
        basis = (
            "android_resources"
            if source.platform is ClientPlatform.ANDROID
            else "patch_manifest"
        )
        if package_release is not None and current.revision_id != baseline.revision_id:
            package_to, package_series, minimum = package_release
            baseline_metadata = baseline.provider_metadata
            if not isinstance(baseline_metadata, ManifestCdnVersionMetadata):
                raise _contract_error(
                    "基础包版本", "baseline manifest metadata unavailable"
                )
            baseline_text = baseline.version_text
            if baseline_text is None:
                raise _contract_error("基础包版本", "baseline version unavailable")
            package_from = baseline_metadata.package_version
            # v4 的国服 PC 1.6 基线没有基础包字段；该发布基包已核验为 16001。
            if package_from is None and baseline_text.startswith("1.6."):
                package_from = 16001
            if package_from is None:
                raise _contract_error(
                    "基础包版本", "baseline package version unavailable"
                )
            if package_from > package_to:
                raise _contract_error("基础包版本", "package rollback")
            if package_from != package_to:
                if baseline_text.startswith(f"{package_series}."):
                    raise _contract_error(
                        "基础包版本", "same-series package patch boundary unavailable"
                    )
                directory = (
                    f"full_{package_to}"
                    if package_from < minimum
                    else f"v{package_from}_to_v{package_to}"
                )
                relative = f"{config.package_branch}/{package_series}/{package_to}/{directory}/HPatchDiffMd5.json"
                payload, _ = await self._get_json_with_fallback(
                    session,
                    primary_url=f"{version_base_url}/{relative}",
                    fallback_url=(
                        f"{alternate_base_url}/{relative}"
                        if alternate_base_url is not None
                        else None
                    ),
                    user_agent=config.user_agent,
                    resource="HPatchDiffMd5",
                )
                package_size = hdiff_download_size(payload)
                basis = "hdiff_and_patch"
                # 新基包只应用当前发行系列的热更；旧系列文件已被基包替换。
                cached = {
                    version.revision_id: pair
                    for version, pair in zip(new_versions, manifests, strict=True)
                }
                plan_versions = tuple(
                    version
                    for version in versions
                    if cast(str, version.version_text).startswith(f"{package_series}.")
                )
                manifests = [
                    cached[version.revision_id]
                    if version.revision_id in cached
                    else await self._get_manifest_patch_manifests(
                        session, source, config, version, base_url=version_base_url
                    )
                    for version in plan_versions
                ]
        if baseline_index is None and basis != "hdiff_and_patch":
            raise _contract_error(
                "下载计划", "history gap without a verified base-package upgrade"
            )
        plan = manifest_download_plan(
            [
                (
                    _manifest_directory(
                        source,
                        cast(ManifestCdnVersionMetadata, version.provider_metadata),
                    ),
                    pak,
                    res,
                )
                for version, (pak, res) in zip(plan_versions, manifests, strict=True)
            ],
            config.pak_manifest_key,
            config.res_manifest_key,
            basis=basis,
            package_size=package_size,
            package_from=package_from,
            package_to=package_to,
        )
        return ClientSourceObservation(
            current=current,
            observed_versions=versions,
            history_complete=baseline_index is not None,
            added_size_bytes=added_size_bytes,
            download_plan=plan,
        )

    async def _get_android_package(
        self, session: Any, url: str, user_agent: str
    ) -> tuple[str, int, int]:
        etag: str | None = None

        async def read_range(start: int, end: int | None) -> tuple[bytes, int]:
            nonlocal etag
            span = f"bytes={start}" if end is None else f"bytes={start}-{end}"

            async def decode(response: Any) -> tuple[bytes, int]:
                nonlocal etag
                if response.status != 206:
                    raise _contract_error("Android APK", "server did not honor Range")
                match = re.fullmatch(
                    r"bytes ([0-9]+)-([0-9]+)/([0-9]+)",
                    response.headers.get("Content-Range", ""),
                )
                if match is None:
                    raise _contract_error("Android APK", "invalid Content-Range")
                first, last, total = map(int, match.groups())
                expected_first = max(0, total + start) if start < 0 else start
                expected_last = total - 1 if end is None else end
                if (
                    total <= 0
                    or (first, last) != (expected_first, expected_last)
                    or last >= total
                ):
                    raise _contract_error("Android APK", "unexpected APK range")
                current_etag = response.headers.get("ETag")
                if etag is not None and current_etag != etag:
                    raise _contract_error(
                        "Android APK", "APK changed during metadata read"
                    )
                etag = current_etag
                body = await response.read()
                if len(body) != last - first + 1:
                    raise _contract_error("Android APK", "truncated APK range")
                return body, total

            result = await self._request(
                session,
                url,
                user_agent,
                "Android APK",
                decode,
                headers={"Range": span, **({"If-Match": etag} if etag else {})},
            )
            return cast(tuple[bytes, int], result)

        try:
            return await read_official_android_package(read_range)
        except (
            ValueError,
            KeyError,
            IndexError,
            struct.error,
            zlib.error,
            zipfile.BadZipFile,
        ):
            raise _contract_error("Android APK", "invalid APK metadata") from None

    async def _get_manifest_patch_manifests(
        self,
        session: Any,
        source: ClientUpdateSource,
        config: ManifestCdnProviderConfig,
        version: ClientSourceVersion,
        *,
        base_url: str,
    ) -> tuple[object, object]:
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
            sum_manifest_patch_file_sizes(
                config.pak_manifest_key,
                config.res_manifest_key,
                pak_result[0],
                res_result[0],
            )
            return pak_result[0], res_result[0]
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
        accept_nonstandard_json_content_type: bool = False,
    ) -> tuple[object, str]:
        try:
            return (
                await self._get_json(
                    session,
                    primary_url,
                    user_agent=user_agent,
                    resource=resource,
                    accept_nonstandard_json_content_type=accept_nonstandard_json_content_type,
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
                    accept_nonstandard_json_content_type=accept_nonstandard_json_content_type,
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
                    # Apple Lookup / PakJumpUrl 使用非标准 MIME，正文仍按 JSON 校验。
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
        *,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        async def request() -> object:
            try:
                async with session.get(
                    url,
                    headers={"User-Agent": user_agent, **(headers or {})},
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
