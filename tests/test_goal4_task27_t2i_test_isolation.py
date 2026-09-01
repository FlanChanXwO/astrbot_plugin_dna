"""Task 27：全量测试必须显式使用本地 T2I 容器，而不是远程默认端点。"""

from __future__ import annotations

import pytest


@pytest.mark.usefixtures("local_t2i_renderer")
def test_pytest_uses_local_t2i_renderer() -> None:
    """测试环境把 AstrBot 全局网络 renderer 定向到本地容器。"""

    from astrbot.core import html_renderer

    assert html_renderer.network_strategy.endpoints == [
        "http://127.0.0.1:8999/text2img"
    ]
