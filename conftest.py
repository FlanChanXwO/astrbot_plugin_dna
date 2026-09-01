"""pytest 根配置：确保插件根目录可导入 ``dnaby``，且 AstrBot 不写插件目录。

- ``DNABY_DATA_DIR``：让 RESOURCE_PATH 指向临时数据目录。
- ``ASTRBOT_ROOT``：让 astrbot 的 get_astrbot_data_path() 指向临时根，避免在插件目录生成 data/。
"""

import atexit
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


def _prepare_test_environment() -> tuple[Path, Path]:
    """复制只读 fixture 到本次运行专属临时根，避免共享目录累积状态。"""

    session_root = Path(tempfile.mkdtemp(prefix="dnaby-pytest-"))
    astrbot_root = session_root / "astrbot"
    data_root = session_root / "plugin-data"
    shutil.copytree(ROOT / "tests" / ".data", data_root)
    astrbot_root.mkdir()
    (astrbot_root / "temp").mkdir(parents=True, exist_ok=True)
    Path("data/temp").mkdir(parents=True, exist_ok=True)
    return session_root, astrbot_root


_SESSION_ROOT, _ASTRBOT_ROOT = _prepare_test_environment()

# pytest 必须强制覆盖调用环境中的同名变量，否则可能误写外部运行期数据目录。
os.environ["DNABY_DATA_DIR"] = str(_SESSION_ROOT / "plugin-data")
os.environ["ASTRBOT_ROOT"] = str(_ASTRBOT_ROOT)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _cleanup_test_environment() -> None:
    """只清理本次创建的临时根，不触碰仓库中的共享 fixture。"""

    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)


atexit.register(_cleanup_test_environment)


def pytest_sessionfinish(session, exitstatus) -> None:
    """在 pytest 正常结束或失败结束时清理运行期临时根。"""

    del session, exitstatus
    _cleanup_test_environment()


@pytest.fixture(scope="session", autouse=True)
def local_t2i_renderer() -> Iterator[None]:
    """把未显式注入 renderer 的旧测试定向到本地 T2I 容器。

    生产代码仍读取 AstrBot 自身配置；这里只在 pytest 进程内覆盖全局策略，
    避免测试因为远程端点、Cloudflare 错误页或官方端点轮换而产生非确定性失败。
    """

    import astrbot.core

    strategy = astrbot.core.html_renderer.network_strategy
    old_base_url = strategy.BASE_RENDER_URL
    old_endpoints = list(strategy.endpoints)
    endpoint = os.environ.get(
        "DNABY_TEST_T2I_ENDPOINT",
        "http://127.0.0.1:8999/text2img",
    ).rstrip("/")
    strategy.BASE_RENDER_URL = endpoint
    strategy.endpoints = [endpoint]
    try:
        yield
    finally:
        strategy.BASE_RENDER_URL = old_base_url
        strategy.endpoints = old_endpoints
