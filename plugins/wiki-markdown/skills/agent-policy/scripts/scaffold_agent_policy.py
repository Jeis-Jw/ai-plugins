#!/usr/bin/env python3
"""Scaffold concise auto-loaded agent operating policy.

This script is intentionally wiki-agnostic: it only writes agent entry files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


BEGIN = "<!-- BEGIN agent-operating-policy (managed by wiki-markdown) -->"
END = "<!-- END agent-operating-policy (managed by wiki-markdown) -->"

TARGET_FILES: Dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
}


class ScaffoldError(Exception):
    pass


def target_names(target: str) -> List[str]:
    if target == "all":
        return ["claude", "codex"]
    return [target]


def concurrency_line(value: str) -> str:
    if value == "worktree":
        return (
            "Use git worktrees for concurrent tasks; do not let parallel agents "
            "edit the same working tree."
        )
    return (
        "Use the current working tree for one active task at a time; stop and "
        "isolate if another task starts."
    )


def tracker_line(value: str) -> str:
    if value == "task-github":
        return (
            "Use task-github for tracked work. The wiki work-definition (task node) "
            "is the work order/instruction, created FIRST; the GitHub root issue is "
            "the execution view, created and linked afterward. On a plan/prepare-work "
            "request, task-github:define detects the wiki, uses or waits for that task "
            "node (capturing it first if absent), and confirms before creating the "
            "linked issue. With only one plugin present, each does its own part "
            "standalone (wiki: the work-definition doc; task-github: an issue from "
            "session context)."
        )
    return "No external task tracker is bound; keep task state in the active conversation."


def render_policy(profile: str, tracker: str, concurrency: str) -> str:
    lines = [
        BEGIN,
        "## Agent Operating Policy",
        "",
        f"- Profile: {profile}",
        "- Scope: these auto-loaded entry files are the source for working-environment policy.",
        f"- Concurrency: {concurrency_line(concurrency)}",
        f"- Tracker: {tracker_line(tracker)}",
        (
            "- Knowledge capture: use wiki-markdown for product, system, and design "
            "knowledge; do not store working-environment operating policy in a "
            "consumer project's wiki vault."
        ),
        (
            "- Design altitude: brainstorming defines decomposition and thin unit "
            "boundaries; unit-internal schema/API/DDL/prompt contracts belong in "
            "the unit issue body or in DEC/OBS captured during that unit's run. "
            "Do not create wiki task nodes for leaf issues."
        ),
        (
            "- Capture authority: observations may be recorded when low-risk; "
            "decisions, rejected alternatives, trial-error records, and promotions "
            "need explicit user confirmation."
        ),
        (
            "- Capture threshold: small or one-off findings are observations or "
            "commit messages, not decisions; reserve a DEC for choices with real "
            "revisit/reversal cost. Run refresh once at the end of a batch, not per "
            "node. Scale capture to the gear: gear:micro skips the wiki task node "
            "(audit none by default); gear:normal captures only when a candidate "
            "exists; gear:major keeps task plus DEC/SSOT."
        ),
        (
            "- Rationale commits: capture decisions, rejected alternatives, and "
            "other rationale records directly on main; code changes go via PR "
            "branches that reference the DEC id. task-github define commits its "
            "task node and rationale atomically, and define/start warn on a dirty "
            "wiki vault."
        ),
        END,
        "",
    ]
    return "\n".join(lines)


def merge_block(existing: str, block: str) -> Tuple[str, str]:
    has_begin = BEGIN in existing
    has_end = END in existing
    if has_begin != has_end:
        raise ScaffoldError("managed block markers are unbalanced")

    if has_begin:
        before, rest = existing.split(BEGIN, 1)
        _old, after = rest.split(END, 1)
        prefix = before.rstrip()
        suffix = after.lstrip("\n")
        new_text = ""
        if prefix:
            new_text += prefix + "\n\n"
        new_text += block.rstrip() + "\n"
        if suffix:
            new_text += "\n" + suffix
        status = "updated"
    else:
        prefix = existing.rstrip()
        if prefix:
            new_text = prefix + "\n\n" + block
        else:
            new_text = block
        status = "created"

    if new_text == existing:
        status = "unchanged"
    return new_text, status


def write_target(path: Path, block: str, dry_run: bool) -> Dict[str, str]:
    exists = path.exists()
    existing = path.read_text(encoding="utf-8") if exists else ""
    new_text, status = merge_block(existing, block)
    if not exists and status == "created":
        status = "created"
    elif exists and status == "created":
        status = "updated"

    action_status = status
    if dry_run:
        if status == "created":
            action_status = "would-create"
        elif status == "updated":
            action_status = "would-update"
        elif status == "unchanged":
            action_status = "unchanged"
    elif status != "unchanged":
        path.write_text(new_text, encoding="utf-8")

    return {"path": path.name, "status": action_status}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("all", "claude", "codex"), default="all")
    parser.add_argument("--profile", choices=("solo", "team"), default="solo")
    parser.add_argument("--tracker", choices=("task-github", "none"), default="task-github")
    parser.add_argument("--concurrency", choices=("worktree", "shared"), default="worktree")
    parser.add_argument("--root", default=".", help="project root to update")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    block = render_policy(args.profile, args.tracker, args.concurrency)

    try:
        actions = [
            write_target(root / TARGET_FILES[name], block, args.dry_run)
            for name in target_names(args.target)
        ]
    except ScaffoldError as exc:
        payload = {"ok": False, "error_code": "marker_error", "message": str(exc)}
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"error: {exc}")
        return 2

    payload = {"ok": True, "actions": actions}
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for action in actions:
            print(f"{action['status']}: {action['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
