#!/usr/bin/env python3
"""Provider-neutral native execution control for Studio.

This module owns policy decisions and ledger transitions only.  It never runs a
product command or calls a provider API; ``studio.py`` supplies the locked board
transaction around every mutating operation.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any


CONTRACT_SCHEMA = "studio-verification-contract-set/v1"
CONTRACT_DIGEST = "sha256:7df570d1faaba445865c74fd6dffff73178f0102cd3a5728183abf6791ce2b65"
FRESH_PURPOSES = frozenset((
    "integration-full", "release-artifact", "device-check", "production-preflight",
))
TOKEN_POLICIES = frozenset(("fail-closed", "report-only"))
ZERO_TIME = "1970-01-01T00:00:00Z"


class ControlError(ValueError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sealed_digest(value: dict, field: str = "digest") -> str:
    return canonical_digest({key: item for key, item in value.items() if key != field})


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime.datetime | None:
    if value is None:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ControlError("invalid_timestamp", f"invalid RFC3339 timestamp: {value!r}") from exc


def contract_path(plugin_root: Path) -> Path:
    override = os.environ.get("STUDIO_VERIFICATION_CONTRACT")
    repo_root = plugin_root.parent.parent
    return Path(override) if override else repo_root / "tests" / "fixtures" / "studio-verification-contract-v1.json"


def load_contract(plugin_root: Path) -> tuple[dict, Path]:
    path = contract_path(plugin_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise ControlError("verification_contract_unavailable", f"cannot load canonical Studio contract: {path} ({exc})") from exc
    if not isinstance(value, dict) or value.get("schema") != CONTRACT_SCHEMA:
        raise ControlError("verification_contract_drift", "Studio verification contract schema drift")
    if value.get("digest") != CONTRACT_DIGEST or sealed_digest(value) != CONTRACT_DIGEST:
        raise ControlError(
            "verification_contract_drift",
            "Studio verification contract digest drift",
            expected=CONTRACT_DIGEST,
            actual=value.get("digest"),
        )
    if value.get("conformance", {}).get("require_exact_digest") is not True:
        raise ControlError("verification_contract_drift", "Studio contract no longer requires exact digest conformance")
    return value, path


def _matches_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def validate_instance(contract: dict, schema_name: str, value: Any) -> None:
    spec = contract.get("schemas", {}).get(schema_name)
    if not isinstance(spec, dict):
        raise ControlError("unknown_contract_schema", f"unknown contract schema: {schema_name}")
    if not isinstance(value, dict):
        raise ControlError("invalid_contract_instance", f"{schema_name} must be an object")
    fields = set(spec.get("fields") or [])
    if set(value) != fields:
        raise ControlError(
            "invalid_contract_instance",
            f"{schema_name} fields differ from the canonical contract",
            missing=sorted(fields - set(value)),
            unknown=sorted(set(value) - fields),
        )
    for field, type_spec in (spec.get("types") or {}).items():
        if not any(_matches_type(value.get(field), item) for item in type_spec.split("|")):
            raise ControlError("invalid_contract_instance", f"{schema_name}.{field} must be {type_spec}")
    for field, expected in (spec.get("const") or {}).items():
        if value.get(field) != expected:
            raise ControlError("invalid_contract_instance", f"{schema_name}.{field} must equal {expected}")
    for field, allowed in (spec.get("enums") or {}).items():
        if "." in field:
            parent, child = field.split(".", 1)
            nested = value.get(parent)
            if nested is not None and nested.get(child) not in allowed:
                raise ControlError("invalid_contract_instance", f"{schema_name}.{field} is outside the canonical enum")
        elif value.get(field) not in allowed:
            raise ControlError("invalid_contract_instance", f"{schema_name}.{field} is outside the canonical enum")
    for field, shape in (spec.get("shapes") or {}).items():
        nested = value.get(field)
        if nested is not None and (not isinstance(nested, dict) or set(nested) != set(shape)):
            raise ControlError("invalid_contract_instance", f"{schema_name}.{field} shape differs from the canonical contract")
    if value.get("digest") != sealed_digest(value):
        raise ControlError("invalid_instance_digest", f"{schema_name}.digest does not match its canonical payload")


def validate_mutation_request(value: Any) -> dict:
    fields = {
        "mutation_request_id", "provider", "operation", "resource_kind", "target_ref",
        "one_time_usd", "monthly_usd", "digest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ControlError("invalid_mutation_request", "mutation request fields differ from the canonical permit shape")
    for field in ("mutation_request_id", "provider", "operation", "resource_kind", "target_ref"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ControlError("invalid_mutation_request", f"mutation request {field} must be non-empty")
    for field in ("one_time_usd", "monthly_usd"):
        amount = value[field]
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
            raise ControlError("invalid_mutation_request", f"mutation request {field} must be non-negative")
    if value["digest"] != sealed_digest(value):
        raise ControlError("invalid_instance_digest", "mutation request digest does not match its canonical payload")
    return value


def physical_key(permit: dict) -> str:
    payload = {
        key: permit[key]
        for key in ("head", "command_digest", "environment_digest", "tool_version", "purpose")
    }
    if permit.get("fresh_requirement_id") is not None:
        payload["fresh_requirement_id"] = permit["fresh_requirement_id"]
    return canonical_digest(payload)


def fresh_required(permit: dict, profile: dict | None = None) -> bool:
    return bool(
        permit.get("purpose") in FRESH_PURPOSES
        or permit.get("qa_mode") in ("final", "integration")
        or (profile and profile.get("fresh_policy") == "fresh-required")
    )


def command_digest(command: Any) -> str:
    required = {"executable", "args", "cwd", "environment"}
    if not isinstance(command, dict) or set(command) != required:
        raise ControlError("command_not_allowed", "resolved command must contain executable, args, cwd, and environment")
    if not isinstance(command["executable"], str) or not command["executable"].strip():
        raise ControlError("command_not_allowed", "resolved command executable must be non-empty")
    if not isinstance(command["args"], list) or any(not isinstance(item, str) for item in command["args"]):
        raise ControlError("command_not_allowed", "resolved command args must be a string list")
    if not isinstance(command["cwd"], str) or not command["cwd"].strip():
        raise ControlError("command_not_allowed", "resolved command cwd must be non-empty")
    if not isinstance(command["environment"], dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in command["environment"].items()
    ):
        raise ControlError("command_not_allowed", "resolved command environment must be a string mapping")
    return canonical_digest(command)


def enforce_command_profile(profile: dict, command: dict, permit: dict) -> str:
    if profile["profile_id"] != permit["command_profile_id"]:
        raise ControlError("command_not_allowed", "permit command_profile_id does not match the resolved profile")
    if command["executable"] != profile["executable"] or command["args"] != profile["args"]:
        raise ControlError("command_not_allowed", "resolved executable or args are outside the command profile")
    if any(arg in command["args"] for arg in profile["forbidden_args"]):
        raise ControlError("command_not_allowed", "resolved command contains a forbidden argument")
    cwd = Path(command["cwd"])
    scope = Path(profile["cwd_scope"])
    if cwd.is_absolute() or scope.is_absolute() or ".." in cwd.parts or ".." in scope.parts:
        raise ControlError("command_not_allowed", "command cwd and cwd_scope must be repository-relative")
    if scope.as_posix() not in (".", "repository"):
        try:
            cwd.relative_to(scope)
        except ValueError as exc:
            raise ControlError("command_not_allowed", "resolved command cwd is outside cwd_scope") from exc
    if set(command["environment"]) != set(profile["environment_inputs"]):
        raise ControlError("command_not_allowed", "resolved environment differs from command profile inputs")
    digest = command_digest(command)
    if digest != permit["command_digest"]:
        raise ControlError("command_not_allowed", "resolved command digest differs from the execution permit")
    return digest


def _pattern_overlap(left: str, right: str) -> bool:
    left_base = left.split("*", 1)[0].rstrip("/")
    right_base = right.split("*", 1)[0].rstrip("/")
    return left == right or left_base == right_base or left_base.startswith(right_base + "/") or right_base.startswith(left_base + "/")


def evidence_applicability(
    permit: dict,
    evidence: dict,
    *,
    surface_digest: str | None = None,
    required_independence: str | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if evidence.get("result") != "pass" or evidence.get("invalidation") is not None:
        reasons.append("not-valid")
    for field in ("purpose", "target", "head", "command_digest", "environment_digest", "tool_version", "fresh_requirement_id"):
        if evidence.get(field) != permit.get(field):
            reasons.append("fresh_requirement_changed" if field == "fresh_requirement_id" else f"{field.replace('_', '-')}-changed")
    if evidence.get("criteria_digest") != permit.get("criteria_digest"):
        reasons.append("criteria-changed")
    if surface_digest is not None and evidence.get("surface_digest") != surface_digest:
        reasons.append("surface-changed")
    if required_independence and evidence.get("independence") != required_independence:
        reasons.append("independence-required")
    expected_impact = permit.get("impact_set") or []
    actual_impact = evidence.get("impact_set") or []
    covered = evidence.get("covered_paths") or []
    if any(not any(_pattern_overlap(item, candidate) for candidate in actual_impact) for item in expected_impact):
        reasons.append("impact-mismatch")
    if any(not any(_pattern_overlap(item, candidate) for candidate in covered) for item in expected_impact):
        reasons.append("coverage-mismatch")
    return not reasons, list(dict.fromkeys(reasons))


def evidence_change_decision(evidence: dict, change: dict) -> dict:
    if evidence["criteria_digest"] != change.get("criteria_digest"):
        reason = "criteria-changed"
    elif evidence["surface_digest"] != change.get("surface_digest"):
        reason = "surface-changed"
    elif change.get("impact_set") is None:
        reason = "impact-unknown"
    elif any(_pattern_overlap(path, covered) for path in change.get("changed_paths", []) for covered in evidence["covered_paths"]):
        reason = "path-overlap"
    else:
        return {"action": "reuse-evidence", "error": None, "evidence_refs": [evidence["evidence_id"]]}
    return {
        "action": "delta-qa",
        "error": None,
        "invalidated_evidence": [evidence["evidence_id"]],
        "reason": reason,
    }


def capability_key(mission_id: str, capability_id: str, environment_digest: str) -> str:
    return canonical_digest({
        "mission_id": mission_id,
        "capability_id": capability_id,
        "environment_digest": environment_digest,
    })


def capability_decision(
    mission_id: str,
    required_capabilities: list[str],
    environment_digest: str,
    snapshot: dict | None,
    *,
    now: str | None = None,
) -> dict:
    if snapshot is None:
        return {"action": "probe-capability", "error": None, "probe_required": bool(required_capabilities)}
    if (
        snapshot["mission_id"] != mission_id
        or snapshot["environment_digest"] != environment_digest
        or snapshot["capability_id"] not in required_capabilities
    ):
        raise ControlError("capability_snapshot_mismatch", "capability snapshot does not match mission, capability, and environment")
    expires = _parse_time(snapshot.get("expires_at"))
    current = _parse_time(now or utc_now())
    if expires is not None and current is not None and expires <= current:
        return {"action": "probe-capability", "error": None, "probe_required": True}
    if snapshot["status"] == "unavailable":
        return {
            "action": "block-dispatch",
            "error": {"code": "capability_unavailable", "capability_id": snapshot["capability_id"]},
            "probe_required": False,
            "snapshot_id": snapshot["snapshot_id"],
        }
    if snapshot["status"] == "unknown":
        return {"action": "probe-capability", "error": None, "probe_required": True, "snapshot_id": snapshot["snapshot_id"]}
    return {"action": "dispatch", "error": None, "probe_required": False, "snapshot_id": snapshot["snapshot_id"]}


def telemetry_decision(policy: str, receipt: dict) -> dict:
    if policy not in TOKEN_POLICIES:
        raise ControlError("invalid_telemetry_policy", f"unsupported telemetry policy: {policy}")
    measured = receipt.get("tokens") is not None and receipt.get("token_coverage") == "exact"
    if policy == "fail-closed" and not measured:
        return {
            "action": "pause",
            "error": {"code": "token_coverage_unavailable", "receipt_id": receipt["receipt_id"]},
            "tokens_counted": None,
        }
    return {
        "action": "record",
        "error": None,
        "tokens_counted": receipt.get("tokens") if receipt.get("token_coverage") != "unavailable" else None,
        "report_only": policy == "report-only" and not measured,
    }


def closeout_decision(receipt: dict) -> dict:
    required_refs = (
        "track_result_refs", "verification_evidence_refs", "review_lease_refs",
        "delivery_receipt_refs", "cleanup_receipt_refs",
    )
    missing = [field for field in required_refs if not receipt.get(field)]
    if missing or receipt.get("open_findings"):
        return {
            "action": "reject",
            "error": {
                "code": "closeout_incomplete",
                "missing": missing,
                "open_findings": receipt.get("open_findings") or [],
            },
        }
    if receipt.get("result") != "complete" or receipt.get("closed_at") is None:
        return {
            "action": "reject",
            "error": {"code": "closeout_incomplete", "missing": ["complete_result"], "open_findings": []},
        }
    return {"action": "close", "error": None, "closeout_id": receipt["closeout_id"]}


def spend_claim_key(authorization: dict, mutation_request: dict, occurrence_index: int) -> str:
    return canonical_digest({
        "authorization_digest": authorization["digest"],
        "mutation_request_digest": mutation_request["digest"],
        "occurrence_index": occurrence_index,
    })


def spend_claim_decision(
    authorization: dict | None,
    mutation_request: dict,
    existing_consumptions: list[dict],
    *,
    mission_id: str | None = None,
    now: str | None = None,
) -> dict:
    if authorization is None:
        return {
            "action": "reject",
            "error": {"code": "external_spend_not_authorized", "mutation_request_id": mutation_request["mutation_request_id"]},
            "mutation_started": False,
        }
    if not authorization["owner_approved"] or authorization.get("approved_by") is None or authorization.get("approved_at") is None:
        raise ControlError("external_spend_not_authorized", "external spend authorization is not owner-approved")
    if mission_id is not None and authorization["mission_id"] != mission_id:
        raise ControlError("external_spend_not_authorized", "authorization mission_id mismatch")
    pairs = (
        ("mutation_request_ref", "mutation_request_id"),
        ("mutation_request_digest", "digest"),
        ("provider", "provider"),
        ("resource_kind", "resource_kind"),
        ("scope", "target_ref"),
        ("one_time_usd", "one_time_usd"),
        ("monthly_usd", "monthly_usd"),
    )
    if any(authorization[left] != mutation_request[right] for left, right in pairs):
        raise ControlError("external_spend_not_authorized", "authorization does not bind the exact mutation request")
    expires = _parse_time(authorization.get("expires_at"))
    current = _parse_time(now or utc_now())
    if expires is not None and current is not None and expires <= current:
        raise ControlError("external_spend_not_authorized", "external spend authorization has expired")
    used = [
        item for item in existing_consumptions
        if item.get("authorization_digest") == authorization["digest"]
        and item.get("mutation_request_digest") == mutation_request["digest"]
        and item.get("claim_state") in ("claimed", "consumed")
    ]
    occurrence = len(used) + 1
    if occurrence > authorization["max_occurrences"]:
        raise ControlError("external_spend_quota_exhausted", "external spend authorization occurrence quota is exhausted")
    key = spend_claim_key(authorization, mutation_request, occurrence)
    return {
        "action": "claim-spend-consumption",
        "error": None,
        "occurrence_index": occurrence,
        "claim_state": "claimed",
        "claim_key": key,
    }


def evaluate_golden_case(contract: dict, case: dict) -> dict:
    if case.get("input_digest") != canonical_digest(case.get("input")):
        raise ControlError("golden_input_drift", f"golden input digest drift: {case.get('id')}")
    payload = case["input"]
    case_id = case["id"]
    if case_id == "valid-permit":
        permit = payload["permit"]
        validate_instance(contract, "execution-permit", permit)
        return {"action": "claim", "error": None, "permit_id": permit["permit_id"], "physical_key": physical_key(permit)}
    if case_id == "active-duplicate":
        permit, active = payload["permit"], payload["active_claim"]
        validate_instance(contract, "execution-permit", permit)
        if active["physical_key"] == physical_key(permit) and active["state"] == "claimed":
            return {"action": "reject", "error": {"code": "duplicate_active", "claim_id": active["claim_id"]}, "physical_run_started": False}
    if case_id == "success-reuse":
        permit, evidence = payload["permit"], payload["evidence"]
        validate_instance(contract, "execution-permit", permit)
        validate_instance(contract, "verification-evidence", evidence)
        applicable, _ = evidence_applicability(permit, evidence)
        if applicable:
            return {"action": "reuse-evidence", "error": None, "evidence_refs": [evidence["evidence_id"]], "physical_run_started": False}
    if case_id == "fresh-execution":
        permit, evidence = payload["permit"], payload["existing_evidence"]
        validate_instance(contract, "execution-permit", permit)
        validate_instance(contract, "verification-evidence", evidence)
        applicable, reasons = evidence_applicability(permit, evidence)
        if not applicable and "fresh_requirement_changed" in reasons:
            return {"action": "claim", "error": None, "reason": "fresh_requirement_changed", "physical_run_started": True}
    if case_id == "evidence-invalidation":
        validate_instance(contract, "verification-evidence", payload["evidence"])
        return evidence_change_decision(payload["evidence"], payload["change"])
    if case_id == "unavailable-capability-cache":
        validate_instance(contract, "capability-snapshot", payload["snapshot"])
        return capability_decision(payload["mission_id"], payload["required_capabilities"], payload["environment_digest"], payload["snapshot"], now=payload["snapshot"]["observed_at"])
    if case_id == "unauthorized-spend-rejection":
        permit = payload["permit"]
        validate_instance(contract, "execution-permit", permit)
        mutation = validate_mutation_request(permit["mutation_request"])
        return spend_claim_decision(payload["authorization"], mutation, [])
    if case_id == "atomic-spend-consumption":
        validate_instance(contract, "external-spend-authorization", payload["authorization"])
        mutation = validate_mutation_request(payload["mutation_request"])
        return spend_claim_decision(payload["authorization"], mutation, payload["existing_consumptions"], now=payload["authorization"]["approved_at"])
    if case_id == "telemetry-pause":
        validate_instance(contract, "command-receipt", payload["receipt"])
        return telemetry_decision(payload["telemetry_policy"], payload["receipt"])
    if case_id == "closeout-blocked":
        validate_instance(contract, "closeout-receipt", payload["receipt"])
        return closeout_decision(payload["receipt"])
    raise ControlError("unknown_golden_case", f"unknown golden case: {case_id}")


def ensure_execution_state(board: dict) -> dict:
    state = board.setdefault("execution_control", {})
    if not isinstance(state, dict):
        raise ControlError("execution_ledger_invalid", "board.execution_control must be an object")
    pinned = state.setdefault("contract_digest", CONTRACT_DIGEST)
    if pinned != CONTRACT_DIGEST:
        raise ControlError("verification_contract_drift", "board is pinned to another verification contract")
    for field in (
        "permits", "profiles", "claims", "physical_claims", "receipts", "evidence",
        "capability_snapshots", "preflight_receipts", "spend_authorizations",
        "spend_consumptions", "spend_claims", "mutation_receipts", "closeouts",
    ):
        value = state.setdefault(field, {})
        if not isinstance(value, dict):
            raise ControlError("execution_ledger_invalid", f"execution_control.{field} must be an object")
    counters = state.setdefault("counters", {})
    if not isinstance(counters, dict):
        raise ControlError("execution_ledger_invalid", "execution_control.counters must be an object")
    for field in (
        "logical_checks", "physical_runs", "full_qa_runs", "delta_qa_runs",
        "evidence_reuse_count", "duplicate_prevented_count", "capability_probe_count",
        "capability_failure_reuse_count", "owner_intervention_count",
    ):
        counters.setdefault(field, 0)
    mission_counters = state.setdefault("mission_counters", {})
    if not isinstance(mission_counters, dict):
        raise ControlError("execution_ledger_invalid", "execution_control.mission_counters must be an object")
    return state


def _bump(state: dict, field: str, mission_id: str, amount: int = 1) -> None:
    state["counters"][field] = int(state["counters"].get(field) or 0) + amount
    mission = state["mission_counters"].setdefault(mission_id, {})
    mission[field] = int(mission.get(field) or 0) + amount


def _pin(mapping: dict, key: str, value: dict, *, code: str) -> bool:
    prior = mapping.get(key)
    if prior is not None and prior != value:
        raise ControlError(code, f"immutable ledger identity conflicts: {key}")
    if prior is None:
        mapping[key] = value
        return True
    return False


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ControlError("invalid_contract_instance", f"{field} must be a non-empty-string list")
    if len(value) != len(set(value)):
        raise ControlError("invalid_contract_instance", f"{field} must not contain duplicates")
    return value


def record_capability_snapshot(state: dict, contract: dict, snapshot: dict) -> tuple[dict, bool]:
    validate_instance(contract, "capability-snapshot", snapshot)
    key = capability_key(snapshot["mission_id"], snapshot["capability_id"], snapshot["environment_digest"])
    changed = _pin(state["capability_snapshots"], key, snapshot, code="capability_snapshot_conflict")
    if changed:
        _bump(state, "capability_probe_count", snapshot["mission_id"])
    return snapshot, changed


def _cached_capability(
    state: dict,
    mission_id: str,
    capability_id: str,
    environment_digest: str,
    *,
    now: str,
) -> dict | None:
    snapshot = state["capability_snapshots"].get(capability_key(mission_id, capability_id, environment_digest))
    if snapshot is None:
        return None
    expires = _parse_time(snapshot.get("expires_at"))
    current = _parse_time(now)
    if expires is not None and current is not None and expires <= current:
        return None
    return snapshot


def _required_independence(permit: dict, requested: str | None) -> str | None:
    if requested is not None and requested not in ("self", "independent", "not-applicable"):
        raise ControlError("invalid_independence", "required independence is outside the canonical enum")
    if permit["qa_mode"] == "final":
        return "independent"
    return requested


def _spend_consumption(
    authorization: dict,
    mutation_request: dict,
    decision: dict,
) -> dict:
    suffix = decision["claim_key"].split(":", 1)[1]
    value = {
        "schema": "external-spend-consumption/v1",
        "consumption_id": "CONS-" + suffix[:16],
        "authorization_id": authorization["authorization_id"],
        "authorization_digest": authorization["digest"],
        "mutation_request_ref": mutation_request["mutation_request_id"],
        "mutation_request_digest": mutation_request["digest"],
        "scope": authorization["scope"],
        "occurrence_index": decision["occurrence_index"],
        "one_time_usd": authorization["one_time_usd"],
        "monthly_usd": authorization["monthly_usd"],
        "claim_id": "spend-" + suffix[:16],
        "claim_state": "claimed",
        "mutation_receipt_ref": None,
        "consumed_at": None,
        "digest": "pending",
    }
    value["digest"] = sealed_digest(value)
    return value


def _claim_spend(
    state: dict,
    contract: dict,
    permit: dict,
    authorization: dict | None,
    *,
    now: str,
) -> dict | None:
    mutation = permit.get("mutation_request")
    if mutation is None:
        return None
    mutation = validate_mutation_request(mutation)
    if authorization is not None:
        validate_instance(contract, "external-spend-authorization", authorization)
    paid = mutation["one_time_usd"] > 0 or mutation["monthly_usd"] > 0
    if paid and authorization is None:
        raise ControlError(
            "external_spend_not_authorized",
            "paid external mutation requires an authorization",
            mutation_request_id=mutation["mutation_request_id"],
        )
    if not paid:
        return None
    if authorization["authorization_id"] not in permit["external_authorization_refs"]:
        raise ControlError("external_spend_not_authorized", "permit does not pin the supplied authorization")
    _pin(
        state["spend_authorizations"], authorization["authorization_id"], authorization,
        code="external_spend_authorization_conflict",
    )
    existing = list(state["spend_consumptions"].values())
    decision = spend_claim_decision(authorization, mutation, existing, mission_id=permit["mission_id"], now=now)
    key = decision["claim_key"]
    prior_id = state["spend_claims"].get(key)
    if prior_id is not None:
        prior = state["spend_consumptions"][prior_id]
        if prior["claim_state"] in ("claimed", "consumed"):
            return prior
    consumption = _spend_consumption(authorization, mutation, decision)
    validate_instance(contract, "external-spend-consumption", consumption)
    state["spend_consumptions"][consumption["consumption_id"]] = consumption
    state["spend_claims"][key] = consumption["consumption_id"]
    return consumption


def _validate_preflight(
    state: dict,
    contract: dict,
    permit: dict,
    receipt: dict | None,
) -> dict | None:
    mutation = permit.get("mutation_request")
    if mutation is None:
        if receipt is not None:
            raise ControlError("preflight_not_applicable", "preflight receipt requires an external mutation")
        return None
    if receipt is None:
        raise ControlError("preflight_required", "external mutation requires a pinned preflight receipt")
    validate_instance(contract, "preflight-receipt", receipt)
    if (
        receipt["result"] != "pass"
        or receipt["environment_digest"] != permit["environment_digest"]
        or receipt["target_ref"] != mutation["target_ref"]
        or receipt["missing_keys"]
        or receipt["condition_failures"]
        or receipt["topology_drift"]
    ):
        raise ControlError("preflight_failed", "preflight does not authorize this mutation target and environment")
    _pin(state["preflight_receipts"], receipt["receipt_id"], receipt, code="preflight_receipt_conflict")
    return receipt


def dispatch(
    state: dict,
    contract: dict,
    request: Any,
    *,
    now: str | None = None,
) -> dict:
    required = {"permit", "profile", "command", "executor", "claimed_by"}
    allowed = required | {
        "evidence", "capability_snapshots", "authorization", "preflight_receipt",
        "surface_digest", "required_independence",
    }
    if not isinstance(request, dict) or not required.issubset(request) or set(request) - allowed:
        raise ControlError("invalid_dispatch_request", "dispatch request fields differ from the native control contract")
    timestamp = now or utc_now()
    permit, profile, command = request["permit"], request["profile"], request["command"]
    validate_instance(contract, "execution-permit", permit)
    validate_instance(contract, "command-profile", profile)
    for field in ("impact_set", "required_capabilities", "external_authorization_refs"):
        _require_string_list(permit[field], f"execution-permit.{field}")
    for field in ("args", "forbidden_args", "environment_inputs", "required_capabilities"):
        _require_string_list(profile[field], f"command-profile.{field}")
    if not profile["executable"].strip() or not profile["cwd_scope"].strip():
        raise ControlError("invalid_contract_instance", "command profile executable and cwd_scope must be non-empty")
    if permit["state"] != "planned" or permit["max_physical_runs"] < 1:
        raise ControlError("invalid_execution_permit", "dispatch requires a planned permit with a positive run cap")
    if permit["telemetry_policy"] not in TOKEN_POLICIES:
        raise ControlError("invalid_telemetry_policy", "permit telemetry policy is invalid")
    if not isinstance(request["executor"], str) or not request["executor"].strip():
        raise ControlError("invalid_dispatch_request", "executor must be non-empty")
    if not isinstance(request["claimed_by"], str) or not request["claimed_by"].strip():
        raise ControlError("invalid_dispatch_request", "claimed_by must be non-empty")
    enforce_command_profile(profile, command, permit)
    if fresh_required(permit, profile) and permit["fresh_requirement_id"] is None:
        raise ControlError("fresh_requirement_required", "fresh execution gate requires fresh_requirement_id")
    independence = _required_independence(permit, request.get("required_independence"))
    _pin(state["permits"], permit["permit_id"], permit, code="execution_permit_conflict")
    _pin(state["profiles"], profile["profile_id"], profile, code="command_profile_conflict")
    _bump(state, "logical_checks", permit["mission_id"])

    supplied_snapshots = request.get("capability_snapshots") or []
    if not isinstance(supplied_snapshots, list):
        raise ControlError("invalid_dispatch_request", "capability_snapshots must be a list")
    fresh_snapshot_keys = set()
    for snapshot in supplied_snapshots:
        _, changed = record_capability_snapshot(state, contract, snapshot)
        if changed:
            fresh_snapshot_keys.add(capability_key(
                snapshot["mission_id"], snapshot["capability_id"], snapshot["environment_digest"],
            ))
    required_capabilities = list(dict.fromkeys(permit["required_capabilities"] + profile["required_capabilities"]))
    for capability_id in required_capabilities:
        snapshot = _cached_capability(
            state, permit["mission_id"], capability_id, permit["environment_digest"], now=timestamp,
        )
        decision = capability_decision(
            permit["mission_id"], required_capabilities, permit["environment_digest"], snapshot, now=timestamp,
        )
        if decision["action"] == "block-dispatch":
            snapshot_key = capability_key(permit["mission_id"], capability_id, permit["environment_digest"])
            if snapshot_key not in fresh_snapshot_keys:
                _bump(state, "capability_failure_reuse_count", permit["mission_id"])
            return decision
        if decision["action"] == "probe-capability":
            return {**decision, "capability_id": capability_id, "physical_run_started": False}

    supplied_evidence = request.get("evidence") or []
    if not isinstance(supplied_evidence, list):
        raise ControlError("invalid_dispatch_request", "evidence must be a list")
    candidates: list[dict] = []
    for item in supplied_evidence:
        validate_instance(contract, "verification-evidence", item)
        _pin(state["evidence"], item["evidence_id"], item, code="evidence_immutable")
        candidates.append(item)
    key = physical_key(permit)
    physical = state["physical_claims"].setdefault(key, {"physical_key": key, "runs": []})
    for evidence_id in physical.get("evidence_refs", []):
        item = state["evidence"].get(evidence_id)
        if item is not None and item not in candidates:
            candidates.append(item)
    reusable = [
        item["evidence_id"] for item in candidates
        if request.get("surface_digest") is not None and evidence_applicability(
            permit, item, surface_digest=request.get("surface_digest"), required_independence=independence,
        )[0]
    ]
    if reusable:
        _bump(state, "evidence_reuse_count", permit["mission_id"])
        _bump(state, "duplicate_prevented_count", permit["mission_id"])
        return {
            "action": "reuse-evidence", "error": None, "evidence_refs": sorted(reusable),
            "physical_run_started": False, "physical_key": key,
        }
    active = next((run for run in physical["runs"] if run["state"] in ("claimed", "waiting-gate")), None)
    if active is not None:
        _bump(state, "duplicate_prevented_count", permit["mission_id"])
        return {
            "action": "reject",
            "error": {"code": "duplicate_active", "claim_id": active["claim_id"]},
            "physical_run_started": False,
        }
    if len(physical["runs"]) >= permit["max_physical_runs"]:
        _bump(state, "owner_intervention_count", permit["mission_id"])
        return {
            "action": "pause",
            "error": {"code": "physical_run_cap_reached", "max_physical_runs": permit["max_physical_runs"]},
            "physical_run_started": False,
        }
    _validate_preflight(state, contract, permit, request.get("preflight_receipt"))
    spend = _claim_spend(state, contract, permit, request.get("authorization"), now=timestamp)
    occurrence = len(physical["runs"]) + 1
    claim_seed = canonical_digest({"permit_digest": permit["digest"], "physical_key": key, "occurrence_index": occurrence})
    claim_id = "claim-" + claim_seed.split(":", 1)[1][:20]
    run = {
        "claim_id": claim_id,
        "permit_id": permit["permit_id"],
        "profile_id": profile["profile_id"],
        "physical_key": key,
        "occurrence_index": occurrence,
        "state": "claimed",
        "executor": request["executor"],
        "claimed_by": request["claimed_by"],
        "claimed_at": timestamp,
        "completed_at": None,
        "receipt_id": None,
        "spend_consumption_ref": spend["consumption_id"] if spend else None,
        "evidence_refs": [],
    }
    physical["runs"].append(run)
    state["claims"][claim_id] = run
    _bump(state, "physical_runs", permit["mission_id"])
    if permit["qa_mode"] == "full" or permit["purpose"] == "integration-full":
        _bump(state, "full_qa_runs", permit["mission_id"])
    elif permit["qa_mode"] == "delta":
        _bump(state, "delta_qa_runs", permit["mission_id"])
    return {
        "action": "claim", "error": None, "permit_id": permit["permit_id"],
        "claim_id": claim_id, "physical_key": key, "physical_run_started": True,
        "spend_consumption": spend,
    }


def _receipt_binding(receipt: dict, permit: dict, claim: dict) -> None:
    expected = {
        "permit_id": permit["permit_id"],
        "claim_id": claim["claim_id"],
        "profile_id": permit["command_profile_id"],
        "purpose": permit["purpose"],
        "target": permit["target"],
        "head": permit["head"],
        "command_digest": permit["command_digest"],
        "environment_digest": permit["environment_digest"],
        "tool_version": permit["tool_version"],
        "fresh_requirement_id": permit["fresh_requirement_id"],
    }
    mismatches = [field for field, value in expected.items() if receipt.get(field) != value]
    if mismatches:
        raise ControlError("receipt_binding_mismatch", "command receipt differs from its permit/claim", fields=mismatches)


def _complete_mutation(
    state: dict,
    contract: dict,
    claim: dict,
    receipt: dict,
    mutation_receipts: list[dict],
) -> list[dict]:
    consumption_ref = claim.get("spend_consumption_ref")
    if consumption_ref is None:
        if receipt["spend_consumption_refs"] or mutation_receipts or receipt["external_mutation_receipt_refs"]:
            raise ControlError("mutation_receipt_not_authorized", "receipt reports a mutation without a spend claim")
        return []
    consumption = state["spend_consumptions"].get(consumption_ref)
    if consumption is None or receipt["spend_consumption_refs"] != [consumption_ref]:
        raise ControlError("spend_consumption_mismatch", "command receipt must pin its exact spend consumption")
    if len(mutation_receipts) != 1:
        raise ControlError("external_mutation_receipt_required", "authorized mutation requires exactly one mutation receipt")
    mutation = mutation_receipts[0]
    validate_instance(contract, "external-mutation-receipt", mutation)
    if receipt["external_mutation_receipt_refs"] != [mutation["mutation_id"]]:
        raise ControlError("external_mutation_receipt_mismatch", "command receipt mutation refs differ from supplied receipts")
    final_state = "consumed" if mutation["result"] == "applied" else "released"
    final = {
        **consumption,
        "claim_state": final_state,
        "mutation_receipt_ref": mutation["mutation_id"],
        "consumed_at": mutation["finished_at"],
    }
    final["digest"] = sealed_digest(final)
    expected = {
        "mutation_request_ref": final["mutation_request_ref"],
        "mutation_request_digest": final["mutation_request_digest"],
        "authorization_id": final["authorization_id"],
        "authorization_digest": final["authorization_digest"],
        "spend_consumption_ref": final["consumption_id"],
        "spend_consumption_digest": final["digest"],
    }
    if any(mutation.get(field) != value for field, value in expected.items()):
        raise ControlError("external_mutation_receipt_mismatch", "mutation receipt does not cross-reference the final consumption")
    validate_instance(contract, "external-spend-consumption", final)
    state["spend_consumptions"][final["consumption_id"]] = final
    _pin(state["mutation_receipts"], mutation["mutation_id"], mutation, code="external_mutation_receipt_conflict")
    return [mutation]


def record_result(
    state: dict,
    contract: dict,
    request: Any,
) -> dict:
    if not isinstance(request, dict) or set(request) != {"receipt", "mutation_receipts"}:
        raise ControlError("invalid_result_request", "result request must contain receipt and mutation_receipts")
    receipt = request["receipt"]
    mutation_receipts = request["mutation_receipts"]
    if not isinstance(mutation_receipts, list):
        raise ControlError("invalid_result_request", "mutation_receipts must be a list")
    validate_instance(contract, "command-receipt", receipt)
    claim = state["claims"].get(receipt["claim_id"])
    if claim is None:
        raise ControlError("claim_not_found", "command receipt claim is not in the native ledger")
    permit = state["permits"].get(receipt["permit_id"])
    profile = state["profiles"].get(receipt["profile_id"])
    if permit is None or profile is None:
        raise ControlError("receipt_binding_mismatch", "receipt permit/profile is not pinned")
    _receipt_binding(receipt, permit, claim)
    if receipt["command_digest"] != permit["command_digest"] or profile["profile_id"] != receipt["profile_id"]:
        raise ControlError("command_not_allowed", "result command is outside the pinned command profile")
    prior = state["receipts"].get(receipt["receipt_id"])
    if prior is not None:
        if prior != receipt:
            raise ControlError("command_receipt_conflict", "receipt id is immutable")
        return {"action": "record", "error": None, "receipt": receipt, "changed": False}
    telemetry = telemetry_decision(permit["telemetry_policy"], receipt)
    state["receipts"][receipt["receipt_id"]] = receipt
    claim["receipt_id"] = receipt["receipt_id"]
    if telemetry["action"] == "pause":
        claim["state"] = "waiting-gate"
        _bump(state, "owner_intervention_count", permit["mission_id"])
        return {**telemetry, "receipt": receipt, "changed": True}
    completed_mutations = _complete_mutation(state, contract, claim, receipt, mutation_receipts)
    claim["completed_at"] = receipt["finished_at"]
    claim["state"] = {
        "pass": "succeeded", "fail": "failed", "error": "failed", "cancelled": "cancelled",
    }[receipt["result"]]
    return {
        **telemetry,
        "receipt": receipt,
        "claim_state": claim["state"],
        "external_mutation_receipts": completed_mutations,
        "changed": True,
    }


def record_evidence(state: dict, contract: dict, evidence: dict) -> dict:
    validate_instance(contract, "verification-evidence", evidence)
    source_id = evidence["source_receipt_id"]
    if source_id is None:
        raise ControlError("source_receipt_required", "native evidence ingestion requires source_receipt_id")
    receipt = state["receipts"].get(source_id)
    if receipt is None or receipt["result"] != "pass":
        raise ControlError("source_receipt_invalid", "evidence requires a recorded passing command receipt")
    claim = state["claims"].get(receipt["claim_id"])
    permit = state["permits"].get(receipt["permit_id"])
    if claim is None or permit is None:
        raise ControlError("source_receipt_invalid", "evidence source receipt is detached from its claim")
    independence = _required_independence(permit, None)
    applicable, reasons = evidence_applicability(permit, evidence, required_independence=independence)
    if not applicable:
        raise ControlError("evidence_not_applicable", "evidence does not apply to its permit", reasons=reasons)
    changed = _pin(state["evidence"], evidence["evidence_id"], evidence, code="evidence_immutable")
    if evidence["evidence_id"] not in claim["evidence_refs"]:
        claim["evidence_refs"].append(evidence["evidence_id"])
    physical = state["physical_claims"][claim["physical_key"]]
    refs = physical.setdefault("evidence_refs", [])
    if evidence["evidence_id"] not in refs:
        refs.append(evidence["evidence_id"])
    return {"action": "record-evidence", "error": None, "evidence": evidence, "changed": changed}


def invalidate_evidence(
    state: dict,
    contract: dict,
    evidence_id: str,
    change: dict,
    *,
    now: str | None = None,
) -> dict:
    evidence = state["evidence"].get(evidence_id)
    if evidence is None:
        raise ControlError("evidence_not_found", f"evidence not found: {evidence_id}")
    if evidence["invalidation"] is not None:
        return {"action": "already-invalidated", "error": None, "evidence": evidence, "changed": False}
    decision = evidence_change_decision(evidence, change)
    if decision["action"] == "reuse-evidence":
        return {**decision, "evidence": evidence, "changed": False}
    invalidation = {
        "reason": decision["reason"],
        "changed_paths": change.get("changed_paths") or [],
        "surface_digest": change.get("surface_digest") or evidence["surface_digest"],
        "invalidated_at": now or utc_now(),
    }
    updated = {**evidence, "invalidation": invalidation}
    updated["digest"] = sealed_digest(updated)
    validate_instance(contract, "verification-evidence", updated)
    state["evidence"][evidence_id] = updated
    return {**decision, "evidence": updated, "changed": True}


def record_closeout(
    state: dict,
    contract: dict,
    receipt: dict,
    applicability: dict,
) -> dict:
    validate_instance(contract, "closeout-receipt", receipt)
    decision = closeout_decision(receipt)
    if decision["action"] != "close":
        _bump(state, "owner_intervention_count", receipt["mission_id"])
        return {**decision, "changed": False}
    if not isinstance(applicability, dict) or any(not isinstance(ref, str) or not isinstance(head, str) for ref, head in applicability.items()):
        raise ControlError("closeout_applicability_invalid", "closeout applicability must map refs to integration heads")
    all_refs: list[str] = []
    for field in (
        "track_result_refs", "verification_evidence_refs", "review_lease_refs",
        "delivery_receipt_refs", "external_mutation_receipt_refs", "cleanup_receipt_refs",
        "preserved_user_change_refs",
    ):
        all_refs.extend(receipt[field])
    missing = sorted(ref for ref in all_refs if applicability.get(ref) != receipt["integration_head"])
    if missing:
        raise ControlError("closeout_applicability_invalid", "closeout refs are not reconciled to integration_head", refs=missing)
    for evidence_ref in receipt["verification_evidence_refs"]:
        evidence = state["evidence"].get(evidence_ref)
        if evidence is None or evidence["head"] != receipt["integration_head"] or evidence["invalidation"] is not None:
            raise ControlError("closeout_applicability_invalid", "closeout verification evidence is missing, stale, or invalidated")
    integration_evidence = [
        state["evidence"][ref] for ref in receipt["verification_evidence_refs"]
        if ref in state["evidence"] and state["evidence"][ref]["purpose"] == "integration-full"
    ]
    if not integration_evidence:
        raise ControlError("closeout_applicability_invalid", "closeout requires a fresh integration-full evidence receipt")
    required_mutations = {
        mutation_id
        for mutation_id, mutation in state["mutation_receipts"].items()
        if mutation.get("result") == "applied"
        and isinstance(state["spend_authorizations"].get(mutation.get("authorization_id")), dict)
        and state["spend_authorizations"][mutation["authorization_id"]]["mission_id"] == receipt["mission_id"]
    }
    if not required_mutations.issubset(set(receipt["external_mutation_receipt_refs"])):
        raise ControlError("closeout_applicability_invalid", "closeout omits a mission external mutation receipt")
    for mutation_ref in receipt["external_mutation_receipt_refs"]:
        if mutation_ref not in state["mutation_receipts"]:
            raise ControlError("closeout_applicability_invalid", "closeout mutation receipt is not recorded")
    changed = _pin(state["closeouts"], receipt["closeout_id"], receipt, code="closeout_receipt_conflict")
    return {**decision, "receipt": receipt, "changed": changed}


def efficiency_summary(state: dict, mission_id: str) -> dict:
    permits = [item for item in state["permits"].values() if item["mission_id"] == mission_id]
    permit_ids = {item["permit_id"] for item in permits}
    claims = [item for item in state["claims"].values() if item["permit_id"] in permit_ids]
    receipts = [
        state["receipts"][item["receipt_id"]]
        for item in claims
        if item.get("receipt_id") in state["receipts"]
    ]
    snapshots = [item for item in state["capability_snapshots"].values() if item["mission_id"] == mission_id]
    authorizations = [item for item in state["spend_authorizations"].values() if item["mission_id"] == mission_id]
    auth_ids = {item["authorization_id"] for item in authorizations}
    consumptions = [
        item for item in state["spend_consumptions"].values()
        if item["authorization_id"] in auth_ids and item["claim_state"] == "consumed"
    ]
    token_receipts = [item for item in receipts if item["token_coverage"] in ("exact", "estimated") and item["tokens"] is not None]
    unmeasured = [item for item in receipts if item["token_coverage"] == "unavailable" or item["tokens"] is None]
    if not token_receipts:
        coverage = "unavailable"
    elif len(token_receipts) == len(receipts) and all(item["token_coverage"] == "exact" for item in receipts):
        coverage = "exact"
    else:
        coverage = "partial"
    stamps = [item["claimed_at"] for item in claims]
    stamps += [item["finished_at"] for item in receipts]
    stamps += [item["observed_at"] for item in snapshots]
    start = min(stamps) if stamps else ZERO_TIME
    finish = max(stamps) if stamps else ZERO_TIME
    counters = state["mission_counters"].get(mission_id, {})
    summary = {
        "schema": "efficiency-summary/v1",
        "summary_id": "summary-" + canonical_digest({"mission_id": mission_id, "start": start, "finish": finish}).split(":", 1)[1][:16],
        "mission_id": mission_id,
        "window_started_at": start,
        "window_finished_at": finish,
        "logical_checks": int(counters.get("logical_checks") or 0),
        "physical_runs": len(claims),
        "full_qa_runs": sum(
            state["permits"][item["permit_id"]]["qa_mode"] == "full"
            or state["permits"][item["permit_id"]]["purpose"] == "integration-full"
            for item in claims
        ),
        "delta_qa_runs": sum(state["permits"][item["permit_id"]]["qa_mode"] == "delta" for item in claims),
        "evidence_reuse_count": int(counters.get("evidence_reuse_count") or 0),
        "duplicate_prevented_count": int(counters.get("duplicate_prevented_count") or 0),
        "capability_probe_count": len(snapshots),
        "capability_failure_reuse_count": int(counters.get("capability_failure_reuse_count") or 0),
        "token_coverage": coverage,
        "measured_tokens": sum(item["tokens"] for item in token_receipts),
        "unmeasured_runs": len(unmeasured),
        "owner_intervention_count": int(counters.get("owner_intervention_count") or 0),
        "external_spend_one_time_usd": sum(item["one_time_usd"] for item in consumptions),
        "external_spend_monthly_usd": sum(item["monthly_usd"] for item in consumptions),
        "digest": "pending",
    }
    summary["digest"] = sealed_digest(summary)
    return summary
