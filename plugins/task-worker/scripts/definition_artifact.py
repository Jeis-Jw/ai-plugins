#!/usr/bin/env python3
"""Provider-neutral immutable task definitions and local execution lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "task-worker.definition/v1"
LEGACY_SCHEMAS = {"task-github.definition/v1"}
RUN_SCHEMA = "task-worker.local-run/v1"
LEGACY_RUN_SCHEMAS = {"task-github.local-run/v1"}
WORK_GRAPH_SCHEMA = "task-worker.work-graph/v1"
RECEIPT_SCHEMA = "workflow-receipt/v1"
PLUGIN_VERSION = "0.2.0"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DELIVERY_MODES = {"local-ff", "external"}
LEGACY_DELIVERY_MODES = {"local-ff", "pull-request"}
RUN_TRANSITIONS = {
    "run": ("started", "running"),
    "verify": ("running", "verified"),
    "done": ("verified", "done"),
    "closeout": ("done", "closed"),
}
ACTIVE_STATUSES = {"started", "running", "verified", "done"}
GRAPH_STATUSES = {"open", "active", "completed", "gated", "failed"}


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


def _normalise_string_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise DefinitionError("bad_definition", f"{where} must be a string list")
    return [item.strip() for item in value]


def _copy_optional(source: dict[str, Any], target: dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if key in source:
            target[key] = source[key]


def _generated_definition_id(spec: dict[str, Any]) -> str:
    stable_key = (spec.get("root") or {}).get("stable_key")
    if stable_key is not None:
        stable_key = _require_text(stable_key, "root.stable_key")
        return f"def-{stable_digest({'root_stable_key': stable_key})[:20]}"
    return f"def-{uuid.uuid4().hex}"


def node_id(definition_id: str, key: str) -> str:
    return f"node-{stable_digest({'definition_id': definition_id, 'key': key})[:20]}"


def _effective_delivery(artifact: dict[str, Any]) -> str:
    delivery = artifact.get("delivery", "local-ff")
    return "external" if delivery == "pull-request" else delivery


def create_artifact(
    spec: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    delivery: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create a canonical task-worker revision with stable node identities."""
    if not isinstance(spec, dict):
        raise DefinitionError("bad_definition", "spec must be an object")
    if spec.get("record") not in (None, "none"):
        raise DefinitionError(
            "provider_binding_required",
            "provider recording belongs in an adapter binding, not a task-worker definition",
        )
    root = spec.get("root")
    children = spec.get("children", [])
    if not isinstance(root, dict) or not isinstance(children, list):
        raise DefinitionError("bad_definition", "root must be an object and children a list")

    if previous is not None:
        validate_artifact(previous)
        definition_id = previous["definition_id"]
        if spec.get("definition_id") not in (None, definition_id):
            raise DefinitionError("definition_id_changed", "a revision cannot change definition_id")
        revision = int(previous["revision"]) + 1
        previous_digest = previous["digest"]
    else:
        definition_id = _safe_id(spec.get("definition_id") or _generated_definition_id(spec), "definition_id")
        revision = 1
        previous_digest = None

    delivery_mode = delivery or spec.get("delivery") or (
        _effective_delivery(previous) if previous else "local-ff"
    )
    if delivery_mode not in DELIVERY_MODES:
        raise DefinitionError("bad_delivery_mode", f"delivery must be one of {sorted(DELIVERY_MODES)}")

    root_out: dict[str, Any] = {
        "node_id": node_id(definition_id, "root"),
        "key": "root",
        "title": _require_text(root.get("title"), "root.title"),
        "body": _require_text(root.get("body"), "root.body"),
    }
    _copy_optional(root, root_out, ("execution_contract", "gear", "risk"))

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
            "affects_paths": _normalise_string_list(child.get("affects_paths", []), f"{where}.affects_paths"),
            "blocked_by": blocked_by,
            "blocked_by_node_ids": [node_id(definition_id, blocker) for blocker in blocked_by],
        }
        _copy_optional(
            child,
            item,
            ("cross_parent_dependency_reason", "execution_contract", "gear", "risk", "review_required"),
        )
        child_out.append(item)

    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "definition_id": definition_id,
        "revision": revision,
        "previous_digest": previous_digest,
        "created_at": created_at or utc_now(),
        "delivery": delivery_mode,
        "root": root_out,
        "children": child_out,
        "strict_deps": bool(spec.get("strict_deps")),
    }
    _copy_optional(spec, artifact, ("challenge_review", "owner_gates"))
    artifact["digest"] = artifact_digest(artifact)
    validate_artifact(artifact, previous=previous)
    return artifact


