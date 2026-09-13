"""客户端更新 Target / Source 公共契约测试。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

import pytest

from src.infrastructure.http.client_updates import ClientUpdateTransport
from src.modules.client_updates import (
    CLIENT_UPDATE_SOURCES,
    CLIENT_UPDATE_TARGETS,
    DEFAULT_CLIENT_UPDATE_TARGET_IDS,
    AppStoreProviderConfig,
    AppStoreVersionMetadata,
    BilibiliGameCenterProviderConfig,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateBaseline,
    ClientUpdateFailureKind,
    ClientUpdateProviderKind,
    ClientUpdateRegistry,
    ClientUpdateService,
    ClientUpdateSource,
    ClientUpdateStateStore,
    ClientUpdateTarget,
    ClientUpdateTransportError,
    HykbProviderConfig,
    ManifestCdnProviderConfig,
    ManifestCdnVersionMetadata,
    group_client_update_target_ids_by_source,
    normalize_client_update_target_ids,
    parse_version_list_entries,
    resolve_client_update_source,
    resolve_client_update_target,
)


def test_manifest_parser_rejects_unsupported_platform() -> None:
    with pytest.raises(ValueError, match="不支持"):
        parse_version_list_entries({}, "pc_cn")


def test_verified_registry_contains_only_observed_distribution_targets() -> None:
    assert tuple(CLIENT_UPDATE_TARGETS) == (
        "cn-official-pc",
        "cn-official-android",
        "cn-app-store-ios",
        "cn-bilibili-pc",
        "cn-bilibili-android",
        "cn-hykb-android",
        "global-standalone-pc",
        "global-app-store-ios",
    )
    assert tuple(CLIENT_UPDATE_SOURCES) == (
        "cn-official-pc-manifest",
        "cn-official-android-astc-manifest",
        "cn-official-ios-app-store",
        "cn-bilibili-pc-release",
        "cn-bilibili-android-release",
        "cn-hykb-android-release",
        "global-standalone-pc-manifest",
        "global-app-store-ios",
    )
    assert DEFAULT_CLIENT_UPDATE_TARGET_IDS == (
        "cn-official-pc",
        "cn-official-android",
    )
    assert tuple(
        (
            target.target_id,
            target.region_id,
            target.distribution_id,
            target.platform,
            target.source_id,
        )
        for target in CLIENT_UPDATE_TARGETS.values()
    ) == (
        (
            "cn-official-pc",
            "cn",
            "official",
            ClientPlatform.PC,
            "cn-official-pc-manifest",
        ),
        (
            "cn-official-android",
            "cn",
            "official",
            ClientPlatform.ANDROID,
            "cn-official-android-astc-manifest",
        ),
        (
            "cn-app-store-ios",
            "cn",
            "app-store",
            ClientPlatform.IOS,
            "cn-official-ios-app-store",
        ),
        (
            "cn-bilibili-pc",
            "cn",
            "bilibili",
            ClientPlatform.PC,
            "cn-bilibili-pc-release",
        ),
        (
            "cn-bilibili-android",
            "cn",
            "bilibili",
            ClientPlatform.ANDROID,
            "cn-bilibili-android-release",
        ),
        (
            "cn-hykb-android",
            "cn",
            "hykb",
            ClientPlatform.ANDROID,
            "cn-hykb-android-release",
        ),
        (
            "global-standalone-pc",
            "global",
            "standalone",
            ClientPlatform.PC,
            "global-standalone-pc-manifest",
        ),
        (
            "global-app-store-ios",
            "global",
            "app-store",
            ClientPlatform.IOS,
            "global-app-store-ios",
        ),
    )

    pc = resolve_client_update_source("cn-official-pc-manifest")
    assert isinstance(pc.provider_config, ManifestCdnProviderConfig)
    assert pc.provider_config.primary_base_url == "http://pan01-1-eo.shyxhy.com"
    assert pc.provider_config.fallback_base_url == "http://pan01-1-hs.shyxhy.com"
    assert pc.provider_config.branch == (
        "Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub"
    )
    assert pc.provider_config.pak_manifest_key == "WindowsNoEditor"
    assert pc.provider_config.res_manifest_key == "WindowsNoEditor"

    android = resolve_client_update_source("cn-official-android-astc-manifest")
    assert android.platform is ClientPlatform.ANDROID
    assert android.provider_kind is ClientUpdateProviderKind.MANIFEST_CDN
    assert isinstance(android.provider_config, ManifestCdnProviderConfig)
    assert android.provider_config.primary_base_url == "https://pan01-1-hs.shyxhy.com"
    assert android.provider_config.fallback_base_url == "http://pan01-1-eo.shyxhy.com"
    assert android.provider_config.branch == (
        "Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub"
    )
    assert android.provider_config.pak_manifest_key == "Android_ASTC"
    assert android.provider_config.res_manifest_key == "WindowsNoEditor"

    ios = resolve_client_update_source("cn-official-ios-app-store")
    assert ios.platform is ClientPlatform.IOS
    assert ios.provider_kind is ClientUpdateProviderKind.APP_STORE
    assert ios.provider_config == AppStoreProviderConfig(
        track_id=6470771372, country="cn"
    )

    bilibili_pc = resolve_client_update_source("cn-bilibili-pc-release")
    assert bilibili_pc.provider_kind is ClientUpdateProviderKind.BILIBILI_GAME_CENTER
    assert bilibili_pc.provider_config == BilibiliGameCenterProviderConfig(
        game_base_id=111799
    )

    bilibili_android = resolve_client_update_source("cn-bilibili-android-release")
    assert bilibili_android.platform is ClientPlatform.ANDROID
    assert bilibili_android.provider_config == BilibiliGameCenterProviderConfig(
        game_base_id=111015
    )

    hykb = resolve_client_update_source("cn-hykb-android-release")
    assert hykb.provider_kind is ClientUpdateProviderKind.HYKB
    assert hykb.provider_config == HykbProviderConfig(
        game_id=158909,
        expected_package="com.hero.dna.gf",
    )

    global_pc = resolve_client_update_source("global-standalone-pc-manifest")
    assert global_pc.provider_kind is ClientUpdateProviderKind.MANIFEST_CDN
    assert isinstance(global_pc.provider_config, ManifestCdnProviderConfig)
    assert global_pc.provider_config.primary_base_url == (
        "https://pan01-2.oss-ap-northeast-1.aliyuncs.com"
    )
    # 全球服只有一个已验证的可信端点，不伪造 fallback。
    assert global_pc.provider_config.fallback_base_url is None
    assert global_pc.provider_config.branch == (
        "Patches/FinalPatch/Global/Default/WindowsNoEditor/PC_OBT_Global_Pub"
    )

    global_ios = resolve_client_update_source("global-app-store-ios")
    assert global_ios.provider_kind is ClientUpdateProviderKind.APP_STORE
    assert global_ios.provider_config == AppStoreProviderConfig(
        track_id=6744096826, country="us"
    )


def test_registry_rejects_duplicate_identity_and_platform_mismatch() -> None:
    source = ClientUpdateSource(
        source_id="source-pc",
        platform=ClientPlatform.PC,
        provider_kind=ClientUpdateProviderKind.MANIFEST_CDN,
        provider_config=ManifestCdnProviderConfig(
            primary_base_url="https://primary.invalid",
            fallback_base_url="https://fallback.invalid",
            branch="Patches/Test",
            pak_manifest_key="WindowsNoEditor",
            res_manifest_key="WindowsNoEditor",
            user_agent="test-agent",
        ),
    )
    with pytest.raises(TypeError, match="不匹配"):
        ClientUpdateSource(
            source_id="bad-config",
            platform=ClientPlatform.PC,
            provider_kind=ClientUpdateProviderKind.MANIFEST_CDN,
            provider_config=AppStoreProviderConfig(track_id=1, country="cn"),
        )
    with pytest.raises(ValueError, match="iOS"):
        ClientUpdateSource(
            source_id="bad-platform",
            platform=ClientPlatform.PC,
            provider_kind=ClientUpdateProviderKind.APP_STORE,
            provider_config=AppStoreProviderConfig(track_id=1, country="cn"),
        )

    target = ClientUpdateTarget(
        target_id="cn-official-pc",
        region_id="cn",
        distribution_id="official",
        platform=ClientPlatform.PC,
        source_id=source.source_id,
        display_name="国服官服 PC",
    )

    with pytest.raises(ValueError, match="Source ID"):
        ClientUpdateRegistry((source, source), (target,))

    duplicate_identity = ClientUpdateTarget(
        target_id="cn-official-pc-alias",
        region_id="cn",
        distribution_id="official",
        platform=ClientPlatform.PC,
        source_id=source.source_id,
        display_name="重复身份",
    )
    with pytest.raises(ValueError, match="Target 组合"):
        ClientUpdateRegistry((source,), (target, duplicate_identity))

    ambiguous_name = ClientUpdateTarget(
        target_id="cn-other-pc",
        region_id="cn",
        distribution_id="other",
        platform=ClientPlatform.PC,
        source_id=source.source_id,
        display_name=target.display_name,
    )
    with pytest.raises(ValueError, match="展示名"):
        ClientUpdateRegistry((source,), (target, ambiguous_name))

    with pytest.raises(ValueError, match="Target ID"):
        ClientUpdateRegistry((source,), (target, target))

    missing_source_target = ClientUpdateTarget(
        target_id="cn-official-pc-missing-source",
        region_id="cn",
        distribution_id="missing-source",
        platform=ClientPlatform.PC,
        source_id="missing-source",
        display_name="缺失 Source",
    )
    with pytest.raises(ValueError, match="不存在的 Source"):
        ClientUpdateRegistry((source,), (missing_source_target,))

    mismatched_target = ClientUpdateTarget(
        target_id="cn-official-android",
        region_id="cn",
        distribution_id="official",
        platform=ClientPlatform.ANDROID,
        source_id=source.source_id,
        display_name="国服官服 Android",
    )
    with pytest.raises(ValueError, match="平台"):
        ClientUpdateRegistry((source,), (mismatched_target,))

    registry = ClientUpdateRegistry((source,), (target,))
    foreign_source = ClientUpdateSource(
        source_id="foreign-source",
        platform=ClientPlatform.PC,
        provider_kind=ClientUpdateProviderKind.MANIFEST_CDN,
        provider_config=source.provider_config,
    )
    foreign_target = ClientUpdateTarget(
        target_id="foreign-target",
        region_id="cn",
        distribution_id="foreign",
        platform=ClientPlatform.PC,
        source_id=source.source_id,
        display_name="未登记目标",
    )
    with pytest.raises(ValueError, match="Source"):
        registry.resolve_source(foreign_source)
    with pytest.raises(ValueError, match="Target"):
        registry.resolve_target(foreign_target)


def test_registry_normalizes_and_groups_targets_by_source() -> None:
    assert normalize_client_update_target_ids(
        ["cn-app-store-ios", "cn-official-pc", "cn-app-store-ios"]
    ) == ("cn-app-store-ios", "cn-official-pc")

    grouped = group_client_update_target_ids_by_source(
        ["cn-app-store-ios", "cn-official-pc", "cn-official-android"]
    )
    assert grouped == {
        "cn-official-ios-app-store": ("cn-app-store-ios",),
        "cn-official-pc-manifest": ("cn-official-pc",),
        "cn-official-android-astc-manifest": ("cn-official-android",),
    }
    assert resolve_client_update_target("cn-official-pc").display_name == "国服官服 PC"

    with pytest.raises(ValueError, match="Target"):
        normalize_client_update_target_ids(["global-official-pc"])


def test_source_observation_is_source_neutral_and_immutable() -> None:
    previous = ClientSourceVersion(
        source_id="cn-official-pc-manifest",
        version_text="1.6.197.1",
        revision_id="1510197",
        order_key=(1, 6, 197, 1, 1510197),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=1510197,
            patch_version=1510197,
            resource_version_dir=None,
        ),
    )
    current = ClientSourceVersion(
        source_id="cn-official-pc-manifest",
        version_text="1.6.198.1",
        revision_id="1510198",
        order_key=(1, 6, 198, 1, 1510198),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=1510198,
            patch_version=1510198,
            resource_version_dir=None,
        ),
    )
    observation = ClientSourceObservation(
        current=current,
        observed_versions=(previous, current),
        history_complete=True,
        added_size_bytes=3_038_986,
    )

    assert observation.current.revision_id == "1510198"
    assert observation.observed_versions == (previous, current)
    assert current.provider_metadata == ManifestCdnVersionMetadata(
        version_key=1510198,
        patch_version=1510198,
        resource_version_dir=None,
    )

    other_source = ClientSourceVersion(
        source_id="other-source",
        version_text="1.0.0",
        revision_id="1",
    )
    with pytest.raises(ValueError, match="同一 Source"):
        ClientSourceObservation(
            current=current,
            observed_versions=(other_source,),
            history_complete=False,
            added_size_bytes=None,
        )


@dataclass(frozen=True, slots=True)
class _Request:
    url: str
    headers: Mapping[str, str]


class _FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    async def json(self, **_kwargs: object) -> object:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload

    async def text(self, **_kwargs: object) -> str:
        if isinstance(self.payload, BaseException):
            raise self.payload
        if not isinstance(self.payload, str):
            raise TypeError("payload is not text")
        return self.payload


class _JavascriptJsonResponse(_FakeResponse):
    """模拟 Apple Lookup 返回 text/javascript JSON 的真实响应。"""

    async def json(
        self,
        *,
        content_type: str | None = "application/json",
    ) -> object:
        if content_type is not None:
            raise ValueError("unexpected text/javascript content type")
        return await super().json()


class _FakeSession:
    def __init__(self, routes: Mapping[str, _FakeResponse | BaseException]) -> None:
        self.routes = routes
        self.requests: list[_Request] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append(
            _Request(url=url, headers=dict(kwargs.get("headers") or {}))
        )
        route = self.routes[url]
        if isinstance(route, BaseException):
            raise route
        return route


def _version_entry(patch_version: int, revamp: int) -> dict[str, int]:
    return {
        "major": 1,
        "minor": 6,
        "revamp": revamp,
        "patchKey": 1,
        "patchVersion": patch_version,
    }


def _version_list(entries: Mapping[str, Mapping[str, int]]) -> dict[str, object]:
    return {"versionList": dict(entries)}


def _manifest(key: str, name: str, size: int) -> dict[str, object]:
    return {
        "pakFilesMap": {
            key: {
                "pakFileInfos": [{"fileName": name, "fileSize": size}],
            }
        }
    }


def _manifest_source_version(source_id: str, version_key: str) -> ClientSourceVersion:
    number = int(version_key)
    return ClientSourceVersion(
        source_id=source_id,
        version_text=f"1.6.{number}.1",
        revision_id=f"{number}:{number}",
        order_key=(number, number),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=number,
            patch_version=number,
            resource_version_dir=None,
        ),
    )


@pytest.mark.asyncio
async def test_manifest_same_version_key_with_changed_patch_version_is_update(
    tmp_path,
) -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list({"1510203": _version_entry(1510203, 203)}),
            )
        }
    )
    transport = ClientUpdateTransport(session_factory=lambda: session)
    previous_observation = await transport.get_observation(source.source_id)
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await state.save_baseline(
        ClientUpdateBaseline(
            version=previous_observation.current,
            observed_at=datetime(2026, 9, 12, tzinfo=UTC),
        )
    )
    session.routes[version_url] = _FakeResponse(
        200,
        _version_list({"1510203": _version_entry(1510999, 999)}),
    )

    changes = await ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-pc",),
    ).poll_now()

    assert len(changes) == 1
    change = changes[0]
    assert change is not None
    assert change.previous != change.current
    assert change.current.revision_id == "1510203:1510999"
    assert change.history_complete is False
    assert change.added_size_bytes is None
    assert [request.url for request in session.requests] == [version_url, version_url]


@pytest.mark.asyncio
async def test_manifest_transport_sums_continuous_history_records() -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    routes: dict[str, _FakeResponse | BaseException] = {
        version_url: _FakeResponse(
            200,
            _version_list(
                {
                    "100": _version_entry(100, 100),
                    "101": _version_entry(101, 101),
                    "102": _version_entry(102, 102),
                }
            ),
        )
    }
    for revision, size in ((101, 10), (102, 20)):
        base = f"{config.primary_base_url}/{config.branch}/{revision}"
        routes[f"{base}/PakFilesInfo.json"] = _FakeResponse(
            200, _manifest(config.pak_manifest_key, f"{revision}.pak", size)
        )
        routes[f"{base}/ResDiscreteInfo.json"] = _FakeResponse(
            200, _manifest(config.res_manifest_key, f"{revision}.res", 1)
        )

    observation = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession(routes)
    ).get_observation(
        source.source_id, baseline=_manifest_source_version(source.source_id, "100")
    )

    assert observation.current.revision_id == "102:102"
    assert observation.history_complete is True
    assert observation.added_size_bytes == 32


@pytest.mark.asyncio
async def test_manifest_transport_reads_only_real_sparse_history_records() -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    routes: dict[str, _FakeResponse | BaseException] = {
        version_url: _FakeResponse(
            200,
            _version_list(
                {
                    "100": _version_entry(100, 100),
                    "102": _version_entry(102, 102),
                    "103": _version_entry(103, 103),
                }
            ),
        )
    }
    for revision, size in ((102, 20), (103, 30)):
        base = f"{config.primary_base_url}/{config.branch}/{revision}"
        routes[f"{base}/PakFilesInfo.json"] = _FakeResponse(
            200, _manifest(config.pak_manifest_key, f"{revision}.pak", size)
        )
        routes[f"{base}/ResDiscreteInfo.json"] = _FakeResponse(
            200, _manifest(config.res_manifest_key, f"{revision}.res", 1)
        )
    session = _FakeSession(routes)

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(
        source.source_id, baseline=_manifest_source_version(source.source_id, "100")
    )

    assert isinstance(observation, ClientSourceObservation)
    assert observation.current.revision_id == "103:103"
    assert tuple(version.revision_id for version in observation.observed_versions) == (
        "100:100",
        "102:102",
        "103:103",
    )
    assert observation.history_complete is True
    assert observation.added_size_bytes == 52
    assert all("/101/" not in request.url for request in session.requests)


@pytest.mark.asyncio
async def test_manifest_transport_marks_baseline_outside_window_as_history_gap() -> (
    None
):
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "102": _version_entry(102, 102),
                        "103": _version_entry(103, 103),
                    }
                ),
            )
        }
    )

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(
        source.source_id, baseline=_manifest_source_version(source.source_id, "100")
    )

    assert observation.current.revision_id == "103:103"
    assert observation.history_complete is False
    assert observation.added_size_bytes is None
    assert len(session.requests) == 1


@pytest.mark.asyncio
async def test_manifest_transport_handles_large_sparse_revision_span() -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    routes: dict[str, _FakeResponse | BaseException] = {
        version_url: _FakeResponse(
            200,
            _version_list(
                {
                    "1042001": _version_entry(2001, 201),
                    "1510198": _version_entry(2198, 202),
                }
            ),
        )
    }
    latest_base = f"{config.primary_base_url}/{config.branch}/2198"
    routes[f"{latest_base}/PakFilesInfo.json"] = _FakeResponse(
        200, _manifest(config.pak_manifest_key, "latest.pak", 12)
    )
    routes[f"{latest_base}/ResDiscreteInfo.json"] = _FakeResponse(
        200, _manifest(config.res_manifest_key, "latest.res", 3)
    )
    session = _FakeSession(routes)
    baseline = ClientSourceVersion(
        source_id=source.source_id,
        version_text="1.6.201.1",
        revision_id="1042001:2001",
        order_key=(1042001, 2001),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=1042001,
            patch_version=2001,
            resource_version_dir=None,
        ),
    )

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(source.source_id, baseline=baseline)

    assert observation.current.revision_id == "1510198:2198"
    assert observation.added_size_bytes == 15
    assert len(session.requests) == 3


@pytest.mark.asyncio
async def test_android_manifest_uses_version_key_directory_and_separate_keys() -> None:
    source = resolve_client_update_source("cn-official-android-astc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    base = f"{config.primary_base_url}/{config.branch}/5002"
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "5001": _version_entry(201, 201),
                        "5002": _version_entry(202, 202),
                    }
                ),
            ),
            f"{base}/PakFilesInfo.json": _FakeResponse(
                200, _manifest("Android_ASTC", "mobile.pak", 40)
            ),
            f"{base}/ResDiscreteInfo.json": _FakeResponse(
                200, _manifest("WindowsNoEditor", "shared.res", 2)
            ),
        }
    )
    baseline = ClientSourceVersion(
        source_id=source.source_id,
        version_text="1.6.201.1",
        revision_id="5001:201",
        order_key=(5001, 201),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=5001,
            patch_version=201,
            resource_version_dir="5001",
        ),
    )

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(source.source_id, baseline=baseline)

    assert observation.current.revision_id == "5002:202"
    assert observation.added_size_bytes == 42
    assert {
        request.url for request in session.requests if "Info.json" in request.url
    } == {
        f"{base}/PakFilesInfo.json",
        f"{base}/ResDiscreteInfo.json",
    }


def _app_store_version(source_id: str, version: str) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id=source_id,
        version_text=version,
        revision_id=f"6470771372:{version}",
        order_key=None,
        provider_metadata=AppStoreVersionMetadata(
            track_id=6470771372,
            country="cn",
        ),
    )


@pytest.mark.asyncio
async def test_transport_uses_the_injected_registry_for_custom_sources() -> None:
    source = ClientUpdateSource(
        source_id="custom-ios-source",
        platform=ClientPlatform.IOS,
        provider_kind=ClientUpdateProviderKind.APP_STORE,
        provider_config=AppStoreProviderConfig(track_id=123, country="us"),
    )
    registry = ClientUpdateRegistry(sources=(source,), targets=())
    url = "https://itunes.apple.com/lookup?id=123&country=us"
    session = _FakeSession(
        {
            url: _FakeResponse(
                200,
                {
                    "resultCount": 1,
                    "results": [{"trackId": 123, "version": "2.0.0"}],
                },
            )
        }
    )

    observation = await ClientUpdateTransport(
        registry=registry,
        session_factory=lambda: session,
    ).get_observation(source.source_id)

    assert observation.current.source_id == source.source_id
    assert observation.current.revision_id == "123:2.0.0"


@pytest.mark.asyncio
async def test_app_store_transport_reports_changed_and_unchanged_baselines() -> None:
    source = resolve_client_update_source("cn-official-ios-app-store")
    config = source.provider_config
    assert isinstance(config, AppStoreProviderConfig)
    url = (
        f"https://itunes.apple.com/lookup?id={config.track_id}&country={config.country}"
    )
    payload = {
        "resultCount": 1,
        "results": [
            {
                "trackId": config.track_id,
                "version": "1.6.0",
                "currentVersionReleaseDate": "2026-09-01T00:00:00Z",
            }
        ],
    }

    changed = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession({url: _FakeResponse(200, payload)})
    ).get_observation(
        source.source_id, baseline=_app_store_version(source.source_id, "1.5.0")
    )
    unchanged = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession({url: _FakeResponse(200, payload)})
    ).get_observation(
        source.source_id, baseline=_app_store_version(source.source_id, "1.6.0")
    )

    assert changed.current.revision_id == "6470771372:1.6.0"
    assert changed.current.order_key is None
    assert changed.history_complete is False
    assert changed.added_size_bytes is None
    assert unchanged.history_complete is True
    assert unchanged.added_size_bytes == 0


@pytest.mark.asyncio
async def test_app_store_transport_rejects_malformed_lookup_contract() -> None:
    source = resolve_client_update_source("cn-official-ios-app-store")
    config = source.provider_config
    assert isinstance(config, AppStoreProviderConfig)
    url = (
        f"https://itunes.apple.com/lookup?id={config.track_id}&country={config.country}"
    )
    session = _FakeSession(
        {
            url: _FakeResponse(
                200,
                {"resultCount": 1, "results": [{"trackId": config.track_id}]},
            )
        }
    )

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(session_factory=lambda: session).get_observation(
            source.source_id
        )

    assert caught.value.kind is ClientUpdateFailureKind.CONTRACT


@pytest.mark.asyncio
async def test_app_store_transport_accepts_lookup_text_javascript_json() -> None:
    source = resolve_client_update_source("cn-official-ios-app-store")
    config = source.provider_config
    assert isinstance(config, AppStoreProviderConfig)
    url = f"https://itunes.apple.com/lookup?id={config.track_id}&country=cn"
    session = _FakeSession(
        {
            url: _JavascriptJsonResponse(
                200,
                {
                    "resultCount": 1,
                    "results": [
                        {
                            "trackId": config.track_id,
                            "version": "1.6.0",
                            "currentVersionReleaseDate": "2026-09-08T00:27:25Z",
                        }
                    ],
                },
            )
        }
    )

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(source.source_id)

    assert observation.current.version_text == "1.6.0"
    assert observation.current.revision_id == f"{config.track_id}:1.6.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("primary", [OSError("offline"), _FakeResponse(503, {})])
async def test_manifest_transport_falls_back_only_for_retryable_failures(
    primary: _FakeResponse | BaseException,
) -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    primary_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    fallback_url = f"{config.fallback_base_url}/{config.branch}/VersionList.json"
    session = _FakeSession(
        {
            primary_url: primary,
            fallback_url: _FakeResponse(
                200, _version_list({"100": _version_entry(100, 100)})
            ),
        }
    )

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(source.source_id)

    assert observation.current.revision_id == "100:100"
    assert [request.url for request in session.requests] == [primary_url, fallback_url]


@pytest.mark.asyncio
async def test_manifest_transport_logs_safe_primary_failure_before_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    primary_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    fallback_url = f"{config.fallback_base_url}/{config.branch}/VersionList.json"
    session = _FakeSession(
        {
            primary_url: OSError("primary body contains secret-token"),
            fallback_url: _FakeResponse(503, {}),
        }
    )

    with (
        caplog.at_level("WARNING", logger="astrbot"),
        pytest.raises(ClientUpdateTransportError) as caught,
    ):
        await ClientUpdateTransport(session_factory=lambda: session).get_observation(
            source.source_id
        )

    assert caught.value.kind is ClientUpdateFailureKind.STATUS
    assert caught.value.status_code == 503
    assert "endpoint_role=primary" in caplog.text
    assert "endpoint_role=fallback" in caplog.text
    assert "resource=VersionList" in caplog.text
    assert primary_url not in caplog.text
    assert fallback_url not in caplog.text
    assert "secret-token" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("primary", "expected_kind"),
    [
        (_FakeResponse(404, {}), ClientUpdateFailureKind.STATUS),
        (_FakeResponse(200, []), ClientUpdateFailureKind.CONTRACT),
    ],
)
async def test_manifest_transport_does_not_fallback_for_terminal_failures(
    primary: _FakeResponse,
    expected_kind: ClientUpdateFailureKind,
) -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    primary_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    session = _FakeSession({primary_url: primary})

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(session_factory=lambda: session).get_observation(
            source.source_id
        )

    assert caught.value.kind is expected_kind
    assert [request.url for request in session.requests] == [primary_url]


@pytest.mark.asyncio
async def test_manifest_transport_classifies_corrupt_manifest_as_contract_failure() -> (
    None
):
    source = resolve_client_update_source("cn-official-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    base = f"{config.primary_base_url}/{config.branch}/101"
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "100": _version_entry(100, 100),
                        "101": _version_entry(101, 101),
                    }
                ),
            ),
            f"{base}/PakFilesInfo.json": _FakeResponse(200, {"pakFilesMap": {}}),
            f"{base}/ResDiscreteInfo.json": _FakeResponse(
                200, _manifest(config.res_manifest_key, "101.res", 1)
            ),
        }
    )

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(session_factory=lambda: session).get_observation(
            source.source_id,
            baseline=_manifest_source_version(source.source_id, "100"),
        )

    assert caught.value.kind is ClientUpdateFailureKind.CONTRACT


@pytest.mark.asyncio
async def test_manifest_transport_rejects_baseline_from_another_source() -> None:
    source = resolve_client_update_source("cn-official-pc-manifest")

    with pytest.raises(ValueError, match="Source"):
        await ClientUpdateTransport(
            session_factory=lambda: _FakeSession({})
        ).get_observation(
            source.source_id,
            baseline=_manifest_source_version(
                "cn-official-android-astc-manifest", "100"
            ),
        )


def test_registry_allows_distinct_distributions_on_same_region_and_platform() -> None:
    """Target 身份是 region × distribution × platform：不同发行渠道必须共存。"""

    def source(source_id: str) -> ClientUpdateSource:
        return ClientUpdateSource(
            source_id=source_id,
            platform=ClientPlatform.ANDROID,
            provider_kind=ClientUpdateProviderKind.MANIFEST_CDN,
            provider_config=ManifestCdnProviderConfig(
                primary_base_url="https://primary.invalid",
                fallback_base_url=None,
                branch="Patches/Test",
                pak_manifest_key="Android_ASTC",
                res_manifest_key="WindowsNoEditor",
                user_agent="test-agent",
            ),
        )

    sources = tuple(
        source(f"cn-{distribution}-android-release")
        for distribution in ("official", "bilibili", "hykb")
    )
    targets = tuple(
        ClientUpdateTarget(
            target_id=f"cn-{distribution}-android",
            region_id="cn",
            distribution_id=distribution,
            platform=ClientPlatform.ANDROID,
            source_id=f"cn-{distribution}-android-release",
            display_name=f"渠道 {distribution}",
        )
        for distribution in ("official", "bilibili", "hykb")
    )
    registry = ClientUpdateRegistry(sources, targets)
    assert tuple(registry.targets_by_id) == (
        "cn-official-android",
        "cn-bilibili-android",
        "cn-hykb-android",
    )

    duplicate = ClientUpdateTarget(
        target_id="cn-official-android-alias",
        region_id="cn",
        distribution_id="official",
        platform=ClientPlatform.ANDROID,
        source_id="cn-official-android-release",
        display_name="重复渠道",
    )
    with pytest.raises(ValueError, match="Target 组合"):
        ClientUpdateRegistry(sources, (*targets, duplicate))


def test_manifest_provider_config_allows_missing_verified_fallback() -> None:
    base = ManifestCdnProviderConfig(
        primary_base_url="https://primary.invalid",
        fallback_base_url=None,
        branch="Patches/Test",
        pak_manifest_key="WindowsNoEditor",
        res_manifest_key="WindowsNoEditor",
        user_agent="test-agent",
    )
    assert base.fallback_base_url is None

    with pytest.raises(ValueError, match="fallback"):
        ManifestCdnProviderConfig(
            primary_base_url="https://primary.invalid",
            fallback_base_url="https://primary.invalid",
            branch="Patches/Test",
            pak_manifest_key="WindowsNoEditor",
            res_manifest_key="WindowsNoEditor",
            user_agent="test-agent",
        )


@pytest.mark.asyncio
async def test_manifest_transport_without_fallback_surfaces_primary_error() -> None:
    source = resolve_client_update_source("global-standalone-pc-manifest")
    config = source.provider_config
    assert isinstance(config, ManifestCdnProviderConfig)
    assert config.fallback_base_url is None
    version_url = f"{config.primary_base_url}/{config.branch}/VersionList.json"
    session = _FakeSession({version_url: OSError("unreachable")})

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(session_factory=lambda: session).get_observation(
            source.source_id
        )

    assert caught.value.kind is ClientUpdateFailureKind.NETWORK
    assert [request.url for request in session.requests] == [version_url]


_BILIBILI_ANDROID_PAYLOAD = {
    "code": 0,
    "message": "成功",
    "data": {
        "game_base_id": 111015,
        "android_game_status": 0,
        "android_download_link": (
            "https://pkg.biligame.com/games/ezlx_1.6.186.1_20260827_062204_13b21.apk"
        ),
        "android_sign": "df68b18e1dd1c9c0c900c01987e25a52",
        "android_pkg_name": "com.hero.dna.bilibili",
        "android_pkg_ver": 18,
        "android_pkg_size": 1872077064,
    },
}

_BILIBILI_PC_PAYLOAD = {
    "code": 0,
    "message": "成功",
    "data": {
        "game_base_id": 111799,
        "pc_game_status": 0,
        "pc_download_link": (
            "https://pkg.biligame.com/games/"
            "ezlxPCb_bilibili_20260828_015851daedd81c35991766409406854d95f6fdb25b777c.exe"
        ),
    },
}


def _bilibili_url(game_base_id: int) -> str:
    return (
        "https://line1-h5-pc-api.biligame.com/game/detail/gameinfo"
        f"?game_base_id={game_base_id}"
    )


@pytest.mark.asyncio
async def test_bilibili_android_transport_uses_apk_sign_as_revision() -> None:
    source = resolve_client_update_source("cn-bilibili-android-release")
    session = _FakeSession(
        {_bilibili_url(111015): _FakeResponse(200, _BILIBILI_ANDROID_PAYLOAD)}
    )

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(source.source_id)

    assert observation.current.revision_id == "df68b18e1dd1c9c0c900c01987e25a52"
    assert observation.current.version_text == "1.6.186.1"
    assert observation.current.order_key == 18
    assert observation.history_complete is True

    again = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession(
            {_bilibili_url(111015): _FakeResponse(200, _BILIBILI_ANDROID_PAYLOAD)}
        )
    ).get_observation(source.source_id, baseline=observation.current)
    assert again.history_complete is True
    assert again.added_size_bytes == 0


@pytest.mark.asyncio
async def test_bilibili_pc_transport_tracks_installer_identity_without_version() -> (
    None
):
    source = resolve_client_update_source("cn-bilibili-pc-release")
    url = _bilibili_url(111799)
    transport = ClientUpdateTransport(
        session_factory=lambda: _FakeSession(
            {url: _FakeResponse(200, _BILIBILI_PC_PAYLOAD)}
        )
    )

    observation = await transport.get_observation(source.source_id)

    expected_revision = (
        "ezlxPCb_bilibili_20260828_015851daedd81c35991766409406854d95f6fdb25b777c.exe"
    )
    assert observation.current.revision_id == expected_revision
    assert observation.current.version_text is None
    assert observation.current.order_key is None

    updated_link = "https://pkg.biligame.com/games/ezlxPCb_bilibili_20260910_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.exe"
    updated_payload = {
        "code": 0,
        "data": {
            **_BILIBILI_PC_PAYLOAD["data"],
            "pc_download_link": updated_link,
        },
    }
    changed = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession({url: _FakeResponse(200, updated_payload)})
    ).get_observation(source.source_id, baseline=observation.current)
    assert changed.current.revision_id != observation.current.revision_id
    assert changed.history_complete is False
    assert changed.added_size_bytes is None


@pytest.mark.asyncio
async def test_bilibili_transport_rejects_bad_code_and_malformed_sign() -> None:
    source = resolve_client_update_source("cn-bilibili-android-release")
    url = _bilibili_url(111015)
    bad_code = _FakeSession({url: _FakeResponse(200, {"code": -1, "data": {}})})

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(session_factory=lambda: bad_code).get_observation(
            source.source_id
        )
    assert caught.value.kind is ClientUpdateFailureKind.CONTRACT

    payload = {
        "code": 0,
        "data": {
            **_BILIBILI_ANDROID_PAYLOAD["data"],
            "android_sign": "not-a-md5",
        },
    }
    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(
            session_factory=lambda: _FakeSession({url: _FakeResponse(200, payload)})
        ).get_observation(source.source_id)
    assert caught.value.kind is ClientUpdateFailureKind.CONTRACT


_HYKB_PAGE = (
    "<html><body>"
    '<p class="sp2">1.6.186.1</p>'
    "<script>"
    "    var downInfo = {"
    '"kb_id":"158909",'
    '"apkurl":"https:\\\\/\\\\/sj.71acg.com\\\\/release\\\\/hykb\\\\/202608\\\\/20260827gf18_254.apk",'
    '"package":"com.hero.dna.gf",'
    '"appname":"二重螺旋(官服)",'
    '"md5":"9383e221690de1d983878bbb0ecceb4d"},'
    "</script>"
    "</body></html>"
)


@pytest.mark.asyncio
async def test_hykb_transport_uses_apk_md5_as_revision() -> None:
    source = resolve_client_update_source("cn-hykb-android-release")
    url = "https://m.3839.com/a/158909.htm"
    session = _FakeSession({url: _FakeResponse(200, _HYKB_PAGE)})

    observation = await ClientUpdateTransport(
        session_factory=lambda: session
    ).get_observation(source.source_id)

    assert observation.current.revision_id == "9383e221690de1d983878bbb0ecceb4d"
    assert observation.current.version_text == "1.6.186.1"
    assert observation.current.order_key is None
    assert observation.history_complete is True

    unchanged = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession({url: _FakeResponse(200, _HYKB_PAGE)})
    ).get_observation(source.source_id, baseline=observation.current)
    assert unchanged.history_complete is True
    assert unchanged.added_size_bytes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        "<html><body>无下载信息</body></html>",
        (
            "<html><body><script>var downInfo = {"
            '"kb_id":"158909",'
            '"apkurl":"https:\\\\/\\\\/sj.71acg.com\\\\/x.apk",'
            '"package":"com.other.game",'
            '"md5":"9383e221690de1d983878bbb0ecceb4d"},'
            "</script></body></html>"
        ),
    ],
)
async def test_hykb_transport_rejects_malformed_or_wrong_package(page: str) -> None:
    source = resolve_client_update_source("cn-hykb-android-release")
    url = "https://m.3839.com/a/158909.htm"

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(
            session_factory=lambda: _FakeSession({url: _FakeResponse(200, page)})
        ).get_observation(source.source_id)

    assert caught.value.kind is ClientUpdateFailureKind.CONTRACT
