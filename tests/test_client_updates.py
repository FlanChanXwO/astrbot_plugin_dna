"""客户端更新 Target / Source 公共契约测试。"""

from __future__ import annotations

import pytest

from src.modules.client_updates import (
    CLIENT_UPDATE_SOURCES,
    CLIENT_UPDATE_TARGETS,
    DEFAULT_CLIENT_UPDATE_TARGET_IDS,
    AppStoreProviderConfig,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateProviderKind,
    ClientUpdateRegistry,
    ClientUpdateSource,
    ClientUpdateTarget,
    ManifestCdnProviderConfig,
    ManifestCdnVersionMetadata,
    group_client_update_target_ids_by_source,
    normalize_client_update_platforms,
    normalize_client_update_target_ids,
    resolve_client_update_source,
    resolve_client_update_target,
)


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
