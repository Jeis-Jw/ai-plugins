#!/usr/bin/env python3
"""Provider-neutral immutable task definition artifacts.

The artifact is the definition source of truth. GitHub issues are an optional
projection of one pinned revision, never the definition itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "task-github.definition/v1"
PROJECTION_SCHEMA = "task-github.github-projection/v1"
RUN_SCHEMA = "task-github.local-run/v1"
RECEIPT_SCHEMA = "workflow-receipt/v1"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RECORD_MODES = {"none", "github"}
DELIVERY_MODES = {"local-ff", "pull-request"}
RUN_TRANSITIONS = {
    "run": ("started", "running"),
    "verify": ("running", "verified"),
    "done": ("verified", "done"),
    "closeout": ("done", "closed"),
}


class DefinitionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in artifact.items() if key != "digest"}


def artifact_digest(artifact: dict[str, Any]) -> str:
    return stable_digest(_artifact_payload(artifact))


def _require_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DefinitionError("bad_definition", f"{where} must be a non-empty string")
    return value.strip()


def _safe_id(value: Any, where: str) -> str:
    text = _require_text(value, where)
    if not SAFE_ID_RE.fullmatch(text):
        raise DefinitionError("unsafe_id", f"{where} is not a safe stable id: {text!r}")
    return text


def _generated_definition_id(spec: dict[str, Any]) -> str:
    root = spec.get("root") or {}
    stable_key = root.get("stable_key")
    if stable_key is not None:
        stable_key = _require_text(stable_key, "root.stable_key")
        return f"def-{stable_digest({'root_stable_key': stable_key})[:20]}"
    return f"def-{uuid.uuid4().hex}"


def node_id(definition_id: str, key: str) -> str:
    return f"node-{stable_digest({'definition_id': definition_id, 'key': key})[:20]}"


def _normalise_string_list(value: Any, where: str, *, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise DefinitionError("bad_definition", f"{where} must be a string list")
    result = [item.strip() for item in value]
    if required and not result:
        raise DefinitionError("bad_definition", f"{where} must not be empty")
    return result


def _copy_optional(source: dict[str, Any], target: dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if key in source:
            target[key] = source[key]


def create_artifact(
    spec: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    record: str | None = None,
    delivery: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create revision 1 or a successor revision from a define spec.

    Stable node ids are derived only from ``definition_id`` and logical keys.
    Revisions may change content, recording, or delivery without changing ids.
    """
    if not isinstance(spec, dict):
        raise DefinitionError("bad_definition", "spec must be an object")
    root = spec.get("root")
    children = spec.get("children", [])
    if not isinstance(root, dict):
        raise DefinitionError("bad_definition", "root must be an object")
    if not isinstance(children, list):
        raise DefinitionError("bad_definition", "children must be a list")

    if previous is not None:
        validate_artifact(previous)
        definition_id = previous["definition_id"]
        requested_id = spec.get("definition_id")
        if requested_id is not None and requested_id != definition_id:
            raise DefinitionError("definition_id_changed", "a revision cannot change definition_id")
        revision = int(previous["revision"]) + 1
        previous_digest = previous["digest"]
    else:
        definition_id = _safe_id(
            spec.get("definition_id") or _generated_definition_id(spec), "definition_id"
        )
        revision = 1
        previous_digest = None

    record_mode = record or spec.get("record") or (previous or {}).get("record") or "none"
    delivery_mode = delivery or spec.get("delivery") or (previous or {}).get("delivery") or "local-ff"
    if record_mode not in RECORD_MODES:
        raise DefinitionError("bad_record_mode", f"record must be one of {sorted(RECORD_MODES)}")
    if delivery_mode not in DELIVERY_MODES:
        raise DefinitionError("bad_delivery_mode", f"delivery must be one of {sorted(DELIVERY_MODES)}")

    root_out: dict[str, Any] = {
        "node_id": node_id(definition_id, "root"),
        "key": "root",
        "title": _require_text(root.get("title"), "root.title"),
        "body": _require_text(root.get("body"), "root.body"),
    }
    _copy_optional(root, root_out, ("execution_contract",))

    child_out: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, child in enumerate(children):
        where = f"children[{index}]"
        if not isinstance(child, dict):
            raise DefinitionError("bad_definition", f"{where} must be an object")
        key = _safe_id(child.get("key"), f"{where}.key")
        if key == "root" or key in keys:
            raise DefinitionError("duplicate_key", f"duplicate or reserved node key: {key}")
        keys.add(key)
        parent = child.get("parent")
        if parent is not None:
            parent = _safe_id(parent, f"{where}.parent")
        blocked_by = _normalise_string_list(child.get("blocked_by", []), f"{where}.blocked_by")
        item: dict[str, Any] = {
            "node_id": node_id(definition_id, key),
            "key": key,
            "title": _require_text(child.get("title"), f"{where}.title"),
            "body": _require_text(child.get("body"), f"{where}.body"),
            "parent": parent,
            "parent_node_id": root_out["node_id"] if parent is None else node_id(definition_id, parent),
            "affects_paths": _normalise_string_list(
                child.get("affects_paths", []), f"{where}.affects_paths"
            ),
            "blocked_by": blocked_by,
            "blocked_by_node_ids": [node_id(definition_id, blocker) for blocker in blocked_by],
        }
        _copy_optional(child, item, ("cross_parent_dependency_reason",))
        child_out.append(item)

    for child in child_out:
        if child["parent"] is not None and child["parent"] not in keys:
            raise DefinitionError("unknown_parent", f"{child['key']} parent is unknown: {child['parent']}")
        for blocker in child["blocked_by"]:
            if blocker not in keys:
                raise DefinitionError("unknown_dependency", f"{child['key']} blocker is unknown: {blocker}")
            if blocker == child["key"]:
                raise DefinitionError("self_dependency", f"{child['key']} cannot block itself")

    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "definition_id": definition_id,
        "revision": revision,
        "previous_digest": previous_digest,
        "created_at": created_at or utc_now(),
        "record": record_mode,
        "delivery": delivery_mode,
        "root": root_out,
        "children": child_out,
        "strict_deps": bool(spec.get("strict_deps")),
    }
    _copy_optional(spec, artifact, ("challenge_review",))
    artifact["digest"] = artifact_digest(artifact)
    validate_artifact(artifact, previous=previous)
    return artifact


