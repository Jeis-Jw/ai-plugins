import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "define" / "scripts"))

import definition_artifact as da  # noqa: E402
import create_issue_tree as tree  # noqa: E402


def definition_spec(*, record="none", delivery="local-ff"):
    return {
        "definition_id": "payments-v1",
        "record": record,
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


class DefinitionArtifactTests(unittest.TestCase):
    def test_revision_chain_keeps_ids_and_pins_previous_digest(self):
        first = da.create_artifact(definition_spec(), created_at="2026-07-10T00:00:00Z")
        revised_spec = definition_spec()
        revised_spec["children"][0]["body"] += "\nchanged"
        second = da.create_artifact(
            revised_spec, previous=first, created_at="2026-07-10T00:01:00Z"
        )

        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["previous_digest"], first["digest"])
        self.assertEqual(second["root"]["node_id"], first["root"]["node_id"])
        self.assertEqual(
            [child["node_id"] for child in second["children"]],
            [child["node_id"] for child in first["children"]],
        )
        da.validate_artifact(second, previous=first)

        tampered = json.loads(json.dumps(second))
        tampered["root"]["title"] = "tampered"
        with self.assertRaisesRegex(da.DefinitionError, "digest"):
            da.validate_artifact(tampered)

    def test_store_never_overwrites_an_immutable_revision(self):
        artifact = da.create_artifact(definition_spec(), created_at="2026-07-10T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            path = da.store_artifact(tmp, artifact)
            self.assertEqual(path, da.store_artifact(tmp, artifact))
            changed = json.loads(json.dumps(artifact))
            changed["created_at"] = "2026-07-10T01:00:00Z"
            changed["digest"] = da.artifact_digest(changed)
            with self.assertRaisesRegex(da.DefinitionError, "overwrite"):
                da.store_artifact(tmp, changed)

    def test_local_lifecycle_has_stable_identity_dependency_gate_and_recovery(self):
        artifact = da.create_artifact(definition_spec(), created_at="2026-07-10T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(da.DefinitionError, "blockers"):
                da.start_local_run(artifact, node_ref="U2", state_dir=tmp)

            first, first_path, created = da.start_local_run(
                artifact, node_ref="U1", state_dir=tmp, now="2026-07-10T00:00:00Z"
            )
            self.assertTrue(created)
            self.assertEqual(first["identity"], da.execution_identity(artifact, "U1"))
            for event, at in (
                ("run", "2026-07-10T00:00:01Z"),
                ("verify", "2026-07-10T00:00:02Z"),
                ("done", "2026-07-10T00:00:03Z"),
                ("closeout", "2026-07-10T00:00:04Z"),
            ):
                first, _ = da.transition_local_run(artifact, first, event, now=at)
            da.write_json_atomic(first_path, first)

            second, _, _ = da.start_local_run(artifact, node_ref="U2", state_dir=tmp)
            self.assertEqual(da.recover_local_run(artifact, second)["next_event"], "run")
            same, _, created = da.start_local_run(
                artifact, node_ref="U2", state_dir=tmp, run_id=second["run_id"]
            )
            self.assertFalse(created)
            self.assertEqual(same["identity"], second["identity"])

            with self.assertRaisesRegex(da.DefinitionError, "children"):
                da.start_local_run(artifact, node_ref="root", state_dir=tmp)

            revised = da.create_artifact(definition_spec(), previous=artifact)
            with self.assertRaisesRegex(da.DefinitionError, "pin"):
                da.recover_local_run(revised, second)

    def test_record_github_requires_full_projection_but_record_none_does_not(self):
        local = da.create_artifact(definition_spec(record="none"))
        github = da.create_artifact(definition_spec(record="github"))
        with tempfile.TemporaryDirectory() as tmp:
            da.start_local_run(local, node_ref="U1", state_dir=Path(tmp) / "local")
            with self.assertRaisesRegex(da.DefinitionError, "full projection"):
                da.start_local_run(github, node_ref="U1", state_dir=Path(tmp) / "github")
            state, _, _ = da.start_local_run(
                github, node_ref="U1", state_dir=Path(tmp) / "github",
                projection=complete_projection(github),
            )
            self.assertEqual(state["record"], "github")

    def test_receipt_preserves_unknown_tokens_as_null_unavailable(self):
        artifact = da.create_artifact({
            "definition_id": "single-work",
            "root": {"title": "single", "body": "single"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            state, _, _ = da.start_local_run(
                artifact, node_ref="root", state_dir=tmp, run_id="run-single",
                now="2026-07-10T00:00:00Z",
            )
            for event, at in (
                ("run", "2026-07-10T00:00:01Z"),
                ("verify", "2026-07-10T00:00:02Z"),
                ("done", "2026-07-10T00:00:03Z"),
                ("closeout", "2026-07-10T00:00:04Z"),
            ):
                state, _ = da.transition_local_run(artifact, state, event, now=at)
        receipt = da.build_receipt(state, counters={"github_writes": 0}, quality={"passed": True})
        self.assertEqual(set(receipt), {
            "schema", "emitter", "workflow", "run_id", "started_at", "finished_at",
            "elapsed_ms", "tokens", "token_coverage", "counters", "quality",
        })
        self.assertIsNone(receipt["tokens"])
        self.assertEqual(receipt["token_coverage"], "unavailable")
        self.assertEqual(receipt["elapsed_ms"], 4000)
        with self.assertRaisesRegex(da.DefinitionError, "unavailable"):
            da.build_receipt(state, token_coverage="measured")
        known = da.build_receipt(state, tokens=42)
        self.assertEqual(known["token_coverage"], "exact")
        with self.assertRaisesRegex(da.DefinitionError, "exact"):
            da.build_receipt(state, tokens=42, token_coverage="measured")

    def test_legacy_issue_identity_is_unchanged(self):
        self.assertEqual(da.legacy_issue_identity(58), {
            "branch": "task/issue-58",
            "worktree": ".worktrees/issue-58",
        })

    def test_public_lifecycle_skills_expose_record_none_artifact_mode(self):
        for skill in ("start", "run", "verify", "done"):
            text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=skill):
                self.assertIn("record:none DefinitionArtifact mode", text)
                self.assertIn("--artifact", text)
                self.assertIn("definition_artifact.py", text)
                self.assertIn("Issue 경로", text)
        self.assertIn("--node", (PLUGIN / "skills" / "start" / "SKILL.md").read_text())
        for skill in ("run", "verify", "done"):
            self.assertIn(
                "--run-state",
                (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"),
            )


class FakeProjectionProvider:
    def __init__(
        self, *, fail_child=None, fail_node_id_for=None, start=100,
        remote=None, remote_dependencies=None,
    ):
        self.fail_child = fail_child
        self.fail_node_id_for = fail_node_id_for
        self.next_number = start
        self.calls = []
        self.remote = remote if remote is not None else {}
        self.remote_dependencies = remote_dependencies if remote_dependencies is not None else set()
        self.number_keys = {}
        self.failed_node_ids = set()

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

    @staticmethod
    def assert_projection_marker(marker):
        if not marker.startswith("task-github-definition-node:v1:"):
            raise AssertionError(f"projection marker missing: {marker!r}")

    def create_root(self, root):
        self.calls.append(("root",))
        return self._record_remote("root", root)

    def create_child(self, repo_id, parent_id, child):
        self.calls.append(("child", child["key"]))
        if child["key"] == self.fail_child:
            raise tree.IssueTreeError("gh_failed", "injected child failure")
        return self._record_remote(child["key"], child)

    def add_dependency(self, owner, repo, child_number, blocker_number):
        self.calls.append(("dependency", child_number, blocker_number))
        self.remote_dependencies.add((child_number, blocker_number))
        return True


class ProjectionResumeTests(unittest.TestCase):
    def test_failure_checkpoints_and_resume_fills_missing_nodes_and_edges(self):
        artifact = da.create_artifact(definition_spec(record="github"))
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
            self.assertNotIn(("root",), resumed.calls)
            self.assertEqual([call for call in resumed.calls if call[0] == "child"], [("child", "U2")])
            self.assertEqual(len([call for call in resumed.calls if call[0] == "dependency"]), 1)
            self.assertEqual([call for call in resumed.calls if call[0] == "dependency_check"], [])

            no_writes = FakeProjectionProvider(start=300)
            result = tree.execute_projection(spec, artifact, state_path, provider=no_writes)
            self.assertTrue(result["projection_complete"])
            self.assertEqual(no_writes.calls, [])

    def test_post_create_root_node_id_failure_reuses_marker_issue_on_retry(self):
        artifact = da.create_artifact({
            "definition_id": "root-reconcile",
            "record": "github",
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
            self.assertEqual(partial["status"], "issue_created")
            self.assertIn("marker", partial)

            resumed = FakeProjectionProvider(remote=first.remote, start=500)
            result = tree.execute_projection(spec, artifact, state_path, provider=resumed)
            self.assertTrue(result["projection_complete"])
            self.assertEqual(result["root_number"], original_number)
            self.assertNotIn(("root",), resumed.calls)
            self.assertEqual([call[0] for call in resumed.calls].count("find"), 0)
            self.assertTrue(any(call[0] == "check" and call[1] == original_number for call in resumed.calls))

    def test_post_create_number_checkpoint_failure_scans_marker_and_reuses_issue(self):
        artifact = da.create_artifact({
            "definition_id": "checkpoint-reconcile",
            "record": "github",
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

    def test_post_create_child_node_id_failure_reuses_marker_issue_on_retry(self):
        artifact = da.create_artifact(definition_spec(record="github"))
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
        artifact = da.create_artifact(definition_spec(record="github"))
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
        artifact = da.create_artifact(definition_spec(record="none"))
        spec = tree.validate_spec(da.artifact_to_issue_spec(artifact))
        provider = FakeProjectionProvider()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(tree.IssueTreeError, "forbids"):
                tree.execute_projection(spec, artifact, Path(tmp) / "projection.json", provider=provider)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
