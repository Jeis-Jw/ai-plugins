from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "cockpit.py"

STUB_RESUME_OK = """import json
print(json.dumps({"ok": True, "resume": {"plan": {
    "ready_actions": [{"node_id": "n1", "key": "unit-a"}],
    "manual_actions": [],
}}}))
"""

STUB_FAIL_PROSE = """import sys
sys.stderr.write("Traceback (most recent call last): boom prose not machine readable\\n")
sys.exit(3)
"""

STUB_RECEIPT_SHOW = """import json
print(json.dumps({"ok": True, "mission": "demo-mission", "resume": ["step-1"]}))
"""

# session-review facade stub: `snapshot-dir` prints the provider dir, `status`
# answers per slug; slugs listed in FAIL exit nonzero (no review status block).
STUB_SESSION_REVIEW = """import json, sys
DIR = {snapshot_dir!r}
STATUS = {status!r}
if sys.argv[1] == "snapshot-dir":
    print(DIR)
elif sys.argv[1] == "status":
    slug = sys.argv[sys.argv.index("--slug") + 1]
    if slug not in STATUS:
        sys.stderr.write("no status block\\n")
        sys.exit(2)
    print(json.dumps({{"ok": True, "status": STATUS[slug]}}))
"""

BINDING = {
    "schema": "task-worker.provider-binding/v1",
    "binding_id": "b-demo",
    "aliases": ["demo"],
    "dispatch": "worker",
    "artifact_path": ".task-worker/local/definitions/demo.json",
}

