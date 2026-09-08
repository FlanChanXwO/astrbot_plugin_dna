"""pytest 测试配置：隔离运行期数据，并为渲染测试提供确定性实现。

- ``DNABY_DATA_DIR``：让 RESOURCE_PATH 指向临时数据目录。
- ``ASTRBOT_ROOT``：让 AstrBot 数据目录指向临时根，避免测试写入真实运行期数据。
"""

import atexit
import io
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent


def _prepare_test_environment() -> tuple[Path, Path]:
    """复制只读 fixture 到本次运行专属临时根，避免共享目录累积状态。"""

    session_root = Path(tempfile.mkdtemp(prefix="dna-pytest-"))
    astrbot_root = session_root / "astrbot"
    data_root = session_root / "plugin-data"
    fixture_root = TESTS_DIR / ".data"
    if fixture_root.is_dir():
        shutil.copytree(fixture_root, data_root)
    else:
        data_root.mkdir(parents=True)
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
    """为未显式注入 renderer 的领域测试提供确定性的内存 T2I。"""

    from PIL import Image

    import astrbot.core

    renderer = astrbot.core.html_renderer
    original = renderer.render_custom_template

    async def _render_custom_template(
        *,
        tmpl_str: str,
        tmpl_data: dict,
        return_url: bool = True,
        options: dict | None = None,
    ):
        del tmpl_str, tmpl_data
        if return_url:
            return "https://example.invalid/dna-test-render"

        render_options = options or {}
        image_format = str(render_options.get("type", "jpeg")).lower()
        pillow_format = "PNG" if image_format == "png" else "JPEG"
        width = int(render_options.get("viewport_width", 8))
        height = int(render_options.get("viewport_height", 8))
        buffer = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(buffer, format=pillow_format)
        return buffer.getvalue()

    renderer.render_custom_template = _render_custom_template
    try:
        yield
    finally:
        renderer.render_custom_template = original
