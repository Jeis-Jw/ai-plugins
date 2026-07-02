#!/usr/bin/env python3
"""Create a root GitHub issue with parented child issues from a JSON spec.

The dry-run path is intentionally network-free so define workflows can validate
tree shape before touching GitHub.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, List

TASK_GITHUB_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TASK_GITHUB_DIR / "scripts"))

import context_bundle  # noqa: E402


API_VERSION = "2026-03-10"
PARENT_METHOD = "graphql_create_issue_parentIssueId"

DOMAIN_KEYWORDS = [
    "backend", "mobile", "auth", "wallet", "ops", "infra", "api", "ui",
    "백엔드", "모바일", "인증", "지갑", "운영", "인프라",
]
VERTICAL_SLICE_RE = re.compile(r"vertical\s*slice|\be2e\b|onboarding|온보딩", re.I)


class IssueTreeError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def read_spec(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IssueTreeError("spec_read_failed", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise IssueTreeError("spec_json_invalid", str(exc)) from exc


def _require_text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IssueTreeError("bad_spec", f"{where}.{key} must be a non-empty string")
    return value


def _require_string_list(obj: dict, key: str, where: str) -> List[str]:
    value = obj.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise IssueTreeError("quality_gate_failed", f"{where}.{key} must be a non-empty string list")
    return [v.strip() for v in value]


def _assert_child_quality(child: dict, where: str) -> None:
    body = child["body"]
    if not re.search(r"(완료\s*기준|completion\s*criteria|done\s*criteria)", body, re.I):
        raise IssueTreeError("quality_gate_failed",
                             f"{where}.body must include completion criteria")
    if not re.search(r"(검증|테스트|verification|verify|test)", body, re.I):
        raise IssueTreeError("quality_gate_failed",
                             f"{where}.body must include verification/test criteria")
    if not re.search(r"(affects[_ -]?paths?|touched[_ -]?paths?|영향\s*경로|경로|파일|paths?)", body, re.I):
        raise IssueTreeError("quality_gate_failed",
                             f"{where}.body must include affected path/file anchor")


def _paths_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    return fnmatch.fnmatch(left, right) or fnmatch.fnmatch(right, left)


def _cluster_key(path: str) -> str:
    """Domain cluster key: up to 2 leading path segments, stopping at a glob."""
    segments = [s for s in path.split("/") if s and s != "**"]
    key_segments: List[str] = []
    for seg in segments:
        if "*" in seg:
            break
        key_segments.append(seg)
        if len(key_segments) == 2:
            break
    return "/".join(key_segments) if key_segments else path


def _detect_flat_understructuring(topology: str | None, leaves: List[dict], root_body: str) -> dict | None:
    """Static heuristic: 2+ of 5 signals on a flat leaf-only tree suggest stacked."""
    if str(topology) != "flat" or not leaves:
        return None

    signals: List[str] = []

    leaf_count = len(leaves)
    if leaf_count >= 6:
        signals.append(f"leaf_count>={leaf_count}")

    clusters = sorted({_cluster_key(p) for leaf in leaves for p in leaf["affects_paths"]})
    if len(clusters) >= 3:
        signals.append(f"path_clusters>={len(clusters)}")

    keyword_hits = {kw: 0 for kw in DOMAIN_KEYWORDS}
    for leaf in leaves:
        title_lower = leaf["title"].lower()
        for kw in DOMAIN_KEYWORDS:
            if kw.lower() in title_lower:
                keyword_hits[kw] += 1
    repeated_keywords = [kw for kw, count in keyword_hits.items() if count >= 2]
    if len(repeated_keywords) >= 2:
        signals.append(f"domain_prefix_repeated={repeated_keywords}")

    leaf_cluster = {leaf["key"]: _cluster_key(leaf["affects_paths"][0]) for leaf in leaves}
    cross_cluster_deps = sum(
        1
        for leaf in leaves
        for blocker in leaf["blocked_by"]
        if blocker in leaf_cluster and leaf_cluster[blocker] != leaf_cluster[leaf["key"]]
    )
    if cross_cluster_deps >= 2:
        signals.append(f"cross_cluster_blocked_by>={cross_cluster_deps}")

    if VERTICAL_SLICE_RE.search(root_body) and len(clusters) >= 2:
        signals.append("vertical_slice_multi_surface")

    if len(signals) < 2:
        return None

    return {
        "code": "flat_maybe_understructured",
        "message": (
            f"{leaf_count}개 리프가 {len(clusters)}개 경로 클러스터로 갈립니다 — "
            f"stacked topology 후보입니다. 신호: {', '.join(signals)}."
        ),
        "suggested_epics": clusters,
    }


def validate_spec(spec: dict) -> dict:
    root = spec.get("root")
    if not isinstance(root, dict):
        raise IssueTreeError("bad_spec", "root must be an object")
    children = spec.get("children", [])
    if not isinstance(children, list):
        raise IssueTreeError("bad_spec", "children must be a list")

    root_body = _require_text(root, "body", "root")
    execution_contract = root.get("execution_contract", spec.get("execution_contract"))
    topology = None
    if execution_contract is not None:
        if not isinstance(execution_contract, dict):
            raise IssueTreeError("bad_spec", "root.execution_contract must be an object")
        topology = execution_contract.get("topology")
        root_body = context_bundle.materialize_execution_contract(root_body, execution_contract)

    root_out = {
        "title": _require_text(root, "title", "root"),
        "body": root_body,
    }

    # Pass 1: parse keys, parent refs, blocked_by. affects_paths/quality gate
    # are role-dependent (leaf vs epic), so they wait until roles are known.
    child_out: List[dict] = []
    keys = set()
    for idx, child in enumerate(children):
        where = f"children[{idx}]"
        if not isinstance(child, dict):
            raise IssueTreeError("bad_spec", f"{where} must be an object")
        key = _require_text(child, "key", where)
        if key in keys:
            raise IssueTreeError("duplicate_key", f"duplicate child key: {key}")
        keys.add(key)
        parent = child.get("parent")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            raise IssueTreeError("bad_spec", f"{where}.parent must be a child key string or omitted")
        blocked_by = child.get("blocked_by", [])
        if not isinstance(blocked_by, list) or not all(isinstance(v, str) for v in blocked_by):
            raise IssueTreeError("bad_spec", f"{where}.blocked_by must be a string list")
        cross_parent_reason = child.get("cross_parent_dependency_reason")
        if cross_parent_reason is not None and (
            not isinstance(cross_parent_reason, str) or not cross_parent_reason.strip()
        ):
            raise IssueTreeError(
                "bad_spec", f"{where}.cross_parent_dependency_reason must be a non-empty string"
            )
        child_out.append({
            "key": key,
            "title": _require_text(child, "title", where),
            "body": _require_text(child, "body", where),
            "parent": parent.strip() if isinstance(parent, str) else None,
            "affects_paths": child.get("affects_paths"),
            "blocked_by": blocked_by,
            "cross_parent_dependency_reason": cross_parent_reason,
            "_where": where,
        })

    # Parent edges: must reference a known key, no self-parent, no cycles.
    # A key that is some child's parent is an intermediate node (epic); the
    # rest are leaves. Branch derivation is structural (workflow.md §8), so
    # define only needs the shape — per-epic parent_branch is not stored here.
    by_key = {c["key"]: c for c in child_out}
    epic_keys = set()
    for c in child_out:
        parent = c["parent"]
        if parent is None:
            continue
        if parent not in keys:
            raise IssueTreeError("unknown_parent", f"{c['key']} parent unknown child key: {parent}")
        if parent == c["key"]:
            raise IssueTreeError("self_parent", f"{c['key']} cannot parent itself")
        epic_keys.add(parent)
    for c in child_out:
        seen = set()
        cur = c["parent"]
        while cur is not None:
            if cur in seen:
                raise IssueTreeError("parent_cycle", f"parent cycle reaches {c['key']}")
            seen.add(cur)
            cur = by_key[cur]["parent"]

    # Pass 2: role-based quality gate. Leaves are PR units — full gate +
    # required affects_paths. Epics are branch containers — lighter gate,
    # affects_paths optional (empty → excluded from overlap checks below).
    for c in child_out:
        if c["key"] in epic_keys:
            ap = c["affects_paths"]
            if ap is None:
                ap = []
            elif not isinstance(ap, list) or not all(isinstance(v, str) and v.strip() for v in ap):
                raise IssueTreeError("bad_spec", f"{c['_where']}.affects_paths must be a string list")
            c["affects_paths"] = [v.strip() for v in ap]
        else:
            c["affects_paths"] = _require_string_list(c, "affects_paths", c["_where"])
            _assert_child_quality(c, c["_where"])

    for child in child_out:
        for blocker in child["blocked_by"]:
            if blocker not in keys:
                raise IssueTreeError("unknown_dependency",
                                     f"{child['key']} blocked_by unknown child key: {blocker}")
            if blocker == child["key"]:
                raise IssueTreeError("self_dependency",
                                     f"{child['key']} cannot block itself")
            blocker_parent = by_key[blocker]["parent"]
            if blocker_parent != child["parent"] and not child["cross_parent_dependency_reason"]:
                raise IssueTreeError(
                    "cross_parent_dependency_detected",
                    (f"{child['key']} blocked_by {blocker} crosses parent boundaries "
                     f"(blocked_by는 기본적으로 sibling-only). tree를 재구성하거나 "
                     f"{child['_where']}.cross_parent_dependency_reason으로 명시적 사유를 남기세요."),
                )

    for idx, left in enumerate(child_out):
        for right in child_out[idx + 1:]:
            overlaps = [
                (lp, rp)
                for lp in left["affects_paths"]
                for rp in right["affects_paths"]
                if _paths_overlap(lp, rp)
            ]
            if overlaps and not (
                left["key"] in right["blocked_by"] or right["key"] in left["blocked_by"]
            ):
                lp, rp = overlaps[0]
                raise IssueTreeError(
                    "path_overlap_requires_dependency",
                    (f"{left['key']} and {right['key']} share affected paths "
                     f"({lp!r}, {rp!r}); declare blocked_by in one direction"),
                )

    warnings: List[dict] = []
    if str(topology) == "stacked" and child_out and not epic_keys:
        warnings.append({
            "code": "stacked_without_epics",
            "message": (
                "topology=stacked이지만 중간 노드(epic)가 없습니다 — 모든 리프가 root "
                "브랜치에서 분기되어 트랙 격리가 없습니다. 트랙별 독립 브랜치를 원하면 "
                "트랙을 parent로 묶고, 의도된 평면이면 topology=flat을 쓰세요."
            ),
        })
    elif str(topology) == "flat":
        leaves = [c for c in child_out if c["key"] not in epic_keys]
        flat_warning = _detect_flat_understructuring(topology, leaves, root_out["body"])
        if flat_warning:
            warnings.append(flat_warning)

    for c in child_out:
        c.pop("_where", None)

    return {
        "root": root_out,
        "children": child_out,
        "strict_deps": bool(spec.get("strict_deps")),
        "epics": sorted(epic_keys),
        "warnings": warnings,
    }


def build_plan(spec: dict) -> dict:
    dependencies = []
    for child in spec["children"]:
        for blocker in child["blocked_by"]:
            dependencies.append({"child": child["key"], "blocked_by": blocker})
    return {
        "ok": True,
        "parent_method": PARENT_METHOD,
        "dependency_api_version": API_VERSION,
        "root": spec["root"],
        "children": spec["children"],
        "dependencies": dependencies,
        "strict_deps": bool(spec.get("strict_deps")),
        "epics": spec.get("epics", []),
        "warnings": spec.get("warnings", []),
    }


def _topo_order(children: List[dict]) -> List[dict]:
    """Order children so every parent precedes its descendants.

    validate_spec already proved the parent graph is acyclic, so this always
    terminates; the no-progress guard is defensive only.
    """
    ordered: List[dict] = []
    placed = set()
    remaining = list(children)
    while remaining:
        next_remaining = []
        for child in remaining:
            if child["parent"] is None or child["parent"] in placed:
                ordered.append(child)
                placed.add(child["key"])
            else:
                next_remaining.append(child)
        if len(next_remaining) == len(remaining):
            raise IssueTreeError("parent_cycle", "unable to order children by parent")
        remaining = next_remaining
    return ordered


def gh(args: List[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["gh", *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise IssueTreeError("gh_failed", result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def repo_context() -> tuple[str, str, str]:
    repo = json.loads(gh(["repo", "view", "--json", "owner,name"]))
    owner = repo["owner"]["login"]
    name = repo["name"]
    repo_id = gh([
        "api", "graphql",
        "-f", "query=query($o:String!,$r:String!){ repository(owner:$o,name:$r){ id } }",
        "-F", f"o={owner}",
        "-F", f"r={name}",
        "--jq", ".data.repository.id",
    ])
    return owner, name, repo_id


def issue_node_id(owner: str, repo: str, number: int) -> str:
    return gh([
        "api", "graphql",
        "-f", "query=query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ id } } }",
        "-F", f"o={owner}",
        "-F", f"r={repo}",
        "-F", f"n={number}",
        "--jq", ".data.repository.issue.id",
    ])


def create_root_issue(root: dict) -> int:
    output = gh(["issue", "create", "--title", root["title"], "--body", root["body"]])
    try:
        return int(output.rstrip("/").split("/")[-1])
    except ValueError as exc:
        raise IssueTreeError("issue_number_parse_failed", output) from exc


def create_child_issue(repo_id: str, parent_id: str, child: dict) -> int:
    output = gh([
        "api", "graphql",
        "-f", (
            "query=mutation($rid:ID!,$pid:ID!,$t:String!,$b:String!){ "
            "createIssue(input:{ repositoryId:$rid, parentIssueId:$pid, title:$t, body:$b })"
            "{ issue { number } } }"
        ),
        "-F", f"rid={repo_id}",
        "-F", f"pid={parent_id}",
        "-F", f"t={child['title']}",
        "-F", f"b={child['body']}",
        "--jq", ".data.createIssue.issue.number",
    ])
    return int(output)


def issue_database_id(owner: str, repo: str, number: int, *, gh_func: Callable = gh) -> int:
    output = gh_func([
        "api", "-H", f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{owner}/{repo}/issues/{number}",
        "--jq", ".id",
    ])
    return int(output)


def add_dependency(
    owner: str,
    repo: str,
    child_number: int,
    blocker_number: int,
    *,
    strict: bool = False,
    gh_func: Callable = gh,
) -> bool:
    try:
        blocker_id = issue_database_id(owner, repo, blocker_number, gh_func=gh_func)
        gh_func([
            "api", "-X", "POST",
            "-H", f"X-GitHub-Api-Version: {API_VERSION}",
            f"repos/{owner}/{repo}/issues/{child_number}/dependencies/blocked_by",
            "-F", f"issue_id={blocker_id}",
        ])
        return True
    except IssueTreeError as exc:
        if strict:
            raise IssueTreeError(
                "dep_create_failed",
                f"failed to create dependency #{child_number} blocked_by #{blocker_number}: {exc.message}",
            ) from exc
        gh_func([
            "issue", "comment", str(child_number),
            "--body", (
                f"[관찰] dependency API 실패: 이 이슈는 #{blocker_number} 완료 뒤 "
                "진행되어야 한다. GitHub dependency가 기록되지 않았으므로 start 전 "
                "수동 확인 필요."
            ),
        ])
        return False


def execute(spec: dict) -> dict:
    owner, repo, repo_id = repo_context()
    strict_deps = bool(spec.get("strict_deps"))
    root_number = create_root_issue(spec["root"])
    # node_ids[None] = root; node_ids[epic_key] = that epic's GraphQL node id.
    # Topological order guarantees an epic exists before its children create.
    node_ids = {None: issue_node_id(owner, repo, root_number)}
    numbers = {}
    children_out = []
    for child in _topo_order(spec["children"]):
        parent_id = node_ids[child["parent"]]
        number = create_child_issue(repo_id, parent_id, child)
        numbers[child["key"]] = number
        node_ids[child["key"]] = issue_node_id(owner, repo, number)
        children_out.append({"key": child["key"], "number": number, "parent": child["parent"]})
    dependencies_out = []
    for child in spec["children"]:
        for blocker in child["blocked_by"]:
            materialized = add_dependency(
                owner, repo, numbers[child["key"]], numbers[blocker], strict=strict_deps,
            )
            dependencies_out.append({
                "child": child["key"],
                "child_number": numbers[child["key"]],
                "blocked_by": blocker,
                "blocked_by_number": numbers[blocker],
                "materialized": materialized,
            })
    return {
        "ok": True,
        "owner": owner,
        "repo": repo,
        "root_number": root_number,
        "children": children_out,
        "dependencies": dependencies_out,
        "strict_deps": strict_deps,
        "epics": spec.get("epics", []),
        "parent_method": PARENT_METHOD,
        "dependency_api_version": API_VERSION,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="JSON spec path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-deps", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def emit(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        spec = validate_spec(read_spec(Path(args.spec)))
        spec["strict_deps"] = bool(spec.get("strict_deps") or args.strict_deps)
        payload = build_plan(spec) if args.dry_run else execute(spec)
    except IssueTreeError as exc:
        emit({"ok": False, "error_code": exc.error_code, "message": exc.message},
             as_json=args.as_json)
        return 2
    emit(payload, as_json=args.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
