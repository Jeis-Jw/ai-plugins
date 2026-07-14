#!/usr/bin/env python3
"""GitHub projection state for task-worker DefinitionArtifact revisions."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import task_worker_bridge


PROJECTION_SCHEMA = "task-github.github-projection/v2"
LEGACY_PROJECTION_SCHEMAS = {"task-github.github-projection/v1"}
_VALIDATED_ARTIFACTS: set[str] = set()


class DefinitionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _bridge(call, *args):
    try:
        return call(*args)
    except task_worker_bridge.TaskWorkerBridgeError as exc:
        raise DefinitionError(exc.code, exc.message) from exc


def validate_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    key = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if key not in _VALIDATED_ARTIFACTS:
        _bridge(task_worker_bridge.validate_artifact, artifact)
        _VALIDATED_ARTIFACTS.add(key)
    return artifact


def artifact_to_issue_spec(artifact: dict[str, Any]) -> dict[str, Any]:
    spec = _bridge(task_worker_bridge.export_artifact, artifact)
    key = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _VALIDATED_ARTIFACTS.add(key)
    return spec


def projection_requirements(artifact: dict[str, Any]) -> dict[str, list[str]]:
    validate_artifact(artifact)
    nodes = [artifact["root"]["node_id"], *[child["node_id"] for child in artifact["children"]]]
    dependencies = [
        f"{child['node_id']}>{blocker_id}"
        for child in artifact["children"]
        for blocker_id in child.get("blocked_by_node_ids", [])
    ]
    return {"nodes": sorted(nodes), "dependencies": sorted(dependencies)}


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
        state.get("schema") in {PROJECTION_SCHEMA, *LEGACY_PROJECTION_SCHEMAS}
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


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target
