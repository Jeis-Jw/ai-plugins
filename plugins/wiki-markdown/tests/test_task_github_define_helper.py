import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "task-github" / "skills" / "define" / "scripts" / "create_issue_tree.py"


class TaskGithubDefineHelperTests(unittest.TestCase):
    def test_dry_run_plans_parented_children_and_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "issue_tree.json"
            spec.write_text(
                json.dumps(
                    {
                        "root": {
                            "title": "Root work",
                            "body": "Root body",
                        },
                        "children": [
                            {
                                "key": "U1",
                                "title": "Unit 1",
                                "body": "Unit 1 body",
                                "blocked_by": [],
                            },
                            {
                                "key": "U2",
                                "title": "Unit 2",
                                "body": "Unit 2 body",
                                "blocked_by": ["U1"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec", str(spec), "--dry-run", "--json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parent_method"], "graphql_create_issue_parentIssueId")
        self.assertEqual(payload["dependency_api_version"], "2026-03-10")
        self.assertEqual([child["key"] for child in payload["children"]], ["U1", "U2"])
        self.assertEqual(payload["dependencies"], [{"child": "U2", "blocked_by": "U1"}])

    def test_dry_run_rejects_unknown_dependency_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "issue_tree.json"
            spec.write_text(
                json.dumps(
                    {
                        "root": {"title": "Root", "body": "Root body"},
                        "children": [
                            {"key": "U1", "title": "Unit 1", "body": "body", "blocked_by": ["U0"]}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec", str(spec), "--dry-run", "--json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error_code"], "unknown_dependency")


if __name__ == "__main__":
    unittest.main()
