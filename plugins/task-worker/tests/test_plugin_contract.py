import json
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]


class PluginContractTests(unittest.TestCase):
    def test_manifests_and_public_skills_are_aligned(self):
        claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())

        self.assertEqual(claude["name"], "task-worker")
        self.assertEqual(claude["version"], codex["version"])
        self.assertEqual(codex["skills"], "./skills/")
        for name in ("define", "start", "run", "verify", "done", "status", "orchestrate"):
            self.assertTrue((PLUGIN / "skills" / name / "SKILL.md").exists(), name)

    def test_runtime_has_no_github_or_studio_execution_dependency(self):
        source = (PLUGIN / "scripts" / "definition_artifact.py").read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import requests", "gh api", "gh issue", "studio.py"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_orchestrate_contract_preserves_ready_set_parallelism(self):
        text = (PLUGIN / "skills" / "orchestrate" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ready_actions[]", text)
        self.assertIn("병렬", text)
        self.assertIn("별도 worktree", text)
        self.assertIn("integration", text)


if __name__ == "__main__":
    unittest.main()
