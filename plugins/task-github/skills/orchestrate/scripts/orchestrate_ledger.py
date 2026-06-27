#!/usr/bin/env python3
"""Tiny persistent liveness ledger for task-github orchestrate pipeline ticks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ready_leaves import parse_number_set


def load_ledger(path: str | Path) -> dict[str, Any]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return {"version": 1, "spawned": [], "failed": []}
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "spawned": sorted(int(issue) for issue in payload.get("spawned", [])),
        "failed": sorted(int(issue) for issue in payload.get("failed", [])),
    }


def update_ledger(
    path: str | Path,
    *,
    spawned: set[int] | None = None,
    failed: set[int] | None = None,
    completed: set[int] | None = None,
) -> dict[str, Any]:
    payload = load_ledger(path)
    spawned_set = set(payload["spawned"]) | (spawned or set())
    failed_set = set(payload["failed"]) | (failed or set())
    completed_set = completed or set()
    spawned_set -= completed_set
    failed_set -= completed_set
    payload["spawned"] = sorted(spawned_set)
    payload["failed"] = sorted(failed_set)

    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="ledger JSON path, e.g. .task-github/orchestrate/1.json")
    parser.add_argument("--spawned", default="", help="comma/space-separated issues to mark active")
    parser.add_argument("--failed", default="", help="comma/space-separated issues to mark failed")
    parser.add_argument("--completed", default="", help="comma/space-separated issues to remove from active/failed")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        payload = update_ledger(
            args.path,
            spawned=parse_number_set(args.spawned),
            failed=parse_number_set(args.failed),
            completed=parse_number_set(args.completed),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False))
        return 1

    if args.as_json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
    else:
        print(",".join(str(issue) for issue in payload["spawned"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