LEDGER = {
    "version": 3,
    "root": 82,
    "snapshot_at": "2026-07-30T14:58:36Z",
    "issues": {
        "82": {"number": 82, "title": "root issue", "state": "OPEN", "parent": None},
        "83": {"number": 83, "title": "leaf a", "state": "OPEN", "parent": 82},
        "84": {"number": 84, "title": "leaf b", "state": "CLOSED", "parent": 82},
    },
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CockpitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.workspace = base / "workspace"
        self.workspace.mkdir()
        # Pin every plugin root at an empty stub dir so the real repo layout
        # (and a later-landing mission_receipt.py) never leaks into a test.
        self.roots = {
            "STUDIO_ROOT": base / "studio-root",
            "TASK_WORKER_ROOT": base / "task-worker-root",
            "SESSION_REVIEW_ROOT": base / "session-review-root",
        }
        for path in self.roots.values():
            path.mkdir()

    def run_status(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update({key: str(path) for key, path in self.roots.items()})
        return subprocess.run(
            [sys.executable, str(SCRIPT), "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            cwd=self.workspace,
            env=env,
        )

    def report(self) -> tuple[subprocess.CompletedProcess[str], dict]:
        proc = self.run_status()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc, json.loads(proc.stdout)

    def source(self, report: dict, name: str) -> dict:
        return next(item for item in report["sources"] if item["source"] == name)

    def test_all_sources_missing_is_absent_everywhere_and_exit_zero(self) -> None:
        _, report = self.report()
        self.assertEqual(report["schema"], "studio.cockpit/v1")
        self.assertEqual(len(report["sources"]), 4)
        for item in report["sources"]:
            self.assertEqual(item["state"], "absent", item)
            self.assertIsNone(item["summary"])
            self.assertIsNone(item["reason"])
        self.assertEqual(report["next"], [])

    def test_task_worker_fixture_yields_summary_and_one_next(self) -> None:
        write(
            self.roots["TASK_WORKER_ROOT"] / "scripts" / "definition_artifact.py",
            STUB_RESUME_OK,
        )
        write(
            self.workspace / ".task-worker" / "local" / "bindings" / "demo.json",
            json.dumps(BINDING),
        )
        _, report = self.report()
        source = self.source(report, "task-worker")
        self.assertEqual(source["state"], "present")
        self.assertEqual(source["authority"], "live")
        self.assertEqual(
            source["summary"],
            {"bindings": [{"alias": "demo", "dispatch": "worker", "ready": 1}]},
        )
        for name in ("session-review", "task-github", "studio"):
            self.assertEqual(self.source(report, name)["state"], "absent")
        self.assertEqual(
            report["next"],
            [{"source": "task-worker", "action": "task-worker:orchestrate", "ref": "demo"}],
        )

    def test_failing_adapter_is_error_with_fixed_reason_and_no_prose(self) -> None:
        write(
            self.roots["TASK_WORKER_ROOT"] / "scripts" / "definition_artifact.py",
            STUB_FAIL_PROSE,
        )
        write(
            self.workspace / ".task-worker" / "local" / "bindings" / "demo.json",
            json.dumps(BINDING),
        )
        proc, report = self.report()
        source = self.source(report, "task-worker")
        self.assertEqual(source["state"], "error")
        self.assertEqual(source["reason"], "exit_nonzero")
        self.assertIsNone(source["summary"])
        self.assertNotIn("boom prose", proc.stdout)
        self.assertEqual(report["next"], [])

    def test_non_json_adapter_output_is_invalid_json_error(self) -> None:
        write(
            self.roots["TASK_WORKER_ROOT"] / "scripts" / "definition_artifact.py",
            'print("plain prose, not json")\n',
        )
        write(
            self.workspace / ".task-worker" / "local" / "bindings" / "demo.json",
            json.dumps(BINDING),
        )
        _, report = self.report()
        source = self.source(report, "task-worker")
        self.assertEqual(source["state"], "error")
        self.assertEqual(source["reason"], "invalid_json")

    def test_task_github_ledger_is_read_directly_as_local_projection(self) -> None:
        write(
            self.workspace / ".task-github" / "orchestrate" / "82.json",
            json.dumps(LEDGER),
        )
        _, report = self.report()
        source = self.source(report, "task-github")
        self.assertEqual(source["state"], "present")
        self.assertEqual(source["authority"], "local-projection")
        self.assertEqual(
            source["summary"],
            {
                "ledgers": [
                    {
                        "root": 82,
                        "title": "root issue",
                        "open_leaves": 1,
                        "closed_leaves": 1,
                        "snapshot_at": "2026-07-30T14:58:36Z",
                    }
                ]
            },
        )
        self.assertEqual(
            report["next"],
            [{"source": "task-github", "action": "task-github:orchestrate", "ref": "#82"}],
        )

    def _write_session_review_stub(self, snapshot_dir: str, status: dict) -> None:
        write(
            self.roots["SESSION_REVIEW_ROOT"] / "scripts" / "session_review.py",
            STUB_SESSION_REVIEW.format(snapshot_dir=snapshot_dir, status=status),
        )

    def test_session_review_scan_uses_snapshot_dir_not_wiki_layout(self) -> None:
        # context-core-shaped provider dir: no wiki/, no SNAP- prefix, its own index file.
        self._write_session_review_stub(
            "context/snapshot",
            {"session-review-h": {"phase": "awaiting-review", "round": 1, "next_actor": "reviewer"}},
        )
        write(self.workspace / "context" / "snapshot" / "session-review-h.md", "---\nid: x\n---\n")
        write(self.workspace / "context" / "snapshot" / "snapshot.index.md", "index\n")
        _, report = self.report()
        source = self.source(report, "session-review")
        self.assertEqual(source["state"], "present")
        self.assertEqual(
            source["summary"],
            {"snapshots": [{"slug": "session-review-h", "phase": "awaiting-review",
                            "round": 1, "next_actor": "reviewer"}]},
        )
        self.assertEqual(
            report["next"],
            [{"source": "session-review", "action": "session-review:review",
              "ref": "session-review-h"}],
        )

    def test_session_review_scan_strips_snap_prefix_and_skips_non_review_snapshots(self) -> None:
        # wiki-shaped dir: SNAP-<slug>.md naming, snapshot.md index, plus a
        # pause SNAP without a status block that must be skipped, not an error.
        self._write_session_review_stub(
            "wiki/snapshot",
            {"h": {"phase": "approved", "round": 2, "next_actor": "worker"}},
        )
        for name in ("SNAP-h.md", "SNAP-studio-mission-m1.md", "snapshot.md"):
            write(self.workspace / "wiki" / "snapshot" / name, "x\n")
        _, report = self.report()
        source = self.source(report, "session-review")
        self.assertEqual(source["state"], "present")
        self.assertEqual([row["slug"] for row in source["summary"]["snapshots"]], ["h"])
        self.assertEqual(
            report["next"],
            [{"source": "session-review", "action": "session-review:complete", "ref": "h"}],
        )

    def test_session_review_scan_with_only_non_review_snapshots_is_absent(self) -> None:
        self._write_session_review_stub("wiki/snapshot", {})
        write(self.workspace / "wiki" / "snapshot" / "SNAP-studio-mission-m1.md", "x\n")
        _, report = self.report()
        self.assertEqual(self.source(report, "session-review")["state"], "absent")

    def test_session_review_snapshot_dir_failure_is_source_error(self) -> None:
        write(
            self.roots["SESSION_REVIEW_ROOT"] / "scripts" / "session_review.py",
            "import sys\nsys.exit(2)\n",
        )
        _, report = self.report()
        source = self.source(report, "session-review")
        self.assertEqual((source["state"], source["reason"]), ("error", "exit_nonzero"))

    def test_studio_receipt_show_passes_payload_through(self) -> None:
        write(self.roots["STUDIO_ROOT"] / "scripts" / "mission_receipt.py", STUB_RECEIPT_SHOW)
        _, report = self.report()
        source = self.source(report, "studio")
        self.assertEqual(source["state"], "present")
        self.assertEqual(
            source["summary"],
            {"ok": True, "mission": "demo-mission", "resume": ["step-1"]},
        )


REAL_SESSION_REVIEW = PLUGIN.parent / "session-review"


@unittest.skipUnless(
    (REAL_SESSION_REVIEW / "scripts" / "session_review.py").is_file(),
    "session-review not present in this checkout",
)
class CockpitSessionReviewIntegrationTests(CockpitTests):
    """Same scan against the real session-review facade (builtin provider)."""

    def setUp(self) -> None:
        super().setUp()
        self.roots["SESSION_REVIEW_ROOT"] = REAL_SESSION_REVIEW

    def _seed_episode(self, slug: str) -> None:
        status = {
            "phase": "awaiting-review", "active_actor": "none", "lock_since": None,
            "next_actor": "reviewer", "target_mode": "diff", "target_ref": "b",
            "base_ref": "a", "responding_to": "a", "round": 1,
            "flow_mode": "self", "review_strength": "normal", "blocking_count": 0,
        }
        env = os.environ.copy()
        env.update({"SESSION_REVIEW_SNAPSHOT_PROVIDER": "builtin", "WIKI_VAULT": ""})
        script = REAL_SESSION_REVIEW / "scripts" / "session_review.py"
        rendered = subprocess.run(
            [sys.executable, str(script), "render", "--fenced", "--status-json", json.dumps(status)],
            capture_output=True, text=True, cwd=self.workspace, env=env, check=True)
        subprocess.run(
            [sys.executable, str(script), "snapshot-save", "--slug", slug, "--title", "T",
             "--summary", "s", "--tags", "session-review", "--discussion", rendered.stdout],
            capture_output=True, text=True, cwd=self.workspace, env=env, check=True)

    def test_real_builtin_episode_shows_up_with_next_action(self) -> None:
        self._seed_episode("h")
        _, report = self.report()
        source = self.source(report, "session-review")
        self.assertEqual(source["state"], "present", source)
        self.assertEqual(
            source["summary"]["snapshots"],
            [{"slug": "h", "phase": "awaiting-review", "round": 1, "next_actor": "reviewer"}],
        )
        self.assertEqual(
            report["next"],
            [{"source": "session-review", "action": "session-review:review", "ref": "h"}],
        )

    # inherited stub tests rerun harmlessly with the real root only when they
    # write their own SESSION_REVIEW_ROOT stub — which setUp restored, so drop them.
    def test_session_review_scan_uses_snapshot_dir_not_wiki_layout(self) -> None:  # noqa: D102
        pass

    def test_session_review_scan_strips_snap_prefix_and_skips_non_review_snapshots(self) -> None:
        pass

    def test_session_review_scan_with_only_non_review_snapshots_is_absent(self) -> None:
        pass

    def test_session_review_snapshot_dir_failure_is_source_error(self) -> None:
        pass

    def test_all_sources_missing_is_absent_everywhere_and_exit_zero(self) -> None:
        pass

    def test_task_worker_fixture_yields_summary_and_one_next(self) -> None:
        pass

    def test_failing_adapter_is_error_with_fixed_reason_and_no_prose(self) -> None:
        pass

    def test_non_json_adapter_output_is_invalid_json_error(self) -> None:
        pass

    def test_task_github_ledger_is_read_directly_as_local_projection(self) -> None:
        pass

    def test_studio_receipt_show_passes_payload_through(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
