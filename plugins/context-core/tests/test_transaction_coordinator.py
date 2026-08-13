#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli_transactions", CLI_PATH)
assert SPEC and SPEC.loader
context_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_cli
SPEC.loader.exec_module(context_cli)


def git_repo() -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", temp.name], check=True)
    return temp


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize(repo: Path) -> None:
    result = context_cli.build_init_bundle(repo)
    context_cli.apply_bundle(repo, result["bundle"], result["approval_digest"])


def observation_owner_result(identifier: str = "ctx_550e8400e29b41d4a716446655440000") -> dict:
    capability = context_cli.builtin_capability("observation")
    candidate = {
        "schema": "context-capture-candidate/v1",
        "candidate_id": "cand_550e8400e29b41d4a716446655440000",
        "claim_key": "direct",
        "title": "Cookie 전달 관찰",
        "claim": "Safari에서 cookie 전달이 차단된다.",
        "summary": "Safari cookie 전달 실패를 재현했다.",
        "captured_from": "workspace",
        "requested_kind": "observation",
        "specialized_kinds": ["observation"],
        "fallback_kind": None,
        "owner_inputs": {"observation": {"observation": "Safari에서 cookie 전달이 차단된다.", "evidence": ["integration fixture"]}},
    }
    input_digest = context_cli.canonical_digest(candidate)
    fingerprint = context_cli.claim_fingerprint("observation", "", candidate["claim"])
    content = context_cli.render_document(
        {
            "schema": "context-observation/v1",
            "id": identifier,
            "title": candidate["title"],
            "summary": candidate["summary"],
            "created_at": "2026-08-13T18:20:00+09:00",
            "captured_from": "workspace",
            "claim_fingerprint": fingerprint,
        },
        {"관찰": candidate["claim"], "근거": "integration fixture"},
    )
    return {
        "schema": "context-owner-result/v1",
        "result_type": "claim",
        "transition": "capture",
        "owner": "context-core",
        "target_kind": "observation",
        "candidate_id": candidate["candidate_id"],
        "decision": "claim",
        "reason": "reusable evidence",
        "capability_digest": context_cli.canonical_digest(capability),
        "semantic_inputs": [{"operation": "claim", "input_schema": candidate["schema"], "input_digest": input_digest, "value": candidate}],
        "semantic_attestations": [{
            "schema": "context-semantic-attestation/v1",
            "operation": "claim",
            "input_schema": candidate["schema"],
            "input_digest": input_digest,
            "assertions": [
                {"name": "reusable_observation", "value": True, "evidence_pointers": ["/owner_inputs/observation/observation"]},
                {"name": "evidence_present", "value": True, "evidence_pointers": ["/owner_inputs/observation/evidence/0"]},
            ],
        }],
        "artifact_drafts": [{
            "effect_id": "effect_create_observation",
            "path": "context/observation/Cookie-전달-관찰.md",
            "content": content,
            "semantic_projection": {"kind": "observation", "primary_claim": candidate["claim"], "claim_fingerprint": fingerprint, "supporting_context": ["integration fixture"]},
        }],
        "effects": [{"effect_id": "effect_create_observation", "action": "create", "area": "observation", "id": identifier, "state": "current"}],
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": "capture", "operations": [{"op": "create", "effect_id": "effect_create_observation", "area": "observation", "path": "context/observation/Cookie-전달-관찰.md"}]},
    }


