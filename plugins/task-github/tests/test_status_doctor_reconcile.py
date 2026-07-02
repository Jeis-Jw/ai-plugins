import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import doctor  # noqa: E402
import reconcile  # noqa: E402
import status_next  # noqa: E402


class StatusNextTests(unittest.TestCase):
    def test_bridge_mismatch_is_first_next_action(self):
        bundle = {
            "issue": {"number": 42, "state": "OPEN"},
            "root": {"number": 10, "state": "OPEN"},
            "integrity": {"errors": [{"code": "task_relation_missing_root"}], "warnings": []},
            "blockers": [],
            "downstream": [],
            "topology": "stacked",
            "gate": "pr",
        }

        result = status_next.build_status(bundle)

        self.assertEqual(result["next_action"]["kind"], "reconcile")
        self.assertEqual(result["mode"], {"topology": "stacked", "gate": "pr"})

    def test_ready_leaf_suggests_start(self):
        bundle = {
            "issue": {"number": 42, "state": "OPEN", "labels": []},
            "root": {"number": 10, "state": "OPEN"},
            "integrity": {"errors": [], "warnings": []},
            "blockers": [],
            "downstream": [],
            "topology": None,
            "gate": None,
        }

        result = status_next.build_status(bundle)

        self.assertEqual(result["next_action"], {"kind": "start", "issue": 42})


class DoctorTests(unittest.TestCase):
    def test_doctor_is_diagnose_only_by_default(self):
        snapshot = {
            "prereq": {
                "labels": {"missing": ["gear:major"]},
                "gh_auth": {"ok": True},
                "dependency_api": {"ok": False},
                "worktrees_ignored": False,
            },
            "context_bundle": {
                "integrity": {"errors": [{"code": "missing_root_wiki_task"}], "warnings": []}
            },
        }

        result = doctor.diagnose(snapshot)

        self.assertFalse(result["ok"])
        self.assertFalse(result["mutation_allowed"])
        self.assertEqual(
            [item["code"] for item in result["findings"]],
            ["missing_labels", "dependency_api_unavailable", "worktrees_not_ignored", "missing_root_wiki_task"],
        )

    def test_doctor_fix_plans_reconcile_actions(self):
        snapshot = {
            "context_bundle": {
                "owner": "jin",
                "repo": "ai-plugins",
                "root": {"number": 10},
                "wiki_task": {"id": "TASK-2026-06-26-024108-task-github-개선"},
                "integrity": {"errors": [{"code": "root_closed_task_active"}], "warnings": []},
            }
        }

        result = doctor.fix(snapshot, apply=False)

        self.assertFalse(result["applied"])
        self.assertEqual(
            result["actions"][0]["argv"],
            ["wiki", "complete", "TASK-2026-06-26-024108-task-github-개선"],
        )

    def test_doctor_reports_task_config_errors(self):
        snapshot = {
            "task_config": {
                "mode": "solo",
                "orchestrate": {"review-mode": "sometimes"},
            }
        }

        result = doctor.diagnose(snapshot)

        self.assertFalse(result["ok"])
        self.assertEqual(
            [item["code"] for item in result["findings"]],
            ["base_branch_required", "bad_orchestrate_review_mode"],
        )


class ReconcileTests(unittest.TestCase):
    def test_reconcile_plans_wiki_cli_actions_without_applying(self):
        bundle = {
            "owner": "jin",
            "repo": "ai-plugins",
            "root": {"number": 10},
            "wiki_task": {"id": "TASK-2026-06-26-024108-task-github-개선"},
            "integrity": {
                "errors": [
                    {"code": "task_relation_missing_root"},
                    {"code": "root_closed_task_active"},
                ],
                "warnings": [],
            },
        }

        result = reconcile.reconcile(bundle, apply=False)

        self.assertFalse(result["applied"])
        self.assertEqual(
            [action["argv"] for action in result["actions"]],
            [
                ["wiki", "relate", "TASK-2026-06-26-024108-task-github-개선", "--add-tasks", "jin/ai-plugins#10"],
                ["wiki", "complete", "TASK-2026-06-26-024108-task-github-개선"],
            ],
        )

    def test_reconcile_apply_does_not_treat_manual_action_as_success(self):
        bundle = {
            "root": {"number": 10},
            "wiki_task": {"id": "TASK-2026-06-26-024108-task-github-개선"},
            "integrity": {"errors": [{"code": "task_relation_missing_root"}], "warnings": []},
        }

        result = reconcile.reconcile(bundle, apply=True)

        self.assertTrue(result["applied"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["results"][0]["skipped"])


if __name__ == "__main__":
    unittest.main()
