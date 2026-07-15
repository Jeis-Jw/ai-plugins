#!/usr/bin/env python3
"""Provider-neutral immutable task definitions and local execution lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import execution_control
except ModuleNotFoundError:  # importlib callers may not add this script directory to sys.path
    _execution_spec = importlib.util.spec_from_file_location(
        "task_worker_execution_control", Path(__file__).with_name("execution_control.py")
    )
    if _execution_spec is None or _execution_spec.loader is None:  # pragma: no cover
        raise
    execution_control = importlib.util.module_from_spec(_execution_spec)
    _execution_spec.loader.exec_module(execution_control)


SCHEMA = "task-worker.definition/v1"
LEGACY_SCHEMAS = {"task-github.definition/v1"}
RUN_SCHEMA = "task-worker.local-run/v1"
LEGACY_RUN_SCHEMAS = {"task-github.local-run/v1"}
WORK_GRAPH_SCHEMA = "task-worker.work-graph/v1"
RECEIPT_SCHEMA = "workflow-receipt/v1"
BINDING_SCHEMA = "task-worker.provider-binding/v1"
CONTEXT_SCHEMA = "task-worker.context-packet/v1"
EVIDENCE_SCHEMA = "task-worker.verification-evidence/v1"
REVIEW_LEASE_SCHEMA = "workflow-review-lease/v1"
REVIEW_PERMIT_SCHEMA = "task-worker.review-permit/v1"
PLUGIN_VERSION = "0.6.0"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DELIVERY_MODES = {"local-ff", "external"}
DISPATCH_MODES = {"worker", "manual"}
LEGACY_DELIVERY_MODES = {"local-ff", "pull-request"}
RUN_TRANSITIONS = {
    "run": ("started", "running"),
    "verify": ("running", "verified"),
    "done": ("verified", "done"),
    "closeout": ("done", "closed"),
}
ACTIVE_STATUSES = {"started", "running", "verified", "done"}
GRAPH_STATUSES = {"open", "active", "completed", "gated", "failed"}
REVIEW_LEASE_OWNERS = {"studio", "task-worker"}
REVIEW_LEASE_PROVIDERS = {"native", "session-review"}
REVIEW_REQUIREMENTS = {"self", "independent"}
REVIEW_LEASE_KEYS = {
    "schema", "lease_id", "owner", "provider", "episode_id", "edge_id",
    "requirement", "criteria_digest", "evidence_refs", "digest",
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


def tagged_digest(value: Any) -> str:
    return f"sha256:{stable_digest(value)}"


def validate_review_lease(lease: dict[str, Any]) -> dict[str, Any]:
    """Validate the cross-orchestrator review ownership contract exactly.

    A missing lease means the caller's existing local review policy applies.
    Keeping this object strict prevents similarly named legacy handoff fields
    from silently creating a second reviewer owner.
    """
    if not isinstance(lease, dict) or lease.get("schema") != REVIEW_LEASE_SCHEMA:
        raise DefinitionError(
            "bad_review_lease_schema", f"review lease schema must be {REVIEW_LEASE_SCHEMA!r}"
        )
    extra = set(lease) - REVIEW_LEASE_KEYS
    missing = REVIEW_LEASE_KEYS - set(lease)
    if extra or missing:
        raise DefinitionError(
            "bad_review_lease",
            f"review lease fields differ from contract (missing={sorted(missing)}, extra={sorted(extra)})",
        )
    for key in ("lease_id", "episode_id", "edge_id"):
        _safe_id(lease.get(key), f"review_lease.{key}")
    if lease.get("owner") not in REVIEW_LEASE_OWNERS:
        raise DefinitionError("bad_review_lease", "review_lease.owner must be studio or task-worker")
    if lease.get("provider") not in REVIEW_LEASE_PROVIDERS:
        raise DefinitionError("bad_review_lease", "review_lease.provider must be native or session-review")
    if lease.get("requirement") not in REVIEW_REQUIREMENTS:
        raise DefinitionError("bad_review_lease", "review_lease.requirement must be self or independent")
    criteria_digest = lease.get("criteria_digest")
    if not isinstance(criteria_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", criteria_digest):
        raise DefinitionError("bad_review_lease", "review_lease.criteria_digest must be a tagged sha256")
    evidence_refs = lease.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not all(isinstance(value, str) and value.strip() for value in evidence_refs)
        or len(set(evidence_refs)) != len(evidence_refs)
    ):
        raise DefinitionError("bad_review_lease", "review_lease.evidence_refs must be a unique string list")
    expected = tagged_digest({key: lease[key] for key in REVIEW_LEASE_KEYS if key != "digest"})
    if lease.get("digest") != expected:
        raise DefinitionError("review_lease_digest_mismatch", "review lease digest does not match canonical content")
    return lease


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
    dispatch_mode = spec.get("dispatch") or (previous.get("dispatch") if previous else "worker")
    if dispatch_mode not in DISPATCH_MODES:
        raise DefinitionError("bad_dispatch_mode", f"dispatch must be one of {sorted(DISPATCH_MODES)}")

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
        "dispatch": dispatch_mode,
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
    if artifact.get("dispatch", "worker") not in DISPATCH_MODES:
        raise DefinitionError("bad_dispatch_mode", f"dispatch must be one of {sorted(DISPATCH_MODES)}")
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
        "dispatch": artifact.get("dispatch", "worker"),
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
    dispatch = artifact.get("dispatch", "worker")
    planned_ready = [
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
        "dispatch": dispatch,
        "ready_actions": planned_ready if dispatch == "worker" else [],
        "manual_actions": planned_ready if dispatch == "manual" else [],
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
    if artifact.get("dispatch", "worker") != "worker":
        raise DefinitionError("manual_dispatch", "manual dispatch does not create task-worker local runs")
    node = _definition_node(artifact, node_ref)
    states = Path(state_dir)
    matching_states = _read_matching_states(artifact, states)
    closed = {state["node_id"] for state in matching_states if state["status"] == "closed"}
    child_ids = {
        child["node_id"]
        for child in artifact["children"]
        if child.get("parent_node_id") == node["node_id"]
    }
    missing_children = sorted(child_ids - closed)
    if missing_children:
        raise DefinitionError("integration_not_ready", f"container children are not closed: {missing_children}")
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
        "run_kind": "integration" if child_ids else "work",
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
    if state.get("run_kind", "work") not in {"work", "integration"}:
        raise DefinitionError("bad_run_kind", "run_kind must be work or integration")
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
        "run_kind": state.get("run_kind", "work"),
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
    require_token_coverage: bool = False,
) -> dict[str, Any]:
    if state.get("schema") not in {RUN_SCHEMA, *LEGACY_RUN_SCHEMAS} or state.get("status") != "closed":
        raise DefinitionError("receipt_incomplete", "receipt requires a closed local run")
    started = _parse_time(state.get("started_at"), "started_at")
    finished = _parse_time(state.get("finished_at"), "finished_at")
    elapsed_ms = int((finished - started).total_seconds() * 1000)
    if elapsed_ms < 0:
        raise DefinitionError("bad_timestamp", "finished_at precedes started_at")
    if tokens is None:
        if require_token_coverage:
            raise DefinitionError("token_coverage_required", "token telemetry is required by task-worker config")
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


def _state_path(state_root: str | Path, kind: str) -> Path:
    return Path(state_root) / kind


def _context_packet(artifact: dict[str, Any], facts: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    if not isinstance(facts, dict):
        raise DefinitionError("bad_context", "context facts must be an object")
    digest = stable_digest(facts)
    return {
        "schema": CONTEXT_SCHEMA,
        "definition": _run_pin(artifact),
        "digest": digest,
        "created_at": now or utc_now(),
        "facts": facts,
    }


def validate_binding(binding: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, dict) or binding.get("schema") != BINDING_SCHEMA:
        raise DefinitionError("bad_binding_schema", f"schema must be {BINDING_SCHEMA!r}")
    _safe_id(binding.get("binding_id"), "binding_id")
    pin = binding.get("definition")
    if not isinstance(pin, dict):
        raise DefinitionError("bad_binding", "definition pin is required")
    _safe_id(pin.get("definition_id"), "definition.definition_id")
    if not isinstance(pin.get("revision"), int) or pin["revision"] < 1:
        raise DefinitionError("bad_binding", "definition.revision must be positive")
    if not isinstance(pin.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", pin["digest"]):
        raise DefinitionError("bad_binding", "definition.digest must be sha256")
    if binding.get("dispatch") not in DISPATCH_MODES:
        raise DefinitionError("bad_dispatch_mode", "binding dispatch is invalid")
    if not isinstance(binding.get("artifact_path"), str) or not binding["artifact_path"]:
        raise DefinitionError("bad_binding", "artifact_path is required")
    aliases = binding.get("aliases")
    if not isinstance(aliases, list) or not all(isinstance(value, str) and value for value in aliases):
        raise DefinitionError("bad_binding", "aliases must be a non-empty string list")
    if len(set(aliases)) != len(aliases):
        raise DefinitionError("bad_binding", "aliases must be unique")
    providers = binding.get("providers", {})
    if not isinstance(providers, dict) or not all(
        isinstance(name, str) and name and isinstance(value, dict)
        for name, value in providers.items()
    ):
        raise DefinitionError("bad_binding", "providers must be an object of opaque provider objects")
    review_leases = binding.get("review_leases", [])
    if not isinstance(review_leases, list):
        raise DefinitionError("bad_binding", "review_leases must be a list")
    lease_ids: set[str] = set()
    review_edges: set[str] = set()
    for lease in review_leases:
        validate_review_lease(lease)
        lease_id = lease["lease_id"]
        review_edge = lease["edge_id"]
        if lease_id in lease_ids or review_edge in review_edges:
            raise DefinitionError("review_lease_conflict", "review lease id and episode/edge must be unique")
        lease_ids.add(lease_id)
        review_edges.add(review_edge)
    context = binding.get("context")
    if context is not None and (
        not isinstance(context, dict)
        or not isinstance(context.get("path"), str)
        or not isinstance(context.get("digest"), str)
    ):
        raise DefinitionError("bad_binding", "context must contain path and digest")
    work_graph = binding.get("work_graph")
    if work_graph is not None and (
        not isinstance(work_graph, dict)
        or not isinstance(work_graph.get("path"), str)
        or not isinstance(work_graph.get("digest"), str)
    ):
        raise DefinitionError("bad_binding", "work_graph must contain path and digest")
    return binding


def _binding_files(state_root: str | Path) -> list[Path]:
    directory = _state_path(state_root, "bindings")
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def resolve_binding(ref: str, state_root: str | Path) -> tuple[dict[str, Any], Path]:
    matches = []
    for path in _binding_files(state_root):
        binding = validate_binding(read_json(path))
        if ref in {binding["binding_id"], binding["definition"]["definition_id"], *binding["aliases"]}:
            matches.append((binding, path))
    if not matches:
        raise DefinitionError("binding_not_found", f"no provider binding matches {ref!r}")
    if len(matches) != 1:
        raise DefinitionError("binding_ambiguous", f"multiple provider bindings match {ref!r}")
    return matches[0]


def upsert_binding(
    artifact: dict[str, Any],
    *,
    artifact_path: str | Path,
    state_root: str | Path,
    aliases: Iterable[str] = (),
    provider: str | None = None,
    provider_data: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    work_graph: dict[str, Any] | None = None,
    review_leases: Iterable[dict[str, Any]] = (),
    now: str | None = None,
) -> tuple[dict[str, Any], Path, bool]:
    validate_artifact(artifact)
    definition_id = artifact["definition_id"]
    binding_id = f"binding-{definition_id}"
    path = _state_path(state_root, "bindings") / f"{definition_id}.json"
    current = validate_binding(read_json(path)) if path.exists() else None
    if current and current["definition"]["definition_id"] != definition_id:
        raise DefinitionError("binding_conflict", "binding id belongs to another definition")

    alias_set = {f"task-worker:{definition_id}", definition_id, *aliases}
    if not all(isinstance(value, str) and value.strip() for value in alias_set):
        raise DefinitionError("bad_binding", "aliases must be non-empty strings")
    for other_path in _binding_files(state_root):
        if other_path == path:
            continue
        other = validate_binding(read_json(other_path))
        overlap = alias_set & set(other["aliases"])
        if overlap:
            raise DefinitionError("binding_alias_conflict", f"aliases already bound: {sorted(overlap)}")

    providers = dict(current.get("providers", {})) if current else {}
    if provider is not None:
        provider_name = _safe_id(provider, "provider")
        if not isinstance(provider_data, dict):
            raise DefinitionError("bad_binding", "provider_data must be an object")
        providers[provider_name] = provider_data
    leases_by_id = {
        lease["lease_id"]: json.loads(json.dumps(lease))
        for lease in (current.get("review_leases", []) if current else [])
    }
    edge_to_id = {
        lease["edge_id"]: lease["lease_id"]
        for lease in leases_by_id.values()
    }
    for raw_lease in review_leases:
        lease = validate_review_lease(json.loads(json.dumps(raw_lease)))
        lease_id = lease["lease_id"]
        edge = lease["edge_id"]
        existing = leases_by_id.get(lease_id)
        if existing is not None and existing != lease:
            raise DefinitionError("review_lease_conflict", f"review lease id is already bound: {lease_id}")
        existing_id = edge_to_id.get(edge)
        if existing_id is not None and existing_id != lease_id:
            raise DefinitionError(
                "review_lease_conflict",
                f"review edge is already owned by lease {existing_id}: {edge}",
            )
        leases_by_id[lease_id] = lease
        edge_to_id[edge] = lease_id
    context_ref = current.get("context") if current else None
    if context is not None:
        packet = _context_packet(artifact, context, now=now)
        context_path = _state_path(state_root, "contexts") / definition_id / f"{packet['digest']}.json"
        if context_path.exists():
            existing_packet = read_json(context_path)
            if (
                existing_packet.get("schema") != CONTEXT_SCHEMA
                or existing_packet.get("digest") != packet["digest"]
                or existing_packet.get("facts") != packet["facts"]
            ):
                raise DefinitionError("context_digest_mismatch", f"context packet is corrupt: {context_path}")
        else:
            write_json_atomic(context_path, packet, immutable=True)
        context_ref = {"path": str(context_path.resolve()), "digest": packet["digest"]}
    work_graph_ref = current.get("work_graph") if current else None
    if work_graph is not None:
        graph = validate_work_graph(work_graph)
        graph_path = _state_path(state_root, "graphs") / definition_id / f"{graph['digest']}.json"
        write_json_atomic(graph_path, graph, immutable=True)
        work_graph_ref = {"path": str(graph_path.resolve()), "digest": graph["digest"]}

    timestamp = now or utc_now()
    binding = {
        "schema": BINDING_SCHEMA,
        "binding_id": binding_id,
        "definition": _run_pin(artifact),
        "artifact_path": str(Path(artifact_path).resolve()),
        "dispatch": artifact.get("dispatch", "worker"),
        "aliases": sorted(alias_set | set(current.get("aliases", []) if current else [])),
        "providers": providers,
        "review_leases": sorted(leases_by_id.values(), key=lambda value: value["lease_id"]),
        "context": context_ref,
        "work_graph": work_graph_ref,
        "created_at": current.get("created_at", timestamp) if current else timestamp,
        "updated_at": timestamp,
    }
    validate_binding(binding)
    if current is not None:
        current_semantic = {key: value for key, value in current.items() if key != "updated_at"}
        next_semantic = {key: value for key, value in binding.items() if key != "updated_at"}
        if current_semantic == next_semantic:
            return current, path, False
    changed = True
    if changed:
        write_json_atomic(path, binding)
    return binding, path, changed


def review_permit(
    ref: str,
    *,
    state_root: str | Path,
    episode_id: str,
    edge_id: str,
) -> dict[str, Any]:
    """Return the only allowed reviewer-dispatch action for one review edge."""
    episode = _safe_id(episode_id, "episode_id")
    edge = _safe_id(edge_id, "edge_id")
    binding, path = resolve_binding(ref, state_root)
    matches = [
        lease for lease in binding.get("review_leases", [])
        if lease["episode_id"] == episode and lease["edge_id"] == edge
    ]
    if len(matches) > 1:
        raise DefinitionError("review_lease_conflict", "multiple review leases own the same edge")
    if not matches:
        return {
            "schema": REVIEW_PERMIT_SCHEMA,
            "status": "local-policy",
            "action": "dispatch-or-human-gate",
            "dispatch_reviewer": True,
            "review_lease": None,
            "binding_path": str(path),
        }
    lease = validate_review_lease(matches[0])
    externally_owned = lease["owner"] == "studio"
    return {
        "schema": REVIEW_PERMIT_SCHEMA,
        "status": "externally-owned" if externally_owned else "task-worker-owned",
        "action": "skip" if externally_owned else "dispatch",
        "dispatch_reviewer": not externally_owned,
        "review_lease": lease,
        "handoff": lease if externally_owned else None,
        "binding_path": str(path),
    }


def resume_binding(ref: str, state_root: str | Path) -> dict[str, Any]:
    binding, binding_path = resolve_binding(ref, state_root)
    artifact = read_json(binding["artifact_path"])
    validate_artifact(artifact)
    validate_run_pin(artifact, binding["definition"])
    if artifact.get("dispatch", "worker") != binding["dispatch"]:
        raise DefinitionError("binding_pin_mismatch", "binding dispatch differs from artifact")
    context = None
    if binding.get("context"):
        context = read_json(binding["context"]["path"])
        if context.get("schema") != CONTEXT_SCHEMA or context.get("digest") != binding["context"]["digest"]:
            raise DefinitionError("context_digest_mismatch", "bound context packet is invalid")
        if stable_digest(context.get("facts")) != context["digest"]:
            raise DefinitionError("context_digest_mismatch", "context facts changed")
    if binding.get("work_graph"):
        graph = read_json(binding["work_graph"]["path"])
        if graph.get("digest") != binding["work_graph"]["digest"]:
            raise DefinitionError("work_graph_digest_mismatch", "bound work graph digest changed")
        plan = plan_work_graph(graph)
        plan["dispatch"] = binding["dispatch"]
        if binding["dispatch"] == "manual":
            plan["manual_actions"] = plan.pop("ready_actions")
            plan["ready_actions"] = []
    else:
        plan = ready_plan(artifact, _state_path(state_root, "runs"))
    return {
        "binding": binding,
        "binding_path": str(binding_path),
        "context": context,
        "plan": plan,
    }


def record_provider_event(
    ref: str,
    *,
    state_root: str | Path,
    provider: str,
    event: str,
    receipt: dict[str, Any] | None = None,
    now: str | None = None,
) -> tuple[dict[str, Any], Path, bool]:
    binding, path = resolve_binding(ref, state_root)
    provider_name = _safe_id(provider, "provider")
    if provider_name not in binding["providers"]:
        raise DefinitionError("provider_not_bound", f"provider is not bound: {provider_name}")
    event_name = _safe_id(event, "provider_event")
    if receipt is not None and not isinstance(receipt, dict):
        raise DefinitionError("bad_provider_receipt", "provider receipt must be an object")
    event_id = stable_digest({"provider": provider_name, "event": event_name, "receipt": receipt})
    updated = json.loads(json.dumps(binding))
    provider_state = updated["providers"][provider_name]
    events = provider_state.setdefault("events", [])
    if any(item.get("event_id") == event_id for item in events if isinstance(item, dict)):
        return binding, path, False
    timestamp = now or utc_now()
    events.append({
        "event_id": event_id,
        "event": event_name,
        "at": timestamp,
        "receipt": receipt,
    })
    provider_state["last_event"] = event_name
    updated["updated_at"] = timestamp
    validate_binding(updated)
    write_json_atomic(path, updated)
    return updated, path, True


def evidence_fingerprint(request: dict[str, Any]) -> str:
    identity = {
        key: _require_text(request.get(key), f"evidence.{key}")
        for key in ("head", "command_digest", "environment_digest", "tool_version")
    }
    identity["purpose"] = _require_text(request.get("purpose", "verification"), "evidence.purpose")
    fresh = request.get("fresh_requirement_id")
    if fresh is not None:
        identity["fresh_requirement_id"] = _require_text(fresh, "evidence.fresh_requirement_id")
    # definition/node/cycle/unit/target/profile identifiers remain attribution-only.
    return stable_digest(identity)


def evidence_plan(
    request: dict[str, Any], state_root: str | Path, *, max_physical_runs: int = 3
) -> dict[str, Any]:
    if not isinstance(max_physical_runs, int) or isinstance(max_physical_runs, bool) or max_physical_runs < 1:
        raise DefinitionError("bad_run_limit", "max_physical_runs must be positive")
    fingerprint = evidence_fingerprint(request)
    path = _state_path(state_root, "evidence") / f"{fingerprint}.json"
    if not path.exists():
        return {"execute": True, "duplicate_prevented": False, "fingerprint": fingerprint, "path": str(path)}
    evidence = read_json(path)
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("fingerprint") != fingerprint:
        raise DefinitionError("evidence_corrupt", f"invalid evidence file: {path}")
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list):
        raise DefinitionError("evidence_corrupt", "evidence attempts must be a list")
    successful = next((attempt for attempt in reversed(attempts) if attempt.get("result") == "pass"), None)
    if successful is not None:
        return {
            "execute": False,
            "duplicate_prevented": True,
            "reason": "successful_evidence_reused",
            "fingerprint": fingerprint,
            "path": str(path),
            "evidence": evidence,
        }
    if len(attempts) >= max_physical_runs:
        return {
            "execute": False,
            "duplicate_prevented": False,
            "reason": "physical_run_limit_reached",
            "owner_gate_required": True,
            "fingerprint": fingerprint,
            "path": str(path),
            "evidence": evidence,
        }
    return {"execute": True, "duplicate_prevented": False, "fingerprint": fingerprint, "path": str(path)}


def record_evidence(
    request: dict[str, Any],
    *,
    result: str,
    state_root: str | Path,
    output_digest: str | None = None,
    tokens: int | None = None,
    token_coverage: str | None = None,
    max_physical_runs: int = 3,
    require_token_coverage: bool = False,
    now: str | None = None,
) -> tuple[dict[str, Any], Path, bool]:
    if result not in {"pass", "fail"}:
        raise DefinitionError("bad_evidence_result", "evidence result must be pass or fail")
    plan = evidence_plan(request, state_root, max_physical_runs=max_physical_runs)
    path = Path(plan["path"])
    if plan.get("duplicate_prevented"):
        return plan["evidence"], path, True
    if plan.get("owner_gate_required"):
        raise DefinitionError("physical_run_limit_reached", "evidence run limit requires owner gate")
    if tokens is None:
        if require_token_coverage:
            raise DefinitionError("token_coverage_required", "token telemetry is required by task-worker config")
        coverage = token_coverage or "unavailable"
        if coverage != "unavailable":
            raise DefinitionError("bad_token_coverage", "tokens:null requires unavailable coverage")
    else:
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise DefinitionError("bad_tokens", "tokens must be non-negative")
        coverage = token_coverage or "exact"
        if coverage != "exact":
            raise DefinitionError("bad_token_coverage", "known tokens require exact coverage")
    evidence = read_json(path) if path.exists() else {
        "schema": EVIDENCE_SCHEMA,
        "evidence_id": f"ev-{plan['fingerprint'][:20]}",
        "fingerprint": plan["fingerprint"],
        "request": request,
        "attempts": [],
    }
    evidence["attempts"].append({
        "result": result,
        "output_digest": output_digest,
        "tokens": tokens,
        "token_coverage": coverage,
        "performed_at": now or utc_now(),
    })
    write_json_atomic(path, evidence)
    return evidence, path, False


def token_coverage_required(config_path: str | Path) -> bool:
    path = Path(config_path)
    if not path.is_file():
        return False
    script = Path(__file__).with_name("task_config.py")
    spec = importlib.util.spec_from_file_location("task_worker_runtime_config", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    config = module.load_config(path)
    errors = [item for item in module.validate_config(config) if item.get("severity") == "error"]
    if errors:
        raise DefinitionError("config_invalid", ",".join(item["code"] for item in errors))
    return bool((config.get("evidence") or {}).get("token-coverage-required", False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "revise"):
        command = sub.add_parser(name)
        command.add_argument("--spec", required=True)
        command.add_argument("--store", default=".task-worker/local/definitions")
        command.add_argument("--previous", required=name == "revise")
        command.add_argument("--delivery", choices=sorted(DELIVERY_MODES))
    validate = sub.add_parser("validate")
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--previous")
    export = sub.add_parser("export")
    export.add_argument("--artifact", required=True)
    store = sub.add_parser("store")
    store.add_argument("--artifact", required=True)
    store.add_argument("--store", default=".task-worker/local/definitions")
    graph = sub.add_parser("plan-graph")
    graph.add_argument("--snapshot", required=True)
    sub.add_parser("capabilities")
    ready = sub.add_parser("ready")
    ready.add_argument("--artifact", required=True)
    ready.add_argument("--state-dir", default=".task-worker/local/runs")
    local_start = sub.add_parser("local-start")
    local_start.add_argument("--artifact", required=True)
    local_start.add_argument("--node", required=True)
    local_start.add_argument("--state-dir", default=".task-worker/local/runs")
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
    receipt.add_argument("--config", default=".task-worker.yml")
    bind = sub.add_parser("bind")
    bind.add_argument("--artifact", required=True)
    bind.add_argument("--artifact-path", help="stored artifact path; defaults to --artifact")
    bind.add_argument("--state-root", default=".task-worker/local")
    bind.add_argument("--alias", action="append", default=[])
    bind.add_argument("--provider")
    bind.add_argument("--provider-data", help="JSON object path or '-' when --provider is set")
    bind.add_argument("--context", help="compact context JSON object path or '-'")
    bind.add_argument("--work-graph", help="provider-normalized task-worker.work-graph/v1 path or '-'")
    bind.add_argument(
        "--review-lease", action="append", default=[],
        help="workflow-review-lease/v1 JSON object path or '-'; repeat for multiple edges",
    )
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--ref", required=True)
    resolve.add_argument("--state-root", default=".task-worker/local")
    resume = sub.add_parser("resume")
    resume.add_argument("--ref", required=True)
    resume.add_argument("--state-root", default=".task-worker/local")
    review_permit_parser = sub.add_parser("review-permit")
    review_permit_parser.add_argument("--ref", required=True)
    review_permit_parser.add_argument("--episode-id", required=True)
    review_permit_parser.add_argument("--edge-id", required=True)
    review_permit_parser.add_argument("--state-root", default=".task-worker/local")
    evidence_check = sub.add_parser("evidence-plan")
    evidence_check.add_argument("--request", required=True)
    evidence_check.add_argument("--state-root", default=".task-worker/local")
    evidence_check.add_argument("--max-physical-runs", type=int, default=3)
    evidence_record = sub.add_parser("evidence-record")
    evidence_record.add_argument("--request", required=True)
    evidence_record.add_argument("--result", required=True, choices=("pass", "fail"))
    evidence_record.add_argument("--state-root", default=".task-worker/local")
    evidence_record.add_argument("--output-digest")
    evidence_record.add_argument("--tokens", type=int)
    evidence_record.add_argument("--token-coverage", choices=("exact", "unavailable"))
    evidence_record.add_argument("--max-physical-runs", type=int, default=3)
    evidence_record.add_argument("--config", default=".task-worker.yml")
    policy_plan = sub.add_parser("policy-plan")
    policy_plan.add_argument("--profiles", required=True)
    policy_plan.add_argument("--impact-rules", required=True)
    policy_plan.add_argument("--changed-path", action="append", required=True)
    policy_plan.add_argument("--qa-mode", required=True, choices=sorted(execution_control.QA_MODES))
    policy_plan.add_argument("--profile-id")
    policy_plan.add_argument("--argv", help="JSON argv array")
    policy_plan.add_argument("--cwd", required=True, help="repository-relative resolved cwd")
    policy_plan.add_argument("--environment", required=True, help="JSON resolved environment mapping")
    policy_plan.add_argument("--purpose")
    policy_plan.add_argument("--full-qa-reason", help="JSON machine-readable reason")
    execution_evaluate = sub.add_parser("execution-evaluate")
    execution_evaluate.add_argument("--request", required=True)
    execution_claim = sub.add_parser("execution-claim")
    execution_claim.add_argument("--permit", required=True)
    execution_claim.add_argument("--state-root", default=".task-worker/local")
    execution_claim.add_argument("--claimed-by", required=True)
    execution_claim.add_argument("--evidence")
    execution_claim.add_argument("--profiles", required=True)
    execution_claim.add_argument("--impact-rules", required=True)
    execution_claim.add_argument("--changed-path", action="append", required=True)
    execution_claim.add_argument("--argv", help="JSON argv array")
    execution_claim.add_argument("--cwd", required=True, help="repository-relative resolved cwd")
    execution_claim.add_argument("--environment", required=True, help="JSON resolved environment mapping")
    execution_claim.add_argument("--full-qa-reason", help="JSON machine-readable reason")
    execution_claim.add_argument("--authorization")
    execution_claim.add_argument("--preflight-receipt")
    execution_complete = sub.add_parser("execution-complete")
    execution_complete.add_argument("--permit", required=True)
    execution_complete.add_argument("--claim-id", required=True)
    execution_complete.add_argument("--receipt", required=True)
    execution_complete.add_argument("--evidence")
    execution_complete.add_argument("--mutation-receipt")
    execution_complete.add_argument("--state-root", default=".task-worker/local")
    execution_project = sub.add_parser("execution-project")
    execution_project.add_argument("--receipt", required=True)
    execution_project.add_argument("--evidence")
    spend_claim = sub.add_parser("spend-claim")
    spend_claim.add_argument("--authorization", required=True)
    spend_claim.add_argument("--mutation", required=True)
    spend_claim.add_argument("--preflight-receipt", required=True)
    spend_claim.add_argument("--state-root", default=".task-worker/local")
    mutation_record = sub.add_parser("mutation-record")
    mutation_record.add_argument("--consumption", required=True)
    mutation_record.add_argument("--receipt", required=True)
    mutation_record.add_argument("--state-root", default=".task-worker/local")
    capability_plan = sub.add_parser("capability-plan")
    capability_plan.add_argument("--mission-id", required=True)
    capability_plan.add_argument("--capability", action="append", required=True)
    capability_plan.add_argument("--environment-digest", required=True)
    capability_plan.add_argument("--state-root", default=".task-worker/local")
    capability_record = sub.add_parser("capability-record")
    capability_record.add_argument("--snapshot", required=True)
    capability_record.add_argument("--state-root", default=".task-worker/local")
    provider_event = sub.add_parser("provider-event")
    provider_event.add_argument("--ref", required=True)
    provider_event.add_argument("--provider", required=True)
    provider_event.add_argument("--event", required=True)
    provider_event.add_argument("--receipt", help="provider receipt JSON object path or '-'")
    provider_event.add_argument("--state-root", default=".task-worker/local")
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
        elif args.command == "store":
            artifact = read_json(args.artifact)
            path = store_artifact(args.store, artifact)
            payload = {"ok": True, "artifact": artifact, "path": str(path)}
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
                    "binding": BINDING_SCHEMA,
                    "context": CONTEXT_SCHEMA,
                    "evidence": EVIDENCE_SCHEMA,
                    "review_lease": REVIEW_LEASE_SCHEMA,
                    "review_permit": REVIEW_PERMIT_SCHEMA,
                    "verification_contract": execution_control.CONTRACT_SCHEMA,
                    "execution_permit": execution_control.PERMIT_SCHEMA,
                    "command_profile": execution_control.PROFILE_SCHEMA,
                    "command_receipt": execution_control.RECEIPT_SCHEMA,
                    "verification_evidence": execution_control.EVIDENCE_SCHEMA,
                },
                "commands": [
                    "create", "revise", "validate", "export", "store", "plan-graph", "ready",
                    "local-start", "local-event", "recover", "receipt", "capabilities",
                    "bind", "resolve", "resume", "evidence-plan", "evidence-record",
                    "provider-event", "review-permit",
                    "policy-plan", "execution-evaluate", "execution-claim",
                    "execution-complete", "execution-project",
                    "spend-claim", "mutation-record", "capability-plan", "capability-record",
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
        elif args.command == "receipt":
            receipt = build_receipt(
                read_json(args.run_state), workflow=args.workflow, tokens=args.tokens,
                token_coverage=args.token_coverage, counters=json.loads(args.counters), quality=json.loads(args.quality),
                require_token_coverage=token_coverage_required(args.config),
            )
            if args.out:
                write_json_atomic(args.out, receipt)
            payload = {"ok": True, "receipt": receipt, "path": args.out}
        elif args.command == "bind":
            artifact = read_json(args.artifact)
            provider_data = read_json(args.provider_data) if args.provider_data else None
            context = read_json(args.context) if args.context else None
            work_graph = read_json(args.work_graph) if args.work_graph else None
            review_leases = [read_json(path) for path in args.review_lease]
            binding, path, changed = upsert_binding(
                artifact,
                artifact_path=args.artifact_path or args.artifact,
                state_root=args.state_root,
                aliases=args.alias,
                provider=args.provider,
                provider_data=provider_data,
                context=context,
                work_graph=work_graph,
                review_leases=review_leases,
            )
            payload = {"ok": True, "changed": changed, "path": str(path), "binding": binding}
        elif args.command == "resolve":
            binding, path = resolve_binding(args.ref, args.state_root)
            payload = {"ok": True, "path": str(path), "binding": binding}
        elif args.command == "resume":
            payload = {"ok": True, "resume": resume_binding(args.ref, args.state_root)}
        elif args.command == "review-permit":
            payload = {
                "ok": True,
                "permit": review_permit(
                    args.ref,
                    state_root=args.state_root,
                    episode_id=args.episode_id,
                    edge_id=args.edge_id,
                ),
            }
        elif args.command == "evidence-plan":
            payload = {
                "ok": True,
                "plan": evidence_plan(
                    read_json(args.request), args.state_root,
                    max_physical_runs=args.max_physical_runs,
                ),
            }
        elif args.command == "evidence-record":
            evidence, path, reused = record_evidence(
                read_json(args.request),
                result=args.result,
                state_root=args.state_root,
                output_digest=args.output_digest,
                tokens=args.tokens,
                token_coverage=args.token_coverage,
                max_physical_runs=args.max_physical_runs,
                require_token_coverage=token_coverage_required(args.config),
            )
            payload = {"ok": True, "reused": reused, "path": str(path), "evidence": evidence}
        elif args.command == "policy-plan":
            contract = execution_control.load_contract()
            payload = {
                "ok": True,
                "plan": execution_control.select_execution(
                    profiles=execution_control.load_command_profiles(args.profiles, contract),
                    impact_rules=execution_control.load_impact_rules(args.impact_rules),
                    changed_paths=args.changed_path,
                    qa_mode=args.qa_mode,
                    profile_id=args.profile_id,
                    argv=json.loads(args.argv) if args.argv else None,
                    cwd=args.cwd,
                    environment=json.loads(args.environment),
                    purpose=args.purpose,
                    full_qa_reason=json.loads(args.full_qa_reason) if args.full_qa_reason else None,
                ),
            }
        elif args.command == "execution-evaluate":
            payload = {"ok": True, "decision": execution_control.evaluate_request(read_json(args.request))}
        elif args.command == "execution-claim":
            permit = read_json(args.permit)
            contract = execution_control.load_contract()
            policy_plan = execution_control.select_execution(
                profiles=execution_control.load_command_profiles(args.profiles, contract),
                impact_rules=execution_control.load_impact_rules(args.impact_rules),
                changed_paths=args.changed_path,
                qa_mode=permit.get("qa_mode"),
                profile_id=permit.get("command_profile_id"),
                argv=json.loads(args.argv) if args.argv else None,
                cwd=args.cwd,
                environment=json.loads(args.environment),
                purpose=permit.get("purpose"),
                full_qa_reason=json.loads(args.full_qa_reason) if args.full_qa_reason else None,
            )
            execution_control.validate_permit_policy(permit, policy_plan)
            capability_plan = execution_control.capability_plan(
                permit["mission_id"], permit["required_capabilities"],
                permit["environment_digest"], args.state_root,
            )
            if capability_plan["action"] != "dispatch":
                payload = {"ok": True, "decision": capability_plan}
            else:
                payload = {
                    "ok": True,
                    "decision": execution_control.claim_execution(
                        permit, args.state_root, claimed_by=args.claimed_by,
                        evidence=read_json(args.evidence) if args.evidence else None,
                        authorization=read_json(args.authorization) if args.authorization else None,
                        preflight_receipt=(
                            read_json(args.preflight_receipt) if args.preflight_receipt else None
                        ),
                        contract=contract,
                    ),
                }
        elif args.command == "execution-complete":
            payload = {
                "ok": True,
                "completion": execution_control.complete_execution(
                    read_json(args.permit), args.claim_id, read_json(args.receipt), args.state_root,
                    evidence=read_json(args.evidence) if args.evidence else None,
                    mutation_receipt=(
                        read_json(args.mutation_receipt) if args.mutation_receipt else None
                    ),
                ),
            }
        elif args.command == "execution-project":
            payload = {
                "ok": True,
                "projection": execution_control.project_receipts(
                    read_json(args.receipt), read_json(args.evidence) if args.evidence else None,
                ),
            }
        elif args.command == "spend-claim":
            payload = {
                "ok": True,
                "decision": execution_control.claim_spend_consumption(
                    read_json(args.authorization), read_json(args.mutation), args.state_root,
                    preflight_receipt=read_json(args.preflight_receipt),
                ),
            }
        elif args.command == "mutation-record":
            payload = {
                "ok": True,
                "status": execution_control.record_external_mutation(
                    read_json(args.consumption), read_json(args.receipt), args.state_root,
                ),
            }
        elif args.command == "capability-plan":
            payload = {
                "ok": True,
                "plan": execution_control.capability_plan(
                    args.mission_id, args.capability, args.environment_digest, args.state_root,
                ),
            }
        elif args.command == "capability-record":
            payload = {
                "ok": True,
                "cache": execution_control.record_capability_snapshot(
                    read_json(args.snapshot), args.state_root,
                ),
            }
        elif args.command == "provider-event":
            binding, path, changed = record_provider_event(
                args.ref,
                state_root=args.state_root,
                provider=args.provider,
                event=args.event,
                receipt=read_json(args.receipt) if args.receipt else None,
            )
            payload = {"ok": True, "changed": changed, "path": str(path), "binding": binding}
        else:  # pragma: no cover - argparse prevents this
            raise DefinitionError("unknown_command", f"unsupported command: {args.command}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error_code": "json_invalid", "message": str(exc)}, ensure_ascii=False))
        return 2
    except DefinitionError as exc:
        print(json.dumps({"ok": False, "error_code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    except execution_control.ExecutionControlError as exc:
        print(json.dumps({
            "ok": False, "error_code": exc.code, "message": exc.message, "detail": exc.detail,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
