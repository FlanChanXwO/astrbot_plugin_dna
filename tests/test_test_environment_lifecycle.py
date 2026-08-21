"""pytest 运行期数据目录必须与仓库 fixture 隔离并可安全重复清理。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import conftest


def test_pytest_environment_uses_session_copy_outside_repository() -> None:
    data_root = Path(os.environ["DNABY_DATA_DIR"]).resolve()
    astrbot_root = Path(os.environ["ASTRBOT_ROOT"]).resolve()
    source_fixture = (conftest.ROOT / "tests" / ".data").resolve()

    assert data_root != source_fixture
    session_root = conftest._SESSION_ROOT.resolve()
    assert data_root.is_relative_to(session_root)
    assert astrbot_root.is_relative_to(session_root)
    assert (data_root / "resource" / "alias" / "char_alias.json").is_file()


def test_cleanup_is_idempotent_for_missing_session_root(tmp_path: Path, monkeypatch) -> None:
    owned_root = tmp_path / "dnaby-pytest-owned"
    owned_root.mkdir()
    (owned_root / "runtime.txt").write_text("test", encoding="utf-8")
    monkeypatch.setattr(conftest, "_SESSION_ROOT", owned_root)

    conftest._cleanup_test_environment()
    conftest._cleanup_test_environment()

    assert not owned_root.exists()


def test_external_environment_cannot_override_session_isolation(tmp_path: Path) -> None:
    """调用环境预设路径时，pytest 配置仍必须使用本次受控临时根。"""

    external_data = tmp_path / "external-data"
    external_astrbot = tmp_path / "external-astrbot"
    environment = os.environ.copy()
    environment["DNABY_DATA_DIR"] = str(external_data)
    environment["ASTRBOT_ROOT"] = str(external_astrbot)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, conftest; "
                "print(os.environ['DNABY_DATA_DIR']); "
                "print(os.environ['ASTRBOT_ROOT']); "
                "print(conftest._SESSION_ROOT)"
            ),
        ],
        cwd=conftest.ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    data_root, astrbot_root, session_root = map(Path, result.stdout.splitlines())

    assert data_root.resolve().is_relative_to(session_root.resolve())
    assert astrbot_root.resolve().is_relative_to(session_root.resolve())
    assert data_root != external_data
    assert astrbot_root != external_astrbot
