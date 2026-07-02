import sys
import unittest
from pathlib import Path

TASK_GITHUB = Path(__file__).resolve().parents[1]
ORCH_SCRIPTS = TASK_GITHUB / "skills" / "orchestrate" / "scripts"
MERGE_SCRIPTS = TASK_GITHUB / "skills" / "merge" / "scripts"
sys.path.insert(0, str(ORCH_SCRIPTS))
sys.path.insert(0, str(MERGE_SCRIPTS))

import merge_preflight  # noqa: E402
import orchestrator_ops  # noqa: E402


def gate(paths, **overrides):
    paths = orchestrator_ops.canonical_path_list(paths)
    evidence = merge_preflight.build_gate_evidence(
        changed_paths=paths,
        checked_paths=paths,
        drift_report={"issues": []},
        pr_head_sha="head-1",
        tool_versions={"task-github": "0.15.0"},
    )
    evidence.update(overrides)
    return evidence


class MergePreflightEvidenceTests(unittest.TestCase):
    def test_build_gate_evidence_has_u2_required_fields(self):
        evidence = merge_preflight.build_gate_evidence(
            changed_paths=["b.py", "./a.py", "b.py"],
            checked_paths=["a.py", "b.py"],
            drift_report={"issues": []},
            pr_head_sha="head-1",
            tool_versions={"task-github": "0.15.0"},
            gate_version="changed-path-stale:v1",
        )

        self.assertEqual(evidence["changed_paths"], ["a.py", "b.py"])
        self.assertEqual(evidence["checked_paths"], ["a.py", "b.py"])
        self.assertEqual(evidence["changed_paths_hash"], orchestrator_ops.path_list_hash(["a.py", "b.py"]))
        self.assertEqual(evidence["checked_paths_hash"], orchestrator_ops.path_list_hash(["a.py", "b.py"]))
        self.assertEqual(evidence["changed_path_stale_issues"], [])
        self.assertEqual(evidence["pr_head_sha"], "head-1")
        self.assertEqual(evidence["tool_versions"], {"task-github": "0.15.0"})
        self.assertTrue(evidence["drift_surface_hash"])

    def test_required_gate_evidence_missing_field_is_stop(self):
        evidence = merge_preflight.build_gate_evidence(
            changed_paths=["a.py"],
            checked_paths=["a.py"],
            drift_report={"issues": []},
            pr_head_sha="head-1",
            tool_versions={"task-github": "0.15.0"},
            gate_version="changed-path-stale:v1",
        )
        del evidence["checked_paths_hash"]

        result = merge_preflight.validate_required_gate_evidence(evidence)

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "missing_gate_evidence_field")
        self.assertEqual(result["missing"], ["checked_paths_hash"])

    def test_pr_status_stops_on_head_drift(self):
        result = merge_preflight.validate_pr_status(
            {
                "headRefOid": "new-head",
                "mergeStateStatus": "CLEAN",
                "isDraft": False,
                "reviewDecision": "",
                "statusCheckRollup": [],
            },
            expected_head_oid="old-head",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "pr_head_mismatch")

    def test_pr_status_stops_on_failing_check(self):
        result = merge_preflight.validate_pr_status(
            {
                "headRefOid": "head-1",
                "mergeStateStatus": "CLEAN",
                "isDraft": False,
                "reviewDecision": "",
                "statusCheckRollup": [{"name": "unit", "conclusion": "FAILURE"}],
            },
            expected_head_oid="head-1",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "ci_check_failed")

    def test_pr_status_stops_on_unknown_mergeability(self):
        result = merge_preflight.validate_pr_status(
            {
                "headRefOid": "head-1",
                "mergeStateStatus": "UNKNOWN",
                "isDraft": False,
                "reviewDecision": "",
                "statusCheckRollup": [],
            },
            expected_head_oid="head-1",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "mergeability_not_clean")

    def test_decode_diff_path_decodes_git_quoted_utf8_octal(self):
        raw = r'"wiki/context/observation/OBS-\352\260\220.md"'

        self.assertEqual(
            merge_preflight.decode_diff_path(raw),
            "wiki/context/observation/OBS-감.md",
        )

    def test_build_preflight_evidence_keeps_closeout_view_and_status_covers(self):
        view = {
            "number": 7,
            "title": "change",
            "headRefName": "task/issue-7",
            "headRefOid": "head-1",
            "baseRefName": "main",
            "state": "OPEN",
            "body": "Closes #7",
            "labels": [{"name": "in-review"}],
            "isDraft": False,
            "mergeStateStatus": "CLEAN",
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [{"name": "unit", "conclusion": "SUCCESS"}],
        }
        status = {"ok": True, "headRefOid": "head-1"}

        evidence = merge_preflight.build_preflight_evidence(view, status)

        self.assertEqual(evidence["pr"], 7)
        self.assertEqual(evidence["view"]["headRefOid"], "head-1")
        self.assertEqual(evidence["view"]["labels"], [{"name": "in-review"}])
        self.assertEqual(evidence["status"], status)
        self.assertEqual(
            set(evidence["covers"]),
            {"mergeability", "ci_check", "review_decision", "head_sha"},
        )

    def test_scoped_gate_plan_reduces_child_paths_when_evidence_valid(self):
        child_gate = gate(["child.py"])
        ledger = {
            "issues": {"1": {"children": [2]}, "2": {"number": 2}},
            "merge_evidence": {
                "2": {
                    "kind": "merged_pr",
                    "base": "task/issue-1",
                    "parent_contains_child": True,
                    "head_sha": "head-1",
                }
            },
            "gate_evidence": {"2": child_gate},
        }

        plan = merge_preflight.scoped_gate_plan_from_ledger(
            parent_issue=1,
            expected_base="task/issue-1",
            changed_paths=["parent.py", "child.py"],
            ledger=ledger,
            current_gate_version=merge_preflight.GATE_VERSION,
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hashes={2: child_gate["drift_surface_hash"]},
            expected_pr_heads={2: "head-1"},
        )

        self.assertEqual(plan["target_paths"], ["parent.py"])
        self.assertLess(len(plan["target_paths"]), len(["parent.py", "child.py"]))
        self.assertEqual(plan["reused"], [2])
        self.assertEqual(plan["fallback"], [])

    def test_scoped_gate_plan_uses_parent_branch_for_root_pr_child_evidence(self):
        child_gate = gate(["child.py"])
        ledger = {
            "issues": {"1": {"children": [2]}, "2": {"number": 2}},
            "merge_evidence": {
                "2": {
                    "kind": "merged_pr",
                    "base": "task/issue-1",
                    "parent_contains_child": True,
                    "head_sha": "head-1",
                }
            },
            "gate_evidence": {"2": child_gate},
        }

        plan = merge_preflight.scoped_gate_plan_from_ledger(
            parent_issue=1,
            expected_base="main",
            changed_paths=["parent.py", "child.py"],
            ledger=ledger,
            current_gate_version=merge_preflight.GATE_VERSION,
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hashes={2: child_gate["drift_surface_hash"]},
            expected_pr_heads={2: "head-1"},
        )

        self.assertEqual(plan["target_paths"], ["parent.py"])
        self.assertEqual(plan["reused"], [2])

    def test_scoped_gate_plan_falls_back_on_invalid_child_evidence(self):
        child_gate = gate(["child.py"], tool_versions={"task-github": "0.14.0"})
        ledger = {
            "issues": {"1": {"children": [2]}, "2": {"number": 2}},
            "merge_evidence": {
                "2": {
                    "kind": "merged_pr",
                    "base": "task/issue-1",
                    "parent_contains_child": True,
                    "head_sha": "head-1",
                }
            },
            "gate_evidence": {"2": child_gate},
        }

        plan = merge_preflight.scoped_gate_plan_from_ledger(
            parent_issue=1,
            expected_base="task/issue-1",
            changed_paths=["parent.py", "child.py"],
            ledger=ledger,
            current_gate_version=merge_preflight.GATE_VERSION,
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hashes={2: child_gate["drift_surface_hash"]},
            expected_pr_heads={2: "head-1"},
        )

        self.assertEqual(plan["target_paths"], ["child.py", "parent.py"])
        self.assertEqual(len(plan["target_paths"]), len(["parent.py", "child.py"]))
        self.assertEqual(plan["fallback"][0]["reason"], "tool_version_mismatch")


if __name__ == "__main__":
    unittest.main()
