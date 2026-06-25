#!/usr/bin/env python3
"""Build task-github status and exactly one next action from a context bundle."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


STATE_LABELS = {"in-progress", "in-review", "changes-requested"}


def _labels(bundle: dict[str, Any]) -> set[str]:
    labels = bundle.get("issue", {}).get("labels") or []
    return {str(label) for label in labels}


def _open_blockers(bundle: dict[str, Any]) -> list[dict]:
    return [
        blocker for blocker in bundle.get("blockers", [])
        if str(blocker.get("state") or "").upper() != "CLOSED"
    ]


def choose_next_action(bundle: dict[str, Any]) -> dict[str, Any]:
    issue = bundle.get("issue") or {}
    issue_number = issue.get("number")
    errors = bundle.get("integrity", {}).get("errors") or []
    if errors:
        return {"kind": "reconcile", "reason": errors[0].get("code")}

    blockers = _open_blockers(bundle)
    if blockers:
        return {"kind": "wait", "issue": issue_number, "blocked_by": blockers}

    labels = _labels(bundle)
    if "changes-requested" in labels:
        return {"kind": "run", "issue": issue_number, "reason": "changes-requested"}
    if "in-review" in labels:
        return {"kind": "review", "issue": issue_number}
    if "in-progress" in labels:
        return {"kind": "continue", "issue": issue_number}

    if str(issue.get("state") or "").upper() == "OPEN":
        return {"kind": "start", "issue": issue_number}
    return {"kind": "none", "reason": "issue is not open"}


def build_status(bundle: dict[str, Any]) -> dict[str, Any]:
    labels = _labels(bundle)
    blockers = _open_blockers(bundle)
    errors = bundle.get("integrity", {}).get("errors") or []
    return {
        "ok": not errors,
        "issue": bundle.get("issue"),
        "root": bundle.get("root"),
        "mode": {"topology": bundle.get("topology"), "gate": bundle.get("gate")},
        "ready": not blockers and not errors and "in-review" not in labels,
        "blocked": blockers,
        "review_needed": "in-review" in labels,
        "bridge_mismatch": errors,
        "closeout_pending": "in-review" in labels and not errors,
        "worktree_path": bundle.get("worktree_path"),
        "next_action": choose_next_action(bundle),
    }


def _read_json(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="context bundle JSON path, or '-'")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    status = build_status(_read_json(args.bundle))
    print(json.dumps(status, ensure_ascii=False) if args.as_json else status["next_action"])
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
