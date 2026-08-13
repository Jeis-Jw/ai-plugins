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
                self.assertIn("task-worker", text)
                self.assertIn("dispatch: manual", text)
                self.assertIn("ready-set parallelism", text)
                self.assertIn("Rationale commits", text)
                self.assertIn("Verified_at hygiene", text)
                self.assertIn("name the comparison method", text)

    def test_scaffold_includes_proactive_context_contract_without_capture_gear_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy("--target", "claude", "--json", cwd=tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (Path(tmp) / "CLAUDE.md").read_text()
            self.assertIn("Durable context lifecycle", text)
            self.assertIn("one scoped wiki recall", text)
            self.assertIn("semantic milestone or closeout", text)
            self.assertIn("Finish the original task and primary answer first", text)
            self.assertIn("existing context for an internal candidate audit", text)
            self.assertIn("Only when genuine durable candidates exist", text)
            self.assertIn("bottom of the same final answer", text)
            self.assertIn("otherwise add no user-facing audit, status, or `none` text", text)
            self.assertIn("all wiki writes", text)
            self.assertIn("Knowledge value", text)
            self.assertIn("not task size", text)
            self.assertIn("refresh once", text)
            self.assertNotIn("Scale capture to the gear", text)
            self.assertNotIn("audit none by default", text)

    def test_scaffold_includes_ceremony_scaling(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy("--target", "claude", "--json", cwd=tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (Path(tmp) / "CLAUDE.md").read_text()
            self.assertIn("Ceremony scales to blast radius", text)
            self.assertIn("bundle for shipping", text)
            self.assertIn("rollback unit", text)

    def test_proactive_context_contract_does_not_require_external_tracker(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy(
                "--target", "codex", "--tracker", "none", "--json", cwd=tmp
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (Path(tmp) / "AGENTS.md").read_text()
            self.assertIn("No external task tracker is bound", text)
            self.assertIn("one scoped wiki recall", text)
            self.assertIn("Finish the original task and primary answer first", text)
            self.assertIn("Only when genuine durable candidates exist", text)

    def test_checked_in_policy_uses_the_scaffolded_capture_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_policy("--target", "all", "--json", cwd=tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = (Path(tmp) / "AGENTS.md").read_text()
            lifecycle = next(
                line for line in generated.splitlines() if line.startswith("- Durable context lifecycle:")
            )
            repo = ROOT.parents[1]
            for name in ("AGENTS.md", "CLAUDE.md"):
                self.assertIn(lifecycle, (repo / name).read_text())

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
