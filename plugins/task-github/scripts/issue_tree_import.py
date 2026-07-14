#!/usr/bin/env python3
"""Import an existing GitHub Issue tree into task-worker without rewriting it.

The importer creates an immutable DefinitionArtifact, a provider-normalized work
graph snapshot, compact context, and a persistent provider binding. `manual`
keeps execution with external developers; `worker` exposes the same ready set to
task-github orchestration. GitHub remains the remote execution-state authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

import task_worker_bridge


STATE_LABELS = {"in-progress": "active", "in-review": "gated", "changes-requested": "gated"}


class ImportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _run(command: list[str]) -> str:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise ImportError("github_read_failed", result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _repo_context() -> tuple[str, str]:
    payload = json.loads(_run(["gh", "repo", "view", "--json", "owner,name"]))
    return payload["owner"]["login"], payload["name"]


def _labels(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(value) for value in raw]
    if isinstance(raw, dict):
        return [str(node["name"]) for node in raw.get("nodes", []) if isinstance(node, dict) and node.get("name")]
    return []


def _fetch_page(owner: str, repo: str, number: int, after: str | None) -> dict[str, Any]:
    query = (
        "query($o:String!,$r:String!,$n:Int!,$after:String){repository(owner:$o,name:$r){"
        "issue(number:$n){number title body state labels(first:50){nodes{name}} "
        "subIssues(first:50,after:$after){pageInfo{hasNextPage endCursor}nodes{number}}}}}"
    )
    command = [
        "gh", "api", "graphql", "-f", f"query={query}",
        "-F", f"o={owner}", "-F", f"r={repo}", "-F", f"n={number}",
    ]
    if after:
        command.extend(["-F", f"after={after}"])
    issue = json.loads(_run(command))["data"]["repository"]["issue"]
    if not issue:
        raise ImportError("issue_not_found", f"GitHub Issue #{number} was not found")
    return issue


def _open_blockers(owner: str, repo: str, number: int) -> list[int]:
    output = _run([
        "gh", "api", f"repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by",
        "--jq", '[.[] | select(.state=="open") | .number]',
    ])
    return [int(value) for value in json.loads(output or "[]")]


def fetch_tree(owner: str, repo: str, number: int) -> dict[str, Any]:
    pages = []
    after = None
    while True:
        page = _fetch_page(owner, repo, number, after)
        pages.append(page)
        info = page["subIssues"]["pageInfo"]
        if not info["hasNextPage"]:
            break
        after = info["endCursor"]
    first = pages[0]
    child_numbers = [
        child["number"]
        for page in pages
        for child in page["subIssues"]["nodes"]
    ]
    return {
        "number": first["number"],
        "title": first.get("title") or f"Issue #{number}",
        "body": first.get("body") or "",
        "state": first.get("state") or "OPEN",
        "labels": _labels(first.get("labels")),
        "open_blockers": _open_blockers(owner, repo, number),
        "children": [fetch_tree(owner, repo, child) for child in child_numbers],
    }


def _walk(tree: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any] | None]]:
    stack = [(tree, None)]
    while stack:
        node, parent = stack.pop()
        yield node, parent
        stack.extend((child, node) for child in reversed(node.get("children") or []))


def _node_key(number: int) -> str:
    return f"issue-{number}"


def _body(node: dict[str, Any]) -> str:
    body = str(node.get("body") or "").strip()
    return body or f"GitHub Issue #{node['number']}에서 가져온 작업."


def _affects_paths(body: str) -> list[str]:
    match = re.search(
        r"(?ims)^##+\s*(?:affects paths|영향 경로)\s*$\s*(.*?)(?=^##+\s|\Z)",
        body,
    )
    if not match:
        return []
    return [
        item.strip().strip("`")
        for item in re.findall(r"(?m)^\s*[-*]\s+(.+?)\s*$", match.group(1))
        if item.strip()
    ]


def build_import(
    tree: dict[str, Any], *, owner: str, repo: str, dispatch: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if dispatch not in {"manual", "worker"}:
        raise ImportError("bad_dispatch", "dispatch must be manual or worker")
    flattened = list(_walk(tree))
    numbers = [node.get("number") for node, _ in flattened]
    if not numbers or not all(isinstance(value, int) and value > 0 for value in numbers):
        raise ImportError("bad_tree", "every issue node requires a positive number")
    if len(set(numbers)) != len(numbers):
        raise ImportError("bad_tree", "issue tree contains duplicate numbers")
    number_set = set(numbers)
    root = tree
    definition_id = f"github-{owner}-{repo}-issue-{root['number']}"
    if len(definition_id) > 128:
        source_digest = hashlib.sha256(f"{owner}/{repo}#{root['number']}".encode("utf-8")).hexdigest()[:24]
        definition_id = f"github-{source_digest}-issue-{root['number']}"
    children = []
    for node, parent in flattened[1:]:
        blockers = [
            _node_key(number)
            for number in node.get("open_blockers") or []
            if number in number_set and number != root["number"]
        ]
        children.append({
            "key": _node_key(node["number"]),
            "title": str(node.get("title") or f"Issue #{node['number']}"),
            "body": _body(node),
            "parent": None if parent is root else _node_key(parent["number"]),
            "affects_paths": _affects_paths(_body(node)),
            "blocked_by": blockers,
        })
    spec = {
        "definition_id": definition_id,
        "dispatch": dispatch,
        "delivery": "external",
        "root": {
            "stable_key": f"github:{owner}/{repo}#{root['number']}",
            "title": str(root.get("title") or f"Issue #{root['number']}"),
            "body": _body(root),
        },
        "children": children,
        "strict_deps": True,
    }
    graph_nodes = []
    for node, parent in flattened:
        labels = set(_labels(node.get("labels")))
        status = "completed" if str(node.get("state")).upper() == "CLOSED" else "open"
        if status == "open":
            status = next((STATE_LABELS[label] for label in STATE_LABELS if label in labels), status)
        graph_nodes.append({
            "node_id": str(node["number"]),
            "key": "root" if parent is None else _node_key(node["number"]),
            "title": str(node.get("title") or f"Issue #{node['number']}"),
            "parent_id": None if parent is None else str(parent["number"]),
            "blocked_by": [str(value) for value in node.get("open_blockers") or []],
            "status": status,
        })
    graph = {
        "schema": "task-worker.work-graph/v1",
        "graph_id": definition_id,
        "nodes": graph_nodes,
    }
    context = {
        "source": {"provider": "github", "repository": f"{owner}/{repo}", "root_issue": root["number"]},
        "objective": spec["root"]["title"],
        "root_body": spec["root"]["body"],
        "nodes": [
            {
                "number": node["number"], "title": node.get("title") or "",
                "body": _body(node), "state": node.get("state") or "OPEN",
                "labels": _labels(node.get("labels")),
            }
            for node, _ in flattened
        ],
    }
    context["criteria_digest"] = hashlib.sha256(
        json.dumps(context["nodes"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    provider = {
        "repository": f"{owner}/{repo}",
        "root_issue": root["number"],
        "nodes": {"root" if parent is None else _node_key(node["number"]): node["number"] for node, parent in flattened},
        "remote_state_authority": True,
    }
    return spec, graph, context, provider


def materialize(
    tree: dict[str, Any], *, owner: str, repo: str, dispatch: str,
    state_root: Path, store: Path | None = None, wiki_task: str | None = None,
) -> dict[str, Any]:
    spec, graph, context, provider = build_import(tree, owner=owner, repo=repo, dispatch=dispatch)
    definition_store = store or state_root / "definitions"
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        spec_path = temp / "spec.json"
        graph_path = temp / "graph.json"
        context_path = temp / "context.json"
        provider_path = temp / "provider.json"
        for path, value in (
            (spec_path, spec), (graph_path, graph), (context_path, context), (provider_path, provider),
        ):
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        current_pointer = definition_store / spec["definition_id"] / "current.json"
        if current_pointer.is_file():
            pointer = json.loads(current_pointer.read_text(encoding="utf-8"))
            current_path = current_pointer.parent / pointer["path"]
            current_artifact = json.loads(current_path.read_text(encoding="utf-8"))
            current_spec = task_worker_bridge.export_artifact(current_artifact)
            comparable = dict(spec)
            comparable.pop("definition_id", None)
            comparable.pop("delivery", None)
            comparable["root"] = dict(comparable["root"])
            comparable["root"].pop("stable_key", None)
            if current_spec == comparable:
                created = {"ok": True, "artifact": current_artifact, "path": str(current_path)}
            else:
                created = task_worker_bridge.call_worker([
                    "revise", "--spec", str(spec_path), "--previous", str(current_path),
                    "--store", str(definition_store), "--delivery", "external",
                ])
        else:
            created = task_worker_bridge.call_worker([
                "create", "--spec", str(spec_path), "--store", str(definition_store), "--delivery", "external",
            ])
        aliases = [f"{owner}/{repo}#{tree['number']}", f"github:{owner}/{repo}#{tree['number']}"]
        if wiki_task:
            aliases.append(wiki_task)
        binding = task_worker_bridge.bind_artifact(
            created["path"], state_root=state_root, aliases=aliases,
            provider="github", provider_data_path=provider_path,
            context_path=context_path, work_graph_path=graph_path,
        )
    resumed = task_worker_bridge.resume(f"{owner}/{repo}#{tree['number']}", state_root=state_root)
    return {"artifact": created["artifact"], "path": created["path"], "binding": binding, "plan": resumed["plan"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=int, help="live GitHub root Issue number")
    source.add_argument("--tree", help="Issue tree JSON fixture/path")
    parser.add_argument("--owner")
    parser.add_argument("--repo")
    parser.add_argument("--dispatch", choices=("manual", "worker"), default="manual")
    parser.add_argument("--state-root", default=".task-worker/local")
    parser.add_argument("--store")
    parser.add_argument("--wiki-task")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        owner, repo = (args.owner, args.repo)
        if not owner or not repo:
            owner, repo = _repo_context()
        tree = json.loads(Path(args.tree).read_text(encoding="utf-8")) if args.tree else fetch_tree(owner, repo, args.root)
        payload = materialize(
            tree, owner=owner, repo=repo, dispatch=args.dispatch,
            state_root=Path(args.state_root), store=Path(args.store) if args.store else None,
            wiki_task=args.wiki_task,
        )
        result = {"ok": True, **payload}
    except (ImportError, task_worker_bridge.TaskWorkerBridgeError) as exc:
        result = {"ok": False, "error_code": exc.code, "message": exc.message}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"ok": False, "error_code": "import_failed", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False) if args.as_json else result)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
