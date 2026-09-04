"""CI plugin load workflow 的 required status check 命名契约。"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LIFECYCLE_WORKFLOW = WORKFLOWS / "plugin-lifecycle.yml"
LEGACY_WORKFLOW = WORKFLOWS / "plugin-load.yml"


class PluginLoadWorkflowContractTests(unittest.TestCase):
    def test_workflow_uses_required_plugin_load_check_names(self) -> None:
        self.assertTrue(
            LIFECYCLE_WORKFLOW.is_file(),
            "生命周期 CI 应使用 .github/workflows/plugin-lifecycle.yml",
        )
        self.assertFalse(
            LEGACY_WORKFLOW.exists(),
            "旧 plugin-load.yml 应继续移除，避免同一检查重复触发",
        )

        text = LIFECYCLE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: AstrBot plugin load", text)
        self.assertIn("AstrBot plugin load (${{ matrix.source }})", text)
        self.assertIn("matrix.source", text)
        self.assertRegex(text, r"(?m)^\s*-\s+stable\s*$")
        self.assertRegex(text, r"(?m)^\s*-\s+master\s*$")
        self.assertIn('if [[ "$SOURCE_KIND" == "stable" ]]', text)
        self.assertIn('elif [[ "$SOURCE_KIND" == "master" ]]', text)
        self.assertIn("select_latest_stable_version", text)
        self.assertIn("check_astrbot_plugin_lifecycle.py", text)
        self.assertNotIn("AstrBot plugin lifecycle (latest stable)", text)
        self.assertNotRegex(text, r"--branch\s+[\"']?v?\d+\.\d+\.\d+")
        self.assertNotRegex(
            text,
            r"ASTRBOT_VERSION\s*:\s*[\"']?v?\d+\.\d+\.\d+",
        )


if __name__ == "__main__":
    unittest.main()
