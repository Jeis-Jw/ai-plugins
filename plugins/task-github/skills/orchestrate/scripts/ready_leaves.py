#!/usr/bin/env python3
"""Derive task-github orchestrate ready/stop sets from a GitHub issue tree."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

import orchestrator_ops
from orchestrate_ledger import load_ledger, record_github_read, record_read_decision, record_snapshot, tree_from_ledger

TASK_GITHUB_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TASK_GITHUB_ROOT / "scripts"))
import task_worker_bridge  # noqa: E402
import task_config  # noqa: E402

STATE_LABELS = {"in-progress", "in-review", "changes-requested"}
REVIEW_LABELS = {"in-review", "changes-requested"}


def item(node: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    out = {
        "number": node["number"],
        "title": node.get("title", ""),
        "state": node.get("state", ""),
        "labels": list(node.get("labels") or []),
    }
    if reason:
        out["reason"] = reason
    if isinstance(node.get("pr_transport"), dict):
        out.update(node["pr_transport"])
    elif node.get("pr") is not None:
        out["pr"] = node["pr"]
    if isinstance(node.get("external_review"), dict):
        out["external_review"] = node["external_review"]
    for field in ("ready_for_closeout", "closeout_started", "closeout_failed"):
        if isinstance(node.get(field), dict):
            out.update(node[field])
    return out


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    return list(node.get("children") or [])


def _summary(node: dict[str, Any]) -> dict[str, int]:
    children = _children(node)
    return node.get("subissues_summary") or {
        "total": len(children),
        "completed": sum(1 for child in children if _is_complete_state(child.get("state"))),
    }


def _walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in _children(node):
        yield from _walk(child)


def _is_complete_state(state: str | None) -> bool:
    return state in {"CLOSED", "close_expected"}


def _effective_gear(node: dict[str, Any]) -> str | None:
    """A node's merge-edge gear: a leaf's own gear label, or a container's
    cumulative promotion over its children's effective gears (bubbles up depth-N).
    """
    children = _children(node)
    if not children:
        return orchestrator_ops.gear_of_labels(node.get("labels"))
    return orchestrator_ops.container_gear_promotion([_effective_gear(child) for child in children])


def _blocker_numbers(node: dict[str, Any]) -> list[int]:
    numbers = []
    for blocker in node.get("open_blockers") or []:
        if isinstance(blocker, dict) and isinstance(blocker.get("number"), int):
            numbers.append(blocker["number"])
        elif isinstance(blocker, int):
            numbers.append(blocker)
    return numbers


def _base_result() -> dict[str, Any]:
    return {
        "ok": True,
        "stop_reason": None,
        "ready": [],
        "blocked": [],
        "review_waiting": [],
        "stuck": [],
        "closeout_ready": [],
        "closeout_running": [],
        "closeout_failed": [],
        "done_parents": [],
        "container_done": None,
    }


def _stop(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["ok"] = False
    result["stop_reason"] = reason
    return result


def parse_number_set(raw: str | None) -> set[int]:
    if not raw:
        return set()
    numbers: set[int] = set()
    for part in re.split(r"[\s,]+", raw.strip()):
        if not part:
            continue
        try:
            numbers.add(int(part))
        except ValueError as exc:
            raise ValueError(f"invalid issue number: {part!r}") from exc
    return numbers


def ledger_number_set(ledger: dict[str, Any], field: str) -> set[int]:
    value = ledger.get(field) or []
    if isinstance(value, str):
        return parse_number_set(value)
    return {int(part) for part in value}


def _graph_status(node: dict[str, Any]) -> str:
    state = node.get("state")
    if _is_complete_state(state):
        return "completed"
    if state in {"closeout_ready", "closeout_started", "closeout_failed"}:
        return "active"
    # GitHub's open_blockers snapshot takes precedence over labels. A node
    # that became blocked after being claimed/reviewed must not be reported as
    # merely active or gated and then retried through the wrong recovery lane.
    if _blocker_numbers(node):
        return "open"
    labels = set(node.get("labels") or [])
    if "in-progress" in labels:
        return "active"
    if labels & REVIEW_LABELS:
        return "gated"
    return "open"


def _work_graph_snapshot(tree: dict[str, Any]) -> dict[str, Any]:
    flattened = list(_walk(tree))
    by_number = {node["number"]: node for node in flattened}
    nodes: list[dict[str, Any]] = []

    def append(node: dict[str, Any], parent: dict[str, Any] | None) -> None:
        blockers = []
        for number in _blocker_numbers(node):
            blocker = by_number.get(number)
            # GitHub's open_blockers field is authoritative. Keep a stale or
            # external entry unresolved instead of letting a completed graph
            # node accidentally satisfy it. Open in-tree blockers retain their
            # node id so task-worker can still detect dependency cycles.
            if blocker is not None and _graph_status(blocker) != "completed":
                blockers.append(str(number))
            else:
                blockers.append(f"github-open-blocker-{number}")
        nodes.append({
            "node_id": str(node["number"]),
            "key": f"issue-{node['number']}",
            "title": node.get("title") or f"Issue #{node['number']}",
            "parent_id": None if parent is None else str(parent["number"]),
            "blocked_by": blockers,
            "status": _graph_status(node),
        })
        for child in _children(node):
            append(child, node)

    append(tree, None)
    return {
        "schema": "task-worker.work-graph/v1",
        "graph_id": f"issue-tree-{tree['number']}",
        "nodes": nodes,
    }


def evaluate_tree(
    tree: dict[str, Any],
    *,
    spawned_set: set[int] | None = None,
    failed_set: set[int] | None = None,
) -> dict[str, Any]:
    spawned_set = spawned_set or set()
    failed_set = failed_set or set()
    result = _base_result()
    if _summary(tree).get("total", 0) == 0:
        return _stop(result, "empty_tree")

    descendants = list(_walk(tree))[1:]
    by_number = {node["number"]: node for node in _walk(tree)}
    for node in descendants:
        state = node.get("state")
        if state == "closeout_failed":
            result["closeout_failed"].append(item(node, reason=(node.get("closeout_failed") or {}).get("reason") or "closeout_failed"))
            continue
        if state == "closeout_started":
            result["closeout_running"].append(item(node))
            continue
        if state == "closeout_ready":
            result["closeout_ready"].append(item(node))
    try:
        plan = task_worker_bridge.plan_graph(_work_graph_snapshot(tree))
    except task_worker_bridge.TaskWorkerBridgeError as exc:
        if exc.code == "dependency_cycle":
            return _stop(result, "dep_cycle")
        raise

    for entry in plan["blocked"]:
        node = by_number[int(entry["node_id"])]
        blocked = item(node)
        blocked["open_blockers"] = list(node.get("open_blockers") or [])
        result["blocked"].append(blocked)
    for entry in plan["active"]:
        node = by_number[int(entry["node_id"])]
        if node.get("state") in {"closeout_ready", "closeout_started", "closeout_failed"}:
            continue
        if node["number"] in failed_set:
            result["stuck"].append(item(node, reason="spawned_failed"))
        elif node["number"] not in spawned_set:
            result["stuck"].append(item(node, reason="prior_run"))
    for entry in plan["gated"]:
        node = by_number[int(entry["node_id"])]
        result["review_waiting"].append(item(node))
    for entry in plan["ready_actions"]:
        number = int(entry["node_id"])
        if number != tree["number"]:
            result["ready"].append(item(by_number[number]))
    for entry in plan["integration_candidates"]:
        number = int(entry["node_id"])
        node = by_number[number]
        candidate = item(node)
        candidate["gear"] = _effective_gear(node)
        if number == tree["number"]:
            result["container_done"] = candidate
        else:
            result["done_parents"].append(candidate)

    # Branch order mirrors the skill loop: stuck first, then completed parents,
    # then review gate, then ready work.
    if result["stuck"]:
        return _stop(result, "stuck")
    if result["closeout_failed"]:
        return _stop(result, "closeout_failed")
    if result["container_done"] is not None:
        return result
    if result["done_parents"]:
        return result
    if result["closeout_ready"] or result["closeout_running"]:
        return result
    if result["review_waiting"]:
        return _stop(result, "human_gate_review")
    if result["ready"]:
        return result
    if result["blocked"]:
        return _stop(result, "no_progress")
    return _stop(result, "no_progress")


def collect_tree(
    number: int,
    fetch_page: Callable[[int, str | None], dict[str, Any]],
) -> dict[str, Any]:
    pages = []
    after = None
    while True:
        page = fetch_page(number, after)
        pages.append(page)
        if not page.get("has_next_page"):
            break
        after = page.get("end_cursor")
    root = dict(pages[0]["node"])
    children = [child for page in pages for child in page.get("children", [])]
    root["children"] = [collect_tree(child["number"], fetch_page) for child in children]
    root["subissues_summary"] = {
        "total": len(root["children"]),
        "completed": sum(1 for child in root["children"] if _is_complete_state(child.get("state"))),
    }
    return root


def _run(cmd: list[str], *, code: str) -> str:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"{code}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _repo() -> tuple[str, str]:
    data = json.loads(_run(["gh", "repo", "view", "--json", "owner,name"], code="repo_view_failed"))
    return data["owner"]["login"], data["name"]


def _open_blockers(owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    out = _run([
        "gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by",
        "--jq", '[.[] | select(.state=="open") | {number,title}]',
    ], code="dependency_api_failed")
    return json.loads(out) if out else []


def _labels(issue: dict[str, Any]) -> list[str]:
    labels = issue.get("labels") or {}
    return [node["name"] for node in labels.get("nodes", [])]


def _node(issue: dict[str, Any], owner: str, repo: str) -> dict[str, Any]:
    return {
        "number": issue["number"],
        "title": issue.get("title") or "",
        "state": issue.get("state") or "",
        "labels": _labels(issue),
        "open_blockers": _open_blockers(owner, repo, issue["number"]),
        "subissues_summary": issue.get("subIssuesSummary") or {"total": 0, "completed": 0},
        "children": [],
    }


def github_fetch_page(owner: str, repo: str) -> Callable[[int, str | None], dict[str, Any]]:
    query = (
        "query($o:String!,$r:String!,$n:Int!,$after:String){"
        "repository(owner:$o,name:$r){issue(number:$n){number title state "
        "labels(first:20){nodes{name}} subIssuesSummary{total completed} "
        "subIssues(first:50,after:$after){pageInfo{hasNextPage endCursor}"
        "nodes{number title state labels(first:20){nodes{name}} subIssuesSummary{total completed}}}}}}"
    )

    def fetch(number: int, after: str | None) -> dict[str, Any]:
        args = [
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-F", f"o={owner}",
            "-F", f"r={repo}",
            "-F", f"n={number}",
        ]
        if after:
            args.extend(["-F", f"after={after}"])
        data = json.loads(_run(args, code="graphql_failed"))
        issue = data["data"]["repository"]["issue"]
        subissues = issue["subIssues"]
        return {
            "node": _node(issue, owner, repo),
            "children": [_node(child, owner, repo) for child in subissues["nodes"]],
            "has_next_page": subissues["pageInfo"]["hasNextPage"],
            "end_cursor": subissues["pageInfo"]["endCursor"],
        }

    return fetch


def _decision_summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "ready", "blocked", "review_waiting", "stuck", "done_parents",
        "closeout_ready", "closeout_running", "closeout_failed",
    )
    summary: dict[str, Any] = {"ok": payload.get("ok"), "stop_reason": payload.get("stop_reason")}
    for key in keys:
        summary[key] = [int(item["number"]) for item in payload.get(key) or []]
    container_done = payload.get("container_done")
    summary["container_done"] = int(container_done["number"]) if container_done else None
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", nargs="?", type=int)
    parser.add_argument("--spawned", default="", help="comma/space-separated issue numbers active in this run")
    parser.add_argument("--failed", default="", help="comma/space-separated issue numbers failed in this run")
    parser.add_argument("--ledger", help="persistent orchestrate ledger JSON; merged with --spawned/--failed")
    parser.add_argument("--from-ledger", help="evaluate from local ledger only; no GitHub read")
    parser.add_argument("--reconcile-github", help="refresh ledger from GitHub, then evaluate")
    parser.add_argument("--read-reason", help="reason for GitHub reads written to the orchestrate ledger")
    parser.add_argument("--fixture-json", help="read a tree fixture instead of calling gh")
    parser.add_argument("--dispatch", choices=("worker", "manual"), help="override .task-worker.yml dispatch")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        ledger_path = args.from_ledger or args.reconcile_github or args.ledger
        ledger = None
        if args.from_ledger:
            ledger = load_ledger(args.from_ledger)
            tree = tree_from_ledger(ledger, args.container)
        elif args.fixture_json:
            with open(args.fixture_json, encoding="utf-8") as fp:
                tree = json.load(fp)
            if ledger_path:
                ledger = record_snapshot(ledger_path, tree)
        else:
            if args.container is None:
                raise ValueError("container issue is required unless --from-ledger is used")
            owner, repo = _repo()
            tree = collect_tree(args.container, github_fetch_page(owner, repo))
            if ledger_path:
                ledger = record_snapshot(ledger_path, tree)
                operation = "reconcile_github" if args.reconcile_github else "container_fetch"
                reason = args.read_reason or ("session_start" if args.reconcile_github else "compat_container_fetch")
                ledger = record_github_read(ledger_path, reason=reason, operation=operation, root=args.container)

        spawned = parse_number_set(args.spawned)
        failed = parse_number_set(args.failed)
        if ledger_path and Path(ledger_path).exists():
            ledger = ledger or load_ledger(ledger_path)
            spawned |= ledger_number_set(ledger, "spawned")
            failed |= ledger_number_set(ledger, "failed")
        payload = evaluate_tree(tree, spawned_set=spawned, failed_set=failed)
        dispatch = args.dispatch
        if dispatch is None and Path(".task-worker.yml").is_file():
            worker_config, findings, _ = task_config.load_worker_config(".task-github.yml")
            errors = [item for item in findings if item.get("severity") == "error"]
            if errors:
                raise ValueError("invalid task-worker config: " + ",".join(item["code"] for item in errors))
            dispatch = worker_config.get("dispatch", "worker")
        if dispatch == "manual":
            payload["manual_actions"] = payload.pop("ready")
            payload["ready"] = []
            payload["ok"] = False
            payload["stop_reason"] = "manual_dispatch"
        if args.from_ledger:
            record_read_decision(
                args.from_ledger,
                source="ledger",
                mode="from_ledger",
                root=tree.get("number"),
                result=_decision_summary(payload),
            )
    except task_worker_bridge.TaskWorkerBridgeError as exc:
        payload = {
            **_base_result(),
            "ok": False,
            "stop_reason": exc.code,
            "message": exc.message,
        }
    except Exception as exc:  # CLI boundary: never silently degrade to ready=[]
        payload = {**_base_result(), "ok": False, "stop_reason": "api_failure", "message": str(exc)}
    print(json.dumps(payload, ensure_ascii=False) if args.as_json else json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
