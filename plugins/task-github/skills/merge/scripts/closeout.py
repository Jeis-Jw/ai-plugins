#!/usr/bin/env python3
"""Deterministic post-gate merge closeout for task-github's `merge` skill.

git/gh ONLY — never mutates wiki. Quality gates (integrity/drift) run in the
skill BEFORE this and are passed as evidence for local mode; `wiki complete`
runs in the skill AFTER, using the `task_to_complete` this script emits. Keeping
wiki mutation out makes the script portable and keeps the merge/no-merge
decision with the agent.

PR sequence: resolve PR → dependency recheck → label cleanup → merge →
sync+branch cleanup → downstream advisory → root-close detection.
Local sequence: dependency recheck → temp worktree merge simulation →
required_checks/drift/integrity validation → local merge → issue close →
optional stacked-local Integration Ledger → root-close detection.
`--dry-run` does only the read-only steps and reports the plan; it never merges,
relabels, or deletes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from typing import Iterable, List, Optional

STATE_LABELS = ("in-review", "in-progress", "changes-requested")
# Unicode-safe: the slug may contain Korean. Stop at whitespace or bracket so a
# trailing ``]`` / ``)`` in markdown doesn't get swallowed.
TASK_ID_RE = re.compile(r"TASK-\d{4}-\d{2}-\d{2}-\d{6}-[^\s)\],.]+")
LINKED_ISSUE_RE = re.compile(r"(?i)\b(?:closes|fixes|resolves)\s+#(\d+)")
LEDGER_MARKER = "<!-- task-github:integration-ledger:v1 -->"
LEDGER_FENCE = "task-github-ledger"
LEDGER_RE = re.compile(rf"```{LEDGER_FENCE}\s*\n(?P<body>.*?)\n```", re.DOTALL)
HARD_LEAF_RISKS = {"irreversible", "db", "public-api", "security", "data-loss"}


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
    """First wiki task basename in an issue body (Unicode slug preserved)."""
    m = TASK_ID_RE.search(issue_body or "")
    return m.group(0) if m else None


def labels_to_remove(current: List[str]) -> List[str]:
    """State labels present on the issue/PR that should be cleared on merge
    (gear:* and everything else preserved). Order follows STATE_LABELS."""
    have = set(current or [])
    return [lbl for lbl in STATE_LABELS if lbl in have]


def leaf_policy_requirements(policy: dict | None) -> dict:
    """Return the minimum gates required before local leaf integration."""
    raw_risk = (policy or {}).get("risk_class", "normal")
    risk = str(raw_risk or "normal").strip().lower()
    required = ["verify", "drift", "blocker"]
    if risk == "major":
        required.append("self-flow")
    elif risk in HARD_LEAF_RISKS:
        required.append("pr-or-hard-self-flow")
    elif risk not in {"micro", "normal"}:
        required.append("manual-risk-review")
    return {"risk_class": risk, "required_gates": required}


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


def evaluate_merge_simulation(
    *,
    required_checks: list[str] | None,
    check_results: list[dict] | None,
    drift_report: dict | None,
    integrity_report: dict | None,
) -> dict:
    """Validate required checks + drift + integrity for local closeout."""
    required = list(required_checks or [])
    results = list(check_results or [])
    by_command = {str(item.get("command")): item for item in results}
    failed = []
    for command in required:
        result = by_command.get(command)
        if result is None:
            failed.append({"code": "required_check_missing", "command": command})
        elif int(result.get("returncode", 1)) != 0:
            failed.append({
                "code": "required_check_failed",
                "command": command,
                "returncode": result.get("returncode"),
            })
    if _drift_failed(drift_report):
        failed.append({"code": "changed_path_stale", "report": drift_report})
    if _integrity_failed(integrity_report):
        failed.append({"code": "integrity_failed", "report": integrity_report})
    return {
        "ok": not failed,
        "required_checks": required,
        "check_results": results,
        "drift": drift_report,
        "integrity": integrity_report,
        "failed": failed,
    }


def render_integration_ledger_comment(event: dict) -> str:
    payload = {"schema_version": 1, **event}
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{LEDGER_MARKER}\n```{LEDGER_FENCE}\n{body}\n```"


def parse_integration_ledger_events(comments: Iterable[dict]) -> list[dict]:
    events = []
    for comment in comments or []:
        body = str(comment.get("body") or "")
        if LEDGER_MARKER not in body:
            continue
        for match in LEDGER_RE.finditer(body):
            try:
                payload = json.loads(match.group("body"))
            except json.JSONDecodeError:
                continue
            if payload.get("schema_version") == 1:
                events.append(payload)
    return events


# ── gh/git plumbing ────────────────────────────────────────────────────────
def _run(cmd: List[str], *, code: str) -> str:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise CloseoutError(code, result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def gh(args: List[str], *, code: str = "gh_failed") -> str:
    return _run(["gh", *args], code=code)


def _repo() -> tuple[str, str]:
    data = json.loads(gh(["repo", "view", "--json", "owner,name"]))
    return data["owner"]["login"], data["name"]


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


def run_required_checks(commands: list[str], *, cwd: str) -> list[dict]:
    results = []
    for command in commands or []:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        results.append({
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        })
    return results


def run_merge_simulation(
    *,
    head: str,
    parent_branch: str,
    required_checks: list[str],
    drift_report: dict | None,
    integrity_report: dict | None,
) -> dict:
    tmp = tempfile.mkdtemp(prefix="task-github-merge-sim-")
    check_results: list[dict] = []
    try:
        _run(["git", "worktree", "add", "--detach", tmp, parent_branch],
             code="simulation_worktree_failed")
        _run(["git", "-C", tmp, "merge", "--no-commit", "--no-ff", head],
             code="simulation_merge_failed")
        check_results = run_required_checks(required_checks, cwd=tmp)
        report = evaluate_merge_simulation(
            required_checks=required_checks,
            check_results=check_results,
            drift_report=drift_report,
            integrity_report=integrity_report,
        )
        report["worktree"] = tmp
        return report
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", tmp],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def _sha(ref: str) -> str:
    return _run(["git", "rev-parse", "--short", ref], code="git_failed")


def _local_labels_to_remove(issue_view: dict) -> list[str]:
    return labels_to_remove([l["name"] for l in issue_view.get("labels", [])])


def _append_ledger(owner: str, repo: str, root: int, event: dict) -> None:
    body = render_integration_ledger_comment(event)
    gh(["issue", "comment", str(root), "--body", body], code="ledger_failed")


def run_local_closeout(
    *,
    issue: int,
    head: str,
    parent_branch: str,
    dry_run: bool,
    required_checks: list[str],
    drift_report: dict | None,
    integrity_report: dict | None,
    contract: dict | None,
) -> dict:
    owner, repo = _repo()
    open_blockers = _open_blockers(owner, repo, issue)
    if open_blockers:
        raise CloseoutError("open_blockers",
                            "linked issue has open blocked_by: " + "; ".join(open_blockers))
    root, root_closed_before, _ = _detect_root_task(owner, repo, issue)
    issue_view = json.loads(gh(["issue", "view", str(issue), "--json", "labels,body"]))
    issue_label_removals = _local_labels_to_remove(issue_view)
    downstream = _blocking(owner, repo, issue)
    policy = leaf_policy_requirements((contract or {}).get("leaf_policy"))
    simulation = run_merge_simulation(
        head=head,
        parent_branch=parent_branch,
        required_checks=required_checks,
        drift_report=drift_report,
        integrity_report=integrity_report,
    )
    if not simulation["ok"]:
        raise CloseoutError("merge_simulation_failed", json.dumps(simulation, ensure_ascii=False))

    base_result = {
        "ok": True,
        "dry_run": dry_run,
        "mode": "local",
        "issue": issue,
        "root": root,
        "head": head,
        "parent_branch": parent_branch,
        "root_closed": root_closed_before,
        "task_to_complete": None,
        "downstream": downstream,
        "merged": False,
        "issue_labels_to_remove": issue_label_removals,
        "leaf_policy": policy,
        "merge_simulation": simulation,
    }
    if dry_run:
        base_result["would_merge"] = f"git checkout {parent_branch} && git merge --no-ff {head}"
        return base_result

    _run(["git", "checkout", parent_branch], code="git_failed")
    _run(["git", "merge", "--no-ff", head, "-m",
          f"merge(task-github): local closeout issue #{issue}"], code="local_merge_failed")
    for lbl in issue_label_removals:
        gh(["issue", "edit", str(issue), "--remove-label", lbl], code="label_failed")
    gh(["issue", "close", str(issue), "--comment",
        f"task-github local closeout: merged `{head}` into `{parent_branch}`."],
       code="issue_close_failed")
    root, root_closed, task = _detect_root_task(owner, repo, issue)
    event = {
        "leaf": issue,
        "sha": _sha("HEAD"),
        "checks": simulation["check_results"],
        "drift": drift_report,
        "downstream": downstream,
    }
    topology = (contract or {}).get("topology")
    mode = (contract or {}).get("closeout_mode")
    if topology == "stacked" and mode == "local":
        _append_ledger(owner, repo, root, event)
    base_result.update({
        "dry_run": False,
        "root": root,
        "root_closed": root_closed,
        "task_to_complete": task if root_closed else None,
        "merged": True,
        "ledger_event": event if topology == "stacked" and mode == "local" else None,
    })
    return base_result


def run_pr_closeout(pr: int, *, dry_run: bool) -> dict:
    owner, repo = _repo()
    view = json.loads(gh(["pr", "view", str(pr), "--json",
                          "number,headRefName,baseRefName,state,body,labels"]))
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
            "merged": False, "would_merge": f"gh pr merge {pr} --merge --delete-branch",
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

    gh(["pr", "merge", str(pr), "--merge", "--delete-branch"], code="merge_failed")

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

    # Local sync is best-effort: the merge already landed on the remote, so a
    # failure here must not abort (and must not hide the result above).
    sync_warnings = []
    for cmd in (["git", "checkout", view["baseRefName"]], ["git", "pull"],
                ["git", "branch", "-d", head]):
        r = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            sync_warnings.append(f"{' '.join(cmd)}: {r.stderr.strip() or r.stdout.strip()}")
    if sync_warnings:
        result["sync_warnings"] = sync_warnings
    return result


def _load_json_file(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def _contract_required_checks(contract: dict | None, extras: list[str]) -> list[str]:
    checks = []
    if isinstance(contract, dict) and isinstance(contract.get("required_checks"), list):
        checks.extend(str(item) for item in contract["required_checks"])
    checks.extend(extras or [])
    return checks


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pr", "local"), default="pr")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--head", "--branch", dest="head")
    parser.add_argument("--parent-branch", default="main")
    parser.add_argument("--contract-json")
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--drift-json")
    parser.add_argument("--integrity-json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.mode == "pr":
            if args.pr is None:
                raise CloseoutError("bad_args", "--pr is required in --mode pr")
            result = run_pr_closeout(args.pr, dry_run=args.dry_run)
        else:
            if args.issue is None or not args.head:
                raise CloseoutError("bad_args", "--issue and --head are required in --mode local")
            contract = _load_json_file(args.contract_json)
            result = run_local_closeout(
                issue=args.issue,
                head=args.head,
                parent_branch=args.parent_branch,
                dry_run=args.dry_run,
                required_checks=_contract_required_checks(contract, args.required_check),
                drift_report=_load_json_file(args.drift_json),
                integrity_report=_load_json_file(args.integrity_json),
                contract=contract,
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
            if result.get("mode") == "local":
                print(f"merged {result['head']} into {result['parent_branch']} (issue #{result['issue']})")
            else:
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
