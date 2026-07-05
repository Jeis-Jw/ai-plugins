import json
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

TASK_GITHUB = Path(__file__).resolve().parents[1]
SCRIPTS = TASK_GITHUB / "skills" / "orchestrate" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import closeout_ff_edge  # noqa: E402
import orchestrate_ledger  # noqa: E402


def completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


class CloseoutFFEdgeTests(unittest.TestCase):
    def test_success_records_compact_closeout_once(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append((cmd, str(cwd) if cwd else None))
            if cmd[:4] == ["git", "-C", "wt", "symbolic-ref"]:
                return completed(cmd, stdout="task/issue-2\n")
            if cmd[:4] == ["git", "-C", "wt", "status"]:
                return completed(cmd)
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout="aaa\n")
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                return completed(cmd)
            if cmd[:4] == ["git", "-C", "wt", "rev-parse"]:
                return completed(cmd, stdout="bbb\n")
            if cmd == ["node", "test.js"]:
                return completed(cmd)
            if cmd[:3] == ["git", "fetch", "."]:
                return completed(cmd)
            if cmd[:3] == ["git", "push", "origin"]:
                return completed(cmd)
            if cmd[:3] == ["gh", "issue", "close"]:
                return completed(cmd)
            raise AssertionError(f"unexpected command: {cmd}")

        with tempfile.TemporaryDirectory() as tmp, patch.object(closeout_ff_edge, "_run", fake_run):
            ledger = Path(tmp) / "ledger.json"
            ledger.write_text(json.dumps({
                "version": 3,
                "spawned": [2],
                "failed": [2],
                "issues": {"2": {"number": 2, "labels": ["in-progress"], "children": []}},
                "prs": {},
                "events": [],
                "github_reads": {"count": 0, "reasons": [], "entries": []},
                "read_decisions": [],
                "merge_evidence": {},
                "gate_evidence": {},
                "preflight_evidence": {},
            }), encoding="utf-8")

            result = closeout_ff_edge.closeout_ff_edge(
                ledger=str(ledger),
                issue=2,
                child="task/issue-2",
                parent="task/issue-1",
                worktree="wt",
                tests=[["node", "test.js"]],
            )
            payload = orchestrate_ledger.load_ledger(ledger)

        self.assertTrue(result["ok"])
        self.assertEqual(result["reverse_merge"], "skipped")
        self.assertEqual(result["tests"], [{"cmd": "node test.js", "ok": True}])
        self.assertEqual(payload["spawned"], [])
        self.assertEqual(payload["failed"], [])
        self.assertEqual(payload["issues"]["2"]["state"], "CLOSED")
        self.assertEqual(payload["issues"]["2"]["ff_merged"]["base"], "task/issue-1")
        self.assertEqual([event["type"] for event in payload["events"]], [
            "ff_merged",
            "issue_closed",
            "closeout_done",
            "worker_completed",
        ])
        self.assertIn((["git", "fetch", ".", "task/issue-2:task/issue-1"], None), calls)

    def test_parent_ahead_reverse_merges_in_child_worktree(self):
        commands = []

        def fake_run(cmd, cwd=None):
            commands.append((cmd, str(cwd) if cwd else None))
            if cmd[:4] == ["git", "-C", "wt", "symbolic-ref"]:
                return completed(cmd, stdout="task/issue-2\n")
            if cmd[:4] == ["git", "-C", "wt", "status"]:
                return completed(cmd)
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout="aaa\n")
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                return completed(cmd, returncode=1)
            if cmd[:2] == ["git", "merge"]:
                return completed(cmd)
            if cmd[:4] == ["git", "-C", "wt", "rev-parse"]:
                return completed(cmd, stdout="bbb\n")
            if cmd[:3] == ["git", "fetch", "."] or cmd[:3] == ["git", "push", "origin"]:
                return completed(cmd)
            if cmd[:3] == ["gh", "issue", "close"]:
                return completed(cmd)
            raise AssertionError(f"unexpected command: {cmd}")

        with tempfile.TemporaryDirectory() as tmp, patch.object(closeout_ff_edge, "_run", fake_run):
            result = closeout_ff_edge.closeout_ff_edge(
                ledger=str(Path(tmp) / "ledger.json"),
                issue=2,
                child="task/issue-2",
                parent="task/issue-1",
                worktree="wt",
                tests=[],
            )

        self.assertEqual(result["reverse_merge"], "done")
        self.assertIn((["git", "merge", "--no-edit", "task/issue-1"], "wt"), commands)

    def test_test_failure_records_closeout_failed(self):
        def fake_run(cmd, cwd=None):
            if cmd[:4] == ["git", "-C", "wt", "symbolic-ref"]:
                return completed(cmd, stdout="task/issue-2\n")
            if cmd[:4] == ["git", "-C", "wt", "status"]:
                return completed(cmd)
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout="aaa\n")
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                return completed(cmd)
            if cmd == ["node", "test.js"]:
                return completed(cmd, returncode=1, stderr="failed")
            raise AssertionError(f"unexpected command: {cmd}")

        with tempfile.TemporaryDirectory() as tmp, patch.object(closeout_ff_edge, "_run", fake_run):
            ledger = Path(tmp) / "ledger.json"
            with redirect_stdout(io.StringIO()):
                rc = closeout_ff_edge.main([
                    "--ledger", str(ledger),
                    "--issue", "2",
                    "--child", "task/issue-2",
                    "--parent", "task/issue-1",
                    "--worktree", "wt",
                    "--test", '["node","test.js"]',
                    "--json",
                ])
            payload = orchestrate_ledger.load_ledger(ledger)

        self.assertEqual(rc, 1)
        self.assertEqual(payload["issues"]["2"]["state"], "closeout_failed")
        self.assertEqual(payload["issues"]["2"]["closeout_failed"]["reason"], "test_failed")

    def test_ledger_write_failure_is_machine_readable(self):
        def fake_run(cmd, cwd=None):
            if cmd[:4] == ["git", "-C", "wt", "symbolic-ref"]:
                return completed(cmd, stdout="task/issue-2\n")
            if cmd[:4] == ["git", "-C", "wt", "status"]:
                return completed(cmd)
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout="aaa\n")
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                return completed(cmd)
            if cmd[:4] == ["git", "-C", "wt", "rev-parse"]:
                return completed(cmd, stdout="bbb\n")
            if cmd[:3] == ["git", "fetch", "."] or cmd[:3] == ["git", "push", "origin"]:
                return completed(cmd)
            if cmd[:3] == ["gh", "issue", "close"]:
                return completed(cmd)
            raise AssertionError(f"unexpected command: {cmd}")

        with tempfile.TemporaryDirectory() as tmp, patch.object(closeout_ff_edge, "_run", fake_run):
            ledger = Path(tmp) / "ledger.json"
            ledger.write_text("[]", encoding="utf-8")
            with self.assertRaises(closeout_ff_edge.CloseoutFFError) as raised:
                closeout_ff_edge.closeout_ff_edge(
                    ledger=str(ledger),
                    issue=2,
                    child="task/issue-2",
                    parent="task/issue-1",
                    worktree="wt",
                    tests=[],
                )

        self.assertEqual(raised.exception.stage, "ledger")


if __name__ == "__main__":
    unittest.main()
