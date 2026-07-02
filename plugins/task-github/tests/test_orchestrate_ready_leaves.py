import json
import sys
import unittest
from pathlib import Path

TASK_GITHUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_GITHUB / "skills" / "orchestrate" / "scripts"))

import ready_leaves  # noqa: E402
import orchestrate_ledger  # noqa: E402


def node(number, *, state="OPEN", labels=None, blockers=None, children=None):
    children = children or []
    return {
        "number": number,
        "title": f"issue {number}",
        "state": state,
        "labels": labels or [],
        "open_blockers": blockers or [],
        "subissues_summary": {
            "total": len(children),
            "completed": sum(1 for child in children if child.get("state") == "CLOSED"),
        },
        "children": children,
    }


class ReadyLeavesTests(unittest.TestCase):
    def test_depth_three_ready_fixture(self):
        tree = node(1, children=[
            node(2, children=[
                node(4, state="CLOSED"),
                node(5, blockers=[{"number": 4, "title": "issue 4"}]),
            ]),
            node(3, children=[
                node(6),
                node(7),
            ]),
        ])

        result = ready_leaves.evaluate_tree(tree)

        self.assertTrue(result["ok"])
        self.assertEqual([item["number"] for item in result["ready"]], [6, 7])
        self.assertEqual([item["number"] for item in result["blocked"]], [5])

    def test_done_parent_and_ready_can_coexist(self):
        tree = node(1, children=[
            node(2, children=[node(4, state="CLOSED")]),
            node(3),
        ])

        result = ready_leaves.evaluate_tree(tree)

        self.assertTrue(result["ok"])
        self.assertEqual([item["number"] for item in result["done_parents"]], [2])
        self.assertEqual([item["number"] for item in result["ready"]], [3])

    def test_dropped_ready_reappears_after_parent_closes(self):
        # Self-check ③: the same-tick ready[] dropped while merging done_parents must
        # resurface on the next tick (parent now CLOSED) — guards the starvation regression.
        tick2 = node(1, children=[
            node(2, state="CLOSED", children=[node(4, state="CLOSED")]),
            node(3),
        ])

        result = ready_leaves.evaluate_tree(tick2)

        self.assertTrue(result["ok"])
        self.assertEqual([item["number"] for item in result["done_parents"]], [])
        self.assertEqual([item["number"] for item in result["ready"]], [3])

    def test_api_failure_never_degrades_to_ready(self):
        # Self-check ②: a fetch/parse failure at the CLI boundary returns ok:false +
        # api_failure, never a silent ready=[]. (Central safety invariant.)
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ready_leaves.main(["1", "--fixture-json", "/nonexistent/tree.json", "--json"])
        payload = json.loads(buf.getvalue())

        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stop_reason"], "api_failure")
        self.assertEqual(payload["ready"], [])

    def test_blocked_parent_is_not_silently_dropped(self):
        tree = node(1, children=[
            node(2, blockers=[{"number": 9, "title": "external"}], children=[node(4, state="CLOSED")]),
        ])

        result = ready_leaves.evaluate_tree(tree)

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "no_progress")
        self.assertEqual([item["number"] for item in result["blocked"]], [2])

    def test_review_waiting_stops_with_single_channel(self):
        result = ready_leaves.evaluate_tree(node(1, children=[node(2, labels=["in-review"])]))

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "human_gate_review")
        self.assertEqual([item["number"] for item in result["review_waiting"]], [2])

    def test_review_waiting_preempts_ready_siblings(self):
        result = ready_leaves.evaluate_tree(node(1, children=[
            node(2, labels=["in-review"]),
            node(3),
        ]))

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "human_gate_review")
        self.assertEqual([item["number"] for item in result["ready"]], [3])

    def test_stuck_distinguishes_prior_run_and_spawned_failed(self):
        tree = node(1, children=[
            node(2, labels=["in-progress"]),
            node(3, labels=["in-progress"]),
            node(4, labels=["in-progress"]),
        ])

        result = ready_leaves.evaluate_tree(tree, spawned_set={4}, failed_set={3})

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "stuck")
        self.assertEqual(
            [(item["number"], item["reason"]) for item in result["stuck"]],
            [(2, "prior_run"), (3, "spawned_failed")],
        )

    def test_cli_accepts_space_or_comma_separated_spawned(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "tree.json"
            fixture.write_text(json.dumps(node(1, children=[
                node(2, labels=["in-progress"]),
                node(3, labels=["in-progress"]),
            ])), encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ready_leaves.main([
                    "1",
                    "--fixture-json", str(fixture),
                    "--spawned", "2, 3",
                    "--json",
                ])

        payload = json.loads(buf.getvalue())
        self.assertEqual(rc, 1)
        self.assertEqual(payload["stop_reason"], "no_progress")
        self.assertEqual(payload["stuck"], [])

    def test_cli_reads_persistent_ledger(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "tree.json"
            ledger = Path(tmp) / "ledger.json"
            fixture.write_text(json.dumps(node(1, children=[node(2, labels=["in-progress"])])), encoding="utf-8")
            orchestrate_ledger.update_ledger(ledger, spawned={2})

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ready_leaves.main([
                    "1",
                    "--fixture-json", str(fixture),
                    "--ledger", str(ledger),
                    "--json",
                ])

        payload = json.loads(buf.getvalue())
        self.assertEqual(rc, 1)
        self.assertEqual(payload["stop_reason"], "no_progress")
        self.assertEqual(payload["stuck"], [])

    def test_cli_from_ledger_uses_write_through_state(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            orchestrate_ledger.record_snapshot(ledger, node(1, children=[node(2)]))
            orchestrate_ledger.record_event(ledger, {"type": "issue_closed", "issue": 2})

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ready_leaves.main(["--from-ledger", str(ledger), "--json"])

        payload = json.loads(buf.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["container_done"]["number"], 1)

    def test_cli_from_ledger_records_read_decision_without_github_read(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            orchestrate_ledger.record_snapshot(ledger, node(1, children=[node(2)]))

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ready_leaves.main(["--from-ledger", str(ledger), "--json"])

            payload = orchestrate_ledger.load_ledger(ledger)

        self.assertEqual(rc, 0)
        self.assertEqual(payload["github_reads"]["count"], 0)
        self.assertEqual(len(payload["read_decisions"]), 1)
        self.assertEqual(payload["read_decisions"][0]["source"], "ledger")
        self.assertEqual(payload["read_decisions"][0]["mode"], "from_ledger")

    def test_cli_missing_ledger_starts_empty(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "tree.json"
            missing_ledger = Path(tmp) / "missing.json"
            fixture.write_text(json.dumps(node(1, children=[node(2)])), encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ready_leaves.main([
                    "1",
                    "--fixture-json", str(fixture),
                    "--ledger", str(missing_ledger),
                    "--json",
                ])

        payload = json.loads(buf.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual([item["number"] for item in payload["ready"]], [2])

    def test_empty_tree_is_explicit_stop(self):
        result = ready_leaves.evaluate_tree(node(1))

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "empty_tree")
        self.assertEqual(result["ready"], [])

    def test_dependency_cycle_stop_when_all_blockers_are_in_tree(self):
        tree = node(1, children=[
            node(2, blockers=[{"number": 3, "title": "issue 3"}]),
            node(3, blockers=[{"number": 2, "title": "issue 2"}]),
        ])

        result = ready_leaves.evaluate_tree(tree)

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "dep_cycle")

    def test_paginates_subissues(self):
        calls = []

        def fetch_page(number, after):
            calls.append((number, after))
            if number != 1:
                return {
                    "node": node(number),
                    "children": [],
                    "has_next_page": False,
                    "end_cursor": None,
                }
            if after is None:
                return {
                    "node": node(number),
                    "children": [node(2)],
                    "has_next_page": True,
                    "end_cursor": "cursor-1",
                }
            return {
                "node": node(number),
                "children": [node(3)],
                "has_next_page": False,
                "end_cursor": None,
            }

        tree = ready_leaves.collect_tree(1, fetch_page)

        self.assertEqual(calls, [(1, None), (1, "cursor-1"), (2, None), (3, None)])
        self.assertEqual([child["number"] for child in tree["children"]], [2, 3])

    def test_cli_reconcile_records_github_read_reason(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        old_repo = ready_leaves._repo
        old_fetch_page = ready_leaves.github_fetch_page
        try:
            ready_leaves._repo = lambda: ("owner", "repo")
            ready_leaves.github_fetch_page = lambda owner, repo: (
                lambda number, after: (
                    {
                        "node": node(1),
                        "children": [node(2)],
                        "has_next_page": False,
                        "end_cursor": None,
                    }
                    if number == 1
                    else {
                        "node": node(number),
                        "children": [],
                        "has_next_page": False,
                        "end_cursor": None,
                    }
                )
            )
            with tempfile.TemporaryDirectory() as tmp:
                ledger = Path(tmp) / "ledger.json"
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = ready_leaves.main([
                        "1",
                        "--reconcile-github", str(ledger),
                        "--read-reason", "session_start",
                        "--json",
                    ])
                payload = orchestrate_ledger.load_ledger(ledger)
        finally:
            ready_leaves._repo = old_repo
            ready_leaves.github_fetch_page = old_fetch_page

        self.assertEqual(rc, 0)
        self.assertEqual(payload["github_reads"]["count"], 1)
        self.assertEqual(payload["github_reads"]["reasons"], ["session_start"])
        self.assertEqual(payload["github_reads"]["entries"][0]["operation"], "reconcile_github")

    def test_fixture_json_does_not_record_github_read(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "tree.json"
            ledger = Path(tmp) / "ledger.json"
            fixture.write_text(json.dumps(node(1, children=[node(2)])), encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ready_leaves.main([
                    "1",
                    "--fixture-json", str(fixture),
                    "--ledger", str(ledger),
                    "--json",
                ])
            payload = orchestrate_ledger.load_ledger(ledger)

        self.assertEqual(rc, 0)
        self.assertEqual(payload["github_reads"]["count"], 0)


class MergeEdgeGearTreeTests(unittest.TestCase):
    def test_container_done_carries_promoted_gear(self):
        # 3 micro leaves → container gear promotes to normal.
        tree = node(1, children=[
            node(2, state="CLOSED", labels=["gear:micro"]),
            node(3, state="CLOSED", labels=["gear:micro"]),
            node(4, state="CLOSED", labels=["gear:micro"]),
        ])

        result = ready_leaves.evaluate_tree(tree)

        self.assertIsNotNone(result["container_done"])
        self.assertEqual(result["container_done"]["number"], 1)
        self.assertEqual(result["container_done"]["gear"], "normal")

    def test_done_parents_carry_effective_gear(self):
        tree = node(1, children=[
            node(2, children=[node(4, state="CLOSED", labels=["gear:major"])]),
            node(3),
        ])

        result = ready_leaves.evaluate_tree(tree)

        done = {entry["number"]: entry["gear"] for entry in result["done_parents"]}
        self.assertEqual(done, {2: "major"})

    def test_effective_gear_bubbles_depth_three(self):
        # Two sub-containers each with 2 normal leaves → each promotes to major,
        # so the root sees two major children → major.
        tree = node(1, children=[
            node(2, state="CLOSED", labels=["gear:normal"]),
            node(3, state="CLOSED", labels=["gear:normal"]),
        ])
        self.assertEqual(ready_leaves._effective_gear(tree), "major")

    def test_ledger_ff_merged_event_records_close_evidence(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            orchestrate_ledger.record_event(ledger, {
                "type": "ff_merged",
                "issue": 4,
                "base": "task/issue-2",
                "sha_range": "aaa..bbb",
            })
            payload = orchestrate_ledger.load_ledger(ledger)
            issue = payload["issues"]["4"]
            self.assertEqual(issue["state"], "close_expected")
            self.assertEqual(issue["ff_merged"], {"base": "task/issue-2", "sha_range": "aaa..bbb"})

    def test_load_v2_ledger_default_fills_v3_fields_and_preserves_ff_evidence(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            ledger.write_text(json.dumps({
                "version": 2,
                "spawned": [],
                "failed": [],
                "issues": {
                    "4": {
                        "number": 4,
                        "labels": [],
                        "children": [],
                        "ff_merged": {"base": "task/issue-2", "sha_range": "aaa..bbb"},
                    }
                },
                "prs": {},
                "events": [],
            }), encoding="utf-8")

            payload = orchestrate_ledger.load_ledger(ledger)

        self.assertEqual(payload["version"], 3)
        self.assertEqual(payload["github_reads"], {"count": 0, "reasons": [], "entries": []})
        self.assertEqual(payload["read_decisions"], [])
        self.assertEqual(payload["merge_evidence"], {})
        self.assertEqual(payload["gate_evidence"], {})
        self.assertEqual(payload["issues"]["4"]["ff_merged"], {"base": "task/issue-2", "sha_range": "aaa..bbb"})

    def test_ledger_records_github_reads_read_decisions_and_evidence_separately(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            orchestrate_ledger.record_github_read(ledger, reason="session_start", operation="reconcile_github")
            orchestrate_ledger.record_read_decision(ledger, source="ledger", mode="from_ledger", root=1)
            orchestrate_ledger.record_merge_evidence(ledger, 4, {"pr": 10, "merge_commit": "abc"})
            orchestrate_ledger.record_gate_evidence(ledger, 4, {"gate": "changed-path-stale", "ok": True})
            payload = orchestrate_ledger.load_ledger(ledger)

        self.assertEqual(payload["github_reads"]["count"], 1)
        self.assertEqual(payload["github_reads"]["reasons"], ["session_start"])
        self.assertEqual(len(payload["read_decisions"]), 1)
        self.assertEqual(payload["read_decisions"][0]["mode"], "from_ledger")
        self.assertEqual(payload["merge_evidence"]["4"]["pr"], 10)
        self.assertEqual(payload["gate_evidence"]["4"]["gate"], "changed-path-stale")


if __name__ == "__main__":
    unittest.main()
