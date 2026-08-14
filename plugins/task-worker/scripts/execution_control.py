#!/usr/bin/env python3
"""Provider-neutral command policy, execution claims, and immutable evidence."""

from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONTRACT_SCHEMA = "studio-verification-contract-set/v1"
CONTRACT_DIGEST = "sha256:ad4f7a721a2ad4278dc81c3413b70b0d4be0c68265ffccd62737725c2b907c0c"
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
REUSE_FINGERPRINT_SCHEMA = "task-worker.reuse-fingerprint/v1"
REUSE_RESOLVER_SCHEMA = "task-worker.reuse-resolver/v1"
EVIDENCE_BATCH_SCHEMA = "task-worker.verification-evidence-batch/v1"
FINAL_QA_PROJECTION_SCHEMA = "task-worker.final-qa-projection/v1"
REUSE_FINGERPRINT_FIELDS = frozenset((
    "schema", "commit_ref", "source_tree_digest", "criteria_digest", "impact_set",
    "dependency_digest", "command_profile_digest", "command_digest",
    "tool_version", "tool_identity_digest", "environment_digest",
    "public_surface_digest", "digest",
))
REUSE_RESOLVER_FIELDS = frozenset((
    "schema", "repo_root", "relevant_paths", "dependency_paths",
    "public_surface_paths", "selectors",
))


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


