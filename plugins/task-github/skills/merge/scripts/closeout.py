#!/usr/bin/env python3
"""Deterministic post-gate merge closeout for task-github's `merge` skill.

git/gh ONLY — never mutates wiki. `wiki complete` runs in the skill AFTER, using
the `task_to_complete` this script emits. Keeping wiki mutation out makes the
script portable and keeps the merge/no-merge decision with the agent.

All merges go through `gh pr merge` (remote): leaf PRs and container/epic
merge-up PRs alike. Sequence: resolve PR → dependency recheck → label cleanup →
merge → checkout-free base sync + branch cleanup → downstream advisory →
root-close detection. The base sync never checks out the base branch, so the
operator's primary worktree HEAD stays put during orchestration
(DEC-2026-07-02-212109). `--dry-run` does only the read-only steps and reports
the plan; it never merges, relabels, or deletes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

STATE_LABELS = ("in-review", "in-progress", "changes-requested")
# Unicode-safe: the slug may contain Korean. Stop at whitespace or bracket so a
# trailing ``]`` / ``)`` in markdown doesn't get swallowed.
TASK_ID_RE = re.compile(r"TASK-\d{4}-\d{2}-\d{2}-\d{6}-[^\s)\],.]+")
WIKI_CONTEXT_RE = re.compile(
    r"(?ims)^##\s+Wiki Context\s*\n(?P<body>.*?)(?=^##\s+|\Z)",
)
LINKED_ISSUE_RE = re.compile(r"(?i)\b(?:closes|fixes|resolves)\s+#(\d+)")


class CloseoutError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── pure helpers (unit-tested) ─────────────────────────────────────────────
def parse_linked_issue(pr_body: str) -> Optional[int]:
    """First `Closes/Fixes/Resolves #N` in a PR body, else None."""
    m = LINKED_ISSUE_RE.search(pr_body or "")
    return int(m.group(1)) if m else None


def extract_task_id(issue_body: str) -> Optional[str]:
    """First wiki task basename in the Wiki Context section, else None."""
    section = WIKI_CONTEXT_RE.search(issue_body or "")
    if not section:
        return None
    m = TASK_ID_RE.search(section.group("body"))
    return m.group(0) if m else None


def labels_to_remove(current: List[str]) -> List[str]:
    """State labels present on the issue/PR that should be cleared on merge
    (gear:* and everything else preserved). Order follows STATE_LABELS."""
    have = set(current or [])
    return [lbl for lbl in STATE_LABELS if lbl in have]


def _drift_failed(report: dict | None) -> bool:
    if not report:
        return False
    issues = report.get("issues")
    return bool(issues)


def _integrity_failed(report: dict | None) -> bool:
    if not report:
        return False
    if report.get("ok") is False:
        return True
    issues = report.get("issues")
    return bool(issues)


def _has_drift_evidence(report: dict | None) -> bool:
    return isinstance(report, dict) and (report.get("skipped") is True or "issues" in report)


def _has_integrity_evidence(report: dict | None) -> bool:
    return isinstance(report, dict) and (
        report.get("skipped") is True or "ok" in report or "issues" in report
    )


def _command_key(command) -> str:
    if isinstance(command, list):
        return json.dumps(command, ensure_ascii=False, separators=(",", ":"))
    return str(command)


# ── gh/git plumbing ────────────────────────────────────────────────────────
def _run(cmd: List[str], *, code: str) -> str:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise CloseoutError(code, result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _run_warning(cmd: List[str]) -> str | None:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return f"{' '.join(cmd)}: {result.stderr.strip() or result.stdout.strip()}"
    return None


def gh(args: List[str], *, code: str = "gh_failed") -> str:
    return _run(["gh", *args], code=code)


def _repo() -> tuple[str, str]:
    data = json.loads(gh(["repo", "view", "--json", "owner,name"]))
    return data["owner"]["login"], data["name"]


def _default_branch() -> str:
    data = json.loads(gh(["repo", "view", "--json", "defaultBranchRef"]))
    return data["defaultBranchRef"]["name"]


def _open_blockers(owner: str, repo: str, issue: int) -> List[str]:
    out = gh([
        "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{owner}/{repo}/issues/{issue}/dependencies/blocked_by",
        "--jq", '[.[] | select(.state=="open") | "#\\(.number) \\(.title)"]',
    ], code="dep_check_failed")
    return json.loads(out) if out else []


def _blocking(owner: str, repo: str, issue: int) -> List[str]:
    out = gh([
        "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{owner}/{repo}/issues/{issue}/dependencies/blocking",
        "--jq", '[.[] | "#\\(.number) \\(.title)"]',
    ], code="dep_check_failed")
    return json.loads(out) if out else []


def _parent(owner: str, repo: str, issue: int) -> Optional[int]:
    out = gh([
        "api", "graphql",
        "-f", "query=query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r)"
              "{issue(number:$n){parent{number}}}}",
        "-F", f"o={owner}", "-F", f"r={repo}", "-F", f"n={issue}",
        "--jq", ".data.repository.issue.parent.number // empty",
    ], code="parent_lookup_failed")
    return int(out) if out else None


def _detect_root_task(owner: str, repo: str, issue: int) -> tuple[Optional[int], bool, Optional[str]]:
    """Root issue number, whether it is CLOSED, and its task id (if closed)."""
    parent = _parent(owner, repo, issue)
    root = parent if parent is not None else issue
    state = gh(["issue", "view", str(root), "--json", "state", "--jq", ".state"],
               code="issue_view_failed")
    closed = state == "CLOSED"
    task = None
    if closed:
        body = gh(["issue", "view", str(root), "--json", "body", "--jq", ".body"],
                  code="issue_view_failed")
        task = extract_task_id(body)
    return root, closed, task


def issue_close_failure_is_ok(message: str) -> bool:
    text = (message or "").lower()
    return "already closed" in text or "not open" in text


def _close_issue_best_effort(issue: int, *, comment: str) -> str | None:
    result = subprocess.run(
        ["gh", "issue", "close", str(issue), "--comment", comment],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode == 0:
        return None
    message = result.stderr.strip() or result.stdout.strip()
    if issue_close_failure_is_ok(message):
        return None
    return f"gh issue close {issue}: {message}"


def _worktree_for_branch(branch: str) -> str | None:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    current_path = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line.removeprefix("worktree ")
        elif line == f"branch refs/heads/{branch}" and current_path:
            return current_path
    return None


def _local_branch_exists(branch: str) -> bool:
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).returncode == 0


def _cleanup_local_branch(branch: str) -> list[str]:
    if not _local_branch_exists(branch):
        return []
    warnings = []
    worktree = _worktree_for_branch(branch)
    if worktree:
        status = subprocess.run(
            ["git", "-C", worktree, "status", "--porcelain"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if status.returncode != 0:
            return [f"git -C {worktree} status --porcelain: {status.stderr.strip() or status.stdout.strip()}"]
        if status.stdout.strip():
            return [f"local branch {branch} kept: worktree {worktree} has uncommitted changes"]
        warning = _run_warning(["git", "worktree", "remove", worktree])
        if warning:
            return [warning]
    warning = _run_warning(["git", "branch", "-d", branch])
    if warning:
        warnings.append(warning)
    return warnings


def _record_orchestrate_events(path: str | None, events: list[dict]) -> str | None:
    if not path:
        return None
    try:
        scripts_dir = Path(__file__).resolve().parents[2] / "orchestrate" / "scripts"
        sys.path.insert(0, str(scripts_dir))
        from orchestrate_ledger import record_events, record_github_read  # type: ignore

        record_github_read(path, reason="final_closeout", operation="closeout", detail={"events": events})
        record_events(path, events)
    except Exception as exc:  # post-merge bookkeeping must not hide the merge
        return f"orchestrate ledger update failed: {exc}"
    return None


def run_pr_closeout(pr: int, *, dry_run: bool, orchestrate_ledger: str | None = None) -> dict:
    owner, repo = _repo()
    view = json.loads(gh(["pr", "view", str(pr), "--json",
                          "number,headRefName,headRefOid,baseRefName,state,body,labels"]))
    if view["state"] == "MERGED":
        raise CloseoutError("already_merged", f"PR #{pr} is already merged")
    head = view["headRefName"]
    issue = parse_linked_issue(view["body"])
    if issue is None:
        raise CloseoutError("no_linked_issue", f"PR #{pr} body has no Closes/Fixes/Resolves #N")
    pr_label_removals = labels_to_remove([l["name"] for l in view.get("labels", [])])

    open_blockers = _open_blockers(owner, repo, issue)
    if open_blockers:
        raise CloseoutError("open_blockers",
                            "linked issue has open blocked_by: " + "; ".join(open_blockers))

    issue_view = json.loads(gh(["issue", "view", str(issue), "--json", "labels,body"]))
    issue_label_removals = labels_to_remove([l["name"] for l in issue_view.get("labels", [])])
    downstream = _blocking(owner, repo, issue)

    if dry_run:
        # Root detection on a not-yet-merged tree is best-effort (container may
        # only close after this merge); report current state.
        root, root_closed, task = _detect_root_task(owner, repo, issue)
        return {
            "ok": True, "dry_run": True, "pr": pr, "issue": issue, "head": head,
            "merged": False, "would_merge": f"gh pr merge {pr} --merge",
            "pr_labels_to_remove": pr_label_removals,
            "issue_labels_to_remove": issue_label_removals,
            "downstream": downstream,
            "root": root, "root_closed": root_closed, "root_closed_now": root_closed,
            "task_to_complete": task,
        }

    for lbl in pr_label_removals:
        gh(["pr", "edit", str(pr), "--remove-label", lbl], code="label_failed")
    for lbl in issue_label_removals:
        gh(["issue", "edit", str(issue), "--remove-label", lbl], code="label_failed")

    gh(["pr", "merge", str(pr), "--merge"], code="merge_failed")

    sync_warnings = []
    try:
        default_branch = _default_branch()
    except CloseoutError as exc:
        default_branch = None
        sync_warnings.append(f"default branch lookup failed: {exc.message}")
    if default_branch and view["baseRefName"] != default_branch:
        warning = _close_issue_best_effort(
            issue,
            comment=f"task-github closeout: PR #{pr} merged into `{view['baseRefName']}`.",
        )
        if warning:
            sync_warnings.append(warning)

    # Detect the (possibly now-closed) root + task id RIGHT AFTER the
    # irreversible merge — before any local-sync step that could fail — so a
    # dirty worktree / pull conflict can never swallow `task_to_complete` and
    # leave the wiki task node stranded in active/ while the root issue is closed.
    root, root_closed, task = _detect_root_task(owner, repo, issue)
    result = {
        "ok": True, "dry_run": False, "pr": pr, "issue": issue, "head": head,
        "merged": True, "downstream": downstream,
        "root": root, "root_closed": root_closed, "task_to_complete": task,
    }
    ledger_events = [{
        "type": "pr_merged",
        "issue": issue,
        "pr": pr,
        "head": head,
        "head_sha": view.get("headRefOid"),
        "base": view["baseRefName"],
    }]
    if default_branch and view["baseRefName"] != default_branch and not any(
        warning.startswith(f"gh issue close {issue}:") for warning in sync_warnings
    ):
        ledger_events.append({"type": "issue_closed", "issue": issue})
    warning = _record_orchestrate_events(orchestrate_ledger, ledger_events)
    if warning:
        sync_warnings.append(warning)

    # Local sync is best-effort: the merge already landed on the remote, so a
    # failure here must not abort (and must not hide the result above). Never
    # `git checkout` the base branch — refresh the local base ref via fetch so
    # the operator's primary worktree HEAD stays where it was during
    # orchestration (DEC-2026-07-02-212109). Fetch refuses to update a
    # checked-out branch, so when base IS the current HEAD, pull in place.
    base = view["baseRefName"]
    current = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()
    base_sync = (
        ["git", "pull", "--ff-only"] if base == current
        else ["git", "fetch", "origin", f"{base}:{base}"]
    )
    for cmd in (base_sync, ["git", "push", "origin", "--delete", head]):
        warning = _run_warning(cmd)
        if warning:
            sync_warnings.append(warning)
    sync_warnings.extend(_cleanup_local_branch(head))
    if sync_warnings:
        result["sync_warnings"] = sync_warnings
    if orchestrate_ledger:
        result["ledger_events"] = ledger_events
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--orchestrate-ledger")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = run_pr_closeout(
            args.pr, dry_run=args.dry_run, orchestrate_ledger=args.orchestrate_ledger
        )
    except CloseoutError as exc:
        payload = {"ok": False, "error_code": exc.code, "message": exc.message}
        print(json.dumps(payload, ensure_ascii=False) if args.as_json else f"error: {exc.message}",
              file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result.get("merged"):
            print(f"merged PR #{result['pr']} (issue #{result['issue']})")
            if result.get("task_to_complete"):
                print(f"root closed → run: wiki complete {result['task_to_complete']}")
        else:
            print(f"[dry-run] would: {result.get('would_merge')}")
            if result.get("task_to_complete"):
                print(f"[dry-run] root currently closed → would complete: {result['task_to_complete']}")
        for d in result.get("downstream", []):
            print(f"downstream: {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