class TransactionCoordinatorTests(unittest.TestCase):
    def test_acceptance_01_init_is_idempotent(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            preview = context_cli.build_init_bundle(repo)
            before = tree_digest(repo)
            self.assertEqual(before, tree_digest(repo), "preview must not write")
            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            after_first = tree_digest(repo)
            second = context_cli.build_init_bundle(repo)
            self.assertTrue(second["noop"])
            self.assertNotIn("bundle", second)
            self.assertEqual(after_first, tree_digest(repo))

    def test_acceptance_05_rename_identity(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            capture = context_cli.finalize_owner_result(repo, observation_owner_result())
            context_cli.apply_bundle(repo, capture["bundle"], capture["approval_digest"])
            rename = context_cli.build_rename_bundle(repo, "ctx_550e8400e29b41d4a716446655440000", "새 이름.md")
            context_cli.apply_bundle(repo, rename["bundle"], rename["approval_digest"])
            old_path = repo / "context/observation/Cookie-전달-관찰.md"
            new_path = repo / "context/observation/새 이름.md"
            self.assertFalse(old_path.exists())
            self.assertEqual("ctx_550e8400e29b41d4a716446655440000", context_cli.parse_document(new_path.read_text(encoding="utf-8")).frontmatter["id"])
            index = context_cli.parse_area_index((repo / "context/observation/observation.index.md").read_text(encoding="utf-8"))
            self.assertEqual("context/observation/새 이름.md", index.current[0]["path"])

    def test_owner_result_becomes_final_bundle_and_only_core_applies(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            owner_result = observation_owner_result()
            preview = context_cli.finalize_owner_result(repo, owner_result)
            self.assertEqual("context-mutation-bundle/v1", preview["bundle"]["schema"])
            plan = preview["bundle"]["approval_material"]["plan"]
            self.assertEqual("owner_result", plan["source_type"])
            self.assertEqual({"file_create", "index_rebuild"}, {operation["op"] for operation in plan["operations"]})
            self.assertFalse((repo / owner_result["artifact_drafts"][0]["path"]).exists())
            applied = context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            self.assertTrue(applied["applied"])
            self.assertTrue((repo / owner_result["artifact_drafts"][0]["path"]).exists())

    def test_approval_digest_material_and_hidden_operations_fail_closed(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            preview = context_cli.finalize_owner_result(repo, observation_owner_result())
            before = tree_digest(repo)
            with self.assertRaises(context_cli.ContextError) as digest_error:
                context_cli.apply_bundle(repo, preview["bundle"], "sha256:" + "0" * 64)
            self.assertEqual("approval_digest_mismatch", digest_error.exception.code)

            tampered = copy.deepcopy(preview["bundle"])
            next(material for material in tampered["materials"] if material["path"] is not None)["content"] += "tamper\n"
            with self.assertRaises(context_cli.ContextError) as material_error:
                context_cli.apply_bundle(repo, tampered, preview["approval_digest"])
            self.assertEqual("material_digest_mismatch", material_error.exception.code)

            hidden = copy.deepcopy(preview["bundle"])
            hidden["approval_material"]["plan"]["operations"].insert(0, copy.deepcopy(hidden["approval_material"]["plan"]["operations"][0]))
            hidden["approval_digest"] = context_cli.canonical_digest(hidden["approval_material"])
            with self.assertRaises(context_cli.ContextError) as hidden_error:
                context_cli.apply_bundle(repo, hidden, hidden["approval_digest"])
            self.assertEqual("plan_preview_mismatch", hidden_error.exception.code)
            self.assertEqual(before, tree_digest(repo))

    def test_owner_area_allowlist_and_seed_requirements_fail_closed(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            invalid = observation_owner_result()
            invalid["owner"] = "context-decision"
            with self.assertRaises(context_cli.ContextError) as owner_error:
                context_cli.finalize_owner_result(repo, invalid)
            self.assertEqual("area_owner_mismatch", owner_error.exception.code)
            descriptor = {"schema": "context-owner-descriptor/v1", "owner": "context-decision", "kind": "decision", "artifact_schema": "context-decision/v1", "authority": "authoritative"}
            with self.assertRaises(context_cli.ContextError) as seed_error:
                context_cli.build_area_register_bundle(repo, descriptor, None)
            self.assertEqual("index_seed_required", seed_error.exception.code)

    def test_exact_precondition_blocks_changed_target(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            capture = context_cli.finalize_owner_result(repo, observation_owner_result())
            target = repo / "context/observation/Cookie-전달-관찰.md"
            target.write_text("out-of-band\n", encoding="utf-8")
            before = tree_digest(repo)
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.apply_bundle(repo, capture["bundle"], capture["approval_digest"])
            self.assertEqual("precondition_changed", caught.exception.code)
            self.assertEqual(before, tree_digest(repo))

    def test_index_fix_is_approval_gated_and_document_authoritative(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            artifact = repo / "context/observation/out-of-band.md"
            artifact.write_text(
                context_cli.render_document(
                    {
                        "schema": "context-observation/v1",
                        "id": "ctx_550e8400e29b41d4a716446655440001",
                        "title": "Out-of-band observation",
                        "summary": "Index repair must derive this row from the document.",
                        "created_at": "2026-08-13T18:21:00+09:00",
                        "captured_from": "workspace",
                        "claim_fingerprint": context_cli.claim_fingerprint(
                            "observation", "", "Out-of-band observation"
                        ),
                    },
                    {"관찰": "Out-of-band observation", "근거": "integration fixture"},
                ),
                encoding="utf-8",
            )
            before = tree_digest(repo)
            preview = context_cli.build_index_fix_bundle(repo)
            self.assertEqual(before, tree_digest(repo), "index fix preview must not write")
            self.assertFalse(preview["noop"])
            self.assertEqual("index_fix", preview["bundle"]["approval_material"]["plan"]["transition"])
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.apply_bundle(repo, preview["bundle"], "sha256:" + "0" * 64)
            self.assertEqual("approval_digest_mismatch", caught.exception.code)
            self.assertEqual(before, tree_digest(repo))

            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            self.assertTrue(context_cli.refresh_repository(repo, strict=True)["ok"])
            area_index = context_cli.parse_area_index(
                (repo / "context/observation/observation.index.md").read_text(encoding="utf-8")
            )
            self.assertEqual(["ctx_550e8400e29b41d4a716446655440001"], [row["id"] for row in area_index.current])

    def test_schema_runs_without_repository_and_has_no_root_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            completed = subprocess.run(["python3", str(CLI_PATH), "schema", "--json"], cwd=temp, text=True, capture_output=True)
            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result["ok"])
            self.assertEqual("context-common/v1", result["result"]["protocol"])
            self.assertNotIn("--root", completed.stdout)


if __name__ == "__main__":
    unittest.main()
