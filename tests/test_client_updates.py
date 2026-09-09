"""客户端更新 Target / Source 公共契约测试。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Self

import pytest

import src.modules.client_updates as client_updates_public
from src.infrastructure.http import client_updates as client_updates_module
from src.infrastructure.http.client_updates import ClientUpdateTransport
from src.modules.client_updates import (
    CLIENT_UPDATE_SOURCES,
    CLIENT_UPDATE_TARGETS,
    DEFAULT_CLIENT_UPDATE_TARGET_IDS,
    AppStoreProviderConfig,
    AppStoreVersionMetadata,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateFailureKind,
    ClientUpdateProviderKind,
    ClientUpdateRegistry,
    ClientUpdateSource,
    ClientUpdateTarget,
    ClientUpdateTransportError,
    ClientVersionSnapshot,
    ManifestCdnProviderConfig,
    ManifestCdnVersionMetadata,
    group_client_update_target_ids_by_source,
    normalize_client_update_platforms,
    normalize_client_update_target_ids,
    resolve_client_update_source,
    resolve_client_update_target,
)


def test_public_contract_has_no_legacy_channel_model() -> None:
    package_dir = Path(client_updates_public.__file__).parent
    assert not (package_dir / "channels.py").exists()
    forbidden_exports = (
        "CHANNEL_REGISTRY",
        "CLIENT_UPDATE_CHANNELS",
        "ClientUpdateChannel",
        "ClientRegion",
        "default_channel_id_for_platform",
        "normalize_client_update_channel_ids",
        "resolve_client_update_channel",
        "select_enabled_channels",
        "parse_channel_version_list",
        "parse_channel_version_list_entries",
        "sum_channel_patch_file_sizes",
    )
    assert all(not hasattr(client_updates_public, name) for name in forbidden_exports)
    assert all(
        not hasattr(client_updates_module, name)
        for name in (
            "PC_PRIMARY_BASE_URL",
            "PC_FALLBACK_BASE_URL",
            "ANDROID_PRIMARY_BASE_URL",
            "ANDROID_FALLBACK_BASE_URL",
            "PC_BRANCH",
            "ANDROID_BRANCH",
            "PC_USER_AGENT",
            "ANDROID_USER_AGENT",
        )
    )
    assert tuple(field.name for field in fields(ClientVersionSnapshot)) == (
        "version_key",
        "patch_version",
        "resource_version_dir",
        "major",
        "minor",
        "revamp",
        "patch_key",
    )
    with pytest.raises(ValueError, match="不支持"):
        client_updates_public.parse_version_list_entries({}, "pc_cn")


def test_verified_registry_contains_only_investigated_cn_targets() -> None:
    assert tuple(CLIENT_UPDATE_TARGETS) == (
        "cn-official-pc",
        "cn-official-android",
        "cn-official-ios",
    )
    assert tuple(CLIENT_UPDATE_SOURCES) == (
        "cn-official-pc-manifest",
        "cn-official-android-astc-manifest",
        "cn-official-ios-app-store",
    )
    assert DEFAULT_CLIENT_UPDATE_TARGET_IDS == (
        "cn-official-pc",
        "cn-official-android",
    )
    with pytest.raises(ValueError, match="不支持"):
        normalize_client_update_platforms([ClientPlatform.IOS])

    assert tuple(
        (
            target.target_id,
            target.region_id,
            target.ecosystem_id,
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
            "cn-official-ios",
            "cn",
            "official",
            ClientPlatform.IOS,
            "cn-official-ios-app-store",
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
    assert ios.provider_config == AppStoreProviderConfig(track_id=6470771372, country="cn")


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
        ecosystem_id="official",
        platform=ClientPlatform.PC,
        source_id=source.source_id,
        display_name="国服官服 PC",
    )

    with pytest.raises(ValueError, match="Source ID"):
        ClientUpdateRegistry((source, source), (target,))

    duplicate_identity = ClientUpdateTarget(
        target_id="cn-official-pc-alias",
        region_id="cn",
        ecosystem_id="official",
        platform=ClientPlatform.PC,
        source_id=source.source_id,
        display_name="重复身份",
    )
    with pytest.raises(ValueError, match="Target 组合"):
        ClientUpdateRegistry((source,), (target, duplicate_identity))

    ambiguous_name = ClientUpdateTarget(
        target_id="cn-other-pc",
        region_id="cn",
        ecosystem_id="other",
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
        ecosystem_id="missing-source",
        platform=ClientPlatform.PC,
        source_id="missing-source",
        display_name="缺失 Source",
    )
    with pytest.raises(ValueError, match="不存在的 Source"):
        ClientUpdateRegistry((source,), (missing_source_target,))

    mismatched_target = ClientUpdateTarget(
        target_id="cn-official-android",
        region_id="cn",
        ecosystem_id="official",
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
        ecosystem_id="foreign",
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
        ["cn-official-ios", "cn-official-pc", "cn-official-ios"]
    ) == ("cn-official-ios", "cn-official-pc")

    grouped = group_client_update_target_ids_by_source(
        ["cn-official-ios", "cn-official-pc", "cn-official-android"]
    )
    assert grouped == {
        "cn-official-ios-app-store": ("cn-official-ios",),
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
        self.requests.append(_Request(url=url, headers=dict(kwargs.get("headers") or {})))
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


def _source_version(source_id: str, revision_id: str) -> ClientSourceVersion:
    number = int(revision_id)
    return ClientSourceVersion(
        source_id=source_id,
        version_text=f"1.6.{number}.1",
        revision_id=revision_id,
        order_key=(number, number),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=number,
            patch_version=number,
            resource_version_dir=None,
        ),
    )


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
    ).get_observation(source.source_id, baseline=_source_version(source.source_id, "100"))

    assert observation.current.revision_id == "102"
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
    ).get_observation(source.source_id, baseline=_source_version(source.source_id, "100"))

    assert isinstance(observation, ClientSourceObservation)
    assert observation.current.revision_id == "103"
    assert tuple(version.revision_id for version in observation.observed_versions) == (
        "100",
        "102",
        "103",
    )
    assert observation.history_complete is True
    assert observation.added_size_bytes == 52
    assert all("/101/" not in request.url for request in session.requests)


@pytest.mark.asyncio
async def test_manifest_transport_marks_baseline_outside_window_as_history_gap() -> None:
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
    ).get_observation(source.source_id, baseline=_source_version(source.source_id, "100"))

    assert observation.current.revision_id == "103"
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
        revision_id="1042001",
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

    assert observation.current.revision_id == "1510198"
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
        revision_id="5001",
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

    assert observation.added_size_bytes == 42
    assert {request.url for request in session.requests if "Info.json" in request.url} == {
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
async def test_app_store_transport_reports_changed_and_unchanged_baselines() -> None:
    source = resolve_client_update_source("cn-official-ios-app-store")
    config = source.provider_config
    assert isinstance(config, AppStoreProviderConfig)
    url = f"https://itunes.apple.com/lookup?id={config.track_id}&country={config.country}"
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
    ).get_observation(source.source_id, baseline=_app_store_version(source.source_id, "1.5.0"))
    unchanged = await ClientUpdateTransport(
        session_factory=lambda: _FakeSession({url: _FakeResponse(200, payload)})
    ).get_observation(source.source_id, baseline=_app_store_version(source.source_id, "1.6.0"))

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
    url = f"https://itunes.apple.com/lookup?id={config.track_id}&country={config.country}"
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

    assert observation.current.revision_id == "100"
    assert [request.url for request in session.requests] == [primary_url, fallback_url]


@pytest.mark.asyncio
async def test_manifest_transport_logs_safe_primary_failure_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
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

    class RecordingLogger:
        def __init__(self) -> None:
            self.calls: list[tuple[object, tuple[object, ...]]] = []

        def warning(self, message: object, *args: object) -> None:
            self.calls.append((message, args))

    logger = RecordingLogger()
    monkeypatch.setattr(client_updates_module, "logger", logger)

    with pytest.raises(ClientUpdateTransportError) as caught:
        await ClientUpdateTransport(session_factory=lambda: session).get_observation(
            source.source_id
        )

    assert caught.value.kind is ClientUpdateFailureKind.STATUS
    assert caught.value.status_code == 503
    assert logger.calls == [
        (
            "客户端更新端点失败 endpoint_role=primary next_role=fallback "
            "resource=%s kind=%s status=%s",
            ("VersionList", "network", None),
        ),
        (
            "客户端更新端点失败 endpoint_role=fallback "
            "resource=%s kind=%s status=%s",
            ("VersionList", "status", 503),
        ),
    ]
    assert primary_url not in repr(logger.calls)
    assert fallback_url not in repr(logger.calls)
    assert "secret-token" not in repr(logger.calls)


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
async def test_manifest_transport_classifies_corrupt_manifest_as_contract_failure() -> None:
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
            baseline=_source_version(source.source_id, "100"),
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
            baseline=_source_version("cn-official-android-astc-manifest", "100"),
        )
