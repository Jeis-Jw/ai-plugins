#!/usr/bin/env python3
"""Initialize task-github's local provider configuration without remote writes."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import task_config


DEFAULT_CONFIG = ".task-github.yml"
DEFAULT_STATE_ROOT = ".task-github/local/projections"
DEFAULT_GITIGNORE = ".gitignore"
GITIGNORE_ENTRY = ".task-github/local/"


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _validation(text: str) -> dict[str, Any]:
    try:
        findings = task_config.validate_config(task_config.parse_config(text))
    except ValueError as exc:
        findings = [
            {
                "code": "config_parse_failed",
                "message": str(exc),
                "severity": "error",
            }
        ]
    return {
        "ok": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
    }


def _gitignore_text(existing: str) -> str:
    lines = existing.splitlines()
    if GITIGNORE_ENTRY in lines:
        return existing
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + GITIGNORE_ENTRY + "\n"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _type_conflict(path: Path, *, expected: str, root: Path) -> dict[str, str] | None:
    if path.exists():
        valid = path.is_file() if expected == "file" else path.is_dir()
        if valid:
            return None
        return {
            "path": _relative(path, root),
            "expected": expected,
            "actual": (
                "directory" if path.is_dir()
                else "non-directory" if expected == "directory"
                else "non-file"
            ),
            "reason": "wrong_path_type",
        }

    # A missing target may still be impossible to create because one of its
    # parents is a file. Report that blocker before any sibling path is written.
    parent = path.parent
    while parent != parent.parent:
        if parent.exists():
            if not parent.is_dir():
                return {
                    "path": _relative(path, root),
                    "blocking_path": _relative(parent, root),
                    "expected": expected,
                    "actual": "blocked_by_non_directory_parent",
                    "reason": "wrong_path_type",
                }
            break
        parent = parent.parent
    return None


def initialize(
    *,
    root: Path,
    config_path: Path = Path(DEFAULT_CONFIG),
    state_root: Path = Path(DEFAULT_STATE_ROOT),
    gitignore_path: Path = Path(DEFAULT_GITIGNORE),
    base_branch: str = "main",
    force: bool = False,
    dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    root = root.resolve()
    config = config_path if config_path.is_absolute() else root / config_path
    state = state_root if state_root.is_absolute() else root / state_root
    gitignore = gitignore_path if gitignore_path.is_absolute() else root / gitignore_path
    configured_state_root = state_root.as_posix()
    expected = task_config.render_default_config(
        base_branch=base_branch,
        state_root=configured_state_root,
    )
    intended_validation = _validation(expected)
    paths = {
        "config": _relative(config, root),
        "state_root": _relative(state, root),
        "gitignore": _relative(gitignore, root),
    }

    if not intended_validation["ok"]:
        return {
            "plugin": "task-github",
            "action": "invalid",
            "changed": False,
            "paths": paths,
            "validation": intended_validation,
            "dry_run": dry_run,
        }, 1

    conflicts = [
        conflict
        for conflict in (
            _type_conflict(config, expected="file", root=root),
            _type_conflict(state, expected="directory", root=root),
            _type_conflict(gitignore, expected="file", root=root),
        )
        if conflict is not None
    ]
    if conflicts:
        return {
            "plugin": "task-github",
            "action": "conflict",
            "changed": False,
            "would_change": False,
            "paths": paths,
            "conflicts": conflicts,
            "validation": intended_validation,
            "dry_run": dry_run,
            "error": "path type conflicts must be resolved before init",
        }, 2

    existing_config = config.read_text(encoding="utf-8") if config.is_file() else None
    if existing_config is not None and existing_config != expected and not force:
        return {
            "plugin": "task-github",
            "action": "conflict",
            "changed": False,
            "would_change": False,
            "paths": paths,
            "conflicts": [{
                "path": paths["config"],
                "expected": "generated_content",
                "actual": "different_content",
                "reason": "content_conflict",
            }],
            "validation": _validation(existing_config),
            "dry_run": dry_run,
            "error": f"{paths['config']} already exists with different content; use --force to replace it",
        }, 2

    existing_ignore = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    expected_ignore = _gitignore_text(existing_ignore)
    config_change = existing_config != expected
    state_change = not state.is_dir()
    gitignore_change = existing_ignore != expected_ignore
    would_change = config_change or state_change or gitignore_change

    if dry_run:
        action = "plan" if would_change else "skip"
    elif existing_config is None and config_change:
        action = "create"
    elif config_change:
        action = "update"
    elif state_change or gitignore_change:
        action = "repair"
    else:
        action = "skip"

    if would_change and not dry_run:
        if config_change:
            _atomic_write_text(config, expected)
        if state_change:
            state.mkdir(parents=True, exist_ok=True)
        if gitignore_change:
            _atomic_write_text(gitignore, expected_ignore)

    if not dry_run and config.exists():
        validation = _validation(config.read_text(encoding="utf-8"))
    elif existing_config is not None and not config_change:
        validation = _validation(existing_config)
    else:
        validation = intended_validation

    payload = {
        "plugin": "task-github",
        "action": action,
        "changed": bool(would_change and not dry_run),
        "would_change": would_change,
        "paths": paths,
        "conflicts": [],
        "validation": validation,
        "dry_run": dry_run,
    }
    return payload, 0 if validation["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    parser.add_argument("--gitignore", default=DEFAULT_GITIGNORE)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload, code = initialize(
        root=Path(args.root),
        config_path=Path(args.config),
        state_root=Path(args.state_root),
        gitignore_path=Path(args.gitignore),
        base_branch=args.base_branch,
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"task-github init: {payload['action']}")
        for name, path in payload["paths"].items():
            print(f"  {name}: {path}")
        if payload.get("error"):
            print(f"  error: {payload['error']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
