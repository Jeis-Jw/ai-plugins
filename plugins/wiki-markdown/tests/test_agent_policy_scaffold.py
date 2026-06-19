import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "agent-policy" / "scripts" / "scaffold_agent_policy.py"


def run_policy(*args, cwd=None):
    command = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class AgentPolicyScaffoldTests(unittest.TestCase):
    def test_scaffold_creates_claude_and_agents_without_touching_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy(
                "--target",
                "all",
                "--profile",
                "solo",
                "--tracker",
                "task-github",
                "--concurrency",
                "worktree",
                "--json",
                cwd=tmp,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["ok"], True)

            claude = Path(tmp) / "CLAUDE.md"
            agents = Path(tmp) / "AGENTS.md"
            self.assertTrue(claude.exists())
            self.assertTrue(agents.exists())
            self.assertFalse((Path(tmp) / "wiki" / "ssot" / "agent-operating-model.md").exists())

            for path in (claude, agents):
                text = path.read_text()
                self.assertEqual(text.count("BEGIN agent-operating-policy"), 1)
                self.assertIn("Profile: solo", text)
                self.assertIn("Use git worktrees for concurrent tasks", text)
                self.assertIn("task-github", text)
                self.assertIn("Rationale commits", text)

    def test_scaffold_includes_capture_threshold_and_gear_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy("--target", "claude", "--json", cwd=tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (Path(tmp) / "CLAUDE.md").read_text()
            self.assertIn("Capture threshold", text)
            self.assertIn("refresh once", text)
            self.assertIn("gear:micro", text)
            self.assertIn("gear:major", text)

    def test_scaffold_is_idempotent_and_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude = Path(tmp) / "CLAUDE.md"
            claude.write_text("# Project Notes\n\nKeep this line.\n")

            first = run_policy("--target", "claude", "--profile", "team", "--json", cwd=tmp)
            second = run_policy("--target", "claude", "--profile", "team", "--json", cwd=tmp)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            text = claude.read_text()
            self.assertIn("Keep this line.", text)
            self.assertEqual(text.count("BEGIN agent-operating-policy"), 1)
            self.assertIn("Profile: team", text)

    def test_scaffold_all_is_idempotent_for_both_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = run_policy("--target", "all", "--json", cwd=tmp)
            second = run_policy("--target", "all", "--json", cwd=tmp)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            payload = json.loads(second.stdout)
            statuses = {action["path"]: action["status"] for action in payload["actions"]}
            self.assertEqual(statuses["CLAUDE.md"], "unchanged")
            self.assertEqual(statuses["AGENTS.md"], "unchanged")

    def test_dry_run_reports_actions_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy("--target", "codex", "--dry-run", "--json", cwd=tmp)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["ok"], True)
            self.assertEqual(payload["actions"][0]["path"], "AGENTS.md")
            self.assertFalse((Path(tmp) / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
