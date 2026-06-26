import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import context_bundle  # noqa: E402


class ContextBundleTests(unittest.TestCase):
    def test_leaf_resolves_root_task_and_link_invariants(self):
        leaf = {
            "number": 42,
            "title": "leaf",
            "state": "OPEN",
            "body": "leaf body",
            "labels": [{"name": "gear:normal"}],
        }
        root = {
            "number": 10,
            "title": "root",
            "state": "OPEN",
            "body": (
                "## Wiki Context\n"
                "**메인**: [[TASK-2026-06-26-024108-task-github-개선]]\n"
            ),
            "labels": [{"name": "gear:normal"}],
        }
        task = {
            "id": "TASK-2026-06-26-024108-task-github-개선",
            "path": "wiki/task/TASK-2026-06-26-024108-task-github-개선.md",
            "relations": {"tasks": ["jin/ai-plugins#10"]},
        }

        bundle = context_bundle.build_context_bundle(
            issue=leaf,
            root=root,
            owner="jin",
            repo="ai-plugins",
            wiki_task_record=task,
            blockers=[{"number": 41, "state": "CLOSED", "title": "done"}],
            downstream=[{"number": 43, "state": "OPEN", "title": "next"}],
            worktree_path=".worktrees/issue-42",
        )

        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["owner"], "jin")
        self.assertEqual(bundle["repo"], "ai-plugins")
        self.assertEqual(bundle["issue"]["number"], 42)
        self.assertEqual(bundle["root"]["number"], 10)
        self.assertEqual(bundle["wiki_task"]["id"], task["id"])
        self.assertEqual(bundle["blockers"][0]["number"], 41)
        self.assertEqual(bundle["downstream"][0]["number"], 43)
        self.assertEqual(bundle["worktree_path"], ".worktrees/issue-42")
        self.assertIsNone(bundle["topology"])
        self.assertIsNone(bundle["gate"])
        self.assertIsNone(bundle["parent_branch"])
        self.assertEqual(bundle["default_source"], "profile+gear")
        self.assertEqual(bundle["integrity"]["errors"], [])

    def test_reports_missing_root_task_link(self):
        root = {"number": 10, "state": "OPEN", "body": "no wiki context"}

        bundle = context_bundle.build_context_bundle(
            issue=root,
            root=root,
            owner="jin",
            repo="ai-plugins",
        )

        self.assertFalse(bundle["ok"])
        self.assertEqual(bundle["wiki_task"], None)
        self.assertEqual(bundle["integrity"]["errors"][0]["code"], "missing_root_wiki_task")

    def test_reports_task_relation_and_state_mismatch(self):
        root = {
            "number": 10,
            "state": "CLOSED",
            "body": "## Wiki Context\n[[TASK-2026-06-26-024108-task-github-개선]]",
        }
        task = {
            "id": "TASK-2026-06-26-024108-task-github-개선",
            "path": "wiki/task/TASK-2026-06-26-024108-task-github-개선.md",
            "relations": {"tasks": ["jin/ai-plugins#999"]},
        }

        bundle = context_bundle.build_context_bundle(
            issue=root,
            root=root,
            owner="jin",
            repo="ai-plugins",
            wiki_task_record=task,
        )

        self.assertFalse(bundle["ok"])
        self.assertEqual(
            [err["code"] for err in bundle["integrity"]["errors"]],
            ["task_relation_missing_root", "root_closed_task_active"],
        )

    def test_ignores_task_mentions_outside_wiki_context(self):
        root = {
            "number": 10,
            "state": "OPEN",
            "body": (
                "## Notes\n"
                "[[TASK-2026-06-26-024108-task-github-개선]]\n"
            ),
        }

        bundle = context_bundle.build_context_bundle(issue=root, root=root)

        self.assertFalse(bundle["ok"])
        self.assertIsNone(bundle["wiki_task"])
        self.assertEqual(bundle["integrity"]["errors"][0]["code"], "missing_root_wiki_task")


if __name__ == "__main__":
    unittest.main()
