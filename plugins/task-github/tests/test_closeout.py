import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "merge" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import closeout  # noqa: E402


class ParseLinkedIssueTests(unittest.TestCase):
    def test_closes(self):
        self.assertEqual(closeout.parse_linked_issue("Closes #42\n\nbody"), 42)

    def test_fixes_and_resolves_case_insensitive(self):
        self.assertEqual(closeout.parse_linked_issue("fixes #7"), 7)
        self.assertEqual(closeout.parse_linked_issue("RESOLVES #9"), 9)

    def test_first_wins(self):
        self.assertEqual(closeout.parse_linked_issue("Closes #1 and closes #2"), 1)

    def test_none_when_absent(self):
        self.assertIsNone(closeout.parse_linked_issue("no linkage here #notnum"))
        self.assertIsNone(closeout.parse_linked_issue(""))

    def test_ignores_bare_hash_without_keyword(self):
        self.assertIsNone(closeout.parse_linked_issue("see #15 for context"))


class ExtractTaskIdTests(unittest.TestCase):
    def test_ascii_slug(self):
        body = "## Wiki Context\nTASK-2026-06-19-105638-session-review-plugin\n"
        self.assertEqual(closeout.extract_task_id(body),
                         "TASK-2026-06-19-105638-session-review-plugin")

    def test_korean_slug_preserved(self):
        # The ASCII-only grep in the old SKILL truncated Korean slugs; we must not.
        tid = "TASK-2026-06-19-125723-wiki-markdown-운용-효율-개선-문서-오버헤드-감소"
        self.assertEqual(closeout.extract_task_id(f"## Wiki Context\nroot: {tid} (done)"), tid)

    def test_stops_at_markdown_bracket(self):
        self.assertEqual(closeout.extract_task_id("## Wiki Context\n[[TASK-2026-06-19-120000-abc]]"),
                         "TASK-2026-06-19-120000-abc")

    def test_stops_at_trailing_punctuation(self):
        self.assertEqual(closeout.extract_task_id("## Wiki Context\ndone: TASK-2026-06-19-120000-abc."),
                         "TASK-2026-06-19-120000-abc")
        self.assertEqual(closeout.extract_task_id("## Wiki Context\nTASK-2026-06-19-120000-abc, next"),
                         "TASK-2026-06-19-120000-abc")

    def test_none_when_absent(self):
        self.assertIsNone(closeout.extract_task_id("no task here"))

    def test_none_outside_wiki_context(self):
        self.assertIsNone(closeout.extract_task_id("## Notes\nTASK-2026-06-19-120000-abc"))


class LabelsToRemoveTests(unittest.TestCase):
    def test_intersection_in_order(self):
        self.assertEqual(
            closeout.labels_to_remove(["gear:major", "changes-requested", "in-review"]),
            ["in-review", "changes-requested"])

    def test_preserves_non_state(self):
        self.assertEqual(closeout.labels_to_remove(["gear:micro", "bug"]), [])

    def test_empty(self):
        self.assertEqual(closeout.labels_to_remove([]), [])


class MergeSimulationTests(unittest.TestCase):
    def test_simulation_requires_checks_drift_and_integrity(self):
        result = closeout.evaluate_merge_simulation(
            required_checks=["python3 -m pytest plugins/task-github/tests/ -q"],
            check_results=[
                {
                    "command": "python3 -m pytest plugins/task-github/tests/ -q",
                    "returncode": 0,
                }
            ],
            drift_report={"issues": []},
            integrity_report={"ok": True},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["failed"], [])

    def test_simulation_blocks_missing_check_drift_and_integrity(self):
        result = closeout.evaluate_merge_simulation(
            required_checks=["unit"],
            check_results=[],
            drift_report={"issues": [{"id": "stale"}]},
            integrity_report={"ok": False, "issues": [{"id": "broken"}]},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            [failure["code"] for failure in result["failed"]],
            ["required_check_missing", "changed_path_stale", "integrity_failed"],
        )

    def test_simulation_blocks_missing_evidence_and_empty_checks(self):
        result = closeout.evaluate_merge_simulation(
            required_checks=[],
            check_results=[],
            drift_report=None,
            integrity_report=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            [failure["code"] for failure in result["failed"]],
            ["required_checks_empty", "drift_evidence_missing", "integrity_evidence_missing"],
        )

    def test_explicit_skip_evidence_is_accepted(self):
        result = closeout.evaluate_merge_simulation(
            required_checks=[["python3", "-m", "unittest"]],
            check_results=[{"command": ["python3", "-m", "unittest"], "returncode": 0}],
            drift_report={"skipped": True, "reason": "wiki_unavailable"},
            integrity_report={"skipped": True, "reason": "wiki_unavailable"},
        )

        self.assertTrue(result["ok"])


