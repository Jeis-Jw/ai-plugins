#!/usr/bin/env python3
"""Provider-neutral command policy, execution claims, and immutable evidence."""

from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONTRACT_SCHEMA = "studio-verification-contract-set/v1"
CONTRACT_DIGEST = "sha256:7df570d1faaba445865c74fd6dffff73178f0102cd3a5728183abf6791ce2b65"
PERMIT_SCHEMA = "execution-permit/v1"
PROFILE_SCHEMA = "command-profile/v1"
RECEIPT_SCHEMA = "command-receipt/v1"
EVIDENCE_SCHEMA = "verification-evidence/v1"
EXECUTION_STATE_SCHEMA = "task-worker.execution-state/v1"
IMPACT_RULE_SET_SCHEMA = "impact-rule-set/v1"
QA_MODES = {"development", "delta", "full", "final", "integration"}
FRESH_PURPOSES = frozenset((
    "integration-full", "release-artifact", "device-check", "production-preflight",
))
COMMAND_DIGEST_FIELDS = ("executable", "args", "cwd", "environment")


class ExecutionControlError(Exception):
    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def tagged_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def instance_digest(value: dict[str, Any]) -> str:
    return tagged_digest({key: item for key, item in value.items() if key != "digest"})


def default_contract_path() -> Path:
    override = os.environ.get("STUDIO_VERIFICATION_CONTRACT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "studio-verification-contract-v1.json"


def _matches_type(value: Any, expected: str) -> bool:
    options = expected.split("|")
    if value is None:
        return "null" in options
    checks = {
        "string": lambda: isinstance(value, str),
        "array": lambda: isinstance(value, list),
        "object": lambda: isinstance(value, dict),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
    }
    return any(kind in checks and checks[kind]() for kind in options)


def validate_instance(value: dict[str, Any], schema_name: str, contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionControlError("instance_not_object", f"{schema_name} must be an object")
    schema = (contract.get("schemas") or {}).get(schema_name)
    if not isinstance(schema, dict):
        raise ExecutionControlError("contract_schema_missing", f"contract schema is missing: {schema_name}")
    fields = schema.get("fields") or []
    missing = [key for key in schema.get("required") or [] if key not in value]
    extra = sorted(set(value) - set(fields))
    if missing or extra:
        raise ExecutionControlError(
            "instance_shape_invalid",
            f"{schema_name} fields differ from contract",
            detail={"missing": missing, "extra": extra},
        )
    for key, expected in (schema.get("types") or {}).items():
        if key in value and not _matches_type(value[key], expected):
            raise ExecutionControlError(
                "instance_type_invalid", f"{schema_name}.{key} must be {expected}"
            )
    for key, expected in (schema.get("const") or {}).items():
        if value.get(key) != expected:
            raise ExecutionControlError(
                "instance_const_invalid", f"{schema_name}.{key} must be {expected!r}"
            )
    for key, allowed in (schema.get("enums") or {}).items():
        if "." in key:
            outer, inner = key.split(".", 1)
            nested = value.get(outer)
            actual = nested.get(inner) if isinstance(nested, dict) else None
            if nested is not None and actual not in allowed:
                raise ExecutionControlError("instance_enum_invalid", f"{schema_name}.{key} is invalid")
        elif value.get(key) not in allowed:
            raise ExecutionControlError("instance_enum_invalid", f"{schema_name}.{key} is invalid")
    for key, shape in (schema.get("shapes") or {}).items():
        nested = value.get(key)
        if nested is not None and set(nested) != set(shape):
            raise ExecutionControlError("instance_shape_invalid", f"{schema_name}.{key} has invalid fields")
    if value.get("digest") != instance_digest(value):
        raise ExecutionControlError("instance_digest_mismatch", f"{schema_name} digest does not match")
    return value


def load_contract(path: str | Path | None = None) -> dict[str, Any]:
    resolved = Path(path) if path is not None else default_contract_path()
    try:
        contract = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionControlError("contract_unavailable", str(exc), detail={"path": str(resolved)}) from exc
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ExecutionControlError("contract_schema_mismatch", f"schema must be {CONTRACT_SCHEMA}")
    actual = instance_digest(contract)
    if contract.get("digest") != CONTRACT_DIGEST or actual != CONTRACT_DIGEST:
        raise ExecutionControlError(
            "contract_digest_mismatch", "canonical verification contract digest differs",
            detail={"expected": CONTRACT_DIGEST, "declared": contract.get("digest"), "actual": actual},
        )
    conformance = contract.get("conformance") or {}
    if conformance.get("require_exact_digest") is not True or conformance.get("artifact_digest_ref") != "$.digest":
        raise ExecutionControlError("contract_conformance_invalid", "contract does not require its exact root digest")
    for name, schema in (contract.get("schemas") or {}).items():
        fields = schema.get("fields") or []
        required = schema.get("required") or []
        nullable = schema.get("nullable") or []
        types = schema.get("types") or {}
        if len(fields) != len(set(fields)) or set(required) != set(fields):
            raise ExecutionControlError("contract_schema_invalid", f"{name} fields/required differ")
        if not set(nullable).issubset(fields) or set(types) != set(fields):
            raise ExecutionControlError("contract_schema_invalid", f"{name} nullable/types differ")
    for case in contract.get("golden_cases") or []:
        if case.get("input_digest") != tagged_digest(case.get("input")):
            raise ExecutionControlError(
                "contract_golden_digest_mismatch", f"golden input digest differs: {case.get('id')}"
            )
    return contract


def _profile_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("profiles"), list):
        return value["profiles"]
    raise ExecutionControlError("command_profiles_invalid", "command profile file must be a list or profiles object")


def load_command_profiles(path: str | Path, contract: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    contract = contract or load_contract()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionControlError("command_profiles_invalid", str(exc)) from exc
    profiles: dict[str, dict[str, Any]] = {}
    for profile in _profile_list(raw):
        validate_instance(profile, "command-profile", contract)
        profile_id = profile["profile_id"]
        if profile_id in profiles:
            raise ExecutionControlError("duplicate_command_profile", f"duplicate profile: {profile_id}")
        if not profile["executable"] or not all(isinstance(arg, str) for arg in profile["args"]):
            raise ExecutionControlError("command_profile_invalid", f"invalid executable/args: {profile_id}")
        if not all(isinstance(arg, str) and arg for arg in profile["forbidden_args"]):
            raise ExecutionControlError("command_profile_invalid", f"invalid forbidden_args: {profile_id}")
        if not profile["cwd_scope"] or not all(
            isinstance(item, str) and item for item in profile["environment_inputs"]
        ):
            raise ExecutionControlError("command_profile_invalid", f"invalid cwd/environment: {profile_id}")
        if not all(isinstance(item, str) and item for item in profile["required_capabilities"]):
            raise ExecutionControlError("command_profile_invalid", f"invalid capabilities: {profile_id}")
        profiles[profile_id] = profile
    if not profiles:
        raise ExecutionControlError("command_profiles_empty", "at least one command profile is required")
    return profiles


def load_impact_rules(path: str | Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionControlError("impact_rules_invalid", str(exc)) from exc
    if isinstance(raw, list):
        rules = raw
    elif isinstance(raw, dict) and raw.get("schema") == IMPACT_RULE_SET_SCHEMA:
        rules = raw.get("rules")
    else:
        raise ExecutionControlError("impact_rules_invalid", "impact rules must be a list or impact-rule-set/v1")
    if not isinstance(rules, list) or not rules:
        raise ExecutionControlError("impact_rules_invalid", "impact rules must be a non-empty list")
    seen: set[str] = set()
    for rule in rules:
        required = {"rule_id", "path_globs", "qa_modes", "command_profile_ids"}
        if not isinstance(rule, dict) or not required.issubset(rule):
            raise ExecutionControlError("impact_rule_invalid", "impact rule is missing required fields")
        if set(rule) - (required | {"purposes", "full_qa_reason_codes"}):
            raise ExecutionControlError("impact_rule_invalid", f"unknown fields in {rule.get('rule_id')}")
        rule_id = rule["rule_id"]
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen:
            raise ExecutionControlError("impact_rule_invalid", f"invalid or duplicate rule_id: {rule_id!r}")
        seen.add(rule_id)
        if not isinstance(rule["path_globs"], list) or not rule["path_globs"] or not all(
            isinstance(item, str) and item for item in rule["path_globs"]
        ):
            raise ExecutionControlError("impact_rule_invalid", f"{rule_id}.path_globs must be non-empty")
        if not isinstance(rule["qa_modes"], list) or not rule["qa_modes"] or not set(rule["qa_modes"]).issubset(QA_MODES):
            raise ExecutionControlError("impact_rule_invalid", f"{rule_id}.qa_modes is invalid")
        if not isinstance(rule["command_profile_ids"], list) or not rule["command_profile_ids"] or not all(
            isinstance(item, str) and item for item in rule["command_profile_ids"]
        ):
            raise ExecutionControlError("impact_rule_invalid", f"{rule_id}.command_profile_ids must be non-empty")
    return rules


def _forbidden_token(token: str, forbidden: str) -> bool:
    return token == forbidden or token.startswith(forbidden + "=") or fnmatch.fnmatchcase(token, forbidden)


def resolved_command(
    profile: dict[str, Any], *, cwd: str, environment: dict[str, str],
    argv: list[str] | None = None,
) -> dict[str, Any]:
    """Return the canonical physical command preimage shared with Studio."""
    expected_argv = [profile["executable"], *profile["args"]]
    actual_argv = expected_argv if argv is None else argv
    if not isinstance(actual_argv, list) or not all(isinstance(item, str) for item in actual_argv):
        raise ExecutionControlError("argv_profile_mismatch", "argv must be a string list")
    forbidden = [
        token for token in actual_argv
        if any(_forbidden_token(token, pattern) for pattern in profile["forbidden_args"])
    ]
    if forbidden:
        raise ExecutionControlError("forbidden_argv", "command contains forbidden argv", detail={"argv": forbidden})
    if actual_argv != expected_argv:
        raise ExecutionControlError("argv_profile_mismatch", "argv must exactly match the immutable command profile")
    if not isinstance(cwd, str) or not cwd.strip():
        raise ExecutionControlError("command_cwd_invalid", "resolved command cwd must be non-empty")
    command_cwd = Path(cwd)
    scope = Path(profile["cwd_scope"])
    if command_cwd.is_absolute() or scope.is_absolute() or ".." in command_cwd.parts or ".." in scope.parts:
        raise ExecutionControlError("command_cwd_invalid", "resolved command cwd must stay repository-relative")
    if scope.as_posix() not in (".", "repository"):
        try:
            command_cwd.relative_to(scope)
        except ValueError as exc:
            raise ExecutionControlError("command_cwd_invalid", "resolved command cwd is outside cwd_scope") from exc
    if not isinstance(environment, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()
    ):
        raise ExecutionControlError("command_environment_invalid", "resolved environment must be a string mapping")
    if set(environment) != set(profile["environment_inputs"]):
        raise ExecutionControlError(
            "command_environment_invalid", "resolved environment differs from command profile inputs"
        )
    return {
        "executable": profile["executable"],
        "args": profile["args"],
        "cwd": cwd,
        "environment": environment,
    }


def command_digest(command: dict[str, Any]) -> str:
    if not isinstance(command, dict) or set(command) != set(COMMAND_DIGEST_FIELDS):
        raise ExecutionControlError(
            "command_preimage_invalid",
            "command digest preimage must contain executable, args, cwd, and environment",
        )
    if not isinstance(command["executable"], str) or not command["executable"].strip():
        raise ExecutionControlError("command_preimage_invalid", "command executable must be non-empty")
    if not isinstance(command["args"], list) or any(not isinstance(item, str) for item in command["args"]):
        raise ExecutionControlError("command_preimage_invalid", "command args must be a string list")
    if not isinstance(command["cwd"], str) or not command["cwd"].strip():
        raise ExecutionControlError("command_preimage_invalid", "command cwd must be non-empty")
    if not isinstance(command["environment"], dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in command["environment"].items()
    ):
        raise ExecutionControlError("command_preimage_invalid", "command environment must be a string mapping")
    return tagged_digest(command)


def select_execution(
    *, profiles: dict[str, dict[str, Any]], impact_rules: list[dict[str, Any]],
    changed_paths: Iterable[str], qa_mode: str, profile_id: str | None = None,
    cwd: str, environment: dict[str, str], argv: list[str] | None = None, purpose: str | None = None,
    full_qa_reason: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = sorted(set(changed_paths))
    if not paths:
        raise ExecutionControlError("impact_set_empty", "changed_paths must not be empty")
    matched: list[dict[str, Any]] = []
    uncovered = []
    for changed in paths:
        candidates = [rule for rule in impact_rules if any(fnmatch.fnmatchcase(changed, glob) for glob in rule["path_globs"])]
        if not candidates:
            uncovered.append(changed)
        for rule in candidates:
            if rule not in matched:
                matched.append(rule)
    if uncovered:
        raise ExecutionControlError("impact_unknown", "changed paths have no impact rule", detail={"paths": uncovered})
    allowed_modes = set.intersection(*(set(rule["qa_modes"]) for rule in matched))
    if qa_mode not in allowed_modes:
        raise ExecutionControlError(
            "qa_mode_not_allowed", f"qa mode {qa_mode!r} is not allowed",
            detail={"allowed_qa_modes": sorted(allowed_modes), "rules": [rule["rule_id"] for rule in matched]},
        )
    allowed_profiles = set.intersection(*(set(rule["command_profile_ids"]) for rule in matched))
    selected = profile_id or (next(iter(allowed_profiles)) if len(allowed_profiles) == 1 else None)
    if selected is None or selected not in allowed_profiles or selected not in profiles:
        raise ExecutionControlError(
            "command_profile_not_allowed", "requested command profile is not allowed",
            detail={"allowed_profile_ids": sorted(allowed_profiles)},
        )
    if purpose is not None:
        bad = [rule["rule_id"] for rule in matched if rule.get("purposes") and purpose not in rule["purposes"]]
        if bad:
            raise ExecutionControlError("purpose_not_allowed", f"purpose is not allowed by rules: {bad}")
    if qa_mode == "full":
        code = full_qa_reason.get("code") if isinstance(full_qa_reason, dict) else None
        if not isinstance(code, str) or not code:
            raise ExecutionControlError("full_qa_reason_required", "full QA requires a machine-readable reason")
        allowed_codes = set.intersection(*(
            set(rule.get("full_qa_reason_codes") or [code]) for rule in matched
        ))
        if code not in allowed_codes:
            raise ExecutionControlError("full_qa_reason_not_allowed", f"full QA reason is not allowed: {code}")
    profile = profiles[selected]
    command = resolved_command(profile, cwd=cwd, environment=environment, argv=argv)
    return {
        "action": "execute",
        "qa_mode": qa_mode,
        "profile_id": selected,
        "command_profile_digest": profile["digest"],
        "command_digest": command_digest(command),
        "command": command,
        "argv": [command["executable"], *command["args"]],
        "impact_set": paths,
        "required_capabilities": sorted(set(profile["required_capabilities"])),
        "fresh_policy": profile["fresh_policy"],
        "matched_rule_ids": [rule["rule_id"] for rule in matched],
        "full_qa_reason": full_qa_reason if qa_mode == "full" else None,
    }


def validate_permit_policy(permit: dict[str, Any], plan: dict[str, Any]) -> None:
    expected = {
        "qa_mode": plan["qa_mode"],
        "command_profile_id": plan["profile_id"],
        "command_digest": plan["command_digest"],
        "impact_set": plan["impact_set"],
    }
    mismatch = {
        key: {"permit": permit.get(key), "policy": value}
        for key, value in expected.items() if permit.get(key) != value
    }
    missing_capabilities = sorted(
        set(plan["required_capabilities"]) - set(permit.get("required_capabilities") or [])
    )
    if mismatch or missing_capabilities:
        raise ExecutionControlError(
            "permit_policy_mismatch", "execution permit differs from selected command policy",
            detail={"mismatch": mismatch, "missing_capabilities": missing_capabilities},
        )
    if (
        plan["fresh_policy"] == "fresh-required"
        or permit.get("purpose") in FRESH_PURPOSES
        or permit.get("qa_mode") in {"final", "integration"}
    ) and permit.get("fresh_requirement_id") is None:
        raise ExecutionControlError(
            "fresh_requirement_required", "fresh-required profile needs fresh_requirement_id"
        )


def validate_mutation_request(value: Any) -> dict[str, Any]:
    fields = {
        "mutation_request_id", "provider", "operation", "resource_kind", "target_ref",
        "one_time_usd", "monthly_usd", "digest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ExecutionControlError(
            "invalid_mutation_request", "mutation request fields differ from the canonical permit shape"
        )
    for field in ("mutation_request_id", "provider", "operation", "resource_kind", "target_ref"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ExecutionControlError("invalid_mutation_request", f"mutation request {field} must be non-empty")
    for field in ("one_time_usd", "monthly_usd"):
        amount = value[field]
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
            raise ExecutionControlError("invalid_mutation_request", f"mutation request {field} must be non-negative")
    if value["digest"] != instance_digest(value):
        raise ExecutionControlError("instance_digest_mismatch", "mutation request digest does not match")
    return value


def fresh_required(permit: dict[str, Any]) -> bool:
    return bool(
        permit.get("purpose") in FRESH_PURPOSES
        or permit.get("qa_mode") in {"final", "integration"}
    )


def physical_identity(permit: dict[str, Any]) -> str:
    identity = {
        key: permit[key]
        for key in ("head", "command_digest", "environment_digest", "tool_version", "purpose")
    }
    if permit.get("fresh_requirement_id") is not None:
        identity["fresh_requirement_id"] = permit["fresh_requirement_id"]
    return tagged_digest(identity)


def evidence_applicable(
    permit: dict[str, Any], evidence: dict[str, Any], *,
    criteria_digest: str | None = None, covered_paths: Iterable[str] | None = None,
    surface_digest: str | None = None, independence: str | None = None,
) -> bool:
    if evidence.get("result") != "pass" or evidence.get("invalidation") is not None:
        return False
    if physical_identity(permit) != physical_identity(evidence):
        return False
    exact = ("purpose", "target", "impact_set")
    if any(evidence.get(key) != permit.get(key) for key in exact):
        return False
    if evidence.get("criteria_digest") != (criteria_digest or permit.get("criteria_digest")):
        return False
    if surface_digest is not None and evidence.get("surface_digest") != surface_digest:
        return False
    if independence is not None and evidence.get("independence") != independence:
        return False
    required_paths = set(covered_paths or permit.get("impact_set") or [])
    return required_paths.issubset(set(evidence.get("covered_paths") or []))


def evaluate_permit(
    permit: dict[str, Any], *, contract: dict[str, Any], evidence: dict[str, Any] | None = None,
    active_claim: dict[str, Any] | None = None, attempts: int = 0,
) -> dict[str, Any]:
    validate_instance(permit, "execution-permit", contract)
    if permit["state"] != "planned" or any(
        permit.get(key) is not None for key in ("claim_id", "claimed_by", "claimed_at", "completed_at")
    ):
        raise ExecutionControlError("permit_state_invalid", "only an unclaimed planned permit may execute")
    key = physical_identity(permit)
    if active_claim is not None and active_claim.get("physical_key") == key and active_claim.get("state") == "claimed":
        return {"action": "reject", "error": {"code": "duplicate_active", "claim_id": active_claim.get("claim_id")}, "physical_run_started": False}
    if evidence is not None:
        validate_instance(evidence, "verification-evidence", contract)
        if evidence_applicable(permit, evidence):
            return {"action": "reuse-evidence", "error": None, "evidence_refs": [evidence["evidence_id"]], "physical_run_started": False}
    if attempts >= permit["max_physical_runs"]:
        return {
            "action": "reject",
            "error": {"code": "physical_run_limit_reached", "max_physical_runs": permit["max_physical_runs"]},
            "physical_run_started": False,
            "owner_gate_required": True,
        }
    result: dict[str, Any] = {
        "action": "claim", "error": None, "permit_id": permit["permit_id"], "physical_key": key,
    }
    if evidence is not None and evidence.get("fresh_requirement_id") != permit.get("fresh_requirement_id"):
        result.update({"reason": "fresh_requirement_changed", "physical_run_started": True})
        result.pop("physical_key", None)
        result.pop("permit_id", None)
    return result


def evaluate_request(value: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    if "permit" in value:
        permit = value["permit"]
        mutation = permit.get("mutation_request") if isinstance(permit, dict) else None
        if mutation is not None and (mutation.get("one_time_usd", 0) > 0 or mutation.get("monthly_usd", 0) > 0):
            authorization = value.get("authorization")
            validate_instance(permit, "execution-permit", contract)
            if authorization is None or not authorization_matches(authorization, mutation, contract):
                return {"action": "reject", "error": {"code": "external_spend_not_authorized", "mutation_request_id": mutation["mutation_request_id"]}, "mutation_started": False}
            refs = set(permit.get("external_authorization_refs") or [])
            if authorization["authorization_id"] not in refs and authorization["digest"] not in refs:
                return {"action": "reject", "error": {"code": "external_spend_not_authorized", "mutation_request_id": mutation["mutation_request_id"]}, "mutation_started": False}
        return evaluate_permit(
            permit, contract=contract, evidence=value.get("evidence") or value.get("existing_evidence"),
            active_claim=value.get("active_claim"), attempts=len(value.get("attempts") or []),
        )
    if "evidence" in value and "change" in value:
        evidence, change = value["evidence"], value["change"]
        validate_instance(evidence, "verification-evidence", contract)
        reason = None
        if change.get("criteria_digest") != evidence.get("criteria_digest"):
            reason = "criteria-changed"
        elif change.get("surface_digest") != evidence.get("surface_digest"):
            reason = "surface-changed"
        elif set(change.get("impact_set") or []) != set(evidence.get("impact_set") or []):
            reason = "impact-unknown"
        elif change.get("changed_paths"):
            reason = "path-overlap"
        return {"action": "delta-qa" if reason else "reuse-evidence", "error": None, "invalidated_evidence": [evidence["evidence_id"]] if reason else [], "reason": reason}
    if "required_capabilities" in value:
        snapshot = value.get("snapshot")
        if snapshot is not None:
            validate_instance(snapshot, "capability-snapshot", contract)
            if (
                snapshot["mission_id"] == value["mission_id"]
                and snapshot["environment_digest"] == value["environment_digest"]
                and snapshot["capability_id"] in value["required_capabilities"]
                and snapshot["status"] == "unavailable"
            ):
                return {"action": "block-dispatch", "error": {"code": "capability_unavailable", "capability_id": snapshot["capability_id"]}, "probe_required": False, "snapshot_id": snapshot["snapshot_id"]}
        return {"action": "probe-capability", "error": None, "probe_required": True}
    if "authorization" in value and "mutation_request" in value:
        return evaluate_spend_claim(value["authorization"], value["mutation_request"], value.get("existing_consumptions") or [], contract)
    if "telemetry_policy" in value and "receipt" in value:
        receipt = value["receipt"]
        validate_instance(receipt, "command-receipt", contract)
        if receipt["tokens"] is None and receipt["token_coverage"] != "unavailable":
            raise ExecutionControlError(
                "token_coverage_invalid", "tokens:null requires token_coverage=unavailable"
            )
        if receipt["tokens"] is not None and receipt["token_coverage"] == "unavailable":
            raise ExecutionControlError(
                "token_coverage_invalid", "measured tokens cannot use unavailable coverage"
            )
        if receipt["tokens"] is None and value["telemetry_policy"] == "fail-closed":
            return {"action": "pause", "error": {"code": "token_coverage_unavailable", "receipt_id": receipt["receipt_id"]}, "tokens_counted": None}
        return {"action": "accept-report-only" if receipt["tokens"] is None else "accept", "error": None, "tokens_counted": receipt["tokens"]}
    if "receipt" in value and value["receipt"].get("schema") == "closeout-receipt/v1":
        receipt = value["receipt"]
        validate_instance(receipt, "closeout-receipt", contract)
        required = ("verification_evidence_refs", "review_lease_refs", "delivery_receipt_refs", "cleanup_receipt_refs")
        missing = [key for key in required if not receipt[key]]
        if missing or receipt["open_findings"]:
            return {"action": "reject", "error": {"code": "closeout_incomplete", "missing": missing, "open_findings": receipt["open_findings"]}}
        return {"action": "closeout", "error": None}
    raise ExecutionControlError("request_shape_unknown", "execution control request shape is unknown")


def evaluate_spend_claim(
    authorization: dict[str, Any], mutation: dict[str, Any], consumptions: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    if mutation.get("digest") != instance_digest(mutation):
        raise ExecutionControlError("instance_digest_mismatch", "mutation request digest does not match")
    if not authorization_matches(authorization, mutation, contract):
        return {"action": "reject", "error": {"code": "external_spend_not_authorized"}, "mutation_started": False}
    occurrence = len([
        item for item in consumptions
        if item.get("authorization_digest") == authorization["digest"]
        and item.get("mutation_request_digest") == mutation["digest"]
        and item.get("claim_state") in {"claimed", "consumed"}
    ]) + 1
    if occurrence > authorization["max_occurrences"]:
        return {"action": "reject", "error": {"code": "external_spend_quota_exhausted"}, "mutation_started": False}
    claim_key = tagged_digest({"authorization_digest": authorization["digest"], "mutation_request_digest": mutation["digest"], "occurrence_index": occurrence})
    return {"action": "claim-spend-consumption", "error": None, "occurrence_index": occurrence, "claim_state": "claimed", "claim_key": claim_key}


def authorization_matches(
    authorization: dict[str, Any], mutation: dict[str, Any], contract: dict[str, Any]
) -> bool:
    validate_instance(authorization, "external-spend-authorization", contract)
    return bool(
        authorization["owner_approved"]
        and authorization.get("approved_by") is not None
        and authorization.get("approved_at") is not None
        and authorization["mutation_request_ref"] == mutation.get("mutation_request_id")
        and authorization["mutation_request_digest"] == mutation.get("digest")
        and authorization["provider"] == mutation.get("provider")
        and authorization["resource_kind"] == mutation.get("resource_kind")
        and authorization["scope"] == mutation.get("target_ref")
        and authorization["one_time_usd"] == mutation.get("one_time_usd")
        and authorization["monthly_usd"] == mutation.get("monthly_usd")
    )


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


@contextmanager
def _locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".execution.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionControlError("execution_state_corrupt", str(exc), detail={"path": str(path)}) from exc


def _validate_mutation_gate(
    permit: dict[str, Any], authorization: dict[str, Any] | None,
    preflight_receipt: dict[str, Any] | None, contract: dict[str, Any], *, now: str,
) -> tuple[dict[str, Any] | None, bool]:
    mutation = permit.get("mutation_request")
    if mutation is None:
        if authorization is not None or preflight_receipt is not None:
            raise ExecutionControlError(
                "mutation_gate_not_applicable", "authorization or preflight requires a mutation request"
            )
        return None, False
    mutation = validate_mutation_request(mutation)
    if preflight_receipt is None:
        raise ExecutionControlError("preflight_required", "external mutation requires a preflight receipt")
    validate_instance(preflight_receipt, "preflight-receipt", contract)
    if (
        preflight_receipt["result"] != "pass"
        or preflight_receipt["environment_digest"] != permit["environment_digest"]
        or preflight_receipt["target_ref"] != mutation["target_ref"]
        or preflight_receipt["missing_keys"]
        or preflight_receipt["condition_failures"]
        or preflight_receipt["topology_drift"]
    ):
        raise ExecutionControlError(
            "preflight_failed", "external mutation preflight does not authorize this target and environment"
        )
    paid = mutation["one_time_usd"] > 0 or mutation["monthly_usd"] > 0
    if not paid:
        if authorization is not None or permit["external_authorization_refs"]:
            raise ExecutionControlError(
                "external_spend_not_applicable", "free mutation must not bind spend authorization"
            )
        return mutation, False
    if authorization is None:
        raise ExecutionControlError(
            "external_spend_not_authorized", "paid mutation requires owner-approved authorization"
        )
    validate_instance(authorization, "external-spend-authorization", contract)
    if authorization["mission_id"] != permit["mission_id"] or not authorization_matches(
        authorization, mutation, contract,
    ):
        raise ExecutionControlError(
            "external_spend_not_authorized", "authorization does not bind this mission and mutation"
        )
    refs = set(permit["external_authorization_refs"])
    if authorization["authorization_id"] not in refs and authorization["digest"] not in refs:
        raise ExecutionControlError(
            "external_spend_not_authorized", "permit does not pin the supplied authorization"
        )
    expires_at = _timestamp(authorization.get("expires_at"))
    if expires_at is not None and expires_at <= _timestamp(now):
        raise ExecutionControlError(
            "external_spend_authorization_expired", "external spend authorization expired"
        )
    return mutation, True


def _claim_spend_locked(
    root: Path, permit: dict[str, Any], mutation: dict[str, Any], authorization: dict[str, Any],
    preflight_receipt: dict[str, Any], contract: dict[str, Any], *, claim_id: str,
) -> dict[str, Any]:
    _store_immutable(
        _object_file(root / "spend-authorizations", authorization["authorization_id"]), authorization,
    )
    auth_key = authorization["digest"].removeprefix("sha256:")
    ledger_path = root / "spend" / f"{auth_key}.json"
    ledger = _read(ledger_path) if ledger_path.exists() else {
        "schema": "task-worker.spend-ledger/v1",
        "authorization_digest": authorization["digest"],
        "consumptions": [],
    }
    decision = evaluate_spend_claim(authorization, mutation, ledger["consumptions"], contract)
    if decision["action"] != "claim-spend-consumption":
        code = str((decision.get("error") or {}).get("code") or "external_spend_not_authorized")
        raise ExecutionControlError(code, "external spend claim was rejected", detail=decision)
    consumption = {
        "schema": "external-spend-consumption/v1",
        "consumption_id": "spend-" + decision["claim_key"].removeprefix("sha256:")[:20],
        "authorization_id": authorization["authorization_id"],
        "authorization_digest": authorization["digest"],
        "mutation_request_ref": mutation["mutation_request_id"],
        "mutation_request_digest": mutation["digest"],
        "scope": authorization["scope"],
        "occurrence_index": decision["occurrence_index"],
        "one_time_usd": authorization["one_time_usd"],
        "monthly_usd": authorization["monthly_usd"],
        "claim_id": claim_id,
        "claim_state": "claimed",
        "mutation_receipt_ref": None,
        "consumed_at": None,
    }
    consumption["digest"] = instance_digest(consumption)
    validate_instance(consumption, "external-spend-consumption", contract)
    ledger["consumptions"].append(consumption)
    _write_atomic(ledger_path, ledger)
    _store_immutable(_object_file(root / "spend-consumptions", consumption["consumption_id"]), consumption)
    _store_immutable(
        _object_file(root / "spend-preflight", consumption["consumption_id"]),
        {"receipt_id": preflight_receipt["receipt_id"], "digest": preflight_receipt["digest"]},
    )
    return consumption


def claim_execution(
    permit: dict[str, Any], state_root: str | Path, *, claimed_by: str,
    evidence: dict[str, Any] | None = None, contract: dict[str, Any] | None = None,
    authorization: dict[str, Any] | None = None,
    preflight_receipt: dict[str, Any] | None = None, now: str | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    validate_instance(permit, "execution-permit", contract)
    if fresh_required(permit) and permit.get("fresh_requirement_id") is None:
        raise ExecutionControlError(
            "fresh_requirement_required", "fresh execution purpose requires fresh_requirement_id"
        )
    if evidence is not None:
        validate_instance(evidence, "verification-evidence", contract)
    timestamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    mutation, paid = _validate_mutation_gate(
        permit, authorization, preflight_receipt, contract, now=timestamp,
    )
    key = physical_identity(permit)
    root = Path(state_root) / "execution-control"
    path = root / "executions" / f"{key.removeprefix('sha256:')}.json"
    with _locked(root):
        state = _read(path) if path.exists() else {"schema": EXECUTION_STATE_SCHEMA, "physical_key": key, "claims": []}
        active = next((item for item in state["claims"] if item["state"] == "claimed"), None)
        if active is None and evidence is None and mutation is None:
            for prior in reversed(state["claims"]):
                if prior.get("state") != "succeeded":
                    continue
                for evidence_ref in prior.get("evidence_refs") or []:
                    evidence_path = _object_file(root / "evidence", evidence_ref)
                    if evidence_path.exists():
                        candidate = _read(evidence_path)
                        validate_instance(candidate, "verification-evidence", contract)
                        if evidence_applicable(permit, candidate):
                            return {
                                "action": "reuse-evidence", "error": None,
                                "evidence_refs": [evidence_ref], "physical_run_started": False,
                            }
        decision = evaluate_permit(
            permit, contract=contract, evidence=None if mutation else evidence,
            active_claim=active, attempts=len(state["claims"]),
        )
        if decision["action"] != "claim":
            return decision
        claim_id = "claim-" + uuid.uuid4().hex
        _store_immutable(_object_file(root / "permits", permit["permit_id"]), permit)
        if mutation is not None:
            _store_immutable(
                _object_file(root / "mutation-requests", mutation["mutation_request_id"]), mutation,
            )
        if preflight_receipt is not None:
            _store_immutable(
                _object_file(root / "preflight-receipts", preflight_receipt["receipt_id"]),
                preflight_receipt,
            )
        consumption = _claim_spend_locked(
            root, permit, mutation, authorization, preflight_receipt, contract, claim_id=claim_id,
        ) if paid else None
        claim = {
            "claim_id": claim_id, "permit_id": permit["permit_id"], "permit_digest": permit["digest"],
            "physical_key": key,
            "claimed_by": claimed_by, "claimed_at": timestamp,
            "state": "claimed", "receipt_ref": None, "evidence_refs": [],
            "mutation_request_ref": mutation["mutation_request_id"] if mutation else None,
            "mutation_request_digest": mutation["digest"] if mutation else None,
            "preflight_receipt_ref": preflight_receipt["receipt_id"] if preflight_receipt else None,
            "preflight_receipt_digest": preflight_receipt["digest"] if preflight_receipt else None,
            "spend_consumption_ref": consumption["consumption_id"] if consumption else None,
            "spend_consumption_digest": consumption["digest"] if consumption else None,
            "authorization_ref": authorization["authorization_id"] if authorization else None,
            "authorization_digest": authorization["digest"] if authorization else None,
            "mutation_receipt_ref": None,
        }
        state["claims"].append(claim)
        _write_atomic(path, state)
        return {
            "action": "claimed", "error": None, "physical_key": key, "claim": claim,
            "spend_consumption": consumption, "path": str(path),
        }


def _store_immutable(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        if _read(path) != value:
            raise ExecutionControlError("immutable_receipt_conflict", f"immutable object differs: {path}")
        return
    _write_atomic(path, value)


def _object_file(directory: Path, object_id: str) -> Path:
    safe_name = hashlib.sha256(object_id.encode("utf-8")).hexdigest()
    return directory / f"{safe_name}.json"


def _validate_mutation_completion(
    root: Path, permit: dict[str, Any], claim: dict[str, Any], receipt: dict[str, Any],
    mutation_receipt: dict[str, Any] | None, contract: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    mutation = permit.get("mutation_request")
    if mutation is None:
        if (
            mutation_receipt is not None
            or receipt["spend_consumption_refs"]
            or receipt["external_mutation_receipt_refs"]
        ):
            raise ExecutionControlError(
                "mutation_receipt_not_applicable", "non-mutation execution cannot report mutation receipts"
            )
        return None, None, None
    mutation = validate_mutation_request(mutation)
    if (
        claim.get("mutation_request_ref") != mutation["mutation_request_id"]
        or claim.get("mutation_request_digest") != mutation["digest"]
    ):
        raise ExecutionControlError("mutation_claim_mismatch", "completion mutation differs from claimed request")
    preflight_path = _object_file(root / "preflight-receipts", claim.get("preflight_receipt_ref") or "")
    if not preflight_path.exists():
        raise ExecutionControlError("preflight_receipt_missing", "claimed mutation preflight is missing")
    stored_preflight = _read(preflight_path)
    if stored_preflight.get("digest") != claim.get("preflight_receipt_digest"):
        raise ExecutionControlError("preflight_receipt_mismatch", "claimed mutation preflight digest differs")
    if mutation_receipt is None:
        raise ExecutionControlError(
            "external_mutation_receipt_required", "external mutation requires exactly one completion receipt"
        )
    validate_instance(mutation_receipt, "external-mutation-receipt", contract)
    if receipt["external_mutation_receipt_refs"] != [mutation_receipt["mutation_id"]]:
        raise ExecutionControlError(
            "external_mutation_receipt_mismatch", "command receipt must pin the supplied mutation receipt"
        )
    expected = {
        "mutation_request_ref": mutation["mutation_request_id"],
        "mutation_request_digest": mutation["digest"],
        "provider": mutation["provider"],
        "operation": mutation["operation"],
        "target_ref": mutation["target_ref"],
        "preflight_receipt_id": claim["preflight_receipt_ref"],
    }
    paid = mutation["one_time_usd"] > 0 or mutation["monthly_usd"] > 0
    status = None
    final_consumption = None
    if paid:
        consumption_ref = claim.get("spend_consumption_ref")
        consumption_path = _object_file(root / "spend-consumptions", consumption_ref or "")
        if not consumption_ref or not consumption_path.exists():
            raise ExecutionControlError("spend_claim_not_found", "paid mutation spend claim is missing")
        consumption = _read(consumption_path)
        validate_instance(consumption, "external-spend-consumption", contract)
        if (
            consumption["authorization_id"] != claim.get("authorization_ref")
            or consumption["authorization_digest"] != claim.get("authorization_digest")
        ):
            raise ExecutionControlError("spend_claim_mismatch", "execution claim authorization differs")
        authorization_path = _object_file(
            root / "spend-authorizations", consumption["authorization_id"],
        )
        if not authorization_path.exists() or _read(authorization_path).get("digest") != consumption["authorization_digest"]:
            raise ExecutionControlError("external_spend_not_authorized", "claimed authorization is missing")
        claimed_consumption = {
            **consumption,
            "claim_state": "claimed",
            "mutation_receipt_ref": None,
            "consumed_at": None,
        }
        claimed_consumption["digest"] = instance_digest(claimed_consumption)
        if claimed_consumption["digest"] != claim.get("spend_consumption_digest"):
            raise ExecutionControlError("spend_claim_mismatch", "execution claim spend digest differs")
        if receipt["spend_consumption_refs"] != [consumption_ref]:
            raise ExecutionControlError(
                "spend_consumption_mismatch", "command receipt must pin its exact spend consumption"
            )
        final_consumption = {
            **claimed_consumption,
            "claim_state": "consumed" if mutation_receipt["result"] == "applied" else "released",
            "mutation_receipt_ref": mutation_receipt["mutation_id"],
            "consumed_at": mutation_receipt["finished_at"],
        }
        final_consumption["digest"] = instance_digest(final_consumption)
        validate_instance(final_consumption, "external-spend-consumption", contract)
        expected.update({
            "authorization_id": consumption["authorization_id"],
            "authorization_digest": consumption["authorization_digest"],
            "spend_consumption_ref": consumption["consumption_id"],
            "spend_consumption_digest": final_consumption["digest"],
        })
        status = {
            "schema": "task-worker.spend-consumption-status/v1",
            "consumption_id": consumption["consumption_id"],
            "consumption_digest": final_consumption["digest"],
            "claim_state": final_consumption["claim_state"],
            "mutation_receipt_ref": mutation_receipt["mutation_id"],
            "mutation_receipt_digest": mutation_receipt["digest"],
        }
    else:
        if claim.get("authorization_ref") is not None or claim.get("authorization_digest") is not None:
            raise ExecutionControlError(
                "external_spend_not_applicable", "free mutation claim contains spend authorization"
            )
        if receipt["spend_consumption_refs"]:
            raise ExecutionControlError(
                "spend_consumption_not_applicable", "free mutation cannot report spend consumption"
            )
        expected.update({
            "authorization_id": None,
            "authorization_digest": None,
            "spend_consumption_ref": None,
            "spend_consumption_digest": None,
        })
    mismatches = [field for field, value in expected.items() if mutation_receipt.get(field) != value]
    if mismatches:
        raise ExecutionControlError(
            "external_mutation_receipt_mismatch",
            "mutation receipt does not bind its request, preflight, and spend claim",
            detail={"fields": mismatches},
        )
    return mutation_receipt, status, final_consumption


def _store_final_consumption(root: Path, consumption: dict[str, Any]) -> None:
    consumption_path = _object_file(root / "spend-consumptions", consumption["consumption_id"])
    ledger_path = root / "spend" / f"{consumption['authorization_digest'].removeprefix('sha256:')}.json"
    if not ledger_path.exists():
        raise ExecutionControlError("spend_claim_not_found", "authorization spend ledger is missing")
    ledger = _read(ledger_path)
    matches = [
        index for index, item in enumerate(ledger.get("consumptions") or [])
        if item.get("consumption_id") == consumption["consumption_id"]
    ]
    if len(matches) != 1:
        raise ExecutionControlError("spend_claim_not_found", "authorization spend ledger entry is missing")
    ledger["consumptions"][matches[0]] = consumption
    _write_atomic(consumption_path, consumption)
    _write_atomic(ledger_path, ledger)


def complete_execution(
    permit: dict[str, Any], claim_id: str, receipt: dict[str, Any], state_root: str | Path,
    *, evidence: dict[str, Any] | None = None,
    mutation_receipt: dict[str, Any] | None = None, contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    validate_instance(permit, "execution-permit", contract)
    validate_instance(receipt, "command-receipt", contract)
    if receipt["permit_id"] != permit["permit_id"] or receipt["claim_id"] != claim_id:
        raise ExecutionControlError("receipt_claim_mismatch", "receipt does not bind the permit and claim")
    for source, target in (("profile_id", "command_profile_id"), ("purpose", "purpose"), ("target", "target"), ("head", "head"), ("command_digest", "command_digest"), ("environment_digest", "environment_digest"), ("tool_version", "tool_version"), ("fresh_requirement_id", "fresh_requirement_id")):
        if receipt[source] != permit[target]:
            raise ExecutionControlError("receipt_identity_mismatch", f"receipt {source} differs from permit")
    telemetry = evaluate_request({"telemetry_policy": permit["telemetry_policy"], "receipt": receipt}, contract)
    if telemetry["action"] == "pause":
        raise ExecutionControlError(telemetry["error"]["code"], "token telemetry is unavailable", detail=telemetry)
    if evidence is not None:
        validate_instance(evidence, "verification-evidence", contract)
        if evidence["source_receipt_id"] != receipt["receipt_id"] or not evidence_applicable(permit, evidence):
            raise ExecutionControlError("evidence_receipt_mismatch", "evidence is not applicable to its source receipt")
    key = physical_identity(permit)
    root = Path(state_root) / "execution-control"
    path = root / "executions" / f"{key.removeprefix('sha256:')}.json"
    with _locked(root):
        if not path.exists():
            raise ExecutionControlError("claim_not_found", f"execution claim not found: {claim_id}")
        state = _read(path)
        claims = [item for item in state["claims"] if item["claim_id"] == claim_id]
        if len(claims) != 1:
            raise ExecutionControlError("claim_not_found", f"execution claim not found: {claim_id}")
        claim = claims[0]
        stored_permit_path = _object_file(root / "permits", permit["permit_id"])
        if (
            claim.get("permit_digest") != permit["digest"]
            or not stored_permit_path.exists()
            or _read(stored_permit_path) != permit
        ):
            raise ExecutionControlError("permit_claim_mismatch", "completion permit differs from claimed permit")
        if claim["state"] not in {"claimed", "succeeded", "failed"}:
            raise ExecutionControlError("claim_state_conflict", f"claim cannot complete from {claim['state']}")
        receipt_path = _object_file(root / "receipts", receipt["receipt_id"])
        if receipt_path.exists() and _read(receipt_path) != receipt:
            raise ExecutionControlError("immutable_receipt_conflict", "command receipt id is immutable")
        completed_mutation, spend_status, final_consumption = _validate_mutation_completion(
            root, permit, claim, receipt, mutation_receipt, contract,
        )
        evidence_refs: list[str] = []
        if evidence is not None:
            evidence_path = _object_file(root / "evidence", evidence["evidence_id"])
            if evidence_path.exists() and _read(evidence_path) != evidence:
                raise ExecutionControlError("immutable_receipt_conflict", "verification evidence id is immutable")
            evidence_refs.append(evidence["evidence_id"])
        next_state = "succeeded" if receipt["result"] == "pass" else "failed"
        if claim["state"] not in {"claimed", next_state}:
            raise ExecutionControlError("claim_state_conflict", f"claim cannot complete from {claim['state']}")
        if completed_mutation is not None:
            _store_immutable(
                _object_file(root / "mutation-receipts", completed_mutation["mutation_id"]),
                completed_mutation,
            )
        if spend_status is not None:
            assert final_consumption is not None
            _store_final_consumption(root, final_consumption)
            _store_immutable(
                _object_file(root / "spend-status", spend_status["consumption_id"]), spend_status,
            )
        _store_immutable(receipt_path, receipt)
        if evidence is not None:
            _store_immutable(_object_file(root / "evidence", evidence["evidence_id"]), evidence)
        claim.update({
            "state": next_state,
            "receipt_ref": receipt["receipt_id"],
            "evidence_refs": evidence_refs,
            "mutation_receipt_ref": completed_mutation["mutation_id"] if completed_mutation else None,
        })
        _write_atomic(path, state)
        return {
            "action": "completed", "state": next_state, "receipt_ref": receipt["receipt_id"],
            "evidence_refs": evidence_refs,
            "external_mutation_receipt_ref": completed_mutation["mutation_id"] if completed_mutation else None,
            "spend_status": spend_status, "telemetry": telemetry,
        }


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed
    except ValueError as exc:
        raise ExecutionControlError("timestamp_invalid", f"invalid RFC3339 timestamp: {value}") from exc


def claim_spend_consumption(
    authorization: dict[str, Any], mutation: dict[str, Any], state_root: str | Path,
    *, preflight_receipt: dict[str, Any],
    contract: dict[str, Any] | None = None, now: str | None = None,
) -> dict[str, Any]:
    """Atomically reserve one authorized occurrence before an external mutation."""
    contract = contract or load_contract()
    validate_instance(authorization, "external-spend-authorization", contract)
    mutation = validate_mutation_request(mutation)
    validate_instance(preflight_receipt, "preflight-receipt", contract)
    if (
        preflight_receipt["result"] != "pass"
        or preflight_receipt["target_ref"] != mutation["target_ref"]
        or preflight_receipt["missing_keys"]
        or preflight_receipt["condition_failures"]
        or preflight_receipt["topology_drift"]
    ):
        raise ExecutionControlError("preflight_failed", "external mutation preflight did not pass")
    timestamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    expires_at = _timestamp(authorization.get("expires_at"))
    if expires_at is not None and expires_at <= _timestamp(timestamp):
        raise ExecutionControlError("external_spend_authorization_expired", "external spend authorization expired")
    root = Path(state_root) / "execution-control"
    auth_key = authorization["digest"].removeprefix("sha256:")
    ledger_path = root / "spend" / f"{auth_key}.json"
    with _locked(root):
        _store_immutable(
            _object_file(root / "spend-authorizations", authorization["authorization_id"]), authorization,
        )
        ledger = _read(ledger_path) if ledger_path.exists() else {
            "schema": "task-worker.spend-ledger/v1", "authorization_digest": authorization["digest"],
            "consumptions": [],
        }
        decision = evaluate_spend_claim(authorization, mutation, ledger["consumptions"], contract)
        if decision["action"] != "claim-spend-consumption":
            return decision
        claim_id = "claim-" + uuid.uuid4().hex
        consumption = {
            "schema": "external-spend-consumption/v1",
            "consumption_id": "spend-" + decision["claim_key"].removeprefix("sha256:")[:20],
            "authorization_id": authorization["authorization_id"],
            "authorization_digest": authorization["digest"],
            "mutation_request_ref": mutation["mutation_request_id"],
            "mutation_request_digest": mutation["digest"],
            "scope": authorization["scope"],
            "occurrence_index": decision["occurrence_index"],
            "one_time_usd": authorization["one_time_usd"],
            "monthly_usd": authorization["monthly_usd"],
            "claim_id": claim_id,
            "claim_state": "claimed",
            "mutation_receipt_ref": None,
            "consumed_at": None,
        }
        consumption["digest"] = instance_digest(consumption)
        validate_instance(consumption, "external-spend-consumption", contract)
        ledger["consumptions"].append(consumption)
        _write_atomic(ledger_path, ledger)
        _store_immutable(_object_file(root / "spend-consumptions", consumption["consumption_id"]), consumption)
        preflight_ref = {
            "receipt_id": preflight_receipt["receipt_id"], "digest": preflight_receipt["digest"],
        }
        _store_immutable(
            _object_file(root / "spend-preflight", consumption["consumption_id"]), preflight_ref,
        )
        return {
            **decision, "claim_id": claim_id, "consumption": consumption,
            "preflight_receipt_ref": preflight_ref,
        }


def record_external_mutation(
    consumption: dict[str, Any], mutation_receipt: dict[str, Any], state_root: str | Path,
    *, contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a mutation receipt to the exact immutable spend claim in both directions."""
    contract = contract or load_contract()
    validate_instance(consumption, "external-spend-consumption", contract)
    validate_instance(mutation_receipt, "external-mutation-receipt", contract)
    final_consumption = {
        **consumption,
        "claim_state": "consumed" if mutation_receipt["result"] == "applied" else "released",
        "mutation_receipt_ref": mutation_receipt["mutation_id"],
        "consumed_at": mutation_receipt["finished_at"],
    }
    final_consumption["digest"] = instance_digest(final_consumption)
    validate_instance(final_consumption, "external-spend-consumption", contract)
    expected = {
        "mutation_request_ref": consumption["mutation_request_ref"],
        "mutation_request_digest": consumption["mutation_request_digest"],
        "authorization_id": consumption["authorization_id"],
        "authorization_digest": consumption["authorization_digest"],
        "spend_consumption_ref": consumption["consumption_id"],
        "spend_consumption_digest": final_consumption["digest"],
    }
    if any(mutation_receipt.get(key) != value for key, value in expected.items()):
        raise ExecutionControlError("mutation_consumption_mismatch", "mutation receipt does not bind spend claim")
    root = Path(state_root) / "execution-control"
    with _locked(root):
        stored_consumption = _object_file(root / "spend-consumptions", consumption["consumption_id"])
        if (
            not stored_consumption.exists()
            or _read(stored_consumption) not in (consumption, final_consumption)
        ):
            raise ExecutionControlError("spend_claim_not_found", "immutable spend claim was not recorded")
        preflight_path = _object_file(root / "spend-preflight", consumption["consumption_id"])
        if not preflight_path.exists():
            raise ExecutionControlError("preflight_receipt_missing", "external mutation preflight is missing")
        preflight_ref = _read(preflight_path)
        if mutation_receipt.get("preflight_receipt_id") != preflight_ref.get("receipt_id"):
            raise ExecutionControlError("preflight_receipt_mismatch", "mutation receipt uses another preflight")
        _store_immutable(
            _object_file(root / "mutation-receipts", mutation_receipt["mutation_id"]), mutation_receipt,
        )
        _store_final_consumption(root, final_consumption)
        status_path = _object_file(root / "spend-status", consumption["consumption_id"])
        status = {
            "schema": "task-worker.spend-consumption-status/v1",
            "consumption_id": consumption["consumption_id"],
            "consumption_digest": final_consumption["digest"],
            "claim_state": final_consumption["claim_state"],
            "mutation_receipt_ref": mutation_receipt["mutation_id"],
            "mutation_receipt_digest": mutation_receipt["digest"],
        }
        _store_immutable(status_path, status)
        return status


def capability_plan(
    mission_id: str, required_capabilities: Iterable[str], environment_digest: str,
    state_root: str | Path, *, now: str | None = None,
) -> dict[str, Any]:
    """Claim missing probes once per mission/capability/environment tuple."""
    root = Path(state_root) / "execution-control"
    blocked = []
    probes = []
    pending = []
    current_time = _timestamp(now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    with _locked(root):
        for capability_id in sorted(set(required_capabilities)):
            key = tagged_digest({
                "mission_id": mission_id, "capability_id": capability_id,
                "environment_digest": environment_digest,
            }).removeprefix("sha256:")
            path = root / "capabilities" / f"{key}.json"
            if path.exists():
                state = _read(path)
                snapshot = state.get("snapshot")
                expires = _timestamp(snapshot.get("expires_at")) if isinstance(snapshot, dict) else None
                if isinstance(snapshot, dict) and (expires is None or expires > current_time):
                    status = snapshot.get("status")
                    if status == "available":
                        continue
                    if status == "unavailable":
                        blocked.append({
                            "capability_id": capability_id,
                            "snapshot_id": snapshot["snapshot_id"],
                            "reason": "capability_unavailable",
                        })
                        continue
                    if status != "unknown":
                        raise ExecutionControlError(
                            "capability_snapshot_invalid", f"unexpected capability status: {status!r}"
                        )
                    # Unknown is not availability. Replace the cache entry with a
                    # new probe claim so subsequent callers observe probe-in-progress.
                if state.get("state") == "probing":
                    pending.append({"capability_id": capability_id, "claim_id": state.get("claim_id")})
                    continue
            probe_claim = {
                "schema": "task-worker.capability-probe-claim/v1",
                "mission_id": mission_id, "capability_id": capability_id,
                "environment_digest": environment_digest,
                "claim_id": "claim-" + uuid.uuid4().hex,
                "state": "probing",
            }
            _write_atomic(path, probe_claim)
            probes.append(probe_claim)
    return {
        "action": "block-dispatch" if blocked else (
            "probe-capability" if probes else ("probe-in-progress" if pending else "dispatch")
        ),
        "blocked": blocked,
        "probe_claims": probes,
        "pending_probes": pending,
    }


def record_capability_snapshot(
    snapshot: dict[str, Any], state_root: str | Path,
    *, contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    validate_instance(snapshot, "capability-snapshot", contract)
    root = Path(state_root) / "execution-control"
    key = tagged_digest({
        "mission_id": snapshot["mission_id"], "capability_id": snapshot["capability_id"],
        "environment_digest": snapshot["environment_digest"],
    }).removeprefix("sha256:")
    with _locked(root):
        cache_path = root / "capabilities" / f"{key}.json"
        if not cache_path.exists():
            raise ExecutionControlError("capability_probe_not_claimed", "capability probe was not claimed")
        current = _read(cache_path)
        if current.get("state") != "probing":
            if current.get("snapshot") == snapshot:
                return current
            raise ExecutionControlError("capability_probe_conflict", "capability snapshot conflicts with cache")
        _store_immutable(_object_file(root / "capability-snapshots", snapshot["snapshot_id"]), snapshot)
        state = {
            "schema": "task-worker.capability-cache/v1",
            "mission_id": snapshot["mission_id"], "capability_id": snapshot["capability_id"],
            "environment_digest": snapshot["environment_digest"], "snapshot": snapshot,
        }
        _write_atomic(cache_path, state)
        return state


def project_receipts(receipt: dict[str, Any], evidence: dict[str, Any] | None, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    validate_instance(receipt, "command-receipt", contract)
    evidence_ref = None
    if evidence is not None:
        validate_instance(evidence, "verification-evidence", contract)
        if evidence["source_receipt_id"] != receipt["receipt_id"]:
            raise ExecutionControlError("evidence_receipt_mismatch", "evidence source receipt differs")
        evidence_ref = {"evidence_id": evidence["evidence_id"], "digest": evidence["digest"]}
    return {
        "schema": "task-worker.execution-projection/v1",
        "receipt_ref": {"receipt_id": receipt["receipt_id"], "digest": receipt["digest"]},
        "evidence_ref": evidence_ref,
        "head": receipt["head"],
        "result": receipt["result"],
    }
