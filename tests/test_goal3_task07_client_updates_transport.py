"""Goal 3 / Task 07：客户端更新 HTTP transport 的 fake-transport Red 契约。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

import pytest

import src.infrastructure.http.client_updates as client_updates_http
from src.infrastructure.http.client_updates import ClientUpdateTransport
from src.modules.client_updates.contracts import (
    ClientPlatform,
    ClientUpdateFailureKind,
    ClientUpdateObservation,
    ClientUpdateTransportError,
)


PC_MAIN = "http://pan01-1-eo.shyxhy.com"
PC_FALLBACK = "http://pan01-1-hs.shyxhy.com"
ANDROID_MAIN = "https://pan01-1-hs.shyxhy.com"
ANDROID_FALLBACK = PC_MAIN

PC_BRANCH = "Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub"
ANDROID_BRANCH = "Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub"

PC_USER_AGENT = "EMLauncher/++UE4+Release-4.27-CL-0 Windows/10.0.26100.1.256.64bit"
ANDROID_USER_AGENT = "EM/++UE4+Release-4.27-CL-0 Android/12"


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

    async def json(self) -> object:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class _FakeSession:
    def __init__(self, routes: Mapping[str, _FakeResponse | BaseException]) -> None:
        self.routes = routes
        self.requests: list[_Request] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        headers = kwargs.get("headers") or {}
        self.requests.append(_Request(url=url, headers=dict(headers)))
        route = self.routes[url]
        if isinstance(route, BaseException):
            raise route
        return route


def _version_entry(
    patch_version: int,
    *,
    revamp: int,
    patch_key: int = 1,
) -> dict[str, int]:
    return {
        "major": 1,
        "minor": 5,
        "revamp": revamp,
        "patchKey": patch_key,
        "patchVersion": patch_version,
    }


def _version_list(entries: Mapping[str, Mapping[str, int]]) -> dict[str, object]:
    return {"versionList": dict(entries)}


def _manifest(
    platform_key: str,
    entries: list[dict[str, object]],
    *,
    direct_size: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "pakFilesMap": {
            platform_key: {
                "pakFileInfos": entries,
            }
        }
    }
    if direct_size is not None:
        payload["updateSize"] = direct_size
    return payload


def _version_url(base: str, branch: str) -> str:
    return f"{base}/{branch}/VersionList.json"


def _manifest_url(base: str, branch: str, directory: str, name: str) -> str:
    return f"{base}/{branch}/{directory}/{name}"


def _assert_json_requests(requests: list[_Request], expected_user_agent: str) -> None:
    assert requests
    assert all(request.url.endswith(".json") for request in requests)
    assert all(
        request.headers.get("User-Agent") == expected_user_agent for request in requests
    )


@pytest.mark.asyncio
async def test_pc_transport_reads_exact_paths_and_sums_new_manifest_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC 使用完整分支路径，读取新增补丁清单并按文件名去重汇总。"""

    version_url = _version_url(PC_MAIN, PC_BRANCH)
    manifest_routes = {
        _manifest_url(PC_MAIN, PC_BRANCH, "101", "PakFilesInfo.json"): _FakeResponse(
            200,
            _manifest(
                "WindowsNoEditor",
                [
                    {"fileName": "shared.pak", "fileSize": 20},
                    {"fileName": "pc-101.pak", "fileSize": 10},
                ],
                direct_size=999999,
            ),
        ),
        _manifest_url(PC_MAIN, PC_BRANCH, "101", "ResDiscreteInfo.json"): _FakeResponse(
            200,
            _manifest(
                "WindowsNoEditor",
                [
                    {"fileName": "shared.pak", "fileSize": 20},
                    {"fileName": "res-101.pak", "fileSize": 5},
                ],
            ),
        ),
        _manifest_url(PC_MAIN, PC_BRANCH, "102", "PakFilesInfo.json"): _FakeResponse(
            200,
            _manifest(
                "WindowsNoEditor",
                [{"fileName": "pc-102.pak", "fileSize": 7}],
            ),
        ),
        _manifest_url(PC_MAIN, PC_BRANCH, "102", "ResDiscreteInfo.json"): _FakeResponse(
            200,
            _manifest(
                "WindowsNoEditor",
                [{"fileName": "res-102.pak", "fileSize": 3}],
            ),
        ),
    }
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "100": _version_entry(100, revamp=100),
                        "101": _version_entry(101, revamp=101),
                        "102": _version_entry(102, revamp=102),
                    }
                ),
            ),
            **manifest_routes,
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    observation = await ClientUpdateTransport().get_observation(
        ClientPlatform.PC,
        previous_patch_version=100,
    )

    assert isinstance(observation, ClientUpdateObservation)
    assert observation.snapshot.platform is ClientPlatform.PC
    assert observation.snapshot.patch_version == 102
    assert observation.snapshot.version_text == "1.5.102.1"
    assert observation.snapshot.resource_version_dir is None
    assert observation.patch_sizes == {101: 35, 102: 10}
    assert {request.url for request in session.requests} == {
        version_url,
        *manifest_routes,
    }
    _assert_json_requests(session.requests, PC_USER_AGENT)


