import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import task_config  # noqa: E402


class TaskConfigTests(unittest.TestCase):
    def test_parse_tool_and_orchestrate_commands(self):
        cfg = task_config.parse_config("""
mode: solo
base_branch: main
planning-tool:
verify-tool: session-review:request-review
review-tool: session-review:request-review
orchestrate:
  verify-command: "self turnkey"
  review-mode: gear
  review-command: "self turnkey"
""")

        self.assertEqual(cfg["mode"], "solo")
        self.assertEqual(cfg["base_branch"], "main")
        self.assertIsNone(cfg["planning-tool"])
        self.assertEqual(cfg["verify-tool"], "session-review:request-review")
        self.assertEqual(cfg["orchestrate"]["review-command"], "self turnkey")

    def test_validate_requires_base_branch_and_review_mode(self):
        findings = task_config.validate_config({
            "mode": "solo",
            "orchestrate": {"review-mode": "sometimes"},
        })

        self.assertEqual(
            [finding["code"] for finding in findings],
            ["base_branch_required", "bad_orchestrate_review_mode"],
        )

    def test_command_requires_matching_tool(self):
        findings = task_config.validate_config({
            "mode": "solo",
            "base_branch": "main",
            "orchestrate": {
                "review-mode": "gear",
                "verify-command": "self turnkey",
                "review-command": "self turnkey",
            },
        })

        self.assertEqual(
            [finding["code"] for finding in findings],
            ["verify_tool_required", "review_tool_required"],
        )

    def test_scaffold_contains_required_keys(self):
        text = task_config.render_default_config(base_branch="main")

        cfg = task_config.parse_config(text)

        self.assertEqual(task_config.validate_config(cfg), [])
        self.assertIn("verify-command", cfg["orchestrate"])
        self.assertIn("review-command", cfg["orchestrate"])

    def test_get_returns_value_or_exit_one(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".task-github.yml"
            path.write_text(task_config.render_default_config(base_branch="develop"), encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = task_config.main(["get", "base_branch", "--path", str(path)])
            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), "develop")

            # absent file → exit 1, no output (caller falls back to main)
            self.assertEqual(task_config.main(["get", "base_branch", "--path", str(Path(tmp) / "none.yml")]), 1)
            # missing key → exit 1
            self.assertEqual(task_config.main(["get", "nope", "--path", str(path)]), 1)


if __name__ == "__main__":
    unittest.main()
