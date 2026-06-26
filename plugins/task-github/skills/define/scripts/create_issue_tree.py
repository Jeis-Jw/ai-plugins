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


def validate_spec(spec: dict) -> dict:
    root = spec.get("root")
    if not isinstance(root, dict):
        raise IssueTreeError("bad_spec", "root must be an object")
    children = spec.get("children", [])
    if not isinstance(children, list):
        raise IssueTreeError("bad_spec", "children must be a list")

    root_body = _require_text(root, "body", "root")
    execution_contract = root.get("execution_contract", spec.get("execution_contract"))
    if execution_contract is not None:
        if not isinstance(execution_contract, dict):
            raise IssueTreeError("bad_spec", "root.execution_contract must be an object")
        root_body = context_bundle.materialize_execution_contract(root_body, execution_contract)

    root_out = {
        "title": _require_text(root, "title", "root"),
        "body": root_body,
    }

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
        blocked_by = child.get("blocked_by", [])
        if not isinstance(blocked_by, list) or not all(isinstance(v, str) for v in blocked_by):
            raise IssueTreeError("bad_spec", f"{where}.blocked_by must be a string list")
        normalized_child = {
            "key": key,
            "title": _require_text(child, "title", where),
            "body": _require_text(child, "body", where),
            "affects_paths": _require_string_list(child, "affects_paths", where),
            "blocked_by": blocked_by,
        }
        _assert_child_quality(normalized_child, where)
        child_out.append(normalized_child)

    for child in child_out:
        for blocker in child["blocked_by"]:
            if blocker not in keys:
                raise IssueTreeError("unknown_dependency",
                                     f"{child['key']} blocked_by unknown child key: {blocker}")
            if blocker == child["key"]:
                raise IssueTreeError("self_dependency",
                                     f"{child['key']} cannot block itself")

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

    return {"root": root_out, "children": child_out, "strict_deps": bool(spec.get("strict_deps"))}


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
    }


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
    parent_id = issue_node_id(owner, repo, root_number)
    numbers = {}
    children_out = []
    for child in spec["children"]:
        number = create_child_issue(repo_id, parent_id, child)
        numbers[child["key"]] = number
        children_out.append({"key": child["key"], "number": number})
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
