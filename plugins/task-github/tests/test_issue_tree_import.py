import tempfile
import unittest
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue_tree_import  # noqa: E402


def tree_fixture():
    return {
        "number": 10,
        "title": "Root delivery",
        "body": "Root acceptance criteria",
        "state": "OPEN",
        "labels": [],
        "open_blockers": [],
        "children": [
            {
                "number": 11,
                "title": "Already shipped",
                "body": "done",
                "state": "CLOSED",
                "labels": [],
                "open_blockers": [],
                "children": [],
            },
            {
                "number": 12,
                "title": "External implementation",
                "body": "## 영향 경로\n- `src/mobile/**`\n\n## 완료 조건\n- passes",
                "state": "OPEN",
                "labels": [],
                "open_blockers": [],
                "children": [],
            },
        ],
    }


class IssueTreeImportTests(unittest.TestCase):
    def test_build_preserves_tree_content_and_remote_status(self):
        spec, graph, context, provider = issue_tree_import.build_import(
            tree_fixture(), owner="acme", repo="app", dispatch="manual"
        )

        self.assertEqual(spec["definition_id"], "github-acme-app-issue-10")
        self.assertEqual(spec["dispatch"], "manual")
        self.assertEqual(spec["children"][1]["affects_paths"], ["src/mobile/**"])
        self.assertEqual(graph["nodes"][1]["status"], "completed")
        self.assertEqual(provider["nodes"]["issue-12"], 12)
        self.assertEqual(context["source"]["root_issue"], 10)

    def test_manual_import_materializes_binding_and_never_dispatches_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = issue_tree_import.materialize(
                tree_fixture(), owner="acme", repo="app", dispatch="manual",
                state_root=Path(tmp) / "state",
            )

        self.assertEqual(result["artifact"]["dispatch"], "manual")
        self.assertEqual(result["plan"]["ready_actions"], [])
        self.assertEqual([item["node_id"] for item in result["plan"]["manual_actions"]], ["12"])

    def test_worker_import_exposes_only_current_ready_leaves(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = issue_tree_import.materialize(
                tree_fixture(), owner="acme", repo="app", dispatch="worker",
                state_root=Path(tmp) / "state",
            )

        self.assertEqual([item["node_id"] for item in result["plan"]["ready_actions"]], ["12"])
        self.assertEqual(result["plan"]["integration_candidates"], [])

    def test_reimport_same_tree_reuses_definition_revision_and_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            first = issue_tree_import.materialize(
                tree_fixture(), owner="acme", repo="app", dispatch="manual",
                state_root=state_root,
            )
            second = issue_tree_import.materialize(
                tree_fixture(), owner="acme", repo="app", dispatch="manual",
                state_root=state_root,
            )

        self.assertEqual(first["artifact"]["revision"], 1)
        self.assertEqual(second["artifact"]["revision"], 1)
        self.assertEqual(first["artifact"]["digest"], second["artifact"]["digest"])


if __name__ == "__main__":
    unittest.main()
