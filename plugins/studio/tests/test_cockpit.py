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

    def test_studio_receipt_show_passes_payload_through(self) -> None:
        write(self.roots["STUDIO_ROOT"] / "scripts" / "mission_receipt.py", STUB_RECEIPT_SHOW)
        _, report = self.report()
        source = self.source(report, "studio")
        self.assertEqual(source["state"], "present")
        self.assertEqual(
            source["summary"],
            {"ok": True, "mission": "demo-mission", "resume": ["step-1"]},
        )


if __name__ == "__main__":
    unittest.main()
