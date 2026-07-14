import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_module("task_worker_definition", PLUGIN / "scripts" / "definition_artifact.py")


def graph_spec():
    return {
        "definition_id": "parallel-work",
        "delivery": "local-ff",
        "root": {"title": "root", "body": "integration criteria"},
        "children": [
            {
                "key": "A",
                "title": "contract",
                "body": "contract criteria",
                "affects_paths": ["src/a/**"],
                "blocked_by": [],
            },
            {
                "key": "B",
                "title": "consumer",
                "body": "consumer criteria",
                "affects_paths": ["src/b/**"],
                "blocked_by": ["A"],
            },
            {
                "key": "C",
                "title": "independent",
                "body": "independent criteria",
                "affects_paths": ["src/c/**"],
                "blocked_by": [],
            },
        ],
    }


def close_run(artifact, state, *, start="2026-07-14T00:00:00Z"):
    times = {
        "run": "2026-07-14T00:00:01Z",
        "verify": "2026-07-14T00:00:02Z",
        "done": "2026-07-14T00:00:03Z",
        "closeout": "2026-07-14T00:00:04Z",
    }
    current = state
    for event in ("run", "verify", "done", "closeout"):
        evidence = {"result": "pass"} if event == "verify" else None
        current, _ = worker.transition_local_run(
            artifact, current, event, evidence=evidence, now=times[event]
        )
    return current


