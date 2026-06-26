import sys
import unittest
from pathlib import Path

TASK_GITHUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_GITHUB / "scripts"))
sys.path.insert(0, str(TASK_GITHUB / "skills" / "define" / "scripts"))

import context_bundle  # noqa: E402
import create_issue_tree  # noqa: E402


class ExecutionContractTests(unittest.TestCase):
    def test_contract_round_trip_ignores_unknown_keys(self):
        block = context_bundle.render_execution_contract({
            "wiki_task": "TASK-2026-06-26-024108-task-github-개선",
            "topology": "stacked",
            "gate": "local-merge",
            "parent_branch": "task/root-10",
            "leaf_policy": {"risk_class": "normal"},
            "required_checks": [["python3", "-m", "pytest", "plugins/task-github/tests/", "-q"]],
            "closeout_mode": "local",
            "future_key": "ignored",
        })

        parsed = context_bundle.parse_execution_contract("body\n" + block)

        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["topology"], "stacked")
        self.assertEqual(parsed["gate"], "local-merge")
        self.assertEqual(parsed["parent_branch"], "task/root-10")
        self.assertNotIn("future_key", parsed)
        self.assertEqual(
            sorted(parsed.keys()),
            sorted(["schema_version", *context_bundle.EXECUTION_CONTRACT_KEYS]),
        )

    def test_bundle_reads_contract_from_root_body(self):
        contract = context_bundle.render_execution_contract({
            "topology": "flat",
            "gate": "pr",
            "parent_branch": "main",
            "closeout_mode": "pr",
        })
        root = {
            "number": 10,
            "state": "OPEN",
            "body": "## Wiki Context\n[[TASK-2026-06-26-024108-task-github-개선]]\n" + contract,
        }

        bundle = context_bundle.build_context_bundle(issue=root, root=root)

        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["topology"], "flat")
        self.assertEqual(bundle["gate"], "pr")
        self.assertEqual(bundle["parent_branch"], "main")
        self.assertIsNone(bundle["default_source"])
        self.assertEqual(bundle["execution_contract"]["closeout_mode"], "pr")

    def test_create_issue_tree_materializes_root_execution_contract(self):
        spec = {
            "root": {
                "title": "root",
                "body": "## Wiki Context\n[[TASK-2026-06-26-024108-task-github-개선]]",
                "execution_contract": {
                    "topology": "stacked",
                    "gate": "local-merge",
                    "parent_branch": "task/root-10",
                    "closeout_mode": "local",
                },
            },
            "children": [],
        }

        validated = create_issue_tree.validate_spec(spec)

        parsed = context_bundle.parse_execution_contract(validated["root"]["body"])
        self.assertEqual(parsed["topology"], "stacked")
        self.assertEqual(parsed["gate"], "local-merge")


if __name__ == "__main__":
    unittest.main()
