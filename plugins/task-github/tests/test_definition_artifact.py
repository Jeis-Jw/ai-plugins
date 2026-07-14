import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "define" / "scripts"))

import github_projection as da  # noqa: E402
import create_issue_tree as tree  # noqa: E402

WORKER_PATH = PLUGIN.parent / "task-worker" / "scripts" / "definition_artifact.py"
WORKER_SPEC = importlib.util.spec_from_file_location("task_worker_definition_for_projection_tests", WORKER_PATH)
worker = importlib.util.module_from_spec(WORKER_SPEC)
assert WORKER_SPEC.loader is not None
WORKER_SPEC.loader.exec_module(worker)


def definition_spec(*, delivery="external"):
    return {
        "definition_id": "payments-v1",
        "delivery": delivery,
        "root": {"title": "payments", "body": "root definition"},
        "children": [
            {
                "key": "U1",
                "title": "contract",
                "body": "완료 기준: contract\n검증: unittest\n영향 경로: src/contract/**",
                "affects_paths": ["src/contract/**"],
                "blocked_by": [],
            },
            {
                "key": "U2",
                "title": "consumer",
                "body": "완료 기준: consumer\n검증: unittest\n영향 경로: src/consumer/**",
                "affects_paths": ["src/consumer/**"],
                "blocked_by": ["U1"],
            },
        ],
    }


def complete_projection(artifact):
    state = {
        "schema": da.PROJECTION_SCHEMA,
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "definition_digest": artifact["digest"],
        "nodes": {},
        "dependencies": {},
    }
    for index, node_id in enumerate(da.projection_requirements(artifact)["nodes"], start=1):
        state["nodes"][node_id] = {"number": index, "github_node_id": f"G-{index}"}
    for edge in da.projection_requirements(artifact)["dependencies"]:
        state["dependencies"][edge] = {"materialized": True}
    return state


class FakeProjectionProvider:
    def __init__(
        self, *, fail_child=None, fail_node_id_for=None, start=100,
        lose_create_response_for=None, remote=None, remote_dependencies=None,
    ):
        self.fail_child = fail_child
        self.fail_node_id_for = fail_node_id_for
        self.lose_create_response_for = lose_create_response_for
        self.next_number = start
        self.calls = []
        self.remote = remote if remote is not None else {}
        self.remote_dependencies = remote_dependencies if remote_dependencies is not None else set()
        self.number_keys = {}
        self.failed_node_ids = set()
        self.lost_create_responses = set()

    def context(self):
        self.calls.append(("context",))
        return "owner", "repo", "RID"

    def node_id(self, owner, repo, number):
        key = self.number_keys.get(number)
        self.calls.append(("node_id", key, number))
        if (
            self.fail_node_id_for is not None
            and key == self.fail_node_id_for
            and number not in self.failed_node_ids
        ):
            self.failed_node_ids.add(number)
            raise tree.IssueTreeError("gh_failed", f"injected node_id failure for {key}")
        return f"G-{number}"

    def find_issue(self, owner, repo, marker):
        self.calls.append(("find", marker))
        return self.remote.get(marker)

    def issue_has_marker(self, owner, repo, number, marker):
        self.calls.append(("check", number, marker))
        return self.remote.get(marker) == number

    def dependency_exists(self, owner, repo, child_number, blocker_number):
        self.calls.append(("dependency_check", child_number, blocker_number))
        return (child_number, blocker_number) in self.remote_dependencies

    def _number(self):
        self.next_number += 1
        return self.next_number

    def _record_remote(self, key, issue):
        marker = issue["body"].split("<!-- ")[-1].split(" -->")[0]
        self.assert_projection_marker(marker)
        number = self._number()
        self.remote[marker] = number
        self.number_keys[number] = key
        return number

    def _create_remote(self, key, issue):
        number = self._record_remote(key, issue)
        if (
            key == self.lose_create_response_for
            and key not in self.lost_create_responses
        ):
            self.lost_create_responses.add(key)
            raise tree.IssueTreeError("gh_failed", f"injected lost create response for {key}")
        return number

    @staticmethod
    def assert_projection_marker(marker):
        if not marker.startswith("task-github-definition-node:v1:"):
            raise AssertionError(f"projection marker missing: {marker!r}")

    def create_root(self, root):
        self.calls.append(("root",))
        return self._create_remote("root", root)

    def create_child(self, repo_id, parent_id, child):
        self.calls.append(("child", child["key"]))
        if child["key"] == self.fail_child:
            raise tree.IssueTreeError("gh_failed", "injected child failure")
        return self._create_remote(child["key"], child)

    def add_dependency(self, owner, repo, child_number, blocker_number):
        self.calls.append(("dependency", child_number, blocker_number))
        self.remote_dependencies.add((child_number, blocker_number))
        return True


