#!/usr/bin/env python3
"""Aggregate read-only plugin state for one workspace after session hopping.

cockpit answers "where was I?" with one command. It reads each plugin's
public read-only surface and never writes anything; it is a status board,
not a gate, so it always exits 0 (argparse usage errors exit 2).

Fixed sources (deliberately not configurable — issue #85):

    task-worker      definition_artifact.py resume per local binding    live
    session-review   session_review.py snapshot-dir + status per file   live
    task-github      .task-github/orchestrate/*.json direct read        local-projection
    studio           mission_receipt.py show                            live

A missing script or empty local state is state:absent (graceful skip).
A failing adapter is state:error with a fixed machine reason code; raw
stderr prose is never parsed or stored.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "studio.cockpit/v1"
ADAPTER_TIMEOUT_SECONDS = 30
# Fixed machine reason codes — never free-form prose.
REASON_EXIT_NONZERO = "exit_nonzero"
REASON_INVALID_JSON = "invalid_json"
REASON_READ_FAILED = "read_failed"
REASON_TIMEOUT = "timeout"
REASON_ADAPTER_FAILED = "adapter_failed"


class AdapterError(Exception):
    """An adapter failure carrying only a fixed machine reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _studio_root() -> Path:
    env = os.environ.get("STUDIO_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[1]


def _sibling_root(env_var: str, name: str) -> Path:
    env = os.environ.get(env_var)
    return Path(env) if env else _studio_root().parent / name


def _run_json(script: Path, args: list[str], cwd: Path) -> dict[str, Any]:
    """Run one adapter CLI and parse its single JSON payload from stdout."""
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=ADAPTER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise AdapterError(REASON_TIMEOUT) from error
    if proc.returncode != 0:
        raise AdapterError(REASON_EXIT_NONZERO)
    try:
        payload = json.loads(proc.stdout.strip())
    except (json.JSONDecodeError, ValueError) as error:
        raise AdapterError(REASON_INVALID_JSON) from error
    if not isinstance(payload, dict):
        raise AdapterError(REASON_INVALID_JSON)
    return payload


def _read_json_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise AdapterError(REASON_READ_FAILED) from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise AdapterError(REASON_INVALID_JSON) from error


def _scan_task_worker(root: Path) -> tuple[str, Any, list[dict[str, Any]]]:
    script = _sibling_root("TASK_WORKER_ROOT", "task-worker") / "scripts" / "definition_artifact.py"
    bindings_dir = root / ".task-worker" / "local" / "bindings"
    binding_paths = sorted(bindings_dir.glob("*.json")) if bindings_dir.is_dir() else []
    if not script.is_file() or not binding_paths:
        return "absent", None, []
    rows: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    for path in binding_paths:
        binding = _read_json_file(path)
        if not isinstance(binding, dict) or not isinstance(binding.get("binding_id"), str):
            raise AdapterError(REASON_INVALID_JSON)
        ref = binding["binding_id"]
        aliases = binding.get("aliases")
        alias = aliases[0] if isinstance(aliases, list) and aliases else ref
        payload = _run_json(
            script,
            ["resume", "--ref", ref, "--state-root", str(root / ".task-worker" / "local")],
            cwd=root,
        )
        plan = (payload.get("resume") or {}).get("plan") or {}
        ready = len(plan.get("ready_actions") or []) + len(plan.get("manual_actions") or [])
        rows.append({"alias": alias, "dispatch": binding.get("dispatch"), "ready": ready})
        if ready:
            next_actions.append(
                {"source": "task-worker", "action": "task-worker:orchestrate", "ref": alias}
            )
    return "present", {"bindings": rows}, next_actions


SNAPSHOT_INDEX_FILES = {"snapshot.md", "snapshot.index.md"}  # wiki / context-core area indexes


def _run_line(script: Path, args: list[str], cwd: Path) -> str:
    """Run one adapter CLI that prints a single plain line (not JSON)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=ADAPTER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise AdapterError(REASON_TIMEOUT) from error
    if proc.returncode != 0 or not proc.stdout.strip():
        raise AdapterError(REASON_EXIT_NONZERO)
    return proc.stdout.strip().splitlines()[0]


def _scan_session_review(root: Path) -> tuple[str, Any, list[dict[str, Any]]]:
    script = _sibling_root("SESSION_REVIEW_ROOT", "session-review") / "scripts" / "session_review.py"
    if not script.is_file():
        return "absent", None, []
    # Ask session-review where its snapshots live — the workspace's
    # .session-review.yml decides the provider (wiki vault vs context/snapshot),
    # so cockpit never assumes the wiki layout.
    snapshot_dir = root / _run_line(script, ["snapshot-dir"], cwd=root)
    snapshot_paths = (
        sorted(p for p in snapshot_dir.glob("*.md") if p.name not in SNAPSHOT_INDEX_FILES)
        if snapshot_dir.is_dir()
        else []
    )
    if not snapshot_paths:
        return "absent", None, []
    rows: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    for path in snapshot_paths:
        # builtin/wiki-markdown store SNAP-<slug>.md; context-core stores <slug>.md.
        slug = path.stem[len("SNAP-"):] if path.stem.startswith("SNAP-") else path.stem
        try:
            payload = _run_json(script, ["status", "--slug", slug], cwd=root)
        except AdapterError as error:
            if error.code == REASON_TIMEOUT:
                raise
            continue  # snapshot without a review status block (e.g. a pause SNAP) — not an episode
        status = payload.get("status") or {}
        phase = status.get("phase")
        next_actor = status.get("next_actor")
        rows.append(
            {"slug": slug, "phase": phase, "round": status.get("round"), "next_actor": next_actor}
        )
        if phase == "approved":
            action = "session-review:complete"
        elif next_actor == "worker":
            action = "session-review:address-feedback"
        else:
            action = "session-review:review"
        next_actions.append({"source": "session-review", "action": action, "ref": slug})
    if not rows:
        return "absent", None, []  # only non-review snapshots in the provider dir
    return "present", {"snapshots": rows}, next_actions


def _scan_task_github(root: Path) -> tuple[str, Any, list[dict[str, Any]]]:
    ledger_dir = root / ".task-github" / "orchestrate"
    paths = sorted(ledger_dir.glob("*.json")) if ledger_dir.is_dir() else []
    rows: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    for path in paths:
        data = _read_json_file(path)
        if not isinstance(data, dict) or "root" not in data or "issues" not in data:
            continue  # auxiliary JSON in the ledger dir, not an orchestrate ledger
        root_number = data["root"]
        issues = data["issues"] if isinstance(data["issues"], dict) else {}
        leaves = [
            item
            for item in issues.values()
            if isinstance(item, dict) and item.get("number") != root_number
        ]
        open_leaves = sum(1 for item in leaves if item.get("state") == "OPEN")
        root_issue = issues.get(str(root_number)) or {}
        rows.append(
            {
                "root": root_number,
                "title": root_issue.get("title"),
                "open_leaves": open_leaves,
                "closed_leaves": len(leaves) - open_leaves,
                "snapshot_at": data.get("snapshot_at"),
            }
        )
        if open_leaves:
            next_actions.append(
                {
                    "source": "task-github",
                    "action": "task-github:orchestrate",
                    "ref": f"#{root_number}",
                }
            )
    if not rows:
        return "absent", None, []
    return "present", {"ledgers": rows}, next_actions


def _scan_studio(root: Path) -> tuple[str, Any, list[dict[str, Any]]]:
    script = _studio_root() / "scripts" / "mission_receipt.py"
    if not script.is_file():
        return "absent", None, []  # RECEIPT unit not shipped/installed — not an error
    payload = _run_json(script, ["show"], cwd=root)
    # ponytail: receipt schema belongs to the RECEIPT unit (#83) — pass the
    # parsed object through; map next actions once its fields are pinned.
    return "present", payload, []


ADAPTERS: tuple[tuple[str, str, Any], ...] = (
    ("task-worker", "live", _scan_task_worker),
    ("session-review", "live", _scan_session_review),
    ("task-github", "local-projection", _scan_task_github),
    ("studio", "live", _scan_studio),
)


def collect(root: Path) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    for name, authority, scan in ADAPTERS:
        reason = None
        try:
            state, summary, actions = scan(root)
        except AdapterError as error:
            state, summary, actions = "error", None, []
            reason = error.code
        except Exception:  # ponytail: invariant guard — cockpit must always exit 0
            state, summary, actions = "error", None, []
            reason = REASON_ADAPTER_FAILED
        sources.append(
            {
                "source": name,
                "state": state,
                "authority": authority,
                "summary": summary,
                "reason": reason,
            }
        )
        next_actions.extend(actions)
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "sources": sources,
        "next": next_actions,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [f"cockpit @ {report['generated_at']}"]
    for source in report["sources"]:
        head = f"{source['source']}: {source['state']} ({source['authority']})"
        if source["state"] == "error":
            head += f" reason={source['reason']}"
        elif source["summary"] is not None:
            head += " " + json.dumps(source["summary"], ensure_ascii=False, sort_keys=True)
        lines.append(head)
    if report["next"]:
        lines.append("next:")
        lines.extend(
            f"  {item['source']}: {item['action']} — {item['ref']}" for item in report["next"]
        )
    else:
        lines.append("next: (none)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read-only studio status cockpit")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="aggregate read-only state of the fixed sources")
    status.add_argument(
        "--config",
        default=".studio.yml",
        help="workspace anchor; every source is read relative to its directory",
    )
    status.add_argument("--json", action="store_true", help="emit the machine payload")
    args = parser.parse_args(argv)
    root = Path(args.config).expanduser().resolve().parent
    report = collect(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
