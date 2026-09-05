"""T22：删除 legacy 按函数代理入口，保留统一 typed 网络出口。"""

from __future__ import annotations

from importlib import import_module

from src.infrastructure.config.settings import DnabySettings


def test_legacy_function_proxy_helpers_are_not_exposed() -> None:
    """旧函数级代理 helper 不再成为公开模块入口。"""

    api_module = import_module("src.utils.api.api")

    for helper_name in (
        "get_local_proxy_url",
        "get_need_proxy_func",
        "get_no_need_proxy_func",
    ):
        assert not hasattr(api_module, helper_name)


def test_proxy_configuration_remains_on_typed_network_settings() -> None:
    """删除 helper 不得回退到 legacy 函数配置，统一出口仍可读。"""

    settings = DnabySettings.from_config(
        {"network": {"proxy_url": "http://proxy.example.test:7890"}}
    )

    assert settings.network.proxy_url == "http://proxy.example.test:7890"
