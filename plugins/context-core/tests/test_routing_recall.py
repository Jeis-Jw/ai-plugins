#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli_routing", CLI_PATH)
assert SPEC and SPEC.loader
context_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_cli
SPEC.loader.exec_module(context_cli)


def candidate(candidate_id: str, claim_key: str, *, requested: str | None = None, specialized: list[str] | None = None, fallback: str | None = "observation") -> dict:
    return {
        "schema": "context-capture-candidate/v1",
        "candidate_id": candidate_id,
        "claim_key": claim_key,
        "title": "인증 세션 소유권",
        "claim": "인증 세션은 BFF가 소유한다.",
        "summary": "인증 세션 경계를 BFF로 통합한다.",
        "captured_from": "conversation",
        "requested_kind": requested,
        "specialized_kinds": specialized or ["decision"],
        "fallback_kind": fallback,
        "scope_hint": "project/auth",
        "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
        "owner_inputs": {
            "decision": {
                "decision": "인증 세션은 BFF가 소유한다.",
                "rationale": "cookie 경계를 서버로 모은다.",
                "rejected_alternatives": ["SPA token 소유: 노출 범위가 커져 반려"],
                "decision_key": "session-owner",
            },
            "observation": {
                "observation": "대화에서 BFF 소유 합의가 있었다.",
                "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
            },
        },
    }


def result(value: dict, capability: dict, decision: str, *, owner: str | None = None, kind: str | None = None) -> dict:
    return {
        "schema": "context-owner-result/v1",
        "result_type": "claim",
        "transition": "capture",
        "owner": owner or capability["owner"],
        "target_kind": kind or capability["kind"],
        "candidate_id": value["candidate_id"],
        "decision": decision,
        "reason": "fixture result",
        "capability_digest": context_cli.canonical_digest(capability),
        "semantic_inputs": [{
            "operation": "claim",
            "input_schema": value["schema"],
            "input_digest": context_cli.canonical_digest(value),
            "value": value,
        }],
        "semantic_attestations": [],
        "artifact_drafts": [],
        "effects": [],
        "proposed_plan": None,
    }


def decision_capability() -> dict:
    return {
        "schema": "context-owner-capability/v1",
        "owner": "context-decision",
        "kind": "decision",
        "artifact_schema": "context-decision/v1",
        "authority": "authoritative",
        "claim_surface": {"type": "agent_skill", "name": "context-decision:decision", "operation": "claim"},
        "batch_validation_surface": {"type": "cli", "command": "decision_cli.py batch validate"},
        "claim_rule": "accepted choice",
        "claim_assertions": ["explicit_choice", "scope_identified", "commitment_present"],
        "lifecycle_operations": {"same_claim": {"surface": {"type": "agent_skill", "name": "context-decision:decision", "operation": "same_claim"}, "rule": "same claim", "assertions": ["same_semantic_claim"]}},
        "draft_fields": {
            "required": {
                "decision": {"type": "string", "min_chars": 1, "max_chars": 1200},
                "rationale": {"type": "string", "min_chars": 1, "max_chars": 1200},
                "rejected_alternatives": {"type": "string_list", "min_items": 1, "max_items": 8, "max_item_chars": 500},
                "decision_key": {"type": "string", "min_chars": 1, "max_chars": 80},
            },
            "optional": {},
        },
    }


class RoutingRecallTests(unittest.TestCase):
    def test_acceptance_19_unavailable(self) -> None:
        value = candidate("cand_550e8400e29b41d4a716446655440000", "choice", requested="decision")
        routed = context_cli.route_candidates([value], context_cli.capabilities_result(), [])
        self.assertEqual("owner_unavailable", routed["routes"][0]["status"])
        self.assertNotEqual("observation", routed["routes"][0].get("target_kind"))

        specialized = candidate("cand_123e4567e89b42d3a456426614174000", "choice_two")
        capabilities = context_cli.capabilities_result()
        capabilities["owners"].append(decision_capability())
        fallback_capability = context_cli.builtin_capability("observation")
        fallback_result = result(specialized, fallback_capability, "decline")
        routed = context_cli.route_candidates([specialized], capabilities, [fallback_result])
        self.assertEqual("owner_unavailable", routed["routes"][0]["status"])
        self.assertEqual("specialized_owner_result_missing", routed["routes"][0]["reason"])

    def test_acceptance_20_invalid_type(self) -> None:
        value = candidate("cand_550e8400e29b41d4a716446655440000", "fact", requested="decision")
        capability = decision_capability()
        declined = result(value, capability, "decline")
        routed = context_cli.route_candidates([value], {"schema": "context-owner-capabilities/v1", "owners": [capability]}, [declined])
        self.assertEqual("skipped", routed["routes"][0]["status"])
        self.assertEqual("owner_decline", routed["routes"][0]["reason"])
        self.assertNotIn("authority", routed["routes"][0])

    def test_acceptance_22_owner_call_contract(self) -> None:
        value = candidate("cand_550e8400e29b41d4a716446655440000", "choice")
        capability = decision_capability()
        declined = result(value, capability, "decline")
        before = copy.deepcopy(declined)
        routed = context_cli.route_candidates([value], {"schema": "context-owner-capabilities/v1", "owners": [capability]}, [declined])
        self.assertEqual(0, routed["router_owner_process_invocations"])
        self.assertEqual(0, routed["cache_probe_count"])
        self.assertEqual(0, routed["alternate_runtime_count"])
        self.assertEqual(before, declined)

    def test_malformed_candidate_and_duplicate_claim_fail_closed(self) -> None:
        first = candidate("cand_550e8400e29b41d4a716446655440000", "same", specialized=[], fallback="observation")
        second = candidate("cand_123e4567e89b42d3a456426614174000", "same", specialized=[], fallback="observation")
        with self.assertRaises(context_cli.ContextError) as caught:
            context_cli.route_candidates([first, second], context_cli.capabilities_result(), [])
        self.assertEqual("duplicate_claim", caught.exception.code)

        oversized = copy.deepcopy(first)
        oversized["owner_inputs"]["observation"]["observation"] = "가" * 2100
        with self.assertRaises(context_cli.ContextError) as caught:
            context_cli.route_candidates([oversized], context_cli.capabilities_result(), [])
        self.assertEqual("candidate_too_large", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
