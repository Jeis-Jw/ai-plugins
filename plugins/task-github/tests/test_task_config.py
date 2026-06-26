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


if __name__ == "__main__":
    unittest.main()
