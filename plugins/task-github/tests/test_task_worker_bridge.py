import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))

import task_worker_bridge as bridge  # noqa: E402
import github_projection as projection  # noqa: E402


def studio_review_lease():
    lease = {
        "schema": "workflow-review-lease/v1",
        "lease_id": "lease-studio-1",
        "owner": "studio",
        "provider": "session-review",
        "episode_id": "episode-1",
        "edge_id": "pr-22",
        "requirement": "independent",
        "criteria_digest": "sha256:" + "a" * 64,
        "evidence_refs": ["EV-full-baseline"],
    }
    encoded = json.dumps(lease, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lease["digest"] = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
    return lease


class TaskWorkerBridgeTests(unittest.TestCase):
    def test_preflight_resolves_sibling_worker_and_exact_contracts(self):
        root, payload = bridge.resolve_task_worker_root()
        self.assertEqual(root.name, "task-worker")
        self.assertEqual(payload["plugin"], "task-worker")
        self.assertEqual(payload["version"], "0.4.0")
        self.assertEqual(payload["contracts"], bridge.REQUIRED_CONTRACTS)
        self.assertEqual(payload["contracts"]["review_permit"], "task-worker.review-permit/v1")
        self.assertTrue(bridge.REQUIRED_COMMANDS.issubset(set(payload["commands"])))

    def test_bridge_binds_and_consumes_studio_review_permit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec.json"
            artifact_path = root / "artifact.json"
            lease_path = root / "lease.json"
            spec.write_text(json.dumps({
                "definition_id": "bridge-review",
                "root": {"title": "root", "body": "criteria"},
            }), encoding="utf-8")
            created = bridge.call_worker(["create", "--spec", str(spec), "--store", str(root / "defs")])
            artifact_path.write_text(json.dumps(created["artifact"]), encoding="utf-8")
            lease = studio_review_lease()
            lease_path.write_text(json.dumps(lease), encoding="utf-8")
            binding = bridge.bind_artifact(
                artifact_path,
                state_root=root / "state",
                review_lease_paths=[lease_path],
            )
            permit = bridge.review_permit(
                binding["definition"]["definition_id"],
                state_root=root / "state",
                episode_id=lease["episode_id"],
                edge_id=lease["edge_id"],
            )

        self.assertEqual(binding["review_leases"], [lease])
        self.assertEqual(permit["status"], "externally-owned")
        self.assertFalse(permit["dispatch_reviewer"])

    def test_legacy_cli_path_forwards_to_worker(self):
        result = subprocess.run(
            [sys.executable, str(PLUGIN / "scripts" / "definition_artifact.py"), "capabilities"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["plugin"], "task-worker")
        self.assertEqual(payload["contracts"]["work_graph"], "task-worker.work-graph/v1")

    def test_explicit_missing_worker_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TASK_WORKER_ROOT": tmp}, clear=False):
                with self.assertRaises(bridge.TaskWorkerBridgeError) as raised:
                    bridge.resolve_task_worker_root()
        self.assertEqual(raised.exception.code, "task_worker_missing")

    def test_cache_layout_discovers_newest_sibling_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "marketplace"
            github_root = cache / "task-github" / "0.21.0"
            github_root.mkdir(parents=True)
            for version in ("0.1.0", "0.2.0"):
                script = cache / "task-worker" / version / "scripts" / "definition_artifact.py"
                script.parent.mkdir(parents=True)
                script.write_text("# discovery fixture\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(bridge, "PLUGIN_ROOT", github_root):
                    candidates = bridge._candidate_roots()
        self.assertEqual(candidates[0].name, "0.2.0")

    def test_incompatible_worker_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "scripts" / "definition_artifact.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                "import json\n"
                "print(json.dumps({'ok': True, 'plugin': 'task-worker', "
                "'version': '99.0.0', 'contracts': {}, 'commands': []}))\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"TASK_WORKER_ROOT": str(root)}, clear=False):
                with self.assertRaises(bridge.TaskWorkerBridgeError) as raised:
                    bridge.resolve_task_worker_root()
        self.assertEqual(raised.exception.code, "task_worker_contract_mismatch")

    def test_orchestrate_reports_missing_dependency_without_partial_ready_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "tree.json"
            fixture.write_text(json.dumps({
                "number": 1,
                "title": "root",
                "state": "OPEN",
                "labels": [],
                "open_blockers": [],
                "children": [{
                    "number": 2,
                    "title": "leaf",
                    "state": "OPEN",
                    "labels": [],
                    "open_blockers": [],
                    "children": [],
                }],
            }), encoding="utf-8")
            environment = dict(os.environ)
            environment["TASK_WORKER_ROOT"] = str(Path(tmp) / "missing")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "skills" / "orchestrate" / "scripts" / "ready_leaves.py"),
                    "1", "--fixture-json", str(fixture), "--json",
                ],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["stop_reason"], "task_worker_missing")
        self.assertEqual(payload["ready"], [])

    def test_task_github_has_no_second_execution_core(self):
        compatibility = (PLUGIN / "scripts" / "definition_artifact.py").read_text(encoding="utf-8")
        for duplicate in ("def create_artifact", "def start_local_run", "def ready_plan"):
            self.assertNotIn(duplicate, compatibility)
        self.assertIn("task_worker_bridge", compatibility)

        ready = (
            PLUGIN / "skills" / "orchestrate" / "scripts" / "ready_leaves.py"
        ).read_text(encoding="utf-8")
        self.assertIn("task_worker_bridge.plan_graph", ready)

    def test_projection_reuses_same_artifact_validation_in_process(self):
        artifact = {
            "schema": "task-worker.definition/v1",
            "definition_id": "cache-test",
            "revision": 1,
            "digest": "not-used-by-mock",
        }
        projection._VALIDATED_ARTIFACTS.clear()
        with mock.patch.object(projection.task_worker_bridge, "validate_artifact") as validate:
            projection.validate_artifact(artifact)
            projection.validate_artifact(dict(artifact))
        validate.assert_called_once()

    def test_local_facade_skills_call_bridge_not_duplicate_core(self):
        for skill in ("define", "start", "run", "verify", "done"):
            content = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=skill):
                self.assertIn("task_worker_bridge.py", content)
                self.assertNotIn("scripts/definition_artifact.py", content)


if __name__ == "__main__":
    unittest.main()
