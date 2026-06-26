#!/usr/bin/env python3
"""Derive task-github orchestrate ready/stop sets from a GitHub issue tree."""

from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any, Callable, Iterable

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
    return out


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    return list(node.get("children") or [])


def _summary(node: dict[str, Any]) -> dict[str, int]:
    children = _children(node)
    return node.get("subissues_summary") or {
        "total": len(children),
        "completed": sum(1 for child in children if child.get("state") == "CLOSED"),
    }


def _walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in _children(node):
        yield from _walk(child)


def _is_open(node: dict[str, Any]) -> bool:
    return node.get("state") == "OPEN"


def _is_leaf(node: dict[str, Any]) -> bool:
    return _summary(node).get("total", 0) == 0


def _complete_parent(node: dict[str, Any]) -> bool:
    summary = _summary(node)
    return _is_open(node) and summary.get("total", 0) > 0 and summary.get("completed") == summary.get("total")


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
        "done_parents": [],
        "container_done": None,
    }


def _stop(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["ok"] = False
    result["stop_reason"] = reason
    return result


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
    open_numbers = {node["number"] for node in descendants if _is_open(node)}
    blocked_nodes: list[dict[str, Any]] = []

    for node in descendants:
        labels = set(node.get("labels") or [])
        blockers = _blocker_numbers(node)
        if blockers:
            blocked = item(node)
            blocked["open_blockers"] = list(node.get("open_blockers") or [])
            blocked_nodes.append(blocked)
            continue
        if _complete_parent(node):
            result["done_parents"].append(item(node))
            continue
        if not _is_open(node) or not _is_leaf(node):
            continue
        if "in-progress" in labels:
            if node["number"] in failed_set:
                result["stuck"].append(item(node, reason="spawned_failed"))
            elif node["number"] not in spawned_set:
                result["stuck"].append(item(node, reason="prior_run"))
            continue
        if labels & REVIEW_LABELS:
            result["review_waiting"].append(item(node))
            continue
        result["ready"].append(item(node))

    result["blocked"] = blocked_nodes

    # Branch order mirrors the skill loop: stuck first, then completed parents,
    # then review gate, then ready work.
    if result["stuck"]:
        return _stop(result, "stuck")
    if _complete_parent(tree) and not _blocker_numbers(tree):
        result["container_done"] = item(tree)
        return result
    if result["done_parents"]:
        return result
    if result["review_waiting"]:
        return _stop(result, "human_gate_review")
    if result["ready"]:
        return result
    if blocked_nodes:
        blocked_by = {number for node in descendants for number in _blocker_numbers(node)}
        return _stop(result, "dep_cycle" if blocked_by and blocked_by <= open_numbers else "no_progress")
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
        "completed": sum(1 for child in root["children"] if child.get("state") == "CLOSED"),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", type=int)
    parser.add_argument("--spawned", default="", help="comma-separated issue numbers active in this run")
    parser.add_argument("--failed", default="", help="comma-separated issue numbers failed in this run")
    parser.add_argument("--fixture-json", help="read a tree fixture instead of calling gh")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    def nums(raw: str) -> set[int]:
        return {int(part) for part in raw.split(",") if part.strip()}

    try:
        if args.fixture_json:
            with open(args.fixture_json, encoding="utf-8") as fp:
                tree = json.load(fp)
        else:
            owner, repo = _repo()
            tree = collect_tree(args.container, github_fetch_page(owner, repo))
        payload = evaluate_tree(tree, spawned_set=nums(args.spawned), failed_set=nums(args.failed))
    except Exception as exc:  # CLI boundary: never silently degrade to ready=[]
        payload = {**_base_result(), "ok": False, "stop_reason": "api_failure", "message": str(exc)}
    print(json.dumps(payload, ensure_ascii=False) if args.as_json else json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
