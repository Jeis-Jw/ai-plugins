#!/usr/bin/env python3
"""Plan or apply explicit task-github bridge reconciliation actions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def _task_id(bundle: dict[str, Any]) -> str | None:
    task = bundle.get("wiki_task")
    if isinstance(task, dict):
        value = task.get("id")
        return str(value) if value else None
    return None


def plan_actions(bundle: dict[str, Any], *, wiki_cmd: str = "wiki") -> list[dict[str, Any]]:
    task_id = _task_id(bundle)
    root = bundle.get("root") or {}
    owner = bundle.get("owner")
    repo = bundle.get("repo")
    root_number = root.get("number")
    root_ref = f"{owner}/{repo}#{root_number}" if owner and repo and root_number is not None else None
    actions: list[dict[str, Any]] = []
    for error in (bundle.get("integrity") or {}).get("errors") or []:
        code = error.get("code")
        if code == "task_relation_missing_root" and task_id and root_ref:
            actions.append({
                "code": code,
                "argv": [wiki_cmd, "relate", task_id, "--add-tasks", root_ref],
            })
        elif code == "root_closed_task_active" and task_id:
            actions.append({"code": code, "argv": [wiki_cmd, "complete", task_id]})
        elif code == "root_open_task_done" and task_id:
            actions.append({"code": code, "argv": [wiki_cmd, "reopen", task_id]})
        else:
            actions.append({"code": str(code), "manual": True})
    return actions


def apply_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for action in actions:
        argv = action.get("argv")
        if not argv:
            results.append({"action": action, "skipped": True, "returncode": 1})
            continue
        result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        results.append({
            "action": action,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })
        if result.returncode != 0:
            break
    return results


def reconcile(bundle: dict[str, Any], *, apply: bool, wiki_cmd: str = "wiki") -> dict[str, Any]:
    actions = plan_actions(bundle, wiki_cmd=wiki_cmd)
    result = {
        "ok": not any(action.get("manual") for action in actions),
        "applied": False,
        "actions": actions,
    }
    if apply:
        applied = apply_actions(actions)
        result["applied"] = True
        result["results"] = applied
        result["ok"] = all(item.get("returncode", 1) == 0 for item in applied)
    return result


def _read_json(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="context bundle JSON path, or '-'")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wiki-cmd", default="wiki")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    result = reconcile(_read_json(args.bundle), apply=args.apply, wiki_cmd=args.wiki_cmd)
    print(json.dumps(result, ensure_ascii=False) if args.as_json else result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