def validate_artifact(
    artifact: dict[str, Any], *, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise DefinitionError("bad_artifact", "artifact must be an object")
    if artifact.get("schema") != SCHEMA:
        raise DefinitionError("bad_artifact_schema", f"schema must be {SCHEMA!r}")
    definition_id = _safe_id(artifact.get("definition_id"), "definition_id")
    revision = artifact.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise DefinitionError("bad_revision", "revision must be a positive integer")
    if artifact.get("record") not in RECORD_MODES:
        raise DefinitionError("bad_record_mode", f"record must be one of {sorted(RECORD_MODES)}")
    if artifact.get("delivery") not in DELIVERY_MODES:
        raise DefinitionError("bad_delivery_mode", f"delivery must be one of {sorted(DELIVERY_MODES)}")
    if artifact.get("digest") != artifact_digest(artifact):
        raise DefinitionError("digest_mismatch", "artifact digest does not match canonical content")

    root = artifact.get("root")
    children = artifact.get("children")
    if not isinstance(root, dict) or not isinstance(children, list):
        raise DefinitionError("bad_artifact", "artifact root/children are invalid")
    if root.get("node_id") != node_id(definition_id, "root") or root.get("key") != "root":
        raise DefinitionError("node_id_mismatch", "root node id is not stable for this definition")
    keys: set[str] = set()
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            raise DefinitionError("bad_artifact", f"children[{index}] must be an object")
        key = _safe_id(child.get("key"), f"children[{index}].key")
        if key == "root" or key in keys:
            raise DefinitionError("duplicate_key", f"duplicate or reserved child key: {key}")
        keys.add(key)
        _require_text(child.get("title"), f"children[{index}].title")
        _require_text(child.get("body"), f"children[{index}].body")
        if child.get("node_id") != node_id(definition_id, key):
            raise DefinitionError("node_id_mismatch", f"child {key} node id changed")
        parent = child.get("parent")
        if parent is not None:
            parent = _safe_id(parent, f"children[{index}].parent")
            if parent == key:
                raise DefinitionError("self_parent", f"{key} cannot parent itself")
        expected_parent = root["node_id"] if parent is None else node_id(definition_id, parent)
        if child.get("parent_node_id") != expected_parent:
            raise DefinitionError("node_id_mismatch", f"child {key} parent node id changed")
        blockers = _normalise_string_list(
            child.get("blocked_by", []), f"children[{index}].blocked_by"
        )
        if key in blockers:
            raise DefinitionError("self_dependency", f"{key} cannot block itself")
        expected_blockers = [node_id(definition_id, blocker) for blocker in blockers]
        if child.get("blocked_by_node_ids") != expected_blockers:
            raise DefinitionError("node_id_mismatch", f"child {key} dependency ids changed")
    _require_text(root.get("title"), "root.title")
    _require_text(root.get("body"), "root.body")
    by_key = {child["key"]: child for child in children}
    for child in children:
        if child.get("parent") is not None and child["parent"] not in keys:
            raise DefinitionError("unknown_parent", f"{child['key']} parent is unknown")
        if any(blocker not in keys for blocker in child.get("blocked_by", [])):
            raise DefinitionError("unknown_dependency", f"{child['key']} has an unknown blocker")
        seen: set[str] = set()
        parent = child.get("parent")
        while parent is not None:
            if parent in seen:
                raise DefinitionError("parent_cycle", f"parent cycle reaches {child['key']}")
            seen.add(parent)
            parent = by_key[parent].get("parent")

    previous_digest = artifact.get("previous_digest")
    if revision > 1 and not (
        isinstance(previous_digest, str) and re.fullmatch(r"[0-9a-f]{64}", previous_digest)
    ):
        raise DefinitionError("previous_digest_mismatch", "revision >1 requires a sha256 previous_digest")

    if previous is not None:
        validate_artifact(previous)
        if artifact["definition_id"] != previous["definition_id"]:
            raise DefinitionError("definition_id_changed", "revision chain changed definition_id")
        if artifact["revision"] != previous["revision"] + 1:
            raise DefinitionError("revision_gap", "revision must increment by exactly one")
        if artifact.get("previous_digest") != previous["digest"]:
            raise DefinitionError("previous_digest_mismatch", "previous_digest does not pin predecessor")
    elif revision == 1 and artifact.get("previous_digest") is not None:
        raise DefinitionError("previous_digest_mismatch", "revision 1 must not have previous_digest")
    return artifact


def artifact_to_issue_spec(artifact: dict[str, Any]) -> dict[str, Any]:
    validate_artifact(artifact)
    root = {"title": artifact["root"]["title"], "body": artifact["root"]["body"]}
    _copy_optional(artifact["root"], root, ("execution_contract",))
    children = []
    for child in artifact["children"]:
        item = {
            "key": child["key"],
            "title": child["title"],
            "body": child["body"],
            "parent": child["parent"],
            "affects_paths": child["affects_paths"],
            "blocked_by": child["blocked_by"],
        }
        _copy_optional(child, item, ("cross_parent_dependency_reason",))
        children.append(item)
    spec: dict[str, Any] = {
        "root": root,
        "children": children,
        "strict_deps": bool(artifact.get("strict_deps")),
    }
    _copy_optional(artifact, spec, ("challenge_review",))
    return spec


def projection_requirements(artifact: dict[str, Any]) -> dict[str, list[str]]:
    validate_artifact(artifact)
    node_ids = [artifact["root"]["node_id"]] + [child["node_id"] for child in artifact["children"]]
    dependencies = [
        f"{child['node_id']}>{blocker_id}"
        for child in artifact["children"]
        for blocker_id in child["blocked_by_node_ids"]
    ]
    return {"nodes": sorted(node_ids), "dependencies": sorted(dependencies)}


def projection_coverage(artifact: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    expected = projection_requirements(artifact)
    if not isinstance(state, dict):
        return {
            "complete": False,
            "binding_valid": False,
            "missing_nodes": expected["nodes"],
            "missing_dependencies": expected["dependencies"],
        }
    binding_valid = (
        state.get("schema") == PROJECTION_SCHEMA
        and state.get("definition_id") == artifact["definition_id"]
        and state.get("revision") == artifact["revision"]
        and state.get("definition_digest") == artifact["digest"]
    )
    nodes = state.get("nodes") if isinstance(state.get("nodes"), dict) else {}
    dependencies = state.get("dependencies") if isinstance(state.get("dependencies"), dict) else {}
    covered_nodes = {
        key for key, value in nodes.items()
        if isinstance(value, dict) and value.get("number") and value.get("github_node_id")
    }
    covered_dependencies = {
        key for key, value in dependencies.items()
        if isinstance(value, dict) and value.get("materialized") is True
    }
    missing_nodes = sorted(set(expected["nodes"]) - covered_nodes)
    missing_dependencies = sorted(set(expected["dependencies"]) - covered_dependencies)
    return {
        "complete": binding_valid and not missing_nodes and not missing_dependencies,
        "binding_valid": binding_valid,
        "missing_nodes": missing_nodes,
        "missing_dependencies": missing_dependencies,
    }


def validate_run_pin(artifact: dict[str, Any], pin: dict[str, Any]) -> None:
    validate_artifact(artifact)
    expected = {
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "digest": artifact["digest"],
    }
    actual = {key: pin.get(key) for key in expected} if isinstance(pin, dict) else {}
    if actual != expected:
        raise DefinitionError("run_pin_mismatch", f"run pin {actual!r} does not match {expected!r}")


def _run_pin(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "digest": artifact["digest"],
    }


def _definition_node(artifact: dict[str, Any], ref: str) -> dict[str, Any]:
    nodes = [artifact["root"], *artifact["children"]]
    matches = [node for node in nodes if ref in {node["key"], node["node_id"]}]
    if len(matches) != 1:
        raise DefinitionError("node_not_found", f"definition node not found: {ref!r}")
    return matches[0]


def execution_identity(artifact: dict[str, Any], node_ref: str) -> dict[str, str]:
    """Return branch/worktree identity stable across revisions for one node."""
    validate_artifact(artifact)
    node = _definition_node(artifact, node_ref)
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", artifact["definition_id"]).strip("-")[:28]
    suffix = stable_digest({"definition_id": artifact["definition_id"], "node_id": node["node_id"]})[:12]
    identity = f"{readable}-{suffix}"
    return {
        "branch": f"task/definition-{identity}",
        "worktree": f".worktrees/definition-{identity}",
    }


def legacy_issue_identity(issue_number: int) -> dict[str, str]:
    """Compatibility identity for the unchanged Issue-first workflow."""
    if int(issue_number) < 1:
        raise DefinitionError("bad_issue_number", "issue number must be positive")
    return {
        "branch": f"task/issue-{int(issue_number)}",
        "worktree": f".worktrees/issue-{int(issue_number)}",
    }


def _blockers_closed(artifact: dict[str, Any], node: dict[str, Any], state_dir: Path) -> list[str]:
    blockers = set(node.get("blocked_by_node_ids") or [])
    if not blockers:
        return []
    closed: set[str] = set()
    if state_dir.is_dir():
        for path in state_dir.glob("*.json"):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                isinstance(candidate, dict)
                and candidate.get("schema") == RUN_SCHEMA
                and candidate.get("status") == "closed"
                and candidate.get("pin") == _run_pin(artifact)
                and candidate.get("node_id") in blockers
            ):
                closed.add(candidate["node_id"])
    return sorted(blockers - closed)


def start_local_run(
    artifact: dict[str, Any],
    *,
    node_ref: str,
    state_dir: str | Path,
    run_id: str | None = None,
    projection: dict[str, Any] | None = None,
    now: str | None = None,
) -> tuple[dict[str, Any], Path, bool]:
    """Start or recover a local run pinned to an immutable artifact revision."""
    validate_artifact(artifact)
    node = _definition_node(artifact, node_ref)
    if any(child.get("parent_node_id") == node["node_id"] for child in artifact["children"]):
        raise DefinitionError("container_not_executable", f"node {node['key']} has children")
    if artifact["record"] == "github":
        coverage = projection_coverage(artifact, projection)
        if not coverage["complete"]:
            raise DefinitionError(
                "projection_incomplete",
                f"record:github requires full projection before execution: {coverage}",
            )

    states = Path(state_dir)
    missing_blockers = _blockers_closed(artifact, node, states)
    if missing_blockers:
        raise DefinitionError("blocked_by_open", f"local blockers are not closed: {missing_blockers}")

    effective_run_id = run_id or f"run-{artifact['digest'][:12]}-{node['node_id'][-12:]}"
    _safe_id(effective_run_id, "run_id")
    path = states / f"{effective_run_id}.json"
    if path.exists():
        current = read_json(path)
        validate_local_run(artifact, current)
        if current.get("run_id") != effective_run_id or current.get("node_id") != node["node_id"]:
            raise DefinitionError("run_state_mismatch", "run id is already bound to a different node")
        return current, path, False

    timestamp = now or utc_now()
    state = {
        "schema": RUN_SCHEMA,
        "run_id": effective_run_id,
        "pin": _run_pin(artifact),
        "node_id": node["node_id"],
        "node_key": node["key"],
        "record": artifact["record"],
        "delivery": artifact["delivery"],
        "identity": execution_identity(artifact, node["node_id"]),
        "status": "started",
        "started_at": timestamp,
        "updated_at": timestamp,
        "finished_at": None,
        "events": [{"event": "start", "at": timestamp}],
    }
    write_json_atomic(path, state)
    return state, path, True


def validate_local_run(artifact: dict[str, Any], state: dict[str, Any]) -> None:
    validate_artifact(artifact)
    if state.get("schema") != RUN_SCHEMA:
        raise DefinitionError("bad_run_schema", f"run schema must be {RUN_SCHEMA!r}")
    _safe_id(state.get("run_id"), "run_id")
    validate_run_pin(artifact, state.get("pin"))
    node = _definition_node(artifact, state.get("node_id"))
    if state.get("identity") != execution_identity(artifact, node["node_id"]):
        raise DefinitionError("run_identity_mismatch", "run branch/worktree identity was modified")
    if state.get("record") != artifact["record"] or state.get("delivery") != artifact["delivery"]:
        raise DefinitionError("run_pin_mismatch", "run record/delivery differs from pinned artifact")


def transition_local_run(
    artifact: dict[str, Any],
    state: dict[str, Any],
    event: str,
    *,
    evidence: dict[str, Any] | None = None,
    now: str | None = None,
) -> tuple[dict[str, Any], bool]:
    validate_local_run(artifact, state)
    if event not in RUN_TRANSITIONS:
        raise DefinitionError("bad_run_event", f"event must be one of {sorted(RUN_TRANSITIONS)}")
    before, after = RUN_TRANSITIONS[event]
    status = state.get("status")
    if status == after:
        return state, False
    if status != before:
        raise DefinitionError("invalid_run_transition", f"cannot apply {event}: {status!r} -> {after!r}")
    timestamp = now or utc_now()
    updated = json.loads(json.dumps(state))
    updated["status"] = after
    updated["updated_at"] = timestamp
    if event == "closeout":
        updated["finished_at"] = timestamp
    entry: dict[str, Any] = {"event": event, "at": timestamp}
    if evidence is not None:
        if not isinstance(evidence, dict):
            raise DefinitionError("bad_evidence", "evidence must be an object")
        entry["evidence"] = evidence
    updated.setdefault("events", []).append(entry)
    return updated, True


def recover_local_run(artifact: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    validate_local_run(artifact, state)
    next_events = {
        "started": "run",
        "running": "verify",
        "verified": "done",
        "done": "closeout",
        "closed": None,
    }
    status = state.get("status")
    if status not in next_events:
        raise DefinitionError("bad_run_status", f"unknown local run status: {status!r}")
    return {
        "run_id": state.get("run_id"),
        "status": status,
        "next_event": next_events[status],
        "identity": state.get("identity"),
        "pin": state.get("pin"),
    }


def _parse_time(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DefinitionError("receipt_incomplete", f"{where} is required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DefinitionError("bad_timestamp", f"invalid {where}: {value!r}") from exc


def build_receipt(
    state: dict[str, Any],
    *,
    workflow: str = "task-github",
    tokens: int | None = None,
    token_coverage: str | None = None,
    counters: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit the binding receipt schema v1 without estimating unavailable tokens."""
    if state.get("schema") != RUN_SCHEMA or state.get("status") != "closed":
        raise DefinitionError("receipt_incomplete", "receipt requires a closed local run")
    started = _parse_time(state.get("started_at"), "started_at")
    finished = _parse_time(state.get("finished_at"), "finished_at")
    elapsed_ms = int((finished - started).total_seconds() * 1000)
    if elapsed_ms < 0:
        raise DefinitionError("bad_timestamp", "finished_at precedes started_at")
    if tokens is None:
        coverage = token_coverage or "unavailable"
        if coverage != "unavailable":
            raise DefinitionError("bad_token_coverage", "tokens:null requires token_coverage=unavailable")
    else:
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise DefinitionError("bad_tokens", "tokens must be a non-negative integer or null")
        coverage = token_coverage or "measured"
        if coverage != "measured":
            raise DefinitionError("bad_token_coverage", "known tokens require token_coverage=measured")
    counters_out = {} if counters is None else counters
    quality_out = {} if quality is None else quality
    if not isinstance(counters_out, dict) or not isinstance(quality_out, dict):
        raise DefinitionError("bad_receipt", "counters and quality must be objects")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counters_out.values()):
        raise DefinitionError("bad_receipt", "counter values must be non-negative integers")
    return {
        "schema": RECEIPT_SCHEMA,
        "emitter": "task-github",
        "workflow": _require_text(workflow, "workflow"),
        "run_id": _safe_id(state.get("run_id"), "run_id"),
        "started_at": state["started_at"],
        "finished_at": state["finished_at"],
        "elapsed_ms": elapsed_ms,
        "tokens": tokens,
        "token_coverage": coverage,
        "counters": counters_out,
        "quality": quality_out,
    }


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise DefinitionError("read_failed", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise DefinitionError("json_invalid", str(exc)) from exc
    if not isinstance(value, dict):
        raise DefinitionError("json_invalid", "top-level JSON must be an object")
    return value


def write_json_atomic(path: str | Path, value: dict[str, Any], *, immutable: bool = False) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if immutable and target.exists():
        if target.read_text(encoding="utf-8") == rendered:
            return target
        raise DefinitionError("immutable_revision_exists", f"refusing to overwrite {target}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target


def store_artifact(store: str | Path, artifact: dict[str, Any]) -> Path:
    validate_artifact(artifact)
    base = Path(store) / artifact["definition_id"]
    path = base / f"revision-{artifact['revision']:06d}.json"
    write_json_atomic(path, artifact, immutable=True)
    write_json_atomic(base / "current.json", {
        "schema": SCHEMA,
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "digest": artifact["digest"],
        "path": path.name,
    })
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "revise"):
        command = sub.add_parser(name)
        command.add_argument("--spec", required=True)
        command.add_argument("--store", default=".task-github/local/definitions")
        command.add_argument("--previous", required=name == "revise")
        command.add_argument("--record", choices=sorted(RECORD_MODES))
        command.add_argument("--delivery", choices=sorted(DELIVERY_MODES))
    validate = sub.add_parser("validate")
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--previous")
    coverage = sub.add_parser("coverage")
    coverage.add_argument("--artifact", required=True)
    coverage.add_argument("--projection", required=True)
    local_start = sub.add_parser("local-start")
    local_start.add_argument("--artifact", required=True)
    local_start.add_argument("--node", required=True, help="stable node key or node_id")
    local_start.add_argument("--state-dir", default=".task-github/local/runs")
    local_start.add_argument("--run-id")
    local_start.add_argument("--projection")
    local_event = sub.add_parser("local-event")
    local_event.add_argument("--artifact", required=True)
    local_event.add_argument("--run-state", required=True)
    local_event.add_argument("--event", required=True, choices=sorted(RUN_TRANSITIONS))
    local_event.add_argument("--evidence", help="JSON object")
    recover = sub.add_parser("recover")
    recover.add_argument("--artifact", required=True)
    recover.add_argument("--run-state", required=True)
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--run-state", required=True)
    receipt.add_argument("--workflow", default="task-github")
    receipt.add_argument("--tokens", type=int)
    receipt.add_argument("--token-coverage", choices=("measured", "unavailable"))
    receipt.add_argument("--counters", default="{}", help="JSON object")
    receipt.add_argument("--quality", default="{}", help="JSON object")
    receipt.add_argument("--out")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"create", "revise"}:
            previous = read_json(args.previous) if args.previous else None
            artifact = create_artifact(
                read_json(args.spec), previous=previous, record=args.record, delivery=args.delivery
            )
            path = store_artifact(args.store, artifact)
            payload = {"ok": True, "artifact": artifact, "path": str(path)}
        elif args.command == "validate":
            artifact = read_json(args.artifact)
            previous = read_json(args.previous) if args.previous else None
            validate_artifact(artifact, previous=previous)
            payload = {"ok": True, "definition_id": artifact["definition_id"],
                       "revision": artifact["revision"], "digest": artifact["digest"]}
        elif args.command == "coverage":
            artifact = read_json(args.artifact)
            payload = {"ok": True, "coverage": projection_coverage(artifact, read_json(args.projection))}
        elif args.command == "local-start":
            artifact = read_json(args.artifact)
            projection = read_json(args.projection) if args.projection else None
            state, path, created = start_local_run(
                artifact, node_ref=args.node, state_dir=args.state_dir,
                run_id=args.run_id, projection=projection,
            )
            payload = {"ok": True, "created": created, "path": str(path), "run": state}
        elif args.command == "local-event":
            artifact = read_json(args.artifact)
            state_path = Path(args.run_state)
            evidence = json.loads(args.evidence) if args.evidence else None
            state, changed = transition_local_run(
                artifact, read_json(state_path), args.event, evidence=evidence
            )
            if changed:
                write_json_atomic(state_path, state)
            payload = {"ok": True, "changed": changed, "path": str(state_path), "run": state}
        elif args.command == "recover":
            payload = {"ok": True, "recovery": recover_local_run(
                read_json(args.artifact), read_json(args.run_state)
            )}
        else:
            counters = json.loads(args.counters)
            quality = json.loads(args.quality)
            receipt = build_receipt(
                read_json(args.run_state), workflow=args.workflow, tokens=args.tokens,
                token_coverage=args.token_coverage, counters=counters, quality=quality,
            )
            if args.out:
                write_json_atomic(args.out, receipt)
            payload = {"ok": True, "receipt": receipt, "path": args.out}
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error_code": "json_invalid", "message": str(exc)}, ensure_ascii=False))
        return 2
    except DefinitionError as exc:
        print(json.dumps({"ok": False, "error_code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
