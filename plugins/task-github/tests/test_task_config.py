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
  gear-options:
    micro:
      plan: false
      verify: true
      pr-review: false
    normal:
      plan: true
      verify: o
      pr-review: x
""")

        self.assertEqual(cfg["mode"], "solo")
        self.assertEqual(cfg["base_branch"], "main")
        self.assertIsNone(cfg["planning-tool"])
        self.assertEqual(cfg["verify-tool"], "session-review:request-review")
        self.assertEqual(cfg["orchestrate"]["review-command"], "self turnkey")
        self.assertFalse(cfg["orchestrate"]["gear-options"]["micro"]["plan"])
        self.assertEqual(cfg["orchestrate"]["gear-options"]["normal"]["verify"], "o")

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

    def test_validate_gear_options(self):
        findings = task_config.validate_config({
            "mode": "solo",
            "base_branch": "main",
            "orchestrate": {
                "review-mode": "gear",
                "gear-options": {
                    "micro": {"plan": "x", "verify": "o", "pr-review": False},
                    "major": {"plan": "maybe"},
                    "huge": {"plan": True},
                },
            },
        })

        self.assertEqual(
            [finding["code"] for finding in findings],
            ["bad_orchestrate_gear_option", "unknown_orchestrate_gear"],
        )

    def test_validate_max_workers(self):
        findings = task_config.validate_config({
            "mode": "solo",
            "base_branch": "main",
            "orchestrate": {"review-mode": "gear", "max-workers": "0"},
        })
        self.assertEqual([f["code"] for f in findings], ["bad_orchestrate_max_workers"])

        findings = task_config.validate_config({
            "mode": "solo",
            "base_branch": "main",
            "orchestrate": {"review-mode": "gear", "max-workers": "not-a-number"},
        })
        self.assertEqual([f["code"] for f in findings], ["bad_orchestrate_max_workers"])

        findings = task_config.validate_config({
            "mode": "solo",
            "base_branch": "main",
            "orchestrate": {"review-mode": "gear", "max-workers": "3"},
        })
        self.assertEqual(findings, [])

        findings = task_config.validate_config({
            "mode": "solo",
            "base_branch": "main",
            "orchestrate": {"review-mode": "gear"},
        })
        self.assertEqual(findings, [])

    def test_scaffold_contains_required_keys(self):
        text = task_config.render_default_config(base_branch="main")

        cfg = task_config.parse_config(text)

        self.assertEqual(task_config.validate_config(cfg), [])
        self.assertIn("max-workers", cfg["orchestrate"])
        self.assertIn("verify-command", cfg["orchestrate"])
        self.assertIn("review-command", cfg["orchestrate"])
        self.assertTrue(cfg["orchestrate"]["gear-options"]["major"]["pr-review"])

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
