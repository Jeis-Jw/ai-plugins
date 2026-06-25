#!/usr/bin/env python3
"""Diagnose task-github prerequisites and bridge integrity without mutation."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _finding(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def diagnose(snapshot: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    prereq = snapshot.get("prereq") or {}
    labels = prereq.get("labels") or {}
    missing_labels = labels.get("missing") or []
    if missing_labels:
        findings.append(_finding("missing_labels", "required labels are missing", "error"))
    if (prereq.get("gh_auth") or {}).get("ok") is False:
        findings.append(_finding("gh_auth_failed", "GitHub authentication is unavailable", "error"))
    if (prereq.get("dependency_api") or {}).get("ok") is False:
        findings.append(_finding("dependency_api_unavailable", "GitHub dependency API is unavailable"))
    if prereq.get("worktrees_ignored") is False:
        findings.append(_finding("worktrees_not_ignored", ".worktrees/ is not ignored"))
    if prereq.get("nested_repo_guard") is False:
        findings.append(_finding("nested_repo_guard_failed", "nested repository boundary is unclear", "error"))

    bundle = snapshot.get("context_bundle") or {}
    for item in (bundle.get("integrity") or {}).get("errors") or []:
        findings.append(_finding(str(item.get("code")), str(item.get("message") or item.get("code")), "error"))
    for item in (bundle.get("integrity") or {}).get("warnings") or []:
        findings.append(_finding(str(item.get("code")), str(item.get("message") or item.get("code"))))

    return {
        "ok": not any(item["severity"] == "error" for item in findings),
        "mutation_allowed": False,
        "findings": findings,
    }


def _read_json(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="doctor snapshot JSON path, or '-'")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fix", action="store_true", help="reserved explicit mutation alias; use reconcile --apply")
    args = parser.parse_args(argv)
    result = diagnose(_read_json(args.input))
    if args.fix:
        result["fix_hint"] = "Use reconcile.py --apply with the same context bundle; doctor default is diagnose-only."
    print(json.dumps(result, ensure_ascii=False) if args.as_json else result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
