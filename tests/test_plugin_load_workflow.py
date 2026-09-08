"""稳定版与 master 的 AstrBot loader PR workflow 契约。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "plugin-load.yml"


def _read_workflow() -> tuple[str, dict[str, object]]:
    assert WORKFLOW.is_file(), f"缺少 stable/master loader workflow：{WORKFLOW}"
    text = WORKFLOW.read_text(encoding="utf-8")
    value = yaml.safe_load(text)
    assert isinstance(value, dict)
    return text, value


def test_loader_workflow_is_pr_only_read_only_and_stable_master_matrix() -> None:
    text, workflow = _read_workflow()

    trigger = workflow.get("on", workflow.get(True))
    assert trigger == {"pull_request": None}
    assert "pull_request_target" not in text
    assert workflow.get("permissions") == {"contents": "read"}
    assert "3.12" in text
    assert "continue-on-error" not in text
    assert "secrets." not in text

    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and len(jobs) == 1
    job = next(iter(jobs.values()))
    assert isinstance(job, dict)
    assert job["name"] == "AstrBot plugin load (${{ matrix.source }})"
    assert job["strategy"]["matrix"]["source"] == ["stable", "master"]
    assert job.get("permissions") in (None, {"contents": "read"})

    assert 'if [[ "$SOURCE_KIND" == "stable" ]]' in text
    assert 'elif [[ "$SOURCE_KIND" == "master" ]]' in text
    assert "git ls-remote --tags --refs" in text
    assert "select_latest_stable_version" in text
    assert "scripts/ci/check_astrbot_plugin_load.py" in text
    assert (
        'ASTRBOT_VERSION: "${{ matrix.source }}:${{ steps.astrbot-ref.outputs.ref }}"'
        in text
    )
    assert re.search(r"ASTRBOT_ROOT:.*matrix\.source", text)
