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


if __name__ == "__main__":
    unittest.main()
