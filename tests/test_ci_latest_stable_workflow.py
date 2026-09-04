"""CI 生命周期 workflow 的命名与 AstrBot stable 目标契约。"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LIFECYCLE_WORKFLOW = WORKFLOWS / "plugin-lifecycle.yml"


class LifecycleWorkflowContractTests(unittest.TestCase):
    def test_workflow_uses_lifecycle_name_and_latest_stable_as_runtime_target(self) -> None:
        self.assertTrue(
            LIFECYCLE_WORKFLOW.is_file(),
            "生命周期 CI 应使用 .github/workflows/plugin-lifecycle.yml",
        )

        text = LIFECYCLE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("AstrBot plugin lifecycle", text)
        self.assertIn("git ls-remote --tags --refs", text)
        self.assertIn("select_latest_stable_version", text)
        self.assertIn("check_astrbot_plugin_lifecycle.py", text)
        self.assertNotIn("matrix.source", text)
        self.assertNotRegex(text, r"(?m)^\s*-\s+master\s*$")
        self.assertNotRegex(text, r"--branch\s+[\"']?v?\d+\.\d+\.\d+")
        self.assertNotRegex(
            text,
            r"ASTRBOT_VERSION\s*:\s*[\"']?v?\d+\.\d+\.\d+",
        )


if __name__ == "__main__":
    unittest.main()
