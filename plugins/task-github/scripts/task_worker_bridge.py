#!/usr/bin/env python3
"""Resolve and invoke task-worker through its versioned JSON CLI contract."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CONTRACTS = {
    "definition": "task-worker.definition/v1",
    "local_run": "task-worker.local-run/v1",
    "work_graph": "task-worker.work-graph/v1",
    "ready_plan": "task-worker.ready-plan/v1",
    "receipt": "workflow-receipt/v1",
    "binding": "task-worker.provider-binding/v1",
    "context": "task-worker.context-packet/v1",
    "evidence": "task-worker.verification-evidence/v1",
}
REQUIRED_COMMANDS = {
    "create", "revise", "validate", "export", "store", "plan-graph", "ready",
    "local-start", "local-event", "recover", "receipt", "capabilities",
    "bind", "resolve", "resume", "evidence-plan", "evidence-record",
    "provider-event",
}
_RESOLUTION_CACHE: dict[tuple[str | None, str], tuple[Path, dict[str, Any]]] = {}


class TaskWorkerBridgeError(Exception):
    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _script(root: Path) -> Path:
    return root / "scripts" / "definition_artifact.py"


def _version_key(path: Path) -> tuple[int, int, int, str]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", path.name)
    if match:
        return (*map(int, match.groups()), path.name)
    return (0, 0, 0, path.name)


def _candidate_roots() -> list[Path]:
    explicit = os.environ.get("TASK_WORKER_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not _script(root).is_file():
            raise TaskWorkerBridgeError(
                "task_worker_missing",
                f"TASK_WORKER_ROOT does not contain task-worker: {root}",
            )
        return [root]

    candidates: list[Path] = []
    # Source checkout / vendored marketplace layout.
    candidates.append(PLUGIN_ROOT.parent / "task-worker")
    # Cache layout: <marketplace>/<plugin>/<version>. Search only nearby
    # ancestors; never scan the user's full plugin cache.
    for ancestor in list(PLUGIN_ROOT.parents)[:4]:
        base = ancestor / "task-worker"
        candidates.append(base)
        if base.is_dir() and not _script(base).is_file():
            candidates.extend(sorted(base.iterdir(), key=_version_key, reverse=True))

    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen and _script(resolved).is_file():
            seen.add(resolved)
            result.append(resolved)
    return result


def _invoke(root: Path, args: Iterable[str], *, input_value: dict[str, Any] | None = None) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(_script(root)), *list(args)],
        input=None if input_value is None else json.dumps(input_value, ensure_ascii=False),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TaskWorkerBridgeError(
            "task_worker_invalid_output",
            result.stderr.strip() or result.stdout.strip() or "task-worker returned no JSON",
        ) from exc
    if result.returncode != 0 or payload.get("ok") is not True:
        raise TaskWorkerBridgeError(
            str(payload.get("error_code") or "task_worker_failed"),
            str(payload.get("message") or result.stderr.strip() or "task-worker command failed"),
            detail=payload,
        )
    return payload


def capabilities(root: Path) -> dict[str, Any]:
    payload = _invoke(root, ["capabilities"])
    contracts = payload.get("contracts")
    commands = set(payload.get("commands") or [])
    problems = []
    if payload.get("plugin") != "task-worker":
        problems.append("plugin identity")
    if not isinstance(contracts, dict):
        problems.append("contracts")
    else:
        for name, expected in REQUIRED_CONTRACTS.items():
            if contracts.get(name) != expected:
                problems.append(f"{name}={contracts.get(name)!r}, expected {expected!r}")
    missing_commands = sorted(REQUIRED_COMMANDS - commands)
    if missing_commands:
        problems.append(f"commands={missing_commands}")
    if problems:
        raise TaskWorkerBridgeError(
            "task_worker_contract_mismatch",
            "incompatible task-worker: " + "; ".join(problems),
            detail=payload,
        )
    return payload


def resolve_task_worker_root() -> tuple[Path, dict[str, Any]]:
    cache_key = (os.environ.get("TASK_WORKER_ROOT"), str(PLUGIN_ROOT.resolve()))
    if cache_key in _RESOLUTION_CACHE:
        return _RESOLUTION_CACHE[cache_key]
    candidates = _candidate_roots()
    if not candidates:
        raise TaskWorkerBridgeError(
            "task_worker_missing",
            "task-worker is required; install it beside task-github or set TASK_WORKER_ROOT",
        )
    errors = []
    for root in candidates:
        try:
            resolved = (root, capabilities(root))
            _RESOLUTION_CACHE[cache_key] = resolved
            return resolved
        except TaskWorkerBridgeError as exc:
            errors.append(f"{root}: {exc.message}")
    raise TaskWorkerBridgeError("task_worker_contract_mismatch", " | ".join(errors))


def call_worker(args: Iterable[str], *, input_value: dict[str, Any] | None = None) -> dict[str, Any]:
    root, _ = resolve_task_worker_root()
    return _invoke(root, args, input_value=input_value)


def validate_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    call_worker(["validate", "--artifact", "-"], input_value=artifact)
    return artifact


def export_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return call_worker(["export", "--artifact", "-"], input_value=artifact)["spec"]


def plan_graph(snapshot: dict[str, Any]) -> dict[str, Any]:
    return call_worker(["plan-graph", "--snapshot", "-"], input_value=snapshot)["plan"]


def bind_artifact(
    artifact_path: str | Path,
    *,
    state_root: str | Path,
    aliases: Iterable[str] = (),
    provider: str | None = None,
    provider_data_path: str | Path | None = None,
    context_path: str | Path | None = None,
    work_graph_path: str | Path | None = None,
) -> dict[str, Any]:
    args = [
        "bind", "--artifact", str(artifact_path), "--artifact-path", str(artifact_path),
        "--state-root", str(state_root),
    ]
    for alias in aliases:
        args.extend(["--alias", alias])
    if provider:
        args.extend(["--provider", provider])
        if provider_data_path is None:
            raise TaskWorkerBridgeError("provider_data_required", "provider_data_path is required")
        args.extend(["--provider-data", str(provider_data_path)])
    if context_path is not None:
        args.extend(["--context", str(context_path)])
    if work_graph_path is not None:
        args.extend(["--work-graph", str(work_graph_path)])
    return call_worker(args)["binding"]


def resume(ref: str, *, state_root: str | Path) -> dict[str, Any]:
    return call_worker(["resume", "--ref", ref, "--state-root", str(state_root)])["resume"]


def forward_cli(argv: list[str]) -> int:
    root, capability_payload = resolve_task_worker_root()
    if argv == ["preflight"]:
        print(json.dumps({"ok": True, "root": str(root), "capabilities": capability_payload}, ensure_ascii=False))
        return 0
    return subprocess.run([sys.executable, str(_script(root)), *argv]).returncode


def main(argv: list[str] | None = None) -> int:
    try:
        return forward_cli(list(sys.argv[1:] if argv is None else argv))
    except TaskWorkerBridgeError as exc:
        print(json.dumps({
            "ok": False,
            "error_code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        }, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