class LeafPolicyTests(unittest.TestCase):
    def test_major_adds_self_flow(self):
        result = closeout.leaf_policy_requirements({"risk_class": "major"})

        self.assertEqual(result["risk_class"], "major")
        self.assertIn("self-flow", result["required_gates"])

    def test_hard_risks_force_pr_or_hard_self_flow(self):
        for risk in ["irreversible", "db", "public-api", "security", "data-loss"]:
            with self.subTest(risk=risk):
                result = closeout.leaf_policy_requirements({"risk_class": risk})
                self.assertIn("pr-or-hard-self-flow", result["required_gates"])

    def test_hard_risk_blocks_local_without_hard_self_flow(self):
        failures = closeout.leaf_policy_failures(
            {"risk_class": "db"},
            {"closeout_mode": "local"},
        )

        self.assertEqual([failure["code"] for failure in failures], ["hard_self_flow_required"])

    def test_major_blocks_local_without_self_flow(self):
        failures = closeout.leaf_policy_failures(
            {"risk_class": "major"},
            {"closeout_mode": "local"},
        )

        self.assertEqual([failure["code"] for failure in failures], ["self_flow_required"])

    def test_leaf_policy_accepts_evidence_inside_policy(self):
        self.assertEqual(
            closeout.leaf_policy_failures(
                {"risk_class": "major", "self_flow_verified": True},
                {"closeout_mode": "local"},
            ),
            [],
        )
        self.assertEqual(
            closeout.leaf_policy_failures(
                {"risk_class": "security", "hard_self_flow_verified": True},
                {"closeout_mode": "local"},
            ),
            [],
        )

    def test_safe_required_checks_reject_contract_strings(self):
        with self.assertRaises(closeout.CloseoutError) as ctx:
            closeout.contract_required_checks({"required_checks": ["python3 -m unittest"]}, [])

        self.assertEqual(ctx.exception.code, "unsafe_required_check")

    def test_safe_required_checks_accept_argv_arrays_and_cli_extras(self):
        checks = closeout.contract_required_checks(
            {"required_checks": [["python3", "-m", "unittest"]]},
            ["python3 -m pytest"],
        )

        self.assertEqual(checks, [["python3", "-m", "unittest"], ["python3", "-m", "pytest"]])


class IntegrationLedgerTests(unittest.TestCase):
    def test_render_and_parse_ledger_event(self):
        comment = closeout.render_integration_ledger_comment({
            "leaf": 42,
            "sha": "abc123",
            "checks": [{"command": "unit", "returncode": 0}],
            "drift": {"issues": []},
            "downstream": [{"number": 43, "title": "next"}],
        })

        events = closeout.parse_integration_ledger_events([{"body": comment}])

        self.assertEqual(events[0]["schema_version"], 1)
        self.assertEqual(events[0]["leaf"], 42)
        self.assertEqual(events[0]["sha"], "abc123")

    def test_issue_close_already_closed_is_ok(self):
        self.assertTrue(closeout.issue_close_failure_is_ok("GraphQL: already closed"))
        self.assertTrue(closeout.issue_close_failure_is_ok("issue is not open"))
        self.assertFalse(closeout.issue_close_failure_is_ok("permission denied"))


if __name__ == "__main__":
    unittest.main()
