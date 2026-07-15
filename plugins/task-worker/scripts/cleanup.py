#!/usr/bin/env python3
"""Safely remove merged task-worker worktrees and local branches."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _task_config_module():
    path = Path(__file__).with_name("task_config.py")
    spec = importlib.util.spec_from_file_location("task_worker_cleanup_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load task-worker config: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def _worktrees(repo: Path) -> list[dict[str, str]]:
    output = _git(repo, "worktree", "list", "--porcelain").stdout
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in output.splitlines():
        if line.startswith("worktree "):
            current = {"path": line.removeprefix("worktree ")}
            items.append(current)
        elif current is not None and line.startswith("branch refs/heads/"):
            current["branch"] = line.removeprefix("branch refs/heads/")
    return items


def _blocked(code: str, message: str, **extra: Any) -> tuple[dict[str, Any], int]:
    return {
        "ok": False,
        "schema": "task-worker.cleanup-receipt/v1",
        "action": "blocked",
        "changed": False,
        "error_code": code,
        "message": message,
        **extra,
    }, 2


def run_cleanup(
    *,
    repo: Path,
    branch: str,
    base: str,
    config_path: Path,
    worktree: Path | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    repo = repo.resolve()
    config_file = config_path if config_path.is_absolute() else repo / config_path
    config_module = _task_config_module()
    try:
        config = config_module.load_config(config_file)
    except (OSError, ValueError) as exc:
        return _blocked("config_unavailable", str(exc), branch=branch, base=base, dry_run=dry_run)
    errors = [item for item in config_module.validate_config(config) if item["severity"] == "error"]
    if errors:
        return _blocked("config_invalid", "task-worker config is invalid", findings=errors, branch=branch, base=base, dry_run=dry_run)

    policy = config.get("cleanup", {})
    remove_worktree = policy.get("remove-merged-worktrees", True)
    delete_branch = policy.get("delete-merged-local-branches", True)
    prune = policy.get("prune-stale-worktrees", True)
    entries = _worktrees(repo)
    primary = Path(entries[0]["path"]).resolve() if entries else repo
    branch_entry = next((item for item in entries if item.get("branch") == branch), None)
    base_entry = next((item for item in entries if item.get("branch") == base), None)
    target = worktree.resolve() if worktree else Path(branch_entry["path"]).resolve() if branch_entry else None

    branch_exists = _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    if not branch_exists and target is None:
        return {
            "ok": True,
            "schema": "task-worker.cleanup-receipt/v1",
            "action": "skip",
            "changed": False,
            "branch": branch,
            "base": base,
            "worktree": None,
            "dry_run": dry_run,
            "removed_worktree": False,
            "deleted_local_branch": False,
            "pruned": False,
        }, 0
    if branch == base:
        return _blocked("base_branch_protected", "cleanup branch must differ from base", branch=branch, base=base, dry_run=dry_run)
    if not branch_exists:
        return _blocked("branch_missing", "worktree branch is missing", branch=branch, base=base, worktree=str(target), dry_run=dry_run)
    if _git(repo, "merge-base", "--is-ancestor", branch, base, check=False).returncode != 0:
        return _blocked("branch_not_merged", f"{branch} is not merged into {base}", branch=branch, base=base, worktree=str(target) if target else None, dry_run=dry_run)
    if delete_branch and base_entry is None:
        return _blocked("base_worktree_missing", f"{base} must be checked out to delete the merged branch safely", branch=branch, base=base, worktree=str(target) if target else None, dry_run=dry_run)

    if target is not None:
        if target == primary:
            return _blocked("primary_worktree_protected", "primary worktree cannot be removed", branch=branch, base=base, worktree=str(target), dry_run=dry_run)
        if branch_entry is None or Path(branch_entry["path"]).resolve() != target:
            return _blocked("worktree_binding_mismatch", "worktree is not bound to the requested branch", branch=branch, base=base, worktree=str(target), dry_run=dry_run)
        dirty = _git(repo, "-C", str(target), "status", "--porcelain", check=False)
        if dirty.returncode != 0:
            return _blocked("worktree_unreadable", dirty.stderr.strip() or dirty.stdout.strip(), branch=branch, base=base, worktree=str(target), dry_run=dry_run)
        if dirty.stdout.strip():
            return _blocked("dirty_worktree", "worktree has uncommitted changes", branch=branch, base=base, worktree=str(target), dry_run=dry_run)
        if delete_branch and not remove_worktree:
            return _blocked("cleanup_policy_conflict", "cannot delete a branch while its worktree is retained", branch=branch, base=base, worktree=str(target), dry_run=dry_run)

    actions: list[str] = []
    if target is not None and remove_worktree:
        actions.append("remove_worktree")
    if delete_branch:
        actions.append("delete_local_branch")
    if prune:
        actions.append("prune_worktrees")
    if not dry_run:
        if target is not None and remove_worktree:
            _git(repo, "worktree", "remove", str(target))
        if delete_branch:
            _git(Path(base_entry["path"]), "branch", "-d", branch)
        if prune:
            _git(repo, "worktree", "prune")

    return {
        "ok": True,
        "schema": "task-worker.cleanup-receipt/v1",
        "action": "plan" if dry_run else "cleanup",
        "changed": bool(actions),
        "branch": branch,
        "base": base,
        "worktree": str(target) if target else None,
        "dry_run": dry_run,
        "actions": actions,
        "removed_worktree": bool(target is not None and remove_worktree and not dry_run),
        "deleted_local_branch": bool(delete_branch and not dry_run),
        "pruned": bool(prune and not dry_run),
    }, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--worktree")
    parser.add_argument("--config", default=".task-worker.yml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        payload, code = run_cleanup(
            repo=Path(args.repo),
            branch=args.branch,
            base=args.base,
            config_path=Path(args.config),
            worktree=Path(args.worktree) if args.worktree else None,
            dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        payload, code = _blocked("git_failed", str(exc), branch=args.branch, base=args.base, dry_run=args.dry_run)
    print(json.dumps(payload, ensure_ascii=False) if args.as_json else payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