class ProjectionResumeTests(unittest.TestCase):
    def test_failure_checkpoints_and_resume_fills_missing_nodes_and_edges(self):
        artifact = worker.create_artifact(definition_spec())
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            first = FakeProjectionProvider(fail_child="U2")
            with self.assertRaisesRegex(tree.IssueTreeError, "injected"):
                tree.execute_projection(spec, artifact, state_path, provider=first)
            partial = da.read_json(state_path)
            self.assertFalse(da.projection_coverage(artifact, partial)["complete"])
            self.assertEqual([call[0:2] for call in first.calls if call[0] in {"root", "child"}], [
                ("root",), ("child", "U1"), ("child", "U2"),
            ])
            self.assertEqual([call for call in first.calls if call[0] == "find"], [])

            resumed = FakeProjectionProvider(start=200)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            self.assertTrue(result["projection_complete"])
            self.assertTrue(result["resumed"])
            final = da.read_json(state_path)
            self.assertTrue(all("status" not in node for node in final["nodes"].values()))
            self.assertTrue(all("status" not in edge for edge in final["dependencies"].values()))
            self.assertNotIn(("root",), resumed.calls)
            self.assertEqual([call for call in resumed.calls if call[0] == "child"], [("child", "U2")])
            self.assertEqual(len([call for call in resumed.calls if call[0] == "dependency"]), 1)
            self.assertEqual([call for call in resumed.calls if call[0] == "dependency_check"], [])

            no_writes = FakeProjectionProvider(start=300)
            result = tree.execute_projection(spec, artifact, state_path, provider=no_writes)
            self.assertTrue(result["projection_complete"])
            self.assertEqual(no_writes.calls, [])

    def test_post_create_root_node_id_failure_reuses_marker_issue_on_retry(self):
        artifact = worker.create_artifact({
            "definition_id": "root-reconcile",
            "root": {"title": "root", "body": "root"},
        })
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            first = FakeProjectionProvider(fail_node_id_for="root")
            with self.assertRaisesRegex(tree.IssueTreeError, "node_id failure"):
                tree.execute_projection(spec, artifact, state_path, provider=first)
            root_id = artifact["root"]["node_id"]
            partial = da.read_json(state_path)["nodes"][root_id]
            original_number = partial["number"]
            self.assertNotIn("status", partial)
            self.assertIn("marker", partial)

            resumed = FakeProjectionProvider(remote=first.remote, start=500)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            self.assertTrue(result["projection_complete"])
            self.assertEqual(result["root_number"], original_number)
            self.assertNotIn(("root",), resumed.calls)
            self.assertEqual([call[0] for call in resumed.calls].count("find"), 0)
            self.assertTrue(any(call[0] == "check" and call[1] == original_number for call in resumed.calls))

    def test_post_create_number_checkpoint_failure_scans_marker_and_reuses_issue(self):
        artifact = worker.create_artifact({
            "definition_id": "checkpoint-reconcile",
            "root": {"title": "root", "body": "root"},
        })
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            first = FakeProjectionProvider()
            real_write = da.write_json_atomic
            writes = 0

            def fail_number_checkpoint(*args, **kwargs):
                nonlocal writes
                writes += 1
                if writes == 3:
                    raise da.DefinitionError("write_failed", "injected number checkpoint failure")
                return real_write(*args, **kwargs)

            with mock.patch.object(da, "write_json_atomic", side_effect=fail_number_checkpoint):
                with self.assertRaisesRegex(da.DefinitionError, "checkpoint failure"):
                    tree.execute_projection(spec, artifact, state_path, provider=first)
            root_id = artifact["root"]["node_id"]
            partial = da.read_json(state_path)["nodes"][root_id]
            self.assertNotIn("number", partial)
            original_number = next(iter(first.remote.values()))

            resumed = FakeProjectionProvider(remote=first.remote, start=900)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            self.assertTrue(result["projection_complete"])
            self.assertEqual(result["root_number"], original_number)
            self.assertNotIn(("root",), resumed.calls)
            self.assertEqual([call[0] for call in resumed.calls].count("find"), 1)

    def test_lost_create_response_retry_finds_marker_and_reuses_root_issue(self):
        artifact = worker.create_artifact({
            "definition_id": "lost-response-reconcile",
            "root": {"title": "root", "body": "root"},
        })
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            first = FakeProjectionProvider(lose_create_response_for="root")
            with self.assertRaisesRegex(tree.IssueTreeError, "lost create response"):
                tree.execute_projection(spec, artifact, state_path, provider=first)

            root_id = artifact["root"]["node_id"]
            partial = da.read_json(state_path)["nodes"][root_id]
            self.assertNotIn("number", partial)
            self.assertNotIn("status", partial)
            original_number = next(iter(first.remote.values()))

            resumed = FakeProjectionProvider(remote=first.remote, start=900)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            self.assertTrue(result["projection_complete"])
            self.assertEqual(result["root_number"], original_number)
            self.assertNotIn(("root",), resumed.calls)
            self.assertEqual([call[0] for call in resumed.calls].count("find"), 1)

    def test_incomplete_legacy_checkpoint_without_marker_fails_closed(self):
        artifact = worker.create_artifact({
            "definition_id": "legacy-markerless",
            "root": {"title": "root", "body": "root"},
        })
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            state = tree._new_projection_state(artifact)
            state["owner"] = "owner"
            state["repo"] = "repo"
            state["nodes"][artifact["root"]["node_id"]] = {
                "key": "root",
                "number": 123,
                "status": "issue_created",
            }
            da.write_json_atomic(state_path, state)

            provider = FakeProjectionProvider()
            with self.assertRaisesRegex(tree.IssueTreeError, "no reconciliation marker"):
                tree.execute_projection(spec, artifact, state_path, provider=provider)
            self.assertEqual(
                [call for call in provider.calls if call[0] in {"root", "child"}],
                [],
            )
            self.assertEqual(provider.remote, {})

    def test_legacy_status_fields_are_ignored(self):
        artifact = worker.create_artifact(definition_spec())
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        state = complete_projection(artifact)
        for node in state["nodes"].values():
            node["status"] = "materialized"
        for edge in state["dependencies"].values():
            edge["status"] = "materialized"

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            da.write_json_atomic(state_path, state)
            provider = FakeProjectionProvider()
            result = tree.execute_projection(spec, artifact, state_path, provider=provider)

        self.assertTrue(result["projection_complete"])
        self.assertTrue(result["resumed"])
        self.assertEqual(provider.calls, [])

    def test_post_create_child_node_id_failure_reuses_marker_issue_on_retry(self):
        artifact = worker.create_artifact(definition_spec())
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            first = FakeProjectionProvider(fail_node_id_for="U2")
            with self.assertRaisesRegex(tree.IssueTreeError, "node_id failure"):
                tree.execute_projection(spec, artifact, state_path, provider=first)
            u2 = next(child for child in artifact["children"] if child["key"] == "U2")
            original_number = da.read_json(state_path)["nodes"][u2["node_id"]]["number"]

            resumed = FakeProjectionProvider(remote=first.remote, start=700)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            final = da.read_json(state_path)["nodes"][u2["node_id"]]
            self.assertTrue(result["projection_complete"])
            self.assertEqual(final["number"], original_number)
            self.assertNotIn(("child", "U2"), resumed.calls)
            self.assertEqual([call[0] for call in resumed.calls].count("find"), 0)
            self.assertTrue(any(call[0] == "check" and call[1] == original_number for call in resumed.calls))

    def test_post_add_dependency_checkpoint_failure_reuses_remote_edge_on_retry(self):
        artifact = worker.create_artifact(definition_spec())
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "projection.json"
            first = FakeProjectionProvider()
            real_write = da.write_json_atomic
            failed = False

            def fail_materialized_edge_checkpoint(path, value, **kwargs):
                nonlocal failed
                materialized = any(
                    isinstance(edge, dict) and edge.get("materialized") is True
                    for edge in value.get("dependencies", {}).values()
                )
                if materialized and not failed:
                    failed = True
                    raise da.DefinitionError("write_failed", "injected dependency checkpoint failure")
                return real_write(path, value, **kwargs)

            with mock.patch.object(da, "write_json_atomic", side_effect=fail_materialized_edge_checkpoint):
                with self.assertRaisesRegex(da.DefinitionError, "dependency checkpoint failure"):
                    tree.execute_projection(spec, artifact, state_path, provider=first)
            partial = da.read_json(state_path)
            edge = next(iter(partial["dependencies"].values()))
            remote_edge = (edge["child_number"], edge["blocked_by_number"])
            self.assertFalse(edge["materialized"])
            self.assertIn(remote_edge, first.remote_dependencies)

            resumed = FakeProjectionProvider(remote_dependencies=first.remote_dependencies)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            self.assertTrue(result["projection_complete"])
            self.assertEqual([call for call in resumed.calls if call[0] == "dependency"], [])
            self.assertEqual(
                [call[1:] for call in resumed.calls if call[0] == "dependency_check"],
                [remote_edge],
            )

    def test_record_none_fails_before_provider_is_touched(self):
        artifact = worker.create_artifact(definition_spec(delivery="local-ff"))
        artifact["schema"] = "task-github.definition/v1"
        artifact["record"] = "none"
        artifact["digest"] = worker.artifact_digest(artifact)
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        provider = FakeProjectionProvider()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(tree.IssueTreeError, "forbids"):
                tree.execute_projection(spec, artifact, Path(tmp) / "projection.json", provider=provider)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
