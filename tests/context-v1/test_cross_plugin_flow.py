#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


context_cli = load("context_cli_cross", ROOT / "plugins/context-core/skills/context/scripts/context_cli.py")
decision_cli = load("decision_cli_cross", ROOT / "plugins/context-decision/skills/decision/scripts/decision_cli.py")


def initialize(repo: Path) -> None:
    core = context_cli.build_init_bundle(repo)
    context_cli.apply_bundle(repo, core["bundle"], core["approval_digest"])
    addon = decision_cli.build_init_plan()
    area = context_cli.build_area_register_bundle(repo, addon["owner_descriptor"], addon["index_seed"])
    context_cli.apply_bundle(repo, area["bundle"], area["approval_digest"])


def choice(candidate_id: str = "cand_550e8400e29b41d4a716446655440000", claim_key: str = "choice", *, informed_by: list[str] | None = None) -> dict:
    value = {
        "schema": "context-capture-candidate/v1",
        "candidate_id": candidate_id,
        "claim_key": claim_key,
        "title": "인증 세션 소유권",
        "claim": "인증 세션은 BFF가 소유한다.",
        "summary": "OAuth callback과 cookie 경계를 BFF로 통합한다.",
        "captured_from": "conversation",
        "requested_kind": None,
        "specialized_kinds": ["decision"],
        "fallback_kind": "observation",
        "scope_hint": "project/auth",
        "source_refs": ["conversation:test"],
        "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
        "owner_inputs": {
            "decision": {
                "decision": "인증 세션은 BFF가 소유한다.",
                "rationale": "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
                "rejected_alternatives": ["SPA token 소유: XSS 노출이 커져 반려"],
                "decision_key": "session-owner",
            },
            "observation": {
                "observation": "대화에서 인증 세션을 BFF가 소유하기로 합의했다는 진술이 있었다.",
                "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
            },
        },
    }
    if informed_by:
        value["informed_by"] = informed_by
    return value


def decision_attestation(value: dict) -> dict:
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": value["schema"],
        "input_digest": decision_cli.canonical_digest(value),
        "assertions": [
            {"name": "explicit_choice", "value": True, "evidence_pointers": ["/owner_inputs/decision/decision"]},
            {"name": "scope_identified", "value": True, "evidence_pointers": ["/scope_hint"]},
            {"name": "commitment_present", "value": True, "evidence_pointers": ["/evidence/0"]},
        ],
    }


def obs_attestation(value: dict) -> dict:
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": value["schema"],
        "input_digest": context_cli.canonical_digest(value),
        "assertions": [
            {"name": "reusable_observation", "value": True, "evidence_pointers": ["/owner_inputs/observation/observation"]},
            {"name": "evidence_present", "value": True, "evidence_pointers": ["/owner_inputs/observation/evidence/0"]},
        ],
    }