def _require_tagged_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ExecutionControlError("reuse_pin_invalid", f"{field} must be a sha256 digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ExecutionControlError("reuse_pin_invalid", f"{field} must be a sha256 digest") from exc
    return value


def _git_bytes(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ExecutionControlError(
            "source_tree_unknown", "git could not canonicalize the selected source tree",
            detail={"argv": list(args), "stderr": detail},
        )
    return completed.stdout


def source_tree_pin(repo_root: str | Path, relevant_paths: Iterable[str]) -> dict[str, Any]:
    """Hash index and worktree bytes for a bounded path set without writing git state.

    The pin includes staged blobs, unstaged and untracked worktree bytes, file mode,
    symlink target, and clean submodule HEAD. Dirty selected paths, unreadable
    submodules, and non-regular filesystem entries cannot be reused.
    """
    raw_repo = Path(repo_root)
    repo = raw_repo.resolve()
    values = list(relevant_paths)
    if any(not isinstance(value, str) for value in values):
        raise ExecutionControlError("source_tree_unknown", "source tree paths must be strings")
    selectors = sorted(set(values))
    if not repo.is_dir() or not selectors:
        raise ExecutionControlError("source_tree_unknown", "source tree requires a repository and paths")
    if raw_repo.is_symlink():
        raise ExecutionControlError("source_tree_unknown", "repository root symlinks cannot be reused")
    normalized: list[str] = []
    for value in selectors:
        if not isinstance(value, str) or not value.strip():
            raise ExecutionControlError("source_tree_unknown", "source tree paths must be non-empty strings")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or any(char in value for char in "*?["):
            raise ExecutionControlError(
                "source_tree_unknown", "source tree paths must be expanded repository-relative paths",
                detail={"path": value},
            )
        normalized.append(path.as_posix())
    top = _git_bytes(repo, "rev-parse", "--show-toplevel").decode("utf-8", errors="strict").strip()
    if Path(top).resolve() != repo:
        raise ExecutionControlError(
            "source_tree_unknown", "repo_root must be the git worktree root",
            detail={"expected": str(repo), "actual": top},
        )

    def assert_confined(relative: str, *, allow_final_symlink: bool = True) -> None:
        candidate = repo / relative
        parent = candidate.parent.resolve(strict=False)
        try:
            parent.relative_to(repo)
        except ValueError as exc:
            raise ExecutionControlError(
                "source_tree_unknown", "source path escapes repository",
                detail={"path": relative},
            ) from exc
        if candidate.is_symlink():
            target = candidate.resolve(strict=False)
            try:
                target.relative_to(repo)
            except ValueError as exc:
                raise ExecutionControlError(
                    "source_tree_unknown", "symlink target escapes repository",
                    detail={"path": relative},
                ) from exc
            if not allow_final_symlink:
                raise ExecutionControlError(
                    "source_tree_unknown", "symlinked submodule cannot be reused",
                    detail={"path": relative},
                )

    index_records: list[dict[str, Any]] = []
    index_modes: dict[str, str] = {}
    raw_index = _git_bytes(repo, "ls-files", "--stage", "-z", "--", *normalized)
    for raw in raw_index.split(b"\0"):
        if not raw:
            continue
        metadata, separator, raw_path = raw.partition(b"\t")
        parts = metadata.decode("ascii", errors="strict").split()
        if not separator or len(parts) != 3:
            raise ExecutionControlError("source_tree_unknown", "git index entry is not canonical")
        mode, object_id, stage = parts
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if stage != "0":
            raise ExecutionControlError(
                "source_tree_unknown", "unmerged index entries cannot be reused",
                detail={"path": path, "stage": stage},
            )
        if mode == "160000":
            staged_digest = f"gitlink:{object_id}"
        else:
            staged_blob = _git_bytes(repo, "cat-file", "blob", object_id)
            staged_digest = "sha256:" + hashlib.sha256(staged_blob).hexdigest()
        index_modes[path] = mode
        index_records.append({
            "path": path, "mode": mode, "object_id": object_id,
            "content_digest": staged_digest,
        })

    listed = _git_bytes(repo, "ls-files", "--cached", "--others", "-z", "--", *normalized)
    worktree_paths = sorted(set(
        raw.decode("utf-8", errors="surrogateescape") for raw in listed.split(b"\0") if raw
    ) | set(index_modes))
    if any(selector not in worktree_paths for selector in normalized):
        raise ExecutionControlError(
            "source_tree_unknown", "source paths must be expanded exact files or gitlinks",
        )
    worktree_records: list[dict[str, Any]] = []
    for relative in worktree_paths:
        path = repo / relative
        if index_modes.get(relative) == "160000":
            assert_confined(relative, allow_final_symlink=False)
            if not path.is_dir():
                raise ExecutionControlError(
                    "source_tree_unknown", "missing submodule cannot be reused",
                    detail={"path": relative},
                )
            submodule_head = _git_bytes(path, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
            submodule_status = _git_bytes(
                path, "status", "--porcelain=v1", "--untracked-files=all", "-z",
            )
            if submodule_status:
                raise ExecutionControlError(
                    "source_tree_unknown", "dirty submodule cannot be canonicalized for reuse",
                    detail={"path": relative},
                )
            worktree_records.append({
                "path": relative, "kind": "submodule", "head": submodule_head,
            })
            continue
        assert_confined(relative)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            worktree_records.append({"path": relative, "kind": "missing"})
            continue
        mode = format(metadata.st_mode & 0o177777, "06o")
        if stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(path)
            worktree_records.append({
                "path": relative, "kind": "symlink", "mode": mode,
                "target_digest": tagged_digest({"target": target}),
            })
        elif stat.S_ISREG(metadata.st_mode):
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise ExecutionControlError(
                    "source_tree_unknown", "worktree file could not be read",
                    detail={"path": relative},
                ) from exc
            worktree_records.append({
                "path": relative, "kind": "file", "mode": mode, "size": len(content),
                "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            })
        else:
            raise ExecutionControlError(
                "source_tree_unknown", "special filesystem entries cannot be reused",
                detail={"path": relative, "mode": mode},
            )

    preimage = {
        "schema": "task-worker.source-tree-pin/v1",
        "selectors": normalized,
        "index": sorted(index_records, key=lambda item: item["path"]),
        "worktree": worktree_records,
    }
    dirty = bool(_git_bytes(
        repo, "status", "--porcelain=v1", "--untracked-files=all", "-z", "--", *normalized,
    ))
    return {
        "schema": preimage["schema"], "selectors": normalized,
        "status": "dirty" if dirty else "canonical", "digest": tagged_digest(preimage),
    }


def build_reuse_fingerprint(
    *, commit_ref: str, source_tree_digest: str, criteria_digest: str, impact_set: Iterable[str],
    dependency_digest: str, command_profile_digest: str, command_digest_value: str,
    tool_version: str, tool_identity_digest: str, environment_digest: str,
    public_surface_digest: str,
) -> dict[str, Any]:
    paths = sorted(set(impact_set))
    if not paths or not all(isinstance(path, str) and path for path in paths):
        raise ExecutionControlError("reuse_pin_invalid", "impact_set must contain paths")
    if not isinstance(commit_ref, str) or not commit_ref:
        raise ExecutionControlError("reuse_pin_invalid", "commit_ref must be non-empty")
    for field, value in (
        ("source_tree_digest", source_tree_digest), ("criteria_digest", criteria_digest),
        ("dependency_digest", dependency_digest),
        ("command_profile_digest", command_profile_digest),
        ("command_digest", command_digest_value), ("tool_identity_digest", tool_identity_digest),
        ("environment_digest", environment_digest),
        ("public_surface_digest", public_surface_digest),
    ):
        _require_tagged_digest(value, field)
    if not isinstance(tool_version, str) or not tool_version:
        raise ExecutionControlError("reuse_pin_invalid", "tool_version must be non-empty")
    value: dict[str, Any] = {
        "schema": REUSE_FINGERPRINT_SCHEMA,
        "commit_ref": commit_ref,
        "source_tree_digest": source_tree_digest,
        "criteria_digest": criteria_digest,
        "impact_set": paths,
        "dependency_digest": dependency_digest,
        "command_profile_digest": command_profile_digest,
        "command_digest": command_digest_value,
        "tool_version": tool_version,
        "tool_identity_digest": tool_identity_digest,
        "environment_digest": environment_digest,
        "public_surface_digest": public_surface_digest,
    }
    value["digest"] = instance_digest(value)
    return value


def validate_reuse_fingerprint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != REUSE_FINGERPRINT_FIELDS:
        raise ExecutionControlError("reuse_pin_invalid", "reuse fingerprint fields differ")
    if value.get("schema") != REUSE_FINGERPRINT_SCHEMA:
        raise ExecutionControlError("reuse_pin_invalid", "reuse fingerprint schema differs")
    expected = build_reuse_fingerprint(
        commit_ref=value.get("commit_ref"),
        source_tree_digest=value.get("source_tree_digest"),
        criteria_digest=value.get("criteria_digest"), impact_set=value.get("impact_set") or [],
        dependency_digest=value.get("dependency_digest"),
        command_profile_digest=value.get("command_profile_digest"),
        command_digest_value=value.get("command_digest"), tool_version=value.get("tool_version"),
        tool_identity_digest=value.get("tool_identity_digest"),
        environment_digest=value.get("environment_digest"),
        public_surface_digest=value.get("public_surface_digest"),
    )
    if value != expected:
        raise ExecutionControlError("reuse_pin_invalid", "reuse fingerprint digest differs")
    return value


def validate_reuse_fingerprint_policy(
    fingerprint: dict[str, Any], permit: dict[str, Any], plan: dict[str, Any] | None = None,
) -> None:
    value = validate_reuse_fingerprint(fingerprint)
    expected = {
        "commit_ref": permit.get("head"),
        "criteria_digest": permit.get("criteria_digest"),
        "impact_set": sorted(set(permit.get("impact_set") or [])),
        "command_digest": permit.get("command_digest"),
        "tool_version": permit.get("tool_version"),
        "environment_digest": permit.get("environment_digest"),
    }
    if plan is not None:
        expected["command_profile_digest"] = plan.get("command_profile_digest")
    mismatch = {
        key: {"fingerprint": value.get(key), "expected": expected_value}
        for key, expected_value in expected.items() if value.get(key) != expected_value
    }
    if mismatch:
        raise ExecutionControlError(
            "reuse_pin_policy_mismatch", "reuse fingerprint differs from permit or command policy",
            detail={"mismatch": mismatch},
        )


def resolve_tool_identity(repo: Path, command: dict[str, Any]) -> dict[str, Any]:
    """Pin the trusted profile executable without running its argv or version output."""
    command_digest(command)
    executable = command["executable"]
    if not executable or "\0" in executable:
        raise ExecutionControlError("tool_identity_unknown", "profile executable is invalid")
    command_cwd = Path(command["cwd"])
    if command_cwd.is_absolute() or ".." in command_cwd.parts:
        raise ExecutionControlError("tool_identity_unknown", "physical command cwd escapes repository")
    try:
        physical_cwd = (repo / command_cwd).resolve(strict=True)
        physical_cwd.relative_to(repo)
    except (OSError, ValueError) as exc:
        raise ExecutionControlError(
            "tool_identity_unknown", "physical command cwd is unavailable or escapes repository",
        ) from exc
    if not physical_cwd.is_dir():
        raise ExecutionControlError("tool_identity_unknown", "physical command cwd is not a directory")

    confined_lookup = False
    requested = Path(executable)
    if requested.is_absolute():
        located = requested
    elif "/" in executable:
        located = physical_cwd / requested
        confined_lookup = True
    else:
        selected_path = command["environment"].get("PATH")
        if selected_path is None:
            selected_path = os.environ.get("PATH", os.defpath)
        if "\0" in selected_path:
            raise ExecutionControlError("tool_identity_unknown", "selected PATH is invalid")
        located = None
        for entry in selected_path.split(os.pathsep):
            base = Path(entry) if entry else Path(".")
            relative_entry = not base.is_absolute()
            if relative_entry:
                base = physical_cwd / base
                try:
                    base.resolve(strict=False).relative_to(repo)
                except ValueError as exc:
                    raise ExecutionControlError(
                        "tool_identity_unknown", "relative PATH entry escapes repository",
                    ) from exc
            candidate = base / executable
            try:
                metadata = candidate.stat()
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode) and os.access(candidate, os.X_OK):
                located = candidate
                confined_lookup = relative_entry
                break
        if located is None:
            raise ExecutionControlError("tool_identity_unknown", "profile executable is unavailable")
    located = Path(os.path.abspath(located))
    try:
        requested_stat = located.lstat()
        resolved = located.resolve(strict=True)
        resolved_stat = resolved.stat()
    except (OSError, ValueError) as exc:
        raise ExecutionControlError(
            "tool_identity_unknown", "profile executable cannot be resolved",
        ) from exc
    try:
        located.relative_to(repo)
        located_in_repo = True
    except ValueError:
        located_in_repo = False
    if confined_lookup or located_in_repo:
        try:
            located.relative_to(repo)
            resolved.relative_to(repo)
        except ValueError as exc:
            raise ExecutionControlError(
                "tool_identity_unknown", "relative tool executable escapes repository",
            ) from exc
    if not stat.S_ISREG(resolved_stat.st_mode) or not os.access(resolved, os.X_OK):
        raise ExecutionControlError(
            "tool_identity_unknown", "profile executable must resolve to an executable regular file",
        )
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ExecutionControlError("tool_identity_unknown", "profile executable bytes are unreadable") from exc

    def canonical_path(path: Path) -> str:
        try:
            return "repo:" + path.relative_to(repo).as_posix()
        except ValueError:
            return str(path)

    value: dict[str, Any] = {
        "schema": "task-worker.tool-identity/v1",
        "requested": executable,
        "located_path": canonical_path(located),
        "located_mode": format(requested_stat.st_mode & 0o177777, "06o"),
        "symlink_target": os.readlink(located) if stat.S_ISLNK(requested_stat.st_mode) else None,
        "resolved_path": canonical_path(resolved),
        "resolved_mode": format(resolved_stat.st_mode & 0o177777, "06o"),
        "size": resolved_stat.st_size,
        "content_digest": "sha256:" + digest.hexdigest(),
    }
    value["digest"] = instance_digest(value)
    return value


def resolve_reuse_fingerprint(
    permit: dict[str, Any], plan: dict[str, Any], resolver: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(resolver, dict) or set(resolver) != REUSE_RESOLVER_FIELDS:
        raise ExecutionControlError("reuse_resolver_invalid", "reuse resolver fields differ")
    if resolver.get("schema") != REUSE_RESOLVER_SCHEMA:
        raise ExecutionControlError("reuse_resolver_invalid", "reuse resolver schema differs")
    repo = Path(resolver.get("repo_root") or "")
    if not repo.is_absolute():
        raise ExecutionControlError("reuse_resolver_invalid", "repo_root must be absolute")

    normalized: dict[str, list[str]] = {}
    for field in ("relevant_paths", "dependency_paths", "public_surface_paths", "selectors"):
        values = resolver.get(field)
        if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
            raise ExecutionControlError("reuse_resolver_invalid", f"{field} must be a string list")
        if len(values) != len(set(values)):
            raise ExecutionControlError("reuse_resolver_invalid", f"{field} contains duplicates")
        normalized[field] = sorted(values)
    if normalized["relevant_paths"] != sorted(set(permit.get("impact_set") or [])):
        raise ExecutionControlError("reuse_resolver_invalid", "relevant_paths must equal permit impact_set")
    if not normalized["dependency_paths"] or not normalized["public_surface_paths"]:
        raise ExecutionControlError(
            "reuse_resolver_invalid", "dependency and public-surface paths must be explicit",
        )
    if not normalized["selectors"] or any(
        selector not in plan.get("command", {}).get("args", []) for selector in normalized["selectors"]
    ):
        raise ExecutionControlError(
            "reuse_resolver_invalid", "selectors must be exact command profile arguments",
        )
    if command_digest(plan.get("command")) != permit.get("command_digest"):
        raise ExecutionControlError(
            "reuse_pin_policy_mismatch", "resolved command and permit command digest differ",
        )
    _require_tagged_digest(plan.get("command_profile_digest"), "command_profile_digest")

    repo = repo.resolve()
    commit_ref = _git_bytes(repo, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    if commit_ref != permit.get("head"):
        raise ExecutionControlError("reuse_pin_policy_mismatch", "live commit differs from permit head")

    def pin(paths: list[str], kind: str) -> str:
        resolved = source_tree_pin(repo, paths)
        if resolved["status"] != "canonical":
            raise ExecutionControlError(
                "source_tree_dirty", f"{kind} paths are dirty and cannot be reused",
            )
        return resolved["digest"]

    normalized_resolver = {
        "schema": REUSE_RESOLVER_SCHEMA,
        "repo_root": str(repo),
        **normalized,
    }
    tool_identity = resolve_tool_identity(repo, plan["command"])
    fingerprint = build_reuse_fingerprint(
        commit_ref=commit_ref,
        source_tree_digest=pin(normalized["relevant_paths"], "source"),
        criteria_digest=permit.get("criteria_digest"),
        impact_set=permit.get("impact_set") or [],
        dependency_digest=pin(normalized["dependency_paths"], "dependency"),
        command_profile_digest=plan.get("command_profile_digest"),
        command_digest_value=permit.get("command_digest"),
        tool_version=permit.get("tool_version"),
        tool_identity_digest=tool_identity["digest"],
        environment_digest=permit.get("environment_digest"),
        public_surface_digest=pin(normalized["public_surface_paths"], "public-surface"),
    )
    validate_reuse_fingerprint_policy(fingerprint, permit, plan)
    preimage = {
        "resolver": normalized_resolver,
        "command": plan["command"],
        "command_profile_digest": plan["command_profile_digest"],
        "tool_identity": tool_identity,
        "fingerprint": fingerprint,
    }
    return fingerprint, preimage


def build_evidence_batch(
    *, state_root: str | Path, source_tree_digest: str, command_profile_digest: str,
    criteria_digest: str, target: str, reuse_fingerprint_digest: str,
    expected_selectors: Iterable[str], children: Iterable[dict[str, Any]],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    _require_tagged_digest(source_tree_digest, "source_tree_digest")
    _require_tagged_digest(command_profile_digest, "command_profile_digest")
    _require_tagged_digest(criteria_digest, "criteria_digest")
    _require_tagged_digest(reuse_fingerprint_digest, "reuse_fingerprint_digest")
    if not isinstance(target, str) or not target:
        raise ExecutionControlError("evidence_batch_invalid", "target must be non-empty")
    requested_selectors = list(expected_selectors)
    if (
        not requested_selectors
        or any(not isinstance(item, str) or not item for item in requested_selectors)
        or len(requested_selectors) != len(set(requested_selectors))
    ):
        raise ExecutionControlError(
            "evidence_batch_invalid", "expected selectors must be non-empty unique strings",
        )
    expected = sorted(requested_selectors)
    requests = list(children)
    child_fields = {"evidence_id", "evidence_digest", "receipt_id", "receipt_digest"}
    if any(not isinstance(child, dict) or set(child) != child_fields for child in requests):
        raise ExecutionControlError("evidence_batch_invalid", "child refs fields differ")
    for field in child_fields:
        values = [child[field] for child in requests]
        if any(not isinstance(value, str) or not value for value in values):
            raise ExecutionControlError("evidence_batch_invalid", f"{field} must be non-empty")
        if field.endswith("digest"):
            for value in values:
                _require_tagged_digest(value, field)
        if len(values) != len(set(values)):
            raise ExecutionControlError("evidence_batch_invalid", f"duplicate {field}")

    root = Path(state_root) / "execution-control"
    normalized: list[dict[str, Any]] = []
    covered: set[str] = set()
    for requested in requests:
        receipt_path = _object_file(root / "receipts", requested["receipt_id"])
        evidence_path = _object_file(root / "evidence", requested["evidence_id"])
        if not receipt_path.exists():
            normalized.append({**requested, "result": "missing", "output_digest": None, "selectors": []})
            continue
        receipt = _read(receipt_path)
        validate_instance(receipt, "command-receipt", contract)
        if (
            receipt.get("receipt_id") != requested["receipt_id"]
            or receipt.get("digest") != requested["receipt_digest"]
        ):
            raise ExecutionControlError("evidence_batch_invalid", "stored child receipt differs")
        _, _, claim = _find_claim(root, receipt["claim_id"])
        preimage = claim.get("reuse_preimage") or {}
        fingerprint = preimage.get("fingerprint") or {}
        resolver = preimage.get("resolver") or {}
        selectors = sorted(resolver.get("selectors") or [])
        if (
            claim.get("state") not in {"succeeded", "failed"}
            or claim.get("receipt_ref") != requested["receipt_id"]
            or fingerprint.get("digest") != reuse_fingerprint_digest
            or fingerprint.get("source_tree_digest") != source_tree_digest
            or preimage.get("command_profile_digest") != command_profile_digest
        ):
            raise ExecutionControlError("evidence_batch_invalid", "stored child execution pins differ")
        if not evidence_path.exists():
            normalized.append({
                **requested, "result": "missing", "output_digest": receipt["output_digest"],
                "selectors": selectors,
            })
            continue
        evidence = _read(evidence_path)
        validate_instance(evidence, "verification-evidence", contract)
        permit_path = _object_file(root / "permits", claim["permit_id"])
        if not permit_path.exists():
            raise ExecutionControlError("evidence_batch_invalid", "stored child permit is missing")
        permit = _read(permit_path)
        validate_instance(permit, "execution-permit", contract)
        if (
            evidence.get("evidence_id") != requested["evidence_id"]
            or evidence.get("digest") != requested["evidence_digest"]
            or evidence.get("source_receipt_id") != receipt.get("receipt_id")
            or requested["evidence_id"] not in (claim.get("evidence_refs") or [])
            or not evidence_applicable(permit, evidence, reuse_fingerprint=fingerprint)
        ):
            raise ExecutionControlError("evidence_batch_invalid", "stored child refs or digests differ")
        if (
            evidence.get("criteria_digest") != criteria_digest
            or evidence.get("target") != target
            or evidence.get("surface_digest") != reuse_fingerprint_digest
        ):
            raise ExecutionControlError("evidence_batch_invalid", "stored child pins differ")
        result = receipt["result"] if receipt["result"] != "pass" else evidence["result"]
        covered.update(selectors)
        normalized.append({
            **requested, "result": result, "output_digest": receipt["output_digest"],
            "selectors": selectors,
        })
    missing = sorted(set(expected) - covered)
    unexpected = sorted(covered - set(expected))
    failed = [item["evidence_id"] for item in normalized if item["result"] != "pass"]
    result = "pass" if normalized and not missing and not unexpected and not failed else "fail"
    value: dict[str, Any] = {
        "schema": EVIDENCE_BATCH_SCHEMA,
        "source_tree_digest": source_tree_digest,
        "command_profile_digest": command_profile_digest,
        "criteria_digest": criteria_digest,
        "target": target,
        "reuse_fingerprint_digest": reuse_fingerprint_digest,
        "expected_selectors": expected,
        "covered_selectors": sorted(covered),
        "children": normalized,
        "missing_selectors": missing,
        "unexpected_selectors": unexpected,
        "failed_evidence_refs": failed,
        "result": result,
    }
    value["digest"] = instance_digest(value)
    return value


def final_qa_projection(
    value: dict[str, Any], contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project task-worker-owned final QA receipts; review belongs to Studio."""
    contract = contract or load_contract()
    expected_fields = {"candidate_ref", "state_root", "source_tree_digest", "criteria_digest"}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ExecutionControlError("final_qa_invalid", "final QA request fields differ")
    candidate = value.get("candidate_ref")
    if not isinstance(candidate, str) or not candidate:
        raise ExecutionControlError("final_qa_invalid", "candidate_ref must be non-empty")
    source_digest = _require_tagged_digest(value.get("source_tree_digest"), "source_tree_digest")
    criteria_digest = _require_tagged_digest(value.get("criteria_digest"), "criteria_digest")
    state_root = Path(value.get("state_root") or "")
    if not state_root.is_absolute():
        raise ExecutionControlError("final_qa_invalid", "state_root must be absolute")
    root = state_root / "execution-control"
    projected_attempts: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    seen_receipts: set[str] = set()
    seen_evidence: set[str] = set()
    for execution_path in sorted((root / "executions").glob("*.json")):
        execution = _read(execution_path)
        if (
            execution.get("schema") != EXECUTION_STATE_SCHEMA
            or not isinstance(execution.get("claims"), list)
        ):
            raise ExecutionControlError("final_qa_invalid", "execution state is not canonical")
        for claim in execution["claims"]:
            claim_id = claim.get("claim_id")
            permit_id = claim.get("permit_id")
            if not isinstance(claim_id, str) or not isinstance(permit_id, str):
                raise ExecutionControlError("final_qa_invalid", "execution claim refs are invalid")
            permit_path = _object_file(root / "permits", permit_id)
            if not permit_path.exists():
                raise ExecutionControlError("final_qa_invalid", "stored execution permit is missing")
            stored_permit = _read(permit_path)
            validate_instance(stored_permit, "execution-permit", contract)
            if not (
                stored_permit.get("head") == candidate
                and stored_permit.get("purpose") == "integration-full"
                and stored_permit.get("target") == "repository"
                and stored_permit.get("qa_mode") == "final"
                and stored_permit.get("criteria_digest") == criteria_digest
            ):
                continue
            stored_preimage = claim.get("reuse_preimage")
            if not isinstance(stored_preimage, dict):
                raise ExecutionControlError("final_qa_invalid", "final QA source preimage is missing")
            fingerprint = stored_preimage.get("fingerprint")
            try:
                validate_reuse_fingerprint_policy(fingerprint, stored_permit)
            except ExecutionControlError as exc:
                raise ExecutionControlError("final_qa_invalid", "final QA fingerprint differs") from exc
            if fingerprint.get("criteria_digest") != criteria_digest:
                raise ExecutionControlError("final_qa_invalid", "final QA criteria pin differs")
            if fingerprint.get("source_tree_digest") != source_digest:
                continue
            if claim_id in seen_claims:
                raise ExecutionControlError("final_qa_invalid", "duplicate final QA claim")
            seen_claims.add(claim_id)
            if claim.get("state") == "claimed":
                raise ExecutionControlError("final_qa_incomplete", "matching final QA is still active")
            if claim.get("state") not in {"succeeded", "failed"}:
                raise ExecutionControlError("final_qa_invalid", "final QA claim state differs")
            receipt_id = claim.get("receipt_ref")
            if not isinstance(receipt_id, str) or not receipt_id or receipt_id in seen_receipts:
                raise ExecutionControlError("final_qa_invalid", "final QA receipt ref is invalid or duplicated")
            seen_receipts.add(receipt_id)
            expected_key = physical_identity(stored_permit, fingerprint)
            if (
                execution.get("physical_key") != expected_key
                or claim.get("physical_key") != expected_key
                or execution_path.name != expected_key.removeprefix("sha256:") + ".json"
            ):
                raise ExecutionControlError("final_qa_invalid", "final QA execution identity differs")
            receipt_path = _object_file(root / "receipts", receipt_id)
            if not receipt_path.exists():
                raise ExecutionControlError("final_qa_invalid", "stored final receipt is missing")
            receipt = _read(receipt_path)
            validate_instance(receipt, "command-receipt", contract)
            if receipt.get("receipt_id") != receipt_id:
                raise ExecutionControlError("final_qa_invalid", "stored final receipt differs")
            if (
                claim.get("claim_id") != receipt.get("claim_id")
                or claim.get("permit_id") != receipt.get("permit_id")
                or stored_permit.get("permit_id") != receipt.get("permit_id")
                or claim.get("permit_digest") != stored_permit.get("digest")
                or claim.get("receipt_ref") != receipt_id
                or claim.get("state") != ("succeeded" if receipt.get("result") == "pass" else "failed")
                or receipt.get("head") != candidate or receipt.get("purpose") != "integration-full"
                or receipt.get("target") != "repository" or not receipt.get("fresh_requirement_id")
                or stored_permit.get("qa_mode") != "final"
                or stored_permit.get("criteria_digest") != criteria_digest
                or fingerprint.get("source_tree_digest") != source_digest
                or fingerprint.get("criteria_digest") != criteria_digest
            ):
                raise ExecutionControlError("final_qa_invalid", "final receipt pins differ")
            for receipt_field, permit_field in (
                ("profile_id", "command_profile_id"), ("purpose", "purpose"),
                ("target", "target"), ("head", "head"),
                ("command_digest", "command_digest"),
                ("environment_digest", "environment_digest"),
                ("tool_version", "tool_version"),
                ("fresh_requirement_id", "fresh_requirement_id"),
            ):
                if receipt.get(receipt_field) != stored_permit.get(permit_field):
                    raise ExecutionControlError("final_qa_invalid", "final receipt identity differs")
            started_at = _timestamp(receipt.get("started_at"))
            finished_at = _timestamp(receipt.get("finished_at"))
            if started_at is None or finished_at is None or finished_at < started_at:
                raise ExecutionControlError("final_qa_invalid", "final receipt timestamps differ")
            if receipt["result"] != "pass":
                if claim.get("evidence_refs"):
                    raise ExecutionControlError("final_qa_invalid", "failed final QA claimed evidence")
                projected_attempts.append({
                    "receipt_ref": {"receipt_id": receipt_id, "digest": receipt["digest"]},
                    "evidence_ref": None, "result": receipt["result"],
                    "started_at": receipt["started_at"], "finished_at": receipt["finished_at"],
                })
                continue
            try:
                _, live_preimage = resolve_reuse_fingerprint(
                    stored_permit,
                    {
                        "command": stored_preimage.get("command"),
                        "command_profile_digest": stored_preimage.get("command_profile_digest"),
                    },
                    stored_preimage.get("resolver"),
                )
            except (OSError, ExecutionControlError) as exc:
                raise ExecutionControlError("final_qa_stale", "live final QA pins are unavailable") from exc
            if live_preimage != stored_preimage:
                raise ExecutionControlError("final_qa_stale", "live final QA pins changed")
            evidence_refs = claim.get("evidence_refs") or []
            if len(evidence_refs) != 1 or evidence_refs[0] in seen_evidence:
                raise ExecutionControlError("final_qa_invalid", "final QA evidence ref is invalid or duplicated")
            evidence_id = evidence_refs[0]
            seen_evidence.add(evidence_id)
            evidence_path = _object_file(root / "evidence", evidence_id)
            if not evidence_path.exists():
                raise ExecutionControlError("final_qa_invalid", "stored final evidence is missing")
            evidence = _read(evidence_path)
            validate_instance(evidence, "verification-evidence", contract)
            if (
                evidence.get("evidence_id") != evidence_id
                or evidence.get("source_receipt_id") != receipt_id or evidence.get("result") != "pass"
                or claim.get("evidence_refs") != [evidence_id]
                or evidence.get("criteria_digest") != criteria_digest
                or evidence.get("surface_digest") != fingerprint.get("digest")
                or not evidence_applicable(stored_permit, evidence, reuse_fingerprint=fingerprint)
            ):
                raise ExecutionControlError("final_qa_invalid", "stored final evidence differs")
            projected_attempts.append({
                "receipt_ref": {"receipt_id": receipt_id, "digest": receipt["digest"]},
                "evidence_ref": {"evidence_id": evidence_id, "digest": evidence["digest"]},
                "result": "pass", "started_at": receipt["started_at"],
                "finished_at": receipt["finished_at"],
            })
    projected_attempts.sort(key=lambda item: (
        _timestamp(item["started_at"]), item["receipt_ref"]["receipt_id"],
    ))
    passed = [item for item in projected_attempts if item["result"] == "pass"]
    projection: dict[str, Any] = {
        "schema": FINAL_QA_PROJECTION_SCHEMA,
        "candidate_ref": candidate, "source_tree_digest": source_digest,
        "criteria_digest": criteria_digest, "attempts": projected_attempts,
        "result": "pass" if len(passed) == 1 else "fail",
    }
    projection["digest"] = instance_digest(projection)
    return projection


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


def physical_identity(
    permit: dict[str, Any], reuse_fingerprint: dict[str, Any] | None = None,
) -> str:
    identity = {
        key: permit[key]
        for key in ("head", "command_digest", "environment_digest", "tool_version", "purpose")
    }
    if reuse_fingerprint is not None:
        validate_reuse_fingerprint_policy(reuse_fingerprint, permit)
        identity["reuse_fingerprint_digest"] = reuse_fingerprint["digest"]
    if permit.get("fresh_requirement_id") is not None and (
        reuse_fingerprint is None or fresh_required(permit)
    ):
        identity["fresh_requirement_id"] = permit["fresh_requirement_id"]
    return tagged_digest(identity)


def evidence_applicable(
    permit: dict[str, Any], evidence: dict[str, Any], *,
    criteria_digest: str | None = None, covered_paths: Iterable[str] | None = None,
    surface_digest: str | None = None, independence: str | None = None,
    reuse_fingerprint: dict[str, Any] | None = None,
) -> bool:
    if evidence.get("result") != "pass" or evidence.get("invalidation") is not None:
        return False
    if reuse_fingerprint is not None:
        try:
            validate_reuse_fingerprint_policy(reuse_fingerprint, permit)
        except ExecutionControlError:
            return False
        surface_digest = reuse_fingerprint["digest"]
    if physical_identity(permit, reuse_fingerprint) != physical_identity(evidence, reuse_fingerprint):
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
    reuse_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_instance(permit, "execution-permit", contract)
    if permit["state"] != "planned" or any(
        permit.get(key) is not None for key in ("claim_id", "claimed_by", "claimed_at", "completed_at")
    ):
        raise ExecutionControlError("permit_state_invalid", "only an unclaimed planned permit may execute")
    key = physical_identity(permit, reuse_fingerprint)
    if active_claim is not None and active_claim.get("physical_key") == key and active_claim.get("state") == "claimed":
        return {"action": "reject", "error": {"code": "duplicate_active", "claim_id": active_claim.get("claim_id")}, "physical_run_started": False}
    if evidence is not None and reuse_fingerprint is not None:
        validate_instance(evidence, "verification-evidence", contract)
        if evidence_applicable(permit, evidence, reuse_fingerprint=reuse_fingerprint):
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
    if (
        evidence is not None and fresh_required(permit)
        and evidence.get("fresh_requirement_id") != permit.get("fresh_requirement_id")
    ):
        result.update({"reason": "fresh_requirement_changed", "physical_run_started": True})
        result.pop("physical_key", None)
        result.pop("permit_id", None)
    return result


def evaluate_request(value: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    if "evidence_batch" in value:
        batch = value["evidence_batch"]
        if not isinstance(batch, dict):
            raise ExecutionControlError("evidence_batch_invalid", "evidence_batch must be an object")
        return build_evidence_batch(
            state_root=batch.get("state_root"),
            source_tree_digest=batch.get("source_tree_digest"),
            command_profile_digest=batch.get("command_profile_digest"),
            criteria_digest=batch.get("criteria_digest"), target=batch.get("target"),
            reuse_fingerprint_digest=batch.get("reuse_fingerprint_digest"),
            expected_selectors=batch.get("expected_selectors") or [],
            children=batch.get("children") or [],
            contract=contract,
        )
    if "final_candidate" in value:
        raise ExecutionControlError(
            "final_candidate_provider_boundary_changed",
            "task-worker projects only final_qa; Studio combines canonical review confirmation",
        )
    if "final_qa" in value:
        return final_qa_projection(value["final_qa"], contract)
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
            permit, contract=contract, evidence=None,
            active_claim=value.get("active_claim"), attempts=len(value.get("attempts") or []),
            reuse_fingerprint=None,
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
    contract: dict[str, Any] | None = None, authorization: dict[str, Any] | None = None,
    preflight_receipt: dict[str, Any] | None = None,
    reuse_resolver: dict[str, Any] | None = None,
    policy_plan: dict[str, Any] | None = None, now: str | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    validate_instance(permit, "execution-permit", contract)
    if fresh_required(permit) and permit.get("fresh_requirement_id") is None:
        raise ExecutionControlError(
            "fresh_requirement_required", "fresh execution purpose requires fresh_requirement_id"
        )
    if (reuse_resolver is None) != (policy_plan is None):
        raise ExecutionControlError(
            "reuse_resolver_invalid", "reuse resolver requires its validated command policy plan",
        )
    reuse_fingerprint = None
    reuse_preimage = None
    if reuse_resolver is not None and policy_plan is not None:
        reuse_fingerprint, reuse_preimage = resolve_reuse_fingerprint(
            permit, policy_plan, reuse_resolver,
        )
    timestamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    mutation, paid = _validate_mutation_gate(
        permit, authorization, preflight_receipt, contract, now=timestamp,
    )
    key = physical_identity(permit, reuse_fingerprint)
    root = Path(state_root) / "execution-control"
    path = root / "executions" / f"{key.removeprefix('sha256:')}.json"
    with _locked(root):
        state = _read(path) if path.exists() else {"schema": EXECUTION_STATE_SCHEMA, "physical_key": key, "claims": []}
        active = next((item for item in state["claims"] if item["state"] == "claimed"), None)
        if active is None and mutation is None and reuse_fingerprint is not None:
            for prior in reversed(state["claims"]):
                if prior.get("state") != "succeeded":
                    continue
                for evidence_ref in prior.get("evidence_refs") or []:
                    evidence_path = _object_file(root / "evidence", evidence_ref)
                    if evidence_path.exists():
                        candidate = _read(evidence_path)
                        validate_instance(candidate, "verification-evidence", contract)
                        if evidence_applicable(
                            permit, candidate, reuse_fingerprint=reuse_fingerprint,
                        ):
                            return {
                                "action": "reuse-evidence", "error": None,
                                "evidence_refs": [evidence_ref], "physical_run_started": False,
                            }
        decision = evaluate_permit(
            permit,
            contract=contract,
            evidence=None,
            active_claim=active,
            attempts=len(state["claims"]),
            reuse_fingerprint=reuse_fingerprint,
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
            "mutation_receipt_digest": None,
            "reuse_preimage": reuse_preimage,
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


def _find_claim(root: Path, claim_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    matches: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for path in sorted((root / "executions").glob("*.json")):
        state = _read(path)
        for claim in state.get("claims") or []:
            if claim.get("claim_id") == claim_id:
                matches.append((path, state, claim))
    if len(matches) != 1:
        raise ExecutionControlError("claim_not_found", f"execution claim not unique: {claim_id}")
    return matches[0]


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
    mutation_receipt: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
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
    root = Path(state_root) / "execution-control"
    with _locked(root):
        path, state, claim = _find_claim(root, claim_id)
        reuse_fingerprint = None
        stored_preimage = claim.get("reuse_preimage")
        if stored_preimage is not None:
            if not isinstance(stored_preimage, dict):
                raise ExecutionControlError("execution_state_corrupt", "reuse preimage must be an object")
            try:
                current_fingerprint, current_preimage = resolve_reuse_fingerprint(
                    permit,
                    {
                        "command": stored_preimage.get("command"),
                        "command_profile_digest": stored_preimage.get("command_profile_digest"),
                    },
                    stored_preimage.get("resolver"),
                )
            except ExecutionControlError as exc:
                if exc.code not in {"source_tree_dirty", "source_tree_unknown"}:
                    raise
                raise ExecutionControlError(
                    "reuse_pin_stale", "live source became dirty or unknown after claim",
                ) from exc
            if current_preimage != stored_preimage:
                raise ExecutionControlError(
                    "reuse_pin_stale", "live source or execution preimage changed after claim",
                )
            reuse_fingerprint = current_fingerprint
        key = physical_identity(permit, reuse_fingerprint)
        if state.get("physical_key") != key or claim.get("physical_key") != key:
            raise ExecutionControlError("permit_claim_mismatch", "claim physical key differs")
        if evidence is not None:
            validate_instance(evidence, "verification-evidence", contract)
            if (
                evidence["source_receipt_id"] != receipt["receipt_id"]
                or not evidence_applicable(
                    permit, evidence, reuse_fingerprint=reuse_fingerprint,
                )
            ):
                raise ExecutionControlError(
                    "evidence_receipt_mismatch", "evidence is not applicable to its source receipt",
                )
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
        evidence_refs = [evidence["evidence_id"]] if evidence is not None else []
        next_state = "succeeded" if receipt["result"] == "pass" else "failed"
        if claim["state"] != "claimed":
            if (
                claim["state"] != next_state
                or claim.get("receipt_ref") != receipt["receipt_id"]
                or claim.get("evidence_refs") != evidence_refs
                or not receipt_path.exists()
            ):
                raise ExecutionControlError(
                    "claim_already_completed", "completed claim cannot bind another physical receipt",
                )
            stored_mutation = None
            stored_mutation_ref = claim.get("mutation_receipt_ref")
            if stored_mutation_ref is not None:
                stored_mutation_path = _object_file(root / "mutation-receipts", stored_mutation_ref)
                if not stored_mutation_path.exists():
                    raise ExecutionControlError(
                        "external_mutation_receipt_missing", "stored mutation receipt is missing",
                    )
                stored_mutation = _read(stored_mutation_path)
                validate_instance(stored_mutation, "external-mutation-receipt", contract)
                legacy_digest = claim.get("mutation_receipt_digest")
                if legacy_digest is not None and stored_mutation.get("digest") != legacy_digest:
                    raise ExecutionControlError(
                        "external_mutation_receipt_mismatch", "stored mutation receipt digest differs",
                    )
                if mutation_receipt is not None and mutation_receipt != stored_mutation:
                    raise ExecutionControlError(
                        "external_mutation_receipt_mismatch", "replay supplied another mutation receipt",
                    )
            elif mutation_receipt is not None:
                raise ExecutionControlError(
                    "mutation_receipt_not_applicable", "replay cannot add a mutation receipt",
                )
            replay_mutation, spend_status, final_consumption = _validate_mutation_completion(
                root, permit, claim, receipt, stored_mutation, contract,
            )
            if final_consumption is not None:
                consumption_path = _object_file(
                    root / "spend-consumptions", final_consumption["consumption_id"],
                )
                status_path = _object_file(root / "spend-status", final_consumption["consumption_id"])
                if (
                    not consumption_path.exists() or _read(consumption_path) != final_consumption
                    or not status_path.exists() or _read(status_path) != spend_status
                ):
                    raise ExecutionControlError(
                        "spend_claim_mismatch", "stored spend completion differs on replay",
                    )
            return {
                "action": "completed", "state": next_state,
                "receipt_ref": receipt["receipt_id"], "evidence_refs": evidence_refs,
                "external_mutation_receipt_ref": (
                    replay_mutation["mutation_id"] if replay_mutation is not None else None
                ),
                "spend_status": spend_status, "telemetry": telemetry, "idempotent": True,
            }
        completed_mutation, spend_status, final_consumption = _validate_mutation_completion(
            root, permit, claim, receipt, mutation_receipt, contract,
        )
        if evidence is not None:
            evidence_path = _object_file(root / "evidence", evidence["evidence_id"])
            if evidence_path.exists() and _read(evidence_path) != evidence:
                raise ExecutionControlError("immutable_receipt_conflict", "verification evidence id is immutable")
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
            "mutation_receipt_digest": completed_mutation["digest"] if completed_mutation else None,
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


def project_receipts(
    receipt: dict[str, Any], evidence: dict[str, Any] | None,
    state_root: str | Path, contract: dict[str, Any] | None = None,
    *, evidence_batch_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    validate_instance(receipt, "command-receipt", contract)
    root = Path(state_root) / "execution-control"
    stored_receipt_path = _object_file(root / "receipts", receipt["receipt_id"])
    if not stored_receipt_path.exists() or _read(stored_receipt_path) != receipt:
        raise ExecutionControlError(
            "execution_projection_invalid", "receipt is not canonical immutable execution state",
        )
    _, _, claim = _find_claim(root, receipt["claim_id"])
    permit_path = _object_file(root / "permits", claim.get("permit_id") or "")
    if not permit_path.exists():
        raise ExecutionControlError("execution_projection_invalid", "canonical permit is missing")
    permit = _read(permit_path)
    validate_instance(permit, "execution-permit", contract)
    if (
        claim.get("receipt_ref") != receipt["receipt_id"]
        or claim.get("permit_id") != receipt["permit_id"]
        or claim.get("permit_digest") != permit["digest"]
        or claim.get("state") != ("succeeded" if receipt["result"] == "pass" else "failed")
    ):
        raise ExecutionControlError("execution_projection_invalid", "canonical execution refs differ")
    if evidence is not None and evidence_batch_request is not None:
        raise ExecutionControlError("execution_projection_invalid", "select evidence or batch, not both")
    evidence_ref = None
    if evidence is not None:
        validate_instance(evidence, "verification-evidence", contract)
        stored_evidence_path = _object_file(root / "evidence", evidence["evidence_id"])
        if (
            evidence["source_receipt_id"] != receipt["receipt_id"]
            or claim.get("evidence_refs") != [evidence["evidence_id"]]
            or not stored_evidence_path.exists()
            or _read(stored_evidence_path) != evidence
        ):
            raise ExecutionControlError("evidence_receipt_mismatch", "evidence source receipt differs")
        evidence_ref = {"evidence_id": evidence["evidence_id"], "digest": evidence["digest"]}
    elif evidence_batch_request is not None:
        fields = {
            "source_tree_digest", "command_profile_digest", "criteria_digest", "target",
            "reuse_fingerprint_digest", "expected_selectors", "children",
        }
        if not isinstance(evidence_batch_request, dict) or set(evidence_batch_request) != fields:
            raise ExecutionControlError("execution_projection_invalid", "evidence batch request fields differ")
        evidence_batch = build_evidence_batch(
            state_root=state_root,
            source_tree_digest=evidence_batch_request["source_tree_digest"],
            command_profile_digest=evidence_batch_request["command_profile_digest"],
            criteria_digest=evidence_batch_request["criteria_digest"],
            target=evidence_batch_request["target"],
            reuse_fingerprint_digest=evidence_batch_request["reuse_fingerprint_digest"],
            expected_selectors=evidence_batch_request["expected_selectors"],
            children=evidence_batch_request["children"], contract=contract,
        )
        if evidence_batch["result"] != "pass":
            raise ExecutionControlError("execution_projection_invalid", "evidence batch is not passing")
        evidence_ref = {"batch_digest": evidence_batch["digest"]}
    return {
        "schema": "task-worker.execution-projection/v1",
        "receipt_ref": {"receipt_id": receipt["receipt_id"], "digest": receipt["digest"]},
        "evidence_ref": evidence_ref,
        "head": receipt["head"],
        "result": receipt["result"],
    }
