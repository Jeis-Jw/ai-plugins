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

DECISION_CLI_PATH = PLUGIN.parent / "context-decision/skills/decision/scripts/decision_cli.py"
DECISION_SPEC = importlib.util.spec_from_file_location("decision_cli_transactions", DECISION_CLI_PATH)
assert DECISION_SPEC and DECISION_SPEC.loader
decision_cli = importlib.util.module_from_spec(DECISION_SPEC)
sys.modules[DECISION_SPEC.name] = decision_cli
DECISION_SPEC.loader.exec_module(decision_cli)


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


def decision_candidate(candidate_id: str, decision: str) -> dict:
    return {
        "schema": "context-capture-candidate/v1",
        "candidate_id": candidate_id,
        "claim_key": "choice-1",
        "title": "인증 세션 소유권",
        "claim": decision,
        "summary": "OAuth callback과 cookie boundary를 한 경계로 통합한다.",
        "captured_from": "conversation",
        "requested_kind": "decision",
        "specialized_kinds": ["decision"],
        "fallback_kind": None,
        "scope_hint": "project/auth",
        "source_refs": ["conversation:test"],
        "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
        "tags": ["auth"],
        "owner_inputs": {
            "decision": {
                "decision": decision,
                "rationale": "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
                "rejected_alternatives": ["SPA token 소유: XSS 노출이 커져 반려"],
                "decision_key": "session-owner",
            }
        },
    }


def decision_attestation(candidate: dict) -> dict:
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": candidate["schema"],
        "input_digest": decision_cli.canonical_digest(candidate),
        "assertions": [
            {"name": "explicit_choice", "value": True, "evidence_pointers": ["/owner_inputs/decision/decision"]},
            {"name": "scope_identified", "value": True, "evidence_pointers": ["/scope_hint"]},
            {"name": "commitment_present", "value": True, "evidence_pointers": ["/evidence/0"]},
        ],
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

    def test_acceptance_23_preview(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            owner_result = observation_owner_result()
            before = tree_digest(repo)
            preview = context_cli.finalize_owner_result(repo, owner_result)
            self.assertEqual(before, tree_digest(repo))
            approval = preview["approval_preview"]
            self.assertEqual(owner_result["artifact_drafts"][0]["content"], approval["artifacts"][0]["content"])
            self.assertEqual(owner_result["artifact_drafts"][0]["path"], approval["artifacts"][0]["path"])
            self.assertEqual(owner_result["effects"], approval["effects"])
            self.assertEqual(preview["approval_digest"], preview["bundle"]["approval_digest"])
            frozen = copy.deepcopy(preview["bundle"])
            context_cli.apply_bundle(repo, frozen, preview["approval_digest"])
            self.assertEqual(frozen, preview["bundle"], "apply must not regenerate semantic material")

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

    def test_acceptance_24_digest(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            preview = context_cli.finalize_owner_result(repo, observation_owner_result())
            before = tree_digest(repo)
            variants = []
            changed_preview = copy.deepcopy(preview["bundle"])
            changed_preview["approval_material"]["preview"]["effects"][0]["state"] = "history"
            variants.append(changed_preview)
            changed_plan = copy.deepcopy(preview["bundle"])
            changed_plan["approval_material"]["plan"]["transition"] = "autonomous_maintenance"
            variants.append(changed_plan)
            changed_owner = copy.deepcopy(preview["bundle"])
            owner_material = next(item for item in changed_owner["materials"] if item["path"] is None)
            owner_material["content"] += " "
            variants.append(changed_owner)
            for bundle in variants:
                with self.subTest(bundle=bundle), self.assertRaises(context_cli.ContextError):
                    context_cli.apply_bundle(repo, bundle, preview["approval_digest"])
                self.assertEqual(before, tree_digest(repo))
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"], approval_source="autonomous")
            self.assertEqual("approval_required", caught.exception.code)
            self.assertEqual(before, tree_digest(repo))

    def test_acceptance_38_crash_resume(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            context_cli.apply_bundle(
                repo,
                (capture := context_cli.finalize_owner_result(repo, observation_owner_result()))["bundle"],
                capture["approval_digest"],
            )
            preview = context_cli.build_observation_invalidate_bundle(
                repo,
                "ctx_550e8400e29b41d4a716446655440000",
                "재현 전제가 사라짐",
                now="2026-08-14T09:00:00+09:00",
            )
            plan = preview["bundle"]["approval_material"]["plan"]
            move = next(operation for operation in plan["operations"] if operation["op"] == "file_move")
            materials = {item["material_id"]: item for item in preview["bundle"]["materials"]}
            destination = repo / move["to_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(context_cli.file_bytes(materials[move["material"]]["content"]))
            self.assertTrue((repo / move["from_path"]).exists())
            result = context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            self.assertTrue(result["applied"])
            self.assertFalse((repo / move["from_path"]).exists())
            self.assertTrue(destination.exists())
            repeated = context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            self.assertEqual([], repeated["changed_paths"])

    def test_decision_supersede_preview_matches_applied_repository_index(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            decision_init = decision_cli.build_init_plan()
            registration = context_cli.build_area_register_bundle(
                repo, decision_init["owner_descriptor"], decision_init["index_seed"]
            )
            context_cli.apply_bundle(repo, registration["bundle"], registration["approval_digest"])

            predecessor_candidate = decision_candidate(
                "cand_550e8400e29b41d4a716446655440000",
                "인증 세션은 BFF가 소유한다.",
            )
            predecessor = decision_cli.build_claim_result(
                predecessor_candidate,
                decision_attestation(predecessor_candidate),
                identifier="ctx_550e8400e29b41d4a716446655440000",
                created_at="2026-08-13T18:20:00+09:00",
            )
            predecessor_validation = decision_cli.validate_batch(repo, predecessor)
            capture = context_cli.finalize_owner_result(repo, predecessor, predecessor_validation)
            context_cli.apply_bundle(repo, capture["bundle"], capture["approval_digest"])

            successor_candidate = decision_candidate(
                "cand_550e8400e29b41d4a716446655440001",
                "인증 세션은 auth service가 소유한다.",
            )
            successor = decision_cli.build_supersede_result(
                repo,
                "ctx_550e8400e29b41d4a716446655440000",
                successor_candidate,
                decision_attestation(successor_candidate),
                identifier="ctx_123e4567e89b42d3a456426614174001",
                retired_at="2026-08-14T09:00:00+09:00",
            )
            validation = decision_cli.validate_batch(repo, successor)
            preview = context_cli.finalize_owner_result(repo, successor, validation)
            index_operation = next(
                operation
                for operation in preview["bundle"]["approval_material"]["plan"]["operations"]
                if operation["op"] == "index_rebuild"
            )
            index_path = "context/decision/decision.index.md"

            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])

            applied = (repo / index_path).read_text(encoding="utf-8")
            regenerated = context_cli.render_area_index_from_repository(repo, "decision")
            self.assertEqual(
                index_operation["after_sha256"][index_path],
                context_cli.sha256_bytes(context_cli.file_bytes(applied)),
            )
            self.assertEqual(applied, regenerated)

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
