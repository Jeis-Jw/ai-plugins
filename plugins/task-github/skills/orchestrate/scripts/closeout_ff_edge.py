#!/usr/bin/env python3
"""One-shot FF closeout for an orchestrate review-free merge edge."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import orchestrate_ledger
from orchestrator_ops import ff_merge_command


class CloseoutFFError(Exception):
    def __init__(self, stage: str, message: str, **details: Any):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.details = details


def _run(cmd: list[str], *, cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _checked(cmd: list[str], *, stage: str, cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    result = _run(cmd, cwd=cwd)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"{cmd[0]} failed"
        raise CloseoutFFError(stage, message, cmd=cmd)
    return result


def _git(args: list[str], *, stage: str, cwd: str | Path | None = None) -> str:
    return _checked(["git", *args], stage=stage, cwd=cwd).stdout.strip()


def _issue_close_failed_ok(message: str) -> bool:
    text = message.lower()
    return "already closed" in text or "not open" in text


def _record_failure(ledger: str, *, issue: int, parent: str, child: str, stage: str, message: str) -> None:
    orchestrate_ledger.record_event(
        ledger,
        {
            "type": "closeout_failed",
            "issue": issue,
            "base": parent,
            "head": child,
            "reason": stage,
            "message": message,
        },
    )


def _parse_test(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed
    return shlex.split(value)


def closeout_ff_edge(
    *,
    ledger: str,
    issue: int,
    child: str,
    parent: str,
    worktree: str,
    tests: list[list[str]],
) -> dict[str, Any]:
    child_branch = _git(["-C", worktree, "symbolic-ref", "--short", "-q", "HEAD"], stage="preflight")
    if child_branch != child:
        raise CloseoutFFError("preflight", f"worktree is on {child_branch!r}, expected {child!r}")
    dirty = _git(["-C", worktree, "status", "--porcelain"], stage="preflight")
    if dirty:
        raise CloseoutFFError("preflight_clean", "child worktree has uncommitted changes")

    old_parent = _git(["rev-parse", "--verify", parent], stage="preflight")
    reverse_merge = "skipped"
    ancestor = _run(["git", "merge-base", "--is-ancestor", parent, child])
    if ancestor.returncode not in (0, 1):
        raise CloseoutFFError("preflight", ancestor.stderr.strip() or ancestor.stdout.strip())
    if ancestor.returncode == 1:
        _checked(["git", "merge", "--no-edit", parent], cwd=worktree, stage="reverse_merge")
        reverse_merge = "done"

    test_results = []
    for test in tests:
        result = _run(test, cwd=worktree)
        ok = result.returncode == 0
        test_results.append({"cmd": " ".join(test), "ok": ok})
        if not ok:
            raise CloseoutFFError("test_failed", result.stderr.strip() or result.stdout.strip(), tests=test_results)

    new_child = _git(["-C", worktree, "rev-parse", "HEAD"], stage="preflight")
    _checked(ff_merge_command(child_branch=child, parent_branch=parent), stage="ff")
    _checked(["git", "push", "origin", parent], stage="push")

    close = _run([
        "gh", "issue", "close", str(issue),
        "--comment", f"task-github closeout: `{child}` fast-forwarded into `{parent}`.",
    ])
    if close.returncode != 0:
        message = close.stderr.strip() or close.stdout.strip()
        if not _issue_close_failed_ok(message):
            raise CloseoutFFError("issue_close", message)

    sha_range = f"{old_parent}..{new_child}"
    try:
        orchestrate_ledger.record_closeout_success(
            ledger,
            issue,
            [
                {"type": "ff_merged", "issue": issue, "base": parent, "head": child, "sha_range": sha_range},
                {"type": "issue_closed", "issue": issue},
                {"type": "closeout_done", "issue": issue, "base": parent, "head": child, "sha_range": sha_range},
            ],
        )
    except Exception as exc:
        raise CloseoutFFError("ledger", str(exc)) from exc
    return {
        "ok": True,
        "issue": issue,
        "child": child,
        "parent": parent,
        "reverse_merge": reverse_merge,
        "tests": test_results,
        "ff_range": sha_range,
        "pushed": True,
        "issue_closed": True,
        "ledger": ["ff_merged", "issue_closed", "closeout_done", "worker_completed"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--child", required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--test", action="append", default=[], help="argv JSON array or shell-like command string")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        payload = closeout_ff_edge(
            ledger=args.ledger,
            issue=args.issue,
            child=args.child,
            parent=args.parent,
            worktree=args.worktree,
            tests=[_parse_test(item) for item in args.test],
        )
    except CloseoutFFError as exc:
        try:
            _record_failure(
                args.ledger,
                issue=args.issue,
                parent=args.parent,
                child=args.child,
                stage=exc.stage,
                message=exc.message,
            )
        except Exception as ledger_exc:
            exc.details["ledger_error"] = str(ledger_exc)
        payload = {"ok": False, "stage": exc.stage, "message": exc.message, **exc.details}
        print(json.dumps(payload, ensure_ascii=False) if args.as_json else f"error: {exc.message}")
        return 1
    except Exception as exc:
        payload = {"ok": False, "stage": "internal", "message": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if args.as_json else f"error: {exc}")
        return 1

    print(json.dumps(payload, ensure_ascii=False) if args.as_json else f"closed #{payload['issue']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