def _assert_acyclic(graph: dict[str, list[str]], code: str, label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise DefinitionError(code, f"{label} cycle reaches {key}")
        if key in visited:
            return
        visiting.add(key)
        for target in graph.get(key, []):
            visit(target)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def validate_artifact(
    artifact: dict[str, Any], *, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise DefinitionError("bad_artifact", "artifact must be an object")
    schema = artifact.get("schema")
    if schema not in {SCHEMA, *LEGACY_SCHEMAS}:
        raise DefinitionError("bad_artifact_schema", f"unsupported artifact schema: {schema!r}")
    legacy = schema in LEGACY_SCHEMAS
    definition_id = _safe_id(artifact.get("definition_id"), "definition_id")
    revision = artifact.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise DefinitionError("bad_revision", "revision must be a positive integer")
    delivery = artifact.get("delivery", "local-ff")
    valid_delivery = LEGACY_DELIVERY_MODES if legacy else DELIVERY_MODES
    if delivery not in valid_delivery:
        raise DefinitionError("bad_delivery_mode", f"delivery must be one of {sorted(valid_delivery)}")
    if legacy and artifact.get("record") not in {"none", "github"}:
        raise DefinitionError("bad_record_mode", "legacy record must be none or github")
    if not legacy and "record" in artifact:
        raise DefinitionError("provider_field_forbidden", "record is an adapter concern")
    if artifact.get("digest") != artifact_digest(artifact):
        raise DefinitionError("digest_mismatch", "artifact digest does not match canonical content")

    root = artifact.get("root")
    children = artifact.get("children")
    if not isinstance(root, dict) or not isinstance(children, list):
        raise DefinitionError("bad_artifact", "artifact root/children are invalid")
    if root.get("node_id") != node_id(definition_id, "root") or root.get("key") != "root":
        raise DefinitionError("node_id_mismatch", "root node id is not stable")
    _require_text(root.get("title"), "root.title")
    _require_text(root.get("body"), "root.body")

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
        blockers = _normalise_string_list(child.get("blocked_by", []), f"children[{index}].blocked_by")
        if key in blockers:
            raise DefinitionError("self_dependency", f"{key} cannot block itself")
        if child.get("blocked_by_node_ids") != [node_id(definition_id, item) for item in blockers]:
            raise DefinitionError("node_id_mismatch", f"child {key} dependency ids changed")

    by_key = {child["key"]: child for child in children}
    for child in children:
        if child.get("parent") is not None and child["parent"] not in keys:
            raise DefinitionError("unknown_parent", f"{child['key']} parent is unknown")
        if any(blocker not in keys for blocker in child.get("blocked_by", [])):
            raise DefinitionError("unknown_dependency", f"{child['key']} has an unknown blocker")
    _assert_acyclic(
        {key: [node["parent"]] if node.get("parent") else [] for key, node in by_key.items()},
        "parent_cycle",
        "parent",
    )
    _assert_acyclic(
        {key: list(node.get("blocked_by", [])) for key, node in by_key.items()},
        "dependency_cycle",
        "dependency",
    )

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
    elif revision == 1 and previous_digest is not None:
        raise DefinitionError("previous_digest_mismatch", "revision 1 must not have previous_digest")
    return artifact


def artifact_to_spec(artifact: dict[str, Any]) -> dict[str, Any]:
    """Export a provider-neutral define spec without adapter bindings."""
    validate_artifact(artifact)
    root = {"title": artifact["root"]["title"], "body": artifact["root"]["body"]}
    _copy_optional(artifact["root"], root, ("execution_contract", "gear", "risk"))
    children = []
    for child in artifact["children"]:
        item = {
            "key": child["key"],
            "title": child["title"],
            "body": child["body"],
            "parent": child["parent"],
            "affects_paths": child.get("affects_paths", []),
            "blocked_by": child.get("blocked_by", []),
        }
        _copy_optional(
            child,
            item,
            ("cross_parent_dependency_reason", "execution_contract", "gear", "risk", "review_required"),
        )
        children.append(item)
    spec: dict[str, Any] = {
        "root": root,
        "children": children,
        "strict_deps": bool(artifact.get("strict_deps")),
    }
    _copy_optional(artifact, spec, ("challenge_review", "owner_gates"))
    return spec


def validate_work_graph(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate a provider-neutral execution snapshot supplied by an adapter."""
    if not isinstance(snapshot, dict):
        raise DefinitionError("bad_work_graph", "work graph snapshot must be an object")
    if snapshot.get("schema") != WORK_GRAPH_SCHEMA:
        raise DefinitionError("bad_work_graph_schema", f"schema must be {WORK_GRAPH_SCHEMA!r}")
    _safe_id(snapshot.get("graph_id"), "graph_id")
    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise DefinitionError("bad_work_graph", "nodes must be a non-empty list")

    ids: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for index, raw in enumerate(nodes):
        where = f"nodes[{index}]"
        if not isinstance(raw, dict):
            raise DefinitionError("bad_work_graph", f"{where} must be an object")
        node = dict(raw)
        node_id_value = _safe_id(node.get("node_id"), f"{where}.node_id")
        if node_id_value in ids:
            raise DefinitionError("duplicate_node", f"duplicate node id: {node_id_value}")
        ids.add(node_id_value)
        node["node_id"] = node_id_value
        node["key"] = _safe_id(node.get("key") or node_id_value, f"{where}.key")
        node["title"] = _require_text(node.get("title") or node["key"], f"{where}.title")
        parent_id = node.get("parent_id")
        node["parent_id"] = None if parent_id is None else _safe_id(parent_id, f"{where}.parent_id")
        node["blocked_by"] = [
            _safe_id(value, f"{where}.blocked_by")
            for value in _normalise_string_list(node.get("blocked_by", []), f"{where}.blocked_by")
        ]
        status = node.get("status")
        if status not in GRAPH_STATUSES:
            raise DefinitionError("bad_work_graph_status", f"{where}.status must be one of {sorted(GRAPH_STATUSES)}")
        normalised.append(node)

    by_id = {node["node_id"]: node for node in normalised}
    for node in normalised:
        parent_id = node["parent_id"]
        if parent_id is not None and parent_id not in by_id:
            raise DefinitionError("unknown_parent", f"{node['node_id']} parent is unknown: {parent_id}")
        if parent_id == node["node_id"]:
            raise DefinitionError("self_parent", f"{node['node_id']} cannot parent itself")
        if node["node_id"] in node["blocked_by"]:
            raise DefinitionError("self_dependency", f"{node['node_id']} cannot block itself")

    _assert_acyclic(
        {
            node["node_id"]: [node["parent_id"]] if node["parent_id"] is not None else []
            for node in normalised
        },
        "parent_cycle",
        "parent",
    )
    _assert_acyclic(
        {
            node["node_id"]: [target for target in node["blocked_by"] if target in by_id]
            for node in normalised
        },
        "dependency_cycle",
        "dependency",
    )

    expected_digest = stable_digest({key: value for key, value in snapshot.items() if key != "digest"})
    if snapshot.get("digest") not in (None, expected_digest):
        raise DefinitionError("work_graph_digest_mismatch", "work graph digest does not match canonical content")
    validated = dict(snapshot)
    validated["nodes"] = normalised
    validated["digest"] = expected_digest
    return validated


def _graph_item(node: dict[str, Any]) -> dict[str, Any]:
    return {"node_id": node["node_id"], "node_key": node["key"], "title": node["title"]}


def plan_work_graph(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the complete ready set plus integration candidates for one snapshot."""
    graph = validate_work_graph(snapshot)
    nodes = graph["nodes"]
    by_id = {node["node_id"]: node for node in nodes}
    children: dict[str, list[str]] = {}
    for node in nodes:
        if node["parent_id"] is not None:
            children.setdefault(node["parent_id"], []).append(node["node_id"])
    completed = {node["node_id"] for node in nodes if node["status"] == "completed"}

    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    integration: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    gated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for node in nodes:
        item = _graph_item(node)
        status = node["status"]
        if status == "active":
            active.append(item)
        elif status == "gated":
            gated.append(item)
        elif status == "failed":
            failed.append(item)
        if status != "open":
            continue

        missing = sorted(set(node["blocked_by"]) - completed)
        if missing:
            blocked.append({**item, "missing_blockers": missing})
            continue
        child_ids = children.get(node["node_id"], [])
        if child_ids:
            if all(child_id in completed for child_id in child_ids):
                integration.append(item)
            continue
        ready.append(item)

    return {
        "schema": "task-worker.ready-plan/v1",
        "graph_id": graph["graph_id"],
        "snapshot_digest": graph["digest"],
        "ready_actions": ready,
        "blocked": blocked,
        "active": active,
        "gated": gated,
        "failed": failed,
        "integration_candidates": integration,
        "completed": [node["node_id"] for node in nodes if node["node_id"] in completed],
    }


def _run_pin(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "digest": artifact["digest"],
    }


def validate_run_pin(artifact: dict[str, Any], pin: dict[str, Any]) -> None:
    validate_artifact(artifact)
    expected = _run_pin(artifact)
    actual = {key: pin.get(key) for key in expected} if isinstance(pin, dict) else {}
    if actual != expected:
        raise DefinitionError("run_pin_mismatch", f"run pin {actual!r} does not match {expected!r}")


def _definition_node(artifact: dict[str, Any], ref: str) -> dict[str, Any]:
    matches = [node for node in [artifact["root"], *artifact["children"]] if ref in {node["key"], node["node_id"]}]
    if len(matches) != 1:
        raise DefinitionError("node_not_found", f"definition node not found: {ref!r}")
    return matches[0]


def execution_identity(artifact: dict[str, Any], node_ref: str) -> dict[str, str]:
    validate_artifact(artifact)
    node = _definition_node(artifact, node_ref)
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", artifact["definition_id"]).strip("-")[:28]
    suffix = stable_digest({"definition_id": artifact["definition_id"], "node_id": node["node_id"]})[:12]
    identity = f"{readable}-{suffix}"
    return {
        "branch": f"task/definition-{identity}",
        "worktree": f".worktrees/definition-{identity}",
    }


def _read_matching_states(artifact: dict[str, Any], state_dir: Path) -> list[dict[str, Any]]:
    if not state_dir.is_dir():
        return []
    matches: list[dict[str, Any]] = []
    for path in sorted(state_dir.glob("*.json")):
        candidate = read_json(path)
        pin = candidate.get("pin")
        if not isinstance(pin, dict) or pin.get("definition_id") != artifact["definition_id"]:
            continue
        if pin != _run_pin(artifact):
            continue
        validate_local_run(artifact, candidate)
        candidate = dict(candidate)
        candidate["state_path"] = str(path)
        matches.append(candidate)
    return matches


def ready_plan(artifact: dict[str, Any], state_dir: str | Path) -> dict[str, Any]:
    """Return every currently ready leaf; never collapse the set to one next action."""
    validate_artifact(artifact)
    states = _read_matching_states(artifact, Path(state_dir))
    by_node: dict[str, list[dict[str, Any]]] = {}
    for state in states:
        by_node.setdefault(state["node_id"], []).append(state)
    ambiguous = {node: values for node, values in by_node.items() if len(values) > 1}
    if ambiguous:
        raise DefinitionError("ambiguous_run_state", f"multiple pinned runs exist for nodes: {sorted(ambiguous)}")

    graph_nodes = []
    for node in [artifact["root"], *artifact["children"]]:
        run = by_node.get(node["node_id"], [None])[0]
        if run and run.get("status") == "closed":
            status = "completed"
        elif run and run.get("status") in ACTIVE_STATUSES:
            status = "active"
        else:
            status = "open"
        graph_nodes.append({
            "node_id": node["node_id"],
            "key": node["key"],
            "title": node["title"],
            "parent_id": None if node["key"] == "root" else node["parent_node_id"],
            "blocked_by": list(node.get("blocked_by_node_ids", [])),
            "status": status,
        })
    graph_plan = plan_work_graph({
        "schema": WORK_GRAPH_SCHEMA,
        "graph_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "nodes": graph_nodes,
    })
    ready = [
        {**item, "identity": execution_identity(artifact, item["node_id"])}
        for item in graph_plan["ready_actions"]
    ]
    active = []
    for item in graph_plan["active"]:
        state = by_node[item["node_id"]][0]
        active.append({**item, "status": state["status"], "run_id": state["run_id"]})
    return {
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "digest": artifact["digest"],
        "ready_actions": ready,
        "blocked": graph_plan["blocked"],
        "active": active,
        "integration_candidates": graph_plan["integration_candidates"],
        "completed": graph_plan["completed"],
    }


def start_local_run(
    artifact: dict[str, Any],
    *,
    node_ref: str,
    state_dir: str | Path,
    run_id: str | None = None,
    now: str | None = None,
) -> tuple[dict[str, Any], Path, bool]:
    validate_artifact(artifact)
    node = _definition_node(artifact, node_ref)
    if any(child.get("parent_node_id") == node["node_id"] for child in artifact["children"]):
        raise DefinitionError("container_not_executable", f"node {node['key']} has children")
    states = Path(state_dir)
    matching_states = _read_matching_states(artifact, states)
    closed = {state["node_id"] for state in matching_states if state["status"] == "closed"}
    missing = sorted(set(node.get("blocked_by_node_ids", [])) - closed)
    if missing:
        raise DefinitionError("blocked_by_open", f"local blockers are not closed: {missing}")

    effective_run_id = run_id or f"run-{artifact['digest'][:12]}-{node['node_id'][-12:]}"
    _safe_id(effective_run_id, "run_id")
    path = states / f"{effective_run_id}.json"
    if path.exists():
        current = read_json(path)
        validate_local_run(artifact, current)
        if current.get("node_id") != node["node_id"]:
            raise DefinitionError("run_state_mismatch", "run id is bound to a different node")
        return current, path, False
    existing_node_runs = [state for state in matching_states if state["node_id"] == node["node_id"]]
    if existing_node_runs:
        raise DefinitionError(
            "execution_lease_conflict",
            f"node {node['key']} already has pinned run {existing_node_runs[0]['run_id']}",
        )

    timestamp = now or utc_now()
    state = {
        "schema": RUN_SCHEMA,
        "run_id": effective_run_id,
        "pin": _run_pin(artifact),
        "node_id": node["node_id"],
        "node_key": node["key"],
        "delivery": _effective_delivery(artifact),
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
    schema = state.get("schema")
    if schema not in {RUN_SCHEMA, *LEGACY_RUN_SCHEMAS}:
        raise DefinitionError("bad_run_schema", f"unsupported run schema: {schema!r}")
    _safe_id(state.get("run_id"), "run_id")
    validate_run_pin(artifact, state.get("pin"))
    node = _definition_node(artifact, state.get("node_id"))
    if state.get("identity") != execution_identity(artifact, node["node_id"]):
        raise DefinitionError("run_identity_mismatch", "run branch/worktree identity was modified")
    expected_delivery = artifact.get("delivery") if schema in LEGACY_RUN_SCHEMAS else _effective_delivery(artifact)
    if state.get("delivery") != expected_delivery:
        raise DefinitionError("run_pin_mismatch", "run delivery differs from pinned artifact")
    if state.get("status") not in {*ACTIVE_STATUSES, "closed"}:
        raise DefinitionError("bad_run_status", f"unknown local run status: {state.get('status')!r}")


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
    if state.get("status") == after:
        return state, False
    if state.get("status") != before:
        raise DefinitionError("invalid_run_transition", f"cannot apply {event}: {state.get('status')!r} -> {after!r}")
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
    next_events = {"started": "run", "running": "verify", "verified": "done", "done": "closeout", "closed": None}
    return {
        "run_id": state["run_id"],
        "status": state["status"],
        "next_event": next_events[state["status"]],
        "identity": state["identity"],
        "pin": state["pin"],
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
    workflow: str = "task-worker",
    tokens: int | None = None,
    token_coverage: str | None = None,
    counters: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state.get("schema") not in {RUN_SCHEMA, *LEGACY_RUN_SCHEMAS} or state.get("status") != "closed":
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
        coverage = token_coverage or "exact"
        if coverage != "exact":
            raise DefinitionError("bad_token_coverage", "known tokens require token_coverage=exact")
    counters_out = {} if counters is None else counters
    quality_out = {} if quality is None else quality
    if not isinstance(counters_out, dict) or not isinstance(quality_out, dict):
        raise DefinitionError("bad_receipt", "counters and quality must be objects")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counters_out.values()):
        raise DefinitionError("bad_receipt", "counter values must be non-negative integers")
    return {
        "schema": RECEIPT_SCHEMA,
        "emitter": "task-worker",
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
        raw = sys.stdin.read() if str(path) == "-" else Path(path).read_text(encoding="utf-8")
        value = json.loads(raw)
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
        command.add_argument("--store", default=".task-worker/definitions")
        command.add_argument("--previous", required=name == "revise")
        command.add_argument("--delivery", choices=sorted(DELIVERY_MODES))
    validate = sub.add_parser("validate")
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--previous")
    export = sub.add_parser("export")
    export.add_argument("--artifact", required=True)
    graph = sub.add_parser("plan-graph")
    graph.add_argument("--snapshot", required=True)
    sub.add_parser("capabilities")
    ready = sub.add_parser("ready")
    ready.add_argument("--artifact", required=True)
    ready.add_argument("--state-dir", default=".task-worker/runs")
    local_start = sub.add_parser("local-start")
    local_start.add_argument("--artifact", required=True)
    local_start.add_argument("--node", required=True)
    local_start.add_argument("--state-dir", default=".task-worker/runs")
    local_start.add_argument("--run-id")
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
    receipt.add_argument("--workflow", default="task-worker")
    receipt.add_argument("--tokens", type=int)
    receipt.add_argument("--token-coverage", choices=("exact", "unavailable"))
    receipt.add_argument("--counters", default="{}")
    receipt.add_argument("--quality", default="{}")
    receipt.add_argument("--out")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"create", "revise"}:
            previous = read_json(args.previous) if args.previous else None
            artifact = create_artifact(read_json(args.spec), previous=previous, delivery=args.delivery)
            path = store_artifact(args.store, artifact)
            payload = {"ok": True, "artifact": artifact, "path": str(path)}
        elif args.command == "validate":
            artifact = read_json(args.artifact)
            previous = read_json(args.previous) if args.previous else None
            validate_artifact(artifact, previous=previous)
            payload = {"ok": True, "definition_id": artifact["definition_id"], "revision": artifact["revision"], "digest": artifact["digest"]}
        elif args.command == "export":
            artifact = read_json(args.artifact)
            payload = {"ok": True, "spec": artifact_to_spec(artifact)}
        elif args.command == "plan-graph":
            payload = {"ok": True, "plan": plan_work_graph(read_json(args.snapshot))}
        elif args.command == "capabilities":
            payload = {
                "ok": True,
                "plugin": "task-worker",
                "version": PLUGIN_VERSION,
                "contracts": {
                    "definition": SCHEMA,
                    "local_run": RUN_SCHEMA,
                    "work_graph": WORK_GRAPH_SCHEMA,
                    "ready_plan": "task-worker.ready-plan/v1",
                    "receipt": RECEIPT_SCHEMA,
                },
                "commands": [
                    "create", "revise", "validate", "export", "plan-graph", "ready",
                    "local-start", "local-event", "recover", "receipt", "capabilities",
                ],
            }
        elif args.command == "ready":
            payload = {"ok": True, "plan": ready_plan(read_json(args.artifact), args.state_dir)}
        elif args.command == "local-start":
            state, path, created = start_local_run(
                read_json(args.artifact), node_ref=args.node, state_dir=args.state_dir, run_id=args.run_id
            )
            payload = {"ok": True, "created": created, "path": str(path), "run": state}
        elif args.command == "local-event":
            artifact = read_json(args.artifact)
            state_path = Path(args.run_state)
            evidence = json.loads(args.evidence) if args.evidence else None
            state, changed = transition_local_run(artifact, read_json(state_path), args.event, evidence=evidence)
            if changed:
                write_json_atomic(state_path, state)
            payload = {"ok": True, "changed": changed, "path": str(state_path), "run": state}
        elif args.command == "recover":
            payload = {"ok": True, "recovery": recover_local_run(read_json(args.artifact), read_json(args.run_state))}
        else:
            receipt = build_receipt(
                read_json(args.run_state), workflow=args.workflow, tokens=args.tokens,
                token_coverage=args.token_coverage, counters=json.loads(args.counters), quality=json.loads(args.quality),
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
