"""Task 06：DNABY 单插件仓库的 GitHub 工程治理契约。"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"

EXPECTED_FILES = {
    Path("CODEOWNERS"),
    Path("ISSUE_TEMPLATE/bug-report.yml"),
    Path("ISSUE_TEMPLATE/config.yml"),
    Path("ISSUE_TEMPLATE/feature_request.yml"),
    Path("PULL_REQUEST_TEMPLATE.md"),
    Path("auto_assign.yml"),
    Path("labeler.yml"),
    Path("release-drafter.yml"),
    Path("workflows/auto-assign.yml"),
    Path("workflows/plugin-lifecycle.yml"),
    Path("workflows/pr-triage.yml"),
    Path("workflows/release-from-changelog.yml"),
}

REPOSITORY = "FlanChanXwO/astrbot_plugin_dnaby"
OWNER = "FlanChanXwO"


def _read(relative_path: str) -> str:
    path = GITHUB / relative_path
    assert path.is_file(), f"缺少 GitHub 治理文件：{path}"
    return path.read_text(encoding="utf-8")


def _load_yaml(relative_path: str) -> dict:
    value = yaml.safe_load(_read(relative_path))
    assert isinstance(value, dict), relative_path
    return value


def _trigger(workflow: dict) -> dict:
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def test_github_governance_file_set_is_complete_and_single_plugin_oriented() -> None:
    actual = {
        path.relative_to(GITHUB)
        for path in GITHUB.rglob("*")
        if path.is_file() and path.name != "plugin-load.yml"
    }
    assert actual == EXPECTED_FILES

    public_text = "\n".join(
        (GITHUB / relative_path).read_text(encoding="utf-8")
        for relative_path in sorted(EXPECTED_FILES)
    )
    assert "rsshub" not in public_text.lower()
    assert "astrbot_plugin_rsshub" not in public_text.lower()
    assert "data/plugins/" not in _read("workflows/release-from-changelog.yml")


def test_codeowners_and_templates_target_dnaby_maintainer_and_users() -> None:
    assert "* @FlanChanXwO" in _read("CODEOWNERS")

    issue_config = _load_yaml("ISSUE_TEMPLATE/config.yml")
    assert issue_config["blank_issues_enabled"] is False
    contact_links = issue_config.get("contact_links")
    assert isinstance(contact_links, list) and contact_links
    assert all(REPOSITORY.lower() in link["url"].lower() for link in contact_links)

    bug = _load_yaml("ISSUE_TEMPLATE/bug-report.yml")
    feature = _load_yaml("ISSUE_TEMPLATE/feature_request.yml")
    assert bug["labels"] == ["bug"]
    assert feature["labels"] == ["enhancement"]
    bug_ids = {item["id"] for item in bug["body"] if "id" in item}
    feature_ids = {item["id"] for item in feature["body"] if "id" in item}
    assert bug_ids >= {"describe", "reproduction"}
    assert feature_ids >= {"problem", "feature"}

    pull_request = _read("PULL_REQUEST_TEMPLATE.md")
    assert "改动点" in pull_request
    assert "验证" in pull_request
    assert "检查清单" in pull_request
    assert "pytest" in pull_request
    assert "ruff" in pull_request
    assert "真实账号" in pull_request or "Cookie" in pull_request


def test_labeler_covers_dnaby_document_runtime_test_ci_and_release_paths() -> None:
    labeler = _load_yaml("labeler.yml")
    assert set(labeler) == {
        "area: docs",
        "area: runtime",
        "area: tests",
        "area: github-actions",
        "release",
    }

    def globs_for(label: str) -> set[str]:
        changed = labeler[label][0]["changed-files"][0]["any-glob-to-any-file"]
        return set(changed)

    assert globs_for("area: docs") >= {
        "README.md",
        "CHANGELOG.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/**",
    }
    assert globs_for("area: runtime") >= {"main.py", "src/**"}
    assert globs_for("area: tests") == {"tests/**"}
    assert globs_for("area: github-actions") == {".github/**"}
    assert globs_for("release") >= {"metadata.yaml", "CHANGELOG.md"}


def test_auto_assign_and_release_drafter_keep_dnaby_automation_contract() -> None:
    auto_assign = _load_yaml("auto_assign.yml")
    assert auto_assign["addReviewers"] is True
    assert auto_assign["addAssignees"] is False
    assert auto_assign["reviewers"] == [OWNER]
    assert auto_assign["numberOfReviewers"] == 0

    drafter = _load_yaml("release-drafter.yml")
    assert drafter["name-template"] == "v$RESOLVED_VERSION"
    assert drafter["tag-template"] == "v$RESOLVED_VERSION"
    assert drafter["template"] == "$CHANGES"
    assert drafter["version-resolver"]["default"] == "patch"
    assert {item["title"] for item in drafter["categories"]} >= {
        "💥 Breaking Changes",
        "🚀 Features",
        "🐛 Bug Fixes",
    }


def test_pr_automation_uses_trusted_workflow_target_and_minimal_write_permissions() -> None:
    auto_assign = _load_yaml("workflows/auto-assign.yml")
    assert set(_trigger(auto_assign)) == {"pull_request_target"}
    assert set(_trigger(auto_assign)["pull_request_target"]["types"]) == {
        "opened",
        "ready_for_review",
        "reopened",
    }
    assert auto_assign["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
    }
    assert "secrets." not in _read("workflows/auto-assign.yml")

    triage = _load_yaml("workflows/pr-triage.yml")
    assert set(_trigger(triage)) == {"pull_request_target"}
    assert triage["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "issues": "write",
    }
    triage_text = _read("workflows/pr-triage.yml")
    assert ".github/labeler.yml" in triage_text
    assert OWNER in triage_text
    assert "secrets." not in triage_text
    checkout_steps = [
        step
        for job in triage["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkout_steps) <= 1
    if checkout_steps:
        assert checkout_steps[0]["with"] == {
            "ref": "${{ github.event.pull_request.base.sha }}",
            "persist-credentials": False,
        }


def test_release_from_changelog_is_root_only_and_can_write_release_metadata() -> None:
    workflow = _load_yaml("workflows/release-from-changelog.yml")
    trigger = _trigger(workflow)
    assert set(trigger) == {"push", "workflow_dispatch"}
    assert trigger["push"]["branches"] == ["main"]
    assert trigger["push"]["paths"] == ["CHANGELOG.md"]
    assert workflow["permissions"] == {"contents": "write"}

    text = _read("workflows/release-from-changelog.yml")
    assert "github.token" in text
    assert "secrets." not in text
    assert "data/plugins" not in text
    assert "pull_request_target" not in text
    assert "release" in text.lower()
