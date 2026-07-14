#!/usr/bin/env python3
"""Canonical Studio native execution-control conformance tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "studio.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from execution_control import (  # noqa: E402
    CONTRACT_DIGEST,
    ControlError,
    canonical_digest,
    dispatch,
    efficiency_summary,
    ensure_execution_state,
    evaluate_golden_case,
    load_contract,
    record_closeout,
    record_closeout_ref,
    record_evidence,
    record_permit_plan,
    record_result,
    physical_key,
    sealed_digest,
    validate_instance,
)


NOW = "2026-07-15T00:00:00Z"
LATER = "2026-07-15T00:00:10Z"
ENV_DIGEST = canonical_digest({"environment": "test"})
CRITERIA_DIGEST = canonical_digest({"criteria": ["bounded"]})
SURFACE_DIGEST = canonical_digest({"surface": "src/**"})


def seal(value: dict) -> dict:
    value = dict(value)
    value["digest"] = sealed_digest(value)
    return value


def command() -> dict:
    return {
        "executable": "python3",
        "args": ["-m", "unittest", "tests.test_unit"],
        "cwd": ".",
        "environment": {"MODE": "test"},
    }


def profile(*, fresh: bool = False, capabilities: list[str] | None = None) -> dict:
    return seal({
        "schema": "command-profile/v1",
        "profile_id": "unit-tests",
        "executable": "python3",
        "args": ["-m", "unittest", "tests.test_unit"],
        "forbidden_args": ["--deploy", "--publish"],
        "cwd_scope": "repository",
        "environment_inputs": ["MODE"],
        "required_capabilities": capabilities or [],
        "output_contract": {"result": "pass|fail"},
        "fresh_policy": "fresh-required" if fresh else "reusable",
        "digest": "pending",
    })


def permit(
    permit_id: str,
    *,
    purpose: str = "delta",
    qa_mode: str = "delta",
    fresh_id: str | None = None,
    max_runs: int = 3,
    telemetry: str = "fail-closed",
    capabilities: list[str] | None = None,
    mutation: dict | None = None,
    authorization_refs: list[str] | None = None,
    cycle_id: str | None = None,
) -> dict:
    return seal({
        "schema": "execution-permit/v1",
        "permit_id": permit_id,
        "mission_id": "mission-native",
        "cycle_id": cycle_id,
        "unit_id": "STUDIO",
        "qa_mode": qa_mode,
        "purpose": purpose,
        "target": "repository",
        "head": "head-a",
        "command_profile_id": "unit-tests",
        "command_digest": canonical_digest(command()),
        "environment_digest": ENV_DIGEST,
        "tool_version": "studio/test",
        "fresh_requirement_id": fresh_id,
        "criteria_digest": CRITERIA_DIGEST,
        "impact_set": ["src/**"],
        "required_capabilities": capabilities or [],
        "max_physical_runs": max_runs,
        "telemetry_policy": telemetry,
        "mutation_request": mutation,
        "external_authorization_refs": authorization_refs or [],
        "state": "planned",
        "claim_id": None,
        "claimed_by": None,
        "claimed_at": None,
        "completed_at": None,
        "evidence_refs": [],
        "digest": "pending",
    })


def dispatch_request(pmt: dict, prof: dict | None = None, **overrides: object) -> dict:
    value = {
        "permit": pmt,
        "profile": prof or profile(),
        "command": command(),
        "executor": "native",
        "claimed_by": "studio-producer",
        "surface_digest": SURFACE_DIGEST,
        "permit_source": {
            "kind": "direct-native",
            "plan_digest": None,
            "routing_plan_digest": None,
        },
    }
    value.update(overrides)
    return value


def review_plan(pmt: dict) -> dict:
    value = {
        "schema": "studio-review-next-action/v1",
        "permit_id": pmt["permit_id"],
        "cycle_id": pmt["cycle_id"],
        "episode_id": pmt["cycle_id"],
        "mission_id": pmt["mission_id"],
        "head": pmt["head"],
        "physical_key": physical_key(pmt),
        "action": "delta-qa",
        "qa_mode": pmt["qa_mode"],
        "purpose": pmt["purpose"],
        "impact_set": pmt["impact_set"],
        "command_profile_id": pmt["command_profile_id"],
        "command_digest": pmt["command_digest"],
        "environment_digest": pmt["environment_digest"],
        "tool_version": pmt["tool_version"],
        "fresh_requirement_id": pmt["fresh_requirement_id"],
        "criteria_digest": pmt["criteria_digest"],
        "surface_digest": SURFACE_DIGEST,
        "required_independence": None,
        "allowed_commands": ["unit-tests"],
        "full_qa_reason": None,
        "open_findings": [],
        "reused_evidence": [],
        "invalidated_evidence": [],
        "physical_runs": 1,
        "duplicate_prevented": 0,
        "telemetry_gate": "open",
        "dispatchable": True,
        "digest": "pending",
    }
    return seal(value)


def closeout_ref(
    ref_id: str,
    kind: str,
    *,
    lease_digest: str | None = None,
    evidence_refs: list[str] | None = None,
) -> dict:
    state, result = {
        "track-result": ("succeeded", "pass"),
        "review-verdict": ("completed", "approved"),
        "delivery": ("delivered", "pass"),
        "cleanup": ("cleaned", "pass"),
        "preserved-user-change": ("preserved", "pass"),
    }[kind]
    return seal({
        "schema": "studio-closeout-ref/v1",
        "ref_id": ref_id,
        "kind": kind,
        "mission_id": "mission-native",
        "integration_head": "head-a",
        "criteria_digest": CRITERIA_DIGEST,
        "state": state,
        "result": result,
        "evidence_refs": evidence_refs or ["EV-closeout"],
        "lease_digest": lease_digest,
        "recorded_at": LATER,
        "digest": "pending",
    })


def receipt(
    pmt: dict,
    claim_id: str,
    receipt_id: str,
    *,
    result: str = "pass",
    tokens: int | None = 10,
    coverage: str = "exact",
    spend_refs: list[str] | None = None,
    mutation_refs: list[str] | None = None,
) -> dict:
    return seal({
        "schema": "command-receipt/v1",
        "receipt_id": receipt_id,
        "permit_id": pmt["permit_id"],
        "claim_id": claim_id,
        "profile_id": pmt["command_profile_id"],
        "purpose": pmt["purpose"],
        "target": pmt["target"],
        "head": pmt["head"],
        "command_digest": pmt["command_digest"],
        "environment_digest": pmt["environment_digest"],
        "tool_version": pmt["tool_version"],
        "fresh_requirement_id": pmt["fresh_requirement_id"],
        "started_at": NOW,
        "finished_at": LATER,
        "exit_code": 0 if result == "pass" else 1,
        "result": result,
        "output_digest": SURFACE_DIGEST,
        "tokens": tokens,
        "token_coverage": coverage,
        "executor": "native",
        "spend_consumption_refs": spend_refs or [],
        "external_mutation_receipt_refs": mutation_refs or [],
        "digest": "pending",
    })


def evidence(pmt: dict, receipt_id: str, evidence_id: str, *, independence: str = "self") -> dict:
    return seal({
        "schema": "verification-evidence/v1",
        "evidence_id": evidence_id,
        "source_receipt_id": receipt_id,
        "purpose": pmt["purpose"],
        "independence": independence,
        "target": pmt["target"],
        "head": pmt["head"],
        "command_digest": pmt["command_digest"],
        "environment_digest": pmt["environment_digest"],
        "tool_version": pmt["tool_version"],
        "fresh_requirement_id": pmt["fresh_requirement_id"],
        "criteria_digest": pmt["criteria_digest"],
        "covered_paths": ["src/**"],
        "surface_digest": SURFACE_DIGEST,
        "impact_set": ["src/**"],
        "result": "pass",
        "created_at": LATER,
        "invalidation": None,
        "digest": "pending",
    })


def expect_control_error(code: str, fn, *args, **kwargs) -> ControlError:
    try:
        fn(*args, **kwargs)
    except ControlError as exc:
        assert exc.code == code, (code, exc.code, exc.message)
        return exc
    raise AssertionError(f"expected ControlError {code}")


def test_contract_and_all_golden_cases(contract: dict, path: Path) -> None:
    override = os.environ.get("STUDIO_VERIFICATION_CONTRACT")
    expected_path = Path(override) if override else REPO_ROOT / "tests" / "fixtures" / "studio-verification-contract-v1.json"
    assert path == expected_path
    assert contract["digest"] == CONTRACT_DIGEST == sealed_digest(contract)
    assert contract["conformance"]["required_consumers"] == ["STUDIO", "WORKER"]
    assert len(contract["golden_cases"]) == 10
    for case in contract["golden_cases"]:
        assert case["input_digest"] == canonical_digest(case["input"]), case["id"]
        assert evaluate_golden_case(contract, case) == case["expected"], case["id"]


def test_command_claim_result_evidence_and_reuse(contract: dict) -> None:
    state = ensure_execution_state({})
    pmt = permit("permit-a")
    claimed = dispatch(state, contract, dispatch_request(pmt), now=NOW)
    assert claimed["action"] == "claim" and claimed["physical_run_started"]
    duplicate = dispatch(state, contract, dispatch_request(pmt), now=NOW)
    assert duplicate["error"]["code"] == "duplicate_active"

    bad = command()
    bad["args"] = ["--deploy"]
    expect_control_error(
        "command_not_allowed", dispatch, ensure_execution_state({}), contract,
        dispatch_request(permit("permit-b"), command=bad), now=NOW,
    )

    cmd_receipt = receipt(pmt, claimed["claim_id"], "receipt-a")
    recorded = record_result(state, contract, {"receipt": cmd_receipt, "mutation_receipts": []})
    assert recorded["action"] == "record" and recorded["claim_state"] == "succeeded"
    ev = evidence(pmt, "receipt-a", "EV-a")
    assert record_evidence(state, contract, ev)["changed"]

    pmt_reuse = permit("permit-a-reuse")
    reused = dispatch(state, contract, dispatch_request(pmt_reuse), now=LATER)
    assert reused["action"] == "reuse-evidence" and reused["evidence_refs"] == ["EV-a"]


def test_review_plan_is_consumed_and_cannot_be_bypassed(contract: dict) -> None:
    state = ensure_execution_state({})
    pmt = permit("permit-reviewed", cycle_id="cycle-native")
    plan = review_plan(pmt)
    entry, changed = record_permit_plan(state, plan)
    assert changed and entry["consumed_by"] is None

    expect_control_error(
        "review_plan_required",
        dispatch,
        state,
        contract,
        dispatch_request(pmt),
        now=NOW,
    )
    mismatched = seal({**pmt, "purpose": "verification", "digest": "pending"})
    expect_control_error(
        "review_plan_binding_mismatch",
        dispatch,
        state,
        contract,
        dispatch_request(
            mismatched,
            permit_source={
                "kind": "review-plan",
                "plan_digest": plan["digest"],
                "routing_plan_digest": None,
            },
        ),
        now=NOW,
    )
    claimed = dispatch(
        state,
        contract,
        dispatch_request(
            pmt,
            permit_source={
                "kind": "review-plan",
                "plan_digest": plan["digest"],
                "routing_plan_digest": None,
            },
        ),
        now=NOW,
    )
    assert claimed["action"] == "claim" and claimed["plan_digest"] == plan["digest"]
    assert state["permit_plans"][plan["digest"]]["consumed_by"] == claimed["claim_id"]


def test_fresh_independent_and_run_cap_gates(contract: dict) -> None:
    for purpose, qa_mode in (
        ("integration-full", "integration"),
        ("release-artifact", "delta"),
        ("device-check", "delta"),
    ):
        expect_control_error(
            "fresh_requirement_required", dispatch, ensure_execution_state({}), contract,
            dispatch_request(permit(f"permit-{purpose}", purpose=purpose, qa_mode=qa_mode)), now=NOW,
        )

    state = ensure_execution_state({})
    final_pmt = permit("permit-independent", purpose="verification", qa_mode="final", fresh_id="review-1")
    claim = dispatch(state, contract, dispatch_request(final_pmt), now=NOW)
    record_result(state, contract, {"receipt": receipt(final_pmt, claim["claim_id"], "receipt-independent"), "mutation_receipts": []})
    expect_control_error(
        "evidence_not_applicable", record_evidence, state, contract,
        evidence(final_pmt, "receipt-independent", "EV-self", independence="self"),
    )
    assert record_evidence(
        state, contract, evidence(final_pmt, "receipt-independent", "EV-independent", independence="independent")
    )["changed"]

    capped = ensure_execution_state({})
    cap_pmt = permit("permit-cap-1", max_runs=1)
    first = dispatch(capped, contract, dispatch_request(cap_pmt), now=NOW)
    failed = receipt(cap_pmt, first["claim_id"], "receipt-cap", result="fail")
    record_result(capped, contract, {"receipt": failed, "mutation_receipts": []})
    stopped = dispatch(capped, contract, dispatch_request(permit("permit-cap-2", max_runs=1)), now=LATER)
    assert stopped["action"] == "pause" and stopped["error"]["code"] == "physical_run_cap_reached"


def test_capability_cache_and_telemetry_policies(contract: dict) -> None:
    snapshot = seal({
        "schema": "capability-snapshot/v1",
        "snapshot_id": "CAP-embedded",
        "mission_id": "mission-native",
        "capability_id": "browser:embedded",
        "environment_digest": ENV_DIGEST,
        "status": "unavailable",
        "owner": "integration-owner",
        "probe_receipt_id": "receipt-probe",
        "reason": "host runtime does not expose it",
        "observed_at": NOW,
        "expires_at": None,
        "digest": "pending",
    })
    state = ensure_execution_state({})
    pmt = permit("permit-capability", capabilities=["browser:embedded"])
    prof = profile(capabilities=["browser:embedded"])
    first = dispatch(state, contract, dispatch_request(pmt, prof, capability_snapshots=[snapshot]), now=NOW)
    second = dispatch(state, contract, dispatch_request(pmt, prof), now=LATER)
    assert first["action"] == second["action"] == "block-dispatch"
    assert state["counters"]["capability_probe_count"] == 1
    assert state["counters"]["capability_failure_reuse_count"] >= 1

    report_state = ensure_execution_state({})
    report_pmt = permit("permit-report", telemetry="report-only")
    claimed = dispatch(report_state, contract, dispatch_request(report_pmt), now=NOW)
    unknown = receipt(
        report_pmt, claimed["claim_id"], "receipt-report",
        tokens=None, coverage="unavailable",
    )
    decision = record_result(report_state, contract, {"receipt": unknown, "mutation_receipts": []})
    assert decision["action"] == "record" and decision["report_only"] is True

    closed_state = ensure_execution_state({})
    closed_pmt = permit("permit-closed")
    closed_claim = dispatch(closed_state, contract, dispatch_request(closed_pmt), now=NOW)
    paused = record_result(closed_state, contract, {
        "receipt": receipt(closed_pmt, closed_claim["claim_id"], "receipt-closed", tokens=None, coverage="unavailable"),
        "mutation_receipts": [],
    })
    assert paused["action"] == "pause" and paused["tokens_counted"] is None
    corrected = record_result(closed_state, contract, {
        "receipt": receipt(closed_pmt, closed_claim["claim_id"], "receipt-closed-corrected"),
        "mutation_receipts": [],
    })
    assert corrected["claim_state"] == "succeeded"
    corrected_summary = efficiency_summary(closed_state, "mission-native")
    assert corrected_summary["physical_runs"] == 1
    assert corrected_summary["token_coverage"] == "exact"
    assert corrected_summary["unmeasured_runs"] == 0


def test_spend_mutation_closeout_and_read_only_summary(contract: dict) -> None:
    mutation = seal({
        "mutation_request_id": "mutation-1",
        "provider": "generic-provider",
        "operation": "create",
        "resource_kind": "worker",
        "target_ref": "worker-a",
        "one_time_usd": 1,
        "monthly_usd": 2,
        "digest": "pending",
    })
    authorization = seal({
        "schema": "external-spend-authorization/v1",
        "authorization_id": "AUTH-1",
        "mission_id": "mission-native",
        "mutation_request_ref": mutation["mutation_request_id"],
        "mutation_request_digest": mutation["digest"],
        "provider": mutation["provider"],
        "resource_kind": mutation["resource_kind"],
        "scope": mutation["target_ref"],
        "one_time_usd": 1,
        "monthly_usd": 2,
        "max_occurrences": 1,
        "owner_approved": True,
        "approved_by": "owner",
        "approved_at": NOW,
        "expires_at": "2026-07-16T00:00:00Z",
        "digest": "pending",
    })
    preflight = seal({
        "schema": "preflight-receipt/v1",
        "receipt_id": "preflight-1",
        "adapter_id": "generic-adapter",
        "target_ref": mutation["target_ref"],
        "environment_digest": ENV_DIGEST,
        "manifest_digest": canonical_digest({"manifest": 1}),
        "checked_keys": ["token"],
        "missing_keys": [],
        "condition_failures": [],
        "topology_drift": [],
        "result": "pass",
        "checked_at": NOW,
        "digest": "pending",
    })
    state = ensure_execution_state({})
    paid = permit(
        "permit-paid", purpose="production-preflight", fresh_id="preflight-1", mutation=mutation,
        authorization_refs=[authorization["authorization_id"]],
    )
    expect_control_error(
        "external_spend_not_authorized", dispatch, ensure_execution_state({}), contract,
        dispatch_request(paid, preflight_receipt=preflight), now=NOW,
    )
    claimed = dispatch(state, contract, dispatch_request(
        paid, authorization=authorization, preflight_receipt=preflight,
    ), now=NOW)
    consumption = claimed["spend_consumption"]
    final_consumption = seal({
        **consumption,
        "claim_state": "consumed",
        "mutation_receipt_ref": "MUT-1",
        "consumed_at": LATER,
    })
    mutation_receipt = seal({
        "schema": "external-mutation-receipt/v1",
        "mutation_id": "MUT-1",
        "mutation_request_ref": mutation["mutation_request_id"],
        "mutation_request_digest": mutation["digest"],
        "provider": mutation["provider"],
        "operation": mutation["operation"],
        "target_ref": mutation["target_ref"],
        "authorization_id": authorization["authorization_id"],
        "authorization_digest": authorization["digest"],
        "spend_consumption_ref": consumption["consumption_id"],
        "spend_consumption_digest": final_consumption["digest"],
        "preflight_receipt_id": preflight["receipt_id"],
        "result": "applied",
        "started_at": NOW,
        "finished_at": LATER,
        "rollback_ref": None,
        "digest": "pending",
    })
    paid_receipt = receipt(
        paid, claimed["claim_id"], "receipt-paid",
        spend_refs=[consumption["consumption_id"]], mutation_refs=["MUT-1"],
    )
    result = record_result(state, contract, {
        "receipt": paid_receipt, "mutation_receipts": [mutation_receipt],
    })
    assert result["claim_state"] == "succeeded"
    assert state["spend_consumptions"][consumption["consumption_id"]]["claim_state"] == "consumed"

    free_mutation = seal({
        **mutation,
        "mutation_request_id": "mutation-free",
        "target_ref": "worker-free",
        "one_time_usd": 0,
        "monthly_usd": 0,
        "digest": "pending",
    })
    free_preflight = seal({
        **preflight,
        "receipt_id": "preflight-free",
        "target_ref": free_mutation["target_ref"],
        "digest": "pending",
    })
    free_pmt = permit(
        "permit-free", purpose="production-preflight", fresh_id="preflight-free",
        mutation=free_mutation,
    )
    missing_state = ensure_execution_state({})
    missing_claim = dispatch(
        missing_state,
        contract,
        dispatch_request(free_pmt, preflight_receipt=free_preflight),
        now=NOW,
    )
    expect_control_error(
        "external_mutation_receipt_required",
        record_result,
        missing_state,
        contract,
        {
            "receipt": receipt(free_pmt, missing_claim["claim_id"], "receipt-free-missing"),
            "mutation_receipts": [],
        },
    )
    free_claim = dispatch(
        state,
        contract,
        dispatch_request(free_pmt, preflight_receipt=free_preflight),
        now=NOW,
    )
    free_mutation_receipt = seal({
        "schema": "external-mutation-receipt/v1",
        "mutation_id": "MUT-FREE",
        "mutation_request_ref": free_mutation["mutation_request_id"],
        "mutation_request_digest": free_mutation["digest"],
        "provider": free_mutation["provider"],
        "operation": free_mutation["operation"],
        "target_ref": free_mutation["target_ref"],
        "authorization_id": None,
        "authorization_digest": None,
        "spend_consumption_ref": None,
        "spend_consumption_digest": None,
        "preflight_receipt_id": free_preflight["receipt_id"],
        "result": "applied",
        "started_at": NOW,
        "finished_at": LATER,
        "rollback_ref": None,
        "digest": "pending",
    })
    free_receipt = receipt(
        free_pmt,
        free_claim["claim_id"],
        "receipt-free",
        mutation_refs=["MUT-FREE"],
    )
    free_result = record_result(state, contract, {
        "receipt": free_receipt,
        "mutation_receipts": [free_mutation_receipt],
    })
    assert free_result["external_mutation_receipts"] == [free_mutation_receipt]
    assert state["mutation_receipts"]["MUT-FREE"] == free_mutation_receipt

    verify_pmt = permit(
        "permit-closeout", purpose="integration-full", qa_mode="integration",
        fresh_id="integration-head-a",
    )
    verify_claim = dispatch(state, contract, dispatch_request(verify_pmt), now=NOW)
    record_result(state, contract, {
        "receipt": receipt(verify_pmt, verify_claim["claim_id"], "receipt-closeout"),
        "mutation_receipts": [],
    })
    record_evidence(state, contract, evidence(verify_pmt, "receipt-closeout", "EV-closeout"))
    closeout = seal({
        "schema": "closeout-receipt/v1",
        "closeout_id": "closeout-complete",
        "mission_id": "mission-native",
        "definition_ref": "definition-native",
        "integration_head": "head-a",
        "track_result_refs": ["result-STUDIO"],
        "verification_evidence_refs": ["EV-closeout"],
        "review_lease_refs": ["review-lease-1"],
        "delivery_receipt_refs": ["delivery-1"],
        "external_mutation_receipt_refs": ["MUT-1", "MUT-FREE"],
        "cleanup_receipt_refs": ["cleanup-1"],
        "preserved_user_change_refs": ["user-change-1"],
        "open_findings": [],
        "result": "complete",
        "closed_at": LATER,
        "digest": "pending",
    })
    review_lease = seal({
        "schema": "workflow-review-lease/v1",
        "lease_id": "review-lease-1",
        "owner": "studio",
        "provider": "native",
        "episode_id": "cycle-native",
        "edge_id": "edge-native",
        "requirement": "independent",
        "criteria_digest": CRITERIA_DIGEST,
        "evidence_refs": ["EV-closeout"],
        "digest": "pending",
    })
    typed = (
        closeout_ref("result-STUDIO", "track-result"),
        closeout_ref("review-lease-1", "review-verdict", lease_digest=review_lease["digest"]),
        closeout_ref("delivery-1", "delivery"),
        closeout_ref("cleanup-1", "cleanup"),
        closeout_ref("user-change-1", "preserved-user-change"),
    )
    fabricated = expect_control_error("closeout_applicability_invalid", record_closeout, state, contract, closeout)
    assert fabricated.details["ref"] == "result-STUDIO"
    for item in typed:
        lease = review_lease if item["kind"] == "review-verdict" else None
        assert record_closeout_ref(state, item, accepted_review_lease=lease)["changed"]
    missing_free = seal({
        **closeout,
        "closeout_id": "closeout-omits-free",
        "external_mutation_receipt_refs": ["MUT-1"],
        "digest": "pending",
    })
    expect_control_error(
        "closeout_applicability_invalid",
        record_closeout,
        state,
        contract,
        missing_free,
    )
    assert record_closeout(state, contract, closeout)["action"] == "close"
    before = canonical_digest(state)
    summary = efficiency_summary(state, "mission-native")
    validate_instance(contract, "efficiency-summary", summary)
    assert canonical_digest(state) == before
    assert summary["external_spend_one_time_usd"] == 1
    assert summary["external_spend_monthly_usd"] == 2


def test_cli_atomic_claim_and_read_only_summary(contract_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        ws = tmp / ".studio"
        env = {**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(contract_path)}
        subprocess.run(
            [sys.executable, str(SCRIPT), "--workspace", str(ws), "init"],
            cwd=tmp, env=env, check=True, capture_output=True, text=True,
        )
        cycle = {
            "cycle_id": "cycle-native",
            "track_id": "track-native",
            "criteria_digest": CRITERIA_DIGEST,
            "base_head": "head-base",
            "quality_plan_ref": "quality-native",
            "requires_final_qa": False,
            "requires_integration_gate": False,
        }
        subprocess.run(
            [
                sys.executable, str(SCRIPT), "--workspace", str(ws),
                "review", "open", "--json", json.dumps(cycle),
            ],
            cwd=tmp, env=env, check=True, capture_output=True, text=True,
        )
        reviewed_pmt = permit("permit-cli-reviewed", purpose="development", cycle_id="cycle-native")
        planned = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--workspace", str(ws),
                "review", "plan-next", "cycle-native",
                "--mission-id", reviewed_pmt["mission_id"],
                "--permit-id", reviewed_pmt["permit_id"],
                "--command-profile-id", reviewed_pmt["command_profile_id"],
                "--head", reviewed_pmt["head"],
                "--command-digest", reviewed_pmt["command_digest"],
                "--environment-digest", reviewed_pmt["environment_digest"],
                "--tool-version", reviewed_pmt["tool_version"],
                "--surface-digest", SURFACE_DIGEST,
                "--purpose", reviewed_pmt["purpose"],
                "--changed-path", "src/**",
            ],
            cwd=tmp, env=env, check=True, capture_output=True, text=True,
        )
        review_plan_value = json.loads(planned.stdout)["plan"]
        assert review_plan_value["dispatchable"]
        reviewed_request = dispatch_request(
            reviewed_pmt,
            permit_source={
                "kind": "review-plan",
                "plan_digest": review_plan_value["digest"],
                "routing_plan_digest": None,
            },
        )
        reviewed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--workspace", str(ws),
                "execution", "dispatch", "--json", json.dumps(reviewed_request),
            ],
            cwd=tmp, env=env, check=True, capture_output=True, text=True,
        )
        reviewed_decision = json.loads(reviewed.stdout)["decision"]
        assert reviewed_decision["action"] == "claim"
        board_value = json.loads(subprocess.run(
            [sys.executable, str(SCRIPT), "--workspace", str(ws), "board"],
            cwd=tmp, env=env, check=True, capture_output=True, text=True,
        ).stdout)["board"]
        assert (
            board_value["execution_control"]["permit_plans"][review_plan_value["digest"]]["consumed_by"]
            == reviewed_decision["claim_id"]
        )
        payload = json.dumps(dispatch_request(permit("permit-concurrent")), separators=(",", ":"))
        cmd = [
            sys.executable, str(SCRIPT), "--workspace", str(ws),
            "execution", "dispatch", "--json", "-",
        ]
        processes = [
            subprocess.Popen(cmd, cwd=tmp, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(payload, timeout=10)
            assert process.returncode == 0, stderr
            outputs.append(json.loads(stdout)["decision"])
        assert sorted(item["action"] for item in outputs) == ["claim", "reject"]

        board = ws / "board.md"
        before = board.read_bytes()
        summary = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--workspace", str(ws),
                "execution", "summary", "--mission-id", "mission-native",
            ],
            cwd=tmp, env=env, check=True, capture_output=True, text=True,
        )
        assert json.loads(summary.stdout)["read_only"] is True
        assert board.read_bytes() == before


def main() -> None:
    contract, path = load_contract(PLUGIN_ROOT)
    test_contract_and_all_golden_cases(contract, path)
    test_command_claim_result_evidence_and_reuse(contract)
    test_review_plan_is_consumed_and_cannot_be_bypassed(contract)
    test_fresh_independent_and_run_cap_gates(contract)
    test_capability_cache_and_telemetry_policies(contract)
    test_spend_mutation_closeout_and_read_only_summary(contract)
    test_cli_atomic_claim_and_read_only_summary(path)
    print("all Studio native execution-control checks passed")


if __name__ == "__main__":
    main()
