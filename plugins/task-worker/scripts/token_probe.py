#!/usr/bin/env python3
"""Observe token cost from Claude Code session JSONL. Observation only — never a gate.

probe: sum message.usage across a session's main JSONL plus expected subagent
JSONLs, de-duplicated by message uuid (the same usage block reappears on
consecutive lines and inside iterations[]). Any missing or unparsable target
file forbids a partial sum: tokens:null + token_coverage:"unavailable", exit 0.

aggregate: summarize measured coverage across an existing workflow-receipt/v1
store. Consumers pass probe output to `definition_artifact.py receipt --tokens`
or `session_review.py emit-receipt --tokens`; this module is an optional
resolver, never a hard dependency. Partial coverage keeps `tokens_total:null`;
the observed subset is exposed only as `measured_tokens_subtotal`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE = "claude-code-session-jsonl"
RECEIPT_SCHEMA = "workflow-receipt/v1"
SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")
USAGE_FIELDS = (
    ("input", "input_tokens"),
    ("output", "output_tokens"),
    ("cache_creation", "cache_creation_input_tokens"),
    ("cache_read", "cache_read_input_tokens"),
)


def _usage_from_file(path: Path) -> dict[str, int] | None:
    """Sum usage per breakdown key, de-duplicated by message uuid. None = unavailable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    totals = {key: 0 for key, _ in USAGE_FIELDS}
    seen: set[str] = set()
    counted = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(entry, dict):
            return None
        message = entry.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue  # non-usage line (user message, event) — fine
        uuid = entry.get("uuid")
        if not isinstance(uuid, str) or not uuid:
            return None  # usage without identity cannot be de-duplicated
        if uuid in seen:
            continue  # duplicate usage block — count once
        seen.add(uuid)
        for key, field in USAGE_FIELDS:
            value = usage.get(field, 0)  # absent cache field means 0, not missing data
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None
            totals[key] += value
        counted += 1
    if counted == 0:
        return None  # no usage observed: unavailable, not 0
    return totals


UNAVAILABLE = {
    "tokens": None,
    "token_coverage": "unavailable",
    "source": SOURCE,
    "breakdown": None,
    "agents": [],
}


def probe(session_id: str, agent_ids: list[str], projects_root: Path) -> dict:
    if not SAFE_ID.fullmatch(session_id) or not all(SAFE_ID.fullmatch(a) for a in agent_ids):
        return dict(UNAVAILABLE)
    matches = sorted(projects_root.glob(f"*/{session_id}.jsonl")) if projects_root.is_dir() else []
    if not matches:
        return dict(UNAVAILABLE)  # Codex host / absent path degrade the same way
    main_path = matches[0]
    totals = _usage_from_file(main_path)
    if totals is None:
        return dict(UNAVAILABLE)
    agents = []
    subagent_dir = main_path.parent / session_id / "subagents"
    for agent_id in agent_ids:
        name = agent_id if agent_id.startswith("agent-") else f"agent-{agent_id}"
        usage = _usage_from_file(subagent_dir / f"{name}.jsonl")
        if usage is None:
            return dict(UNAVAILABLE)  # one missing expected file forbids a partial sum
        agents.append({"agent_id": agent_id, "tokens": sum(usage.values())})
        for key in totals:
            totals[key] += usage[key]
    return {
        "tokens": sum(totals.values()),
        "token_coverage": "exact",
        "source": SOURCE,
        "breakdown": totals,
        "agents": agents,
    }


def _stats(values: list[int | None]) -> dict:
    runs = len(values)
    measured = [v for v in values if v is not None]
    complete = bool(runs) and len(measured) == runs
    return {
        "runs": runs,
        "measured_runs": len(measured),
        "coverage_ratio": (len(measured) / runs) if runs else 0.0,
        "tokens_total": sum(measured) if complete else None,
        "measured_tokens_subtotal": sum(measured) if measured else None,
    }


def aggregate(receipts_dir: Path) -> dict:
    by_workflow: dict[str, list[int | None]] = {}
    total: list[int | None] = []
    paths = sorted(receipts_dir.glob("*.json")) if receipts_dir.is_dir() else []
    for path in paths:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # not a receipt — aggregate summarizes, it does not validate
        if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
            continue
        tokens = receipt.get("tokens")
        value = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None
        workflow = receipt.get("workflow")
        key = workflow if isinstance(workflow, str) and workflow else "unknown"
        total.append(value)
        by_workflow.setdefault(key, []).append(value)
    return {
        **_stats(total),
        "by_workflow": {wf: _stats(vals) for wf, vals in sorted(by_workflow.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="token_probe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_probe = sub.add_parser("probe", help="sum session token usage from Claude Code JSONL")
    p_probe.add_argument("--session-id", required=True)
    p_probe.add_argument("--agent-id", action="append", default=[],
                         help="expected subagent id (repeatable); a missing one yields tokens:null")
    p_probe.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"))
    p_probe.add_argument("--json", action="store_true", help="accepted for parity; output is always JSON")
    p_agg = sub.add_parser("aggregate", help="summarize token coverage across a receipt store")
    p_agg.add_argument("--receipts", default=".task-worker/local/receipts")
    p_agg.add_argument("--json", action="store_true", help="accepted for parity; output is always JSON")
    args = parser.parse_args(argv)
    if args.command == "probe":
        result = probe(args.session_id, args.agent_id, Path(args.projects_root))
    else:
        result = aggregate(Path(args.receipts))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0  # numbers never fail the caller — observation, not a gate


if __name__ == "__main__":
    sys.exit(main())
