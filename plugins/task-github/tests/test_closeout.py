import sys
import unittest
import json
from datetime import datetime, timezone
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


class IssueCloseTests(unittest.TestCase):
    def test_issue_close_already_closed_is_ok(self):
        self.assertTrue(closeout.issue_close_failure_is_ok("GraphQL: already closed"))
        self.assertTrue(closeout.issue_close_failure_is_ok("issue is not open"))
        self.assertFalse(closeout.issue_close_failure_is_ok("permission denied"))


def preflight_evidence(**overrides):
    evidence = {
        "at": "2026-07-03T00:00:00Z",
        "pr": 7,
        "covers": ["mergeability", "ci_check", "review_decision", "head_sha"],
        "status": {"ok": True, "headRefOid": "head-1"},
        "view": {
            "number": 7,
            "headRefName": "task/issue-7",
            "headRefOid": "head-1",
            "baseRefName": "main",
            "state": "OPEN",
            "body": "Closes #7",
            "labels": [{"name": "in-review"}],
        },
    }
    evidence.update(overrides)
    return evidence


class PreflightReuseTests(unittest.TestCase):
    def test_fresh_same_pr_preflight_view_is_reusable(self):
        ledger = {"preflight_evidence": {"7": preflight_evidence()}}

        result = closeout.select_reusable_preflight_view(
            ledger,
            pr=7,
            now=datetime(2026, 7, 3, 0, 1, tzinfo=timezone.utc),
            ttl_seconds=180,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "ledger")
        self.assertEqual(result["view"]["headRefOid"], "head-1")
        self.assertEqual(result["match_head_commit"], "head-1")

    def test_expired_preflight_view_is_not_reusable(self):
        ledger = {"preflight_evidence": {"7": preflight_evidence()}}

        result = closeout.select_reusable_preflight_view(
            ledger,
            pr=7,
            now=datetime(2026, 7, 3, 0, 5, 1, tzinfo=timezone.utc),
            ttl_seconds=180,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "preflight_evidence_expired")

    def test_failed_preflight_view_is_not_reusable(self):
        ledger = {
            "preflight_evidence": {
                "7": preflight_evidence(status={"ok": False, "stop_reason": "ci_check_failed"})
            }
        }

        result = closeout.select_reusable_preflight_view(
            ledger,
            pr=7,
            now=datetime(2026, 7, 3, 0, 1, tzinfo=timezone.utc),
            ttl_seconds=180,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "preflight_not_ok")

    def test_preflight_view_missing_closeout_fields_is_not_reusable(self):
        view = dict(preflight_evidence()["view"])
        del view["labels"]
        ledger = {"preflight_evidence": {"7": preflight_evidence(view=view)}}

        result = closeout.select_reusable_preflight_view(
            ledger,
            pr=7,
            now=datetime(2026, 7, 3, 0, 1, tzinfo=timezone.utc),
            ttl_seconds=180,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "missing_preflight_view_field")
        self.assertEqual(result["missing"], ["labels"])


class RunPrCloseoutPreflightReuseTests(unittest.TestCase):
    def test_dry_run_reuses_preflight_view_and_reports_match_head_merge(self):
        calls = []
        originals = {
            "gh": closeout.gh,
            "_repo": closeout._repo,
            "_open_blockers": closeout._open_blockers,
            "_blocking": closeout._blocking,
            "_detect_root_task": closeout._detect_root_task,
            "_select_preflight_view_from_ledger": closeout._select_preflight_view_from_ledger,
            "_record_read_decision_best_effort": closeout._record_read_decision_best_effort,
        }

        def fake_gh(args, *, code="gh_failed"):
            calls.append(args)
            if args[:2] == ["pr", "view"]:
                raise AssertionError("closeout should reuse preflight view")
            if args[:2] == ["issue", "view"]:
                return json.dumps({"labels": [{"name": "in-review"}], "body": "issue"})
            raise AssertionError(f"unexpected gh call: {args}")

        try:
            closeout.gh = fake_gh
            closeout._repo = lambda: ("owner", "repo")
            closeout._open_blockers = lambda owner, repo, issue: []
            closeout._blocking = lambda owner, repo, issue: []
            closeout._detect_root_task = lambda owner, repo, issue: (issue, False, None)
            closeout._select_preflight_view_from_ledger = lambda path, pr, ttl_seconds: (
                {
                    "ok": True,
                    "source": "ledger",
                    "view": preflight_evidence()["view"],
                    "match_head_commit": "head-1",
                    "age_seconds": 10,
                },
                None,
            )
            closeout._record_read_decision_best_effort = lambda path, source, mode, result: None

            result = closeout.run_pr_closeout(
                7,
                dry_run=True,
                orchestrate_ledger="ledger.json",
                preflight_ttl_seconds=180,
            )
        finally:
            for name, value in originals.items():
                setattr(closeout, name, value)

        self.assertTrue(result["ok"])
        self.assertEqual(result["preflight_reuse"]["source"], "ledger")
        self.assertEqual(
            result["would_merge"],
            "gh pr merge 7 --merge --match-head-commit head-1",
        )
        self.assertNotIn(["pr", "view", "7", "--json"], calls)


if __name__ == "__main__":
    unittest.main()