@pytest.mark.asyncio
async def test_android_transport_uses_resource_directory_keys_not_patch_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安卓清单路径必须使用 VersionList 的资源目录 key，不能改写 patchVersion。"""

    version_url = _version_url(ANDROID_MAIN, ANDROID_BRANCH)
    manifest_routes = {
        _manifest_url(
            ANDROID_MAIN,
            ANDROID_BRANCH,
            "1010163",
            "PakFilesInfo.json",
        ): _FakeResponse(
            200,
            _manifest(
                "Android_ASTC",
                [{"fileName": "android-1010163.chunk", "fileSize": 12}],
            ),
        ),
        _manifest_url(
            ANDROID_MAIN,
            ANDROID_BRANCH,
            "1010163",
            "ResDiscreteInfo.json",
        ): _FakeResponse(
            200,
            _manifest(
                "Android_ASTC",
                [{"fileName": "android-res-1010163.chunk", "fileSize": 3}],
            ),
        ),
        _manifest_url(
            ANDROID_MAIN,
            ANDROID_BRANCH,
            "1010164",
            "PakFilesInfo.json",
        ): _FakeResponse(
            200,
            _manifest(
                "Android_ASTC",
                [{"fileName": "android-1010164.chunk", "fileSize": 20}],
            ),
        ),
        _manifest_url(
            ANDROID_MAIN,
            ANDROID_BRANCH,
            "1010164",
            "ResDiscreteInfo.json",
        ): _FakeResponse(
            200,
            _manifest(
                "Android_ASTC",
                [{"fileName": "android-res-1010164.chunk", "fileSize": 4}],
            ),
        ),
    }
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "1010162": _version_entry(1410162, revamp=162),
                        "1010163": _version_entry(1410163, revamp=163),
                        "1010164": _version_entry(1410164, revamp=164),
                    }
                ),
            ),
            **manifest_routes,
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    observation = await ClientUpdateTransport().get_observation(
        ClientPlatform.ANDROID,
        previous_patch_version=1410162,
    )

    assert isinstance(observation, ClientUpdateObservation)
    assert observation.snapshot.platform is ClientPlatform.ANDROID
    assert observation.snapshot.patch_version == 1410164
    assert observation.snapshot.resource_version_dir == "1010164"
    assert observation.snapshot.version_text == "1.5.164.1"
    assert observation.patch_sizes == {1410163: 15, 1410164: 24}
    manifest_urls = {request.url for request in session.requests[1:]}
    assert manifest_urls == set(manifest_routes)
    assert all("/141016" not in url for url in manifest_urls)
    _assert_json_requests(session.requests, ANDROID_USER_AGENT)


@pytest.mark.asyncio
async def test_network_failure_on_one_platform_does_not_hide_other_platform_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一个平台网络失败时，另一个平台仍能得到独立的成功结果。"""

    pc_version_url = _version_url(PC_MAIN, PC_BRANCH)
    android_version_url = _version_url(ANDROID_MAIN, ANDROID_BRANCH)
    network_error = OSError("token=secret-provider-detail")
    session = _FakeSession(
        {
            pc_version_url: _FakeResponse(
                200,
                _version_list({"100": _version_entry(100, revamp=100)}),
            ),
            android_version_url: network_error,
            _version_url(ANDROID_FALLBACK, ANDROID_BRANCH): network_error,
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    pc_result, android_result = await asyncio.gather(
        ClientUpdateTransport().get_observation(ClientPlatform.PC),
        ClientUpdateTransport().get_observation(ClientPlatform.ANDROID),
        return_exceptions=True,
    )

    assert isinstance(pc_result, ClientUpdateObservation)
    assert pc_result.snapshot.platform is ClientPlatform.PC
    assert isinstance(android_result, ClientUpdateTransportError)
    assert android_result.kind is ClientUpdateFailureKind.NETWORK
    assert "secret-provider-detail" not in str(android_result)
    assert "secret-provider-detail" not in repr(android_result)
    assert "secret-provider-detail" not in android_result.detail


@pytest.mark.asyncio
async def test_main_host_network_failure_falls_back_once_to_contract_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主资源主机网络失败时只切换一次契约中声明的回退主机。"""

    primary_url = _version_url(PC_MAIN, PC_BRANCH)
    fallback_url = _version_url(PC_FALLBACK, PC_BRANCH)
    session = _FakeSession(
        {
            primary_url: OSError("primary unavailable"),
            fallback_url: _FakeResponse(
                200,
                _version_list({"100": _version_entry(100, revamp=100)}),
            ),
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    observation = await ClientUpdateTransport().get_observation(ClientPlatform.PC)

    assert isinstance(observation, ClientUpdateObservation)
    assert [request.url for request in session.requests] == [primary_url, fallback_url]
    _assert_json_requests(session.requests, PC_USER_AGENT)


@pytest.mark.asyncio
async def test_malformed_version_or_manifest_is_a_safe_contract_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功响应的结构错误必须显式分类，不能伪装成无更新。"""

    version_url = _version_url(PC_MAIN, PC_BRANCH)
    session = _FakeSession({version_url: _FakeResponse(200, {})})
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    with pytest.raises(ClientUpdateTransportError) as raised:
        await ClientUpdateTransport().get_observation(ClientPlatform.PC)

    assert raised.value.kind is ClientUpdateFailureKind.CONTRACT
    assert "VersionList" not in str(raised.value)
    assert "pan01" not in repr(raised.value)


@pytest.mark.asyncio
async def test_malformed_manifest_does_not_produce_partial_patch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任一新增补丁清单结构错误时，不能返回部分大小结果。"""

    version_url = _version_url(PC_MAIN, PC_BRANCH)
    pak_url = _manifest_url(PC_MAIN, PC_BRANCH, "101", "PakFilesInfo.json")
    res_url = _manifest_url(PC_MAIN, PC_BRANCH, "101", "ResDiscreteInfo.json")
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "100": _version_entry(100, revamp=100),
                        "101": _version_entry(101, revamp=101),
                    }
                ),
            ),
            pak_url: _FakeResponse(200, {"pakFilesMap": {}}),
            res_url: _FakeResponse(
                200,
                _manifest(
                    "WindowsNoEditor",
                    [{"fileName": "res-101.pak", "fileSize": 5}],
                ),
            ),
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    with pytest.raises(ClientUpdateTransportError) as raised:
        await ClientUpdateTransport().get_observation(
            ClientPlatform.PC,
            previous_patch_version=100,
        )

    assert raised.value.kind is ClientUpdateFailureKind.CONTRACT
    assert "pakFilesMap" not in str(raised.value)


@pytest.mark.asyncio
async def test_manifest_network_failure_falls_back_to_contract_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补丁清单主机网络失败时只切换到另一契约主机。"""

    version_url = _version_url(PC_MAIN, PC_BRANCH)
    primary_pak_url = _manifest_url(PC_MAIN, PC_BRANCH, "101", "PakFilesInfo.json")
    fallback_pak_url = _manifest_url(PC_FALLBACK, PC_BRANCH, "101", "PakFilesInfo.json")
    primary_res_url = _manifest_url(PC_MAIN, PC_BRANCH, "101", "ResDiscreteInfo.json")
    session = _FakeSession(
        {
            version_url: _FakeResponse(
                200,
                _version_list(
                    {
                        "100": _version_entry(100, revamp=100),
                        "101": _version_entry(101, revamp=101),
                    }
                ),
            ),
            primary_pak_url: OSError("primary manifest unavailable"),
            fallback_pak_url: _FakeResponse(
                200,
                _manifest(
                    "WindowsNoEditor",
                    [{"fileName": "pc-101.pak", "fileSize": 7}],
                ),
            ),
            primary_res_url: _FakeResponse(
                200,
                _manifest(
                    "WindowsNoEditor",
                    [{"fileName": "res-101.pak", "fileSize": 3}],
                ),
            ),
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    observation = await ClientUpdateTransport().get_observation(
        ClientPlatform.PC,
        previous_patch_version=100,
    )

    assert observation.patch_sizes == {101: 10}
    assert [request.url for request in session.requests].count(fallback_pak_url) == 1
    _assert_json_requests(session.requests, PC_USER_AGENT)
