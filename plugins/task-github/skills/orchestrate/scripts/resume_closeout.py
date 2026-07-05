#!/usr/bin/env python3
"""Requeue one failed/stalled orchestrate closeout from ledger evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from orchestrate_ledger import load_ledger, record_event


def _issue(payload: dict[str, Any], issue: int) -> dict[str, Any]:
    try:
        return dict((payload.get("issues") or {})[str(int(issue))])
    except KeyError as exc:
        raise ValueError(f"ledger has no issue #{issue}") from exc


def resume(path: str | Path, issue: int) -> dict[str, Any]:
    payload = load_ledger(path)
    item = _issue(payload, issue)
    source = (
        item.get("ready_for_closeout")
        or item.get("closeout_failed")
        or item.get("closeout_started")
        or {}
    )
    if item.get("state") not in {"closeout_failed", "closeout_started", "closeout_ready"}:
        raise ValueError(f"issue #{issue} is not a resumable closeout state: {item.get('state')}")
    base = source.get("base")
    head = source.get("head") or f"task/issue-{issue}"
    if not base:
        raise ValueError(f"issue #{issue} has no closeout base in ledger")
    event = {
        "type": "ready_for_pr_closeout" if source.get("mode") == "pr" else "ready_for_closeout",
        "issue": int(issue),
        "base": base,
        "head": head,
    }
    for key in ("head_sha", "gear", "review_skipped", "pr"):
        if source.get(key) is not None:
            event[key] = source[key]
    payload = record_event(path, event)
    return {
        "ok": True,
        "issue": int(issue),
        "base": base,
        "head": head,
        "state": payload["issues"][str(int(issue))]["state"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger")
    parser.add_argument("issue", type=int)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        payload = resume(args.ledger, args.issue)
    except Exception as exc:
        payload = {"ok": False, "message": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if args.as_json else f"error: {exc}")
        return 1
    print(json.dumps(payload, ensure_ascii=False) if args.as_json else f"requeued #{payload['issue']} -> {payload['base']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