class DefinitionArtifactTests(unittest.TestCase):
    def test_revision_keeps_node_ids_and_pins_previous_digest(self):
        first = worker.create_artifact(graph_spec(), created_at="2026-07-14T00:00:00Z")
        revised = graph_spec()
        revised["children"][0]["body"] = "changed criteria"
        second = worker.create_artifact(
            revised, previous=first, created_at="2026-07-14T00:01:00Z"
        )

        self.assertEqual(second["schema"], worker.SCHEMA)
        self.assertEqual(second["previous_digest"], first["digest"])
        self.assertEqual(
            [node["node_id"] for node in second["children"]],
            [node["node_id"] for node in first["children"]],
        )

    def test_provider_recording_is_not_part_of_new_definition(self):
        spec = graph_spec()
        spec["record"] = "github"
        with self.assertRaisesRegex(worker.DefinitionError, "adapter binding"):
            worker.create_artifact(spec)

    def test_legacy_task_github_artifact_is_read_compatible(self):
        old = worker.create_artifact(graph_spec(), created_at="2026-07-14T00:00:00Z")
        old["schema"] = "task-github.definition/v1"
        old["record"] = "none"
        old["digest"] = worker.artifact_digest(old)

        worker.validate_artifact(old)
        successor = worker.create_artifact(graph_spec(), previous=old)

        self.assertEqual(successor["schema"], worker.SCHEMA)
        self.assertEqual(successor["previous_digest"], old["digest"])
        self.assertNotIn("record", successor)

    def test_work_graph_returns_full_ready_set_and_integration_candidates(self):
        snapshot = {
            "schema": worker.WORK_GRAPH_SCHEMA,
            "graph_id": "adapter-graph",
            "nodes": [
                {"node_id": "root", "title": "root", "parent_id": None, "status": "open", "blocked_by": []},
                {"node_id": "A", "title": "A", "parent_id": "root", "status": "open", "blocked_by": []},
                {"node_id": "B", "title": "B", "parent_id": "root", "status": "open", "blocked_by": []},
            ],
        }
        plan = worker.plan_work_graph(snapshot)
        self.assertEqual([item["node_id"] for item in plan["ready_actions"]], ["A", "B"])
        self.assertEqual(plan["integration_candidates"], [])

        for node in snapshot["nodes"][1:]:
            node["status"] = "completed"
        plan = worker.plan_work_graph(snapshot)
        self.assertEqual([item["node_id"] for item in plan["integration_candidates"]], ["root"])

    def test_work_graph_keeps_unknown_external_blocker_blocked(self):
        plan = worker.plan_work_graph({
            "schema": worker.WORK_GRAPH_SCHEMA,
            "graph_id": "external-blocker",
            "nodes": [{
                "node_id": "A", "title": "A", "parent_id": None,
                "status": "open", "blocked_by": ["outside-9"],
            }],
        })
        self.assertEqual(plan["ready_actions"], [])
        self.assertEqual(plan["blocked"][0]["missing_blockers"], ["outside-9"])

    def test_work_graph_dependency_cycle_fails_closed(self):
        snapshot = {
            "schema": worker.WORK_GRAPH_SCHEMA,
            "graph_id": "cycle-graph",
            "nodes": [
                {"node_id": "A", "title": "A", "parent_id": None, "status": "open", "blocked_by": ["B"]},
                {"node_id": "B", "title": "B", "parent_id": None, "status": "open", "blocked_by": ["A"]},
            ],
        }
        with self.assertRaisesRegex(worker.DefinitionError, "dependency cycle"):
            worker.plan_work_graph(snapshot)

    def test_ready_plan_returns_all_independent_leaves(self):
        artifact = worker.create_artifact(graph_spec())
        with tempfile.TemporaryDirectory() as tmp:
            plan = worker.ready_plan(artifact, tmp)

        self.assertEqual([item["node_key"] for item in plan["ready_actions"]], ["A", "C"])
        self.assertEqual([item["node_key"] for item in plan["blocked"]], ["B"])
        self.assertNotEqual(
            plan["ready_actions"][0]["identity"]["worktree"],
            plan["ready_actions"][1]["identity"]["worktree"],
        )

    def test_closed_blocker_unlocks_only_affected_leaf(self):
        artifact = worker.create_artifact(graph_spec())
        with tempfile.TemporaryDirectory() as tmp:
            state, path, _ = worker.start_local_run(
                artifact, node_ref="A", state_dir=tmp, now="2026-07-14T00:00:00Z"
            )
            worker.write_json_atomic(path, close_run(artifact, state))
            plan = worker.ready_plan(artifact, tmp)

        self.assertEqual([item["node_key"] for item in plan["ready_actions"]], ["B", "C"])
        self.assertEqual(plan["completed"], [artifact["children"][0]["node_id"]])

    def test_dependency_cycle_fails_closed(self):
        spec = graph_spec()
        spec["children"][0]["blocked_by"] = ["B"]
        with self.assertRaisesRegex(worker.DefinitionError, "dependency cycle"):
            worker.create_artifact(spec)

    def test_local_lifecycle_is_idempotent_and_keeps_evidence(self):
        artifact = worker.create_artifact({
            "definition_id": "single-work",
            "root": {"title": "single", "body": "criteria"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            state, path, created = worker.start_local_run(
                artifact, node_ref="root", state_dir=tmp, now="2026-07-14T00:00:00Z"
            )
            self.assertTrue(created)
            same, _, created = worker.start_local_run(artifact, node_ref="root", state_dir=tmp)
            self.assertFalse(created)
            self.assertEqual(same["run_id"], state["run_id"])

            state = close_run(artifact, state)
            worker.write_json_atomic(path, state)
            verify_event = next(item for item in state["events"] if item["event"] == "verify")
            self.assertEqual(verify_event["evidence"], {"result": "pass"})
            self.assertIsNone(worker.recover_local_run(artifact, state)["next_event"])

    def test_second_physical_run_for_same_pin_and_node_is_blocked(self):
        artifact = worker.create_artifact({
            "definition_id": "leased-work",
            "root": {"title": "single", "body": "criteria"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            worker.start_local_run(
                artifact, node_ref="root", state_dir=tmp, run_id="first-run"
            )
            with self.assertRaisesRegex(worker.DefinitionError, "already has pinned run"):
                worker.start_local_run(
                    artifact, node_ref="root", state_dir=tmp, run_id="second-run"
                )

    def test_corrupt_run_ledger_fails_ready_planning(self):
        artifact = worker.create_artifact({
            "definition_id": "corrupt-work",
            "root": {"title": "single", "body": "criteria"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "broken.json").write_text("not-json", encoding="utf-8")
            with self.assertRaises(worker.DefinitionError) as raised:
                worker.ready_plan(artifact, tmp)
        self.assertEqual(raised.exception.code, "json_invalid")

    def test_receipt_uses_task_worker_emitter_and_null_token_semantics(self):
        artifact = worker.create_artifact({
            "definition_id": "receipt-work",
            "root": {"title": "single", "body": "criteria"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            state, _, _ = worker.start_local_run(
                artifact, node_ref="root", state_dir=tmp, now="2026-07-14T00:00:00Z"
            )
            state = close_run(artifact, state)
        receipt = worker.build_receipt(state, counters={"physical_runs": 1})
        self.assertEqual(receipt["emitter"], "task-worker")
        self.assertIsNone(receipt["tokens"])
        self.assertEqual(receipt["token_coverage"], "unavailable")
        self.assertEqual(receipt["elapsed_ms"], 4000)


if __name__ == "__main__":
    unittest.main()