class CrossPluginFlowTests(unittest.TestCase):
    def test_acceptance_18_owner_installed(self) -> None:
        value = choice()
        owner_result = decision_cli.build_claim_result(value, decision_attestation(value))
        capabilities = context_cli.capabilities_result()
        capabilities["owners"].append(decision_cli.decision_capability())
        routed = context_cli.route_candidates([value], capabilities, [owner_result])
        self.assertEqual(1, len(routed["routes"]))
        self.assertEqual("context-decision", routed["routes"][0]["owner"])
        self.assertEqual("decision", routed["routes"][0]["target_kind"])

    def test_acceptance_21_independent_claims(self) -> None:
        decision = choice()
        observation = {
            **choice("cand_123e4567e89b42d3a456426614174000", "fact"),
            "requested_kind": "observation",
            "specialized_kinds": ["observation"],
            "fallback_kind": None,
            "claim": "Safari에서 third-party cookie가 차단된다.",
        }
        observation["owner_inputs"] = {"observation": {"observation": observation["claim"], "evidence": ["재현 fixture"]}}
        dec_result = decision_cli.build_claim_result(decision, decision_attestation(decision))
        obs_result = context_cli.draft_owner_result(observation, obs_attestation(observation))
        capabilities = context_cli.capabilities_result()
        capabilities["owners"].append(decision_cli.decision_capability())
        routed = context_cli.route_candidates([observation, decision], capabilities, [obs_result, dec_result])
        self.assertEqual(["observation", "decision"], [item["target_kind"] for item in routed["routes"]])

    def test_acceptance_31_evidence_relation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            initialize(repo)
            obs_candidate = {
                **choice("cand_123e4567e89b42d3a456426614174000", "fact"),
                "requested_kind": "observation",
                "specialized_kinds": ["observation"],
                "fallback_kind": None,
                "title": "Safari cookie 관찰",
                "claim": "Safari에서 third-party cookie가 차단된다.",
                "summary": "Safari cookie 제한을 재현했다.",
            }
            obs_candidate["owner_inputs"] = {"observation": {"observation": obs_candidate["claim"], "evidence": ["재현 fixture"]}}
            obs_result = context_cli.draft_owner_result(obs_candidate, obs_attestation(obs_candidate), now="2026-08-14T09:00:00+09:00")
            obs_bundle = context_cli.finalize_owner_result(repo, obs_result)
            context_cli.apply_bundle(repo, obs_bundle["bundle"], obs_bundle["approval_digest"])
            obs_id = obs_result["effects"][0]["id"]

            value = choice(informed_by=[obs_id])
            dec_result = decision_cli.build_claim_result(value, decision_attestation(value), repo=repo)
            receipt = decision_cli.validate_batch(repo, dec_result)
            dec_bundle = context_cli.finalize_owner_result(repo, dec_result, receipt)
            context_cli.apply_bundle(repo, dec_bundle["bundle"], dec_bundle["approval_digest"])
            self.assertEqual("current", context_cli.observation_read(repo, obs_id)["state"])
            dec_id = dec_result["effects"][0]["id"]
            decision = decision_cli.read_decision(repo, dec_id)
            self.assertEqual([obs_id], decision_cli.find_current(repo, dec_id)["frontmatter"]["relations"]["informed_by"])

    def test_acceptance_32_fallback_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            initialize(repo)
            fallback = choice()
            fallback["requested_kind"] = "observation"
            fallback["specialized_kinds"] = ["observation"]
            fallback["fallback_kind"] = None
            fallback["kind_hint"] = "decision"
            fallback["owner_inputs"] = {"observation": fallback["owner_inputs"]["observation"]}
            obs_result = context_cli.draft_owner_result(fallback, obs_attestation(fallback), now="2026-08-14T09:00:00+09:00")
            obs_bundle = context_cli.finalize_owner_result(repo, obs_result)
            context_cli.apply_bundle(repo, obs_bundle["bundle"], obs_bundle["approval_digest"])
            obs_id = obs_result["effects"][0]["id"]

            dec_candidate = choice("cand_123e4567e89b42d3a456426614174000", "choice-import")
            dec_result = decision_cli.build_claim_result(dec_candidate, decision_attestation(dec_candidate), repo=repo)
            lifecycle = context_cli.prepare_lifecycle_input(repo, "decision_fallback_import", obs_id, dec_result)
            same_claim = {
                "schema": "context-semantic-attestation/v1",
                "operation": "same_claim",
                "input_schema": lifecycle["schema"],
                "input_digest": decision_cli.canonical_digest(lifecycle),
                "assertions": [{"name": "same_semantic_claim", "value": True, "evidence_pointers": ["/predecessor/primary_claim", "/successor/primary_claim"]}],
            }
            imported = decision_cli.build_fallback_import_result(repo, obs_id, dec_result, lifecycle, same_claim, retired_at="2026-08-14T10:00:00+09:00")
            receipt = decision_cli.validate_batch(repo, imported)
            bundle = context_cli.finalize_owner_result(repo, imported, receipt)
            self.assertEqual({"decision", "observation"}, {effect["area"] for effect in bundle["approval_preview"]["effects"]})
            context_cli.apply_bundle(repo, bundle["bundle"], bundle["approval_digest"])
            self.assertEqual("history", context_cli.observation_read(repo, obs_id)["state"])
            dec_id = next(effect["id"] for effect in imported["effects"] if effect["area"] == "decision")
            self.assertIn(obs_id, decision_cli.find_current(repo, dec_id)["frontmatter"]["supersedes"])

    def test_acceptance_37_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            core = context_cli.build_init_bundle(repo)
            context_cli.apply_bundle(repo, core["bundle"], core["approval_digest"])

            def make(number: int) -> dict:
                value = {
                    **choice(f"cand_550e8400e29b41d4a71644665544{number:04x}", f"fact-{number}"),
                    "requested_kind": "observation",
                    "specialized_kinds": ["observation"],
                    "fallback_kind": None,
                    "title": f"병렬 관찰 {number}",
                    "claim": f"병렬 claim {number}",
                    "summary": f"병렬 capture {number}",
                }
                value["owner_inputs"] = {"observation": {"observation": value["claim"], "evidence": [f"fixture {number}"]}}
                return context_cli.draft_owner_result(value, obs_attestation(value), now=f"2026-08-14T09:00:0{number}+09:00")

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(make, (1, 2)))
            bundles = []
            for result in results:
                bundle = context_cli.finalize_owner_result(repo, result, prior_bundles=bundles)
                context_cli.apply_bundle(repo, bundle["bundle"], bundle["approval_digest"])
                bundles.append(bundle["bundle"])
            index = context_cli.parse_area_index((repo / "context/observation/observation.index.md").read_text(encoding="utf-8"))
            self.assertEqual(2, len(index.current))
            self.assertEqual(2, len({row["id"] for row in index.current}))


if __name__ == "__main__":
    unittest.main()
