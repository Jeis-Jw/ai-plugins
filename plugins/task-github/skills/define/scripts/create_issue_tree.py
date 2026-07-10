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
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, List

TASK_GITHUB_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TASK_GITHUB_DIR / "scripts"))

import context_bundle  # noqa: E402
import definition_artifact  # noqa: E402
import task_config  # noqa: E402


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


def _verification_anchor(body: str) -> str | None:
    """Normalized verification command from a leaf body's 검증/verify anchor."""
    m = re.search(r"(?:검증|verification|verify|테스트|tests?)\s*[:：]\s*(.+)", body, re.I)
    return m.group(1).strip().lower() if m else None


# Tokens too generic to signal a shared theme — the pattern is "apply X to
# surface N", so the surface verbs and build-generic nouns are noise; only the X
# (a real feature name) discriminates "same theme, N surfaces" from "N unrelated
# modules". Without stripping the generics, titles like "결제 모듈 구현" /
# "검색 모듈 구현" would intersect on 모듈/구현 and falsely read as one theme.
_THEME_STOPWORDS = {kw.lower() for kw in DOMAIN_KEYWORDS} | {
    # surface/apply verbs
    "apply", "적용", "적용한다", "add", "추가", "update", "갱신", "수정", "fix",
    "refactor", "리팩터", "개선", "support", "지원", "처리", "구성", "설정",
    # build-generic nouns
    "module", "모듈", "implementation", "impl", "구현", "feature", "기능",
    "component", "컴포넌트", "screen", "screens", "화면", "surface", "surfaces",
    "page", "페이지", "work", "작업", "task", "app", "앱",
    # filler
    "the", "to", "for", "and", "with", "of", "in", "on",
}


def _title_theme_tokens(title: str) -> set:
    """Significant lowercased tokens from a title, minus bracket tags/domain/stopwords."""
    stripped = re.sub(r"\[[^\]]*\]", " ", title).lower()
    tokens = re.findall(r"[a-z0-9가-힣]{2,}", stripped)
    return {t for t in tokens if t not in _THEME_STOPWORDS}


def _detect_siblings_maybe_phases(leaves: List[dict]) -> List[dict]:
    """Reverse of flat-understructuring: same-theme sibling leaves fanning out
    from one shared predecessor are phase candidates, not separate leaves.

    Precondition (hard): >=3 same-parent leaves whose blocked_by is exactly one
    common predecessor. Then warn only when a **shared title theme** (a real
    feature name common to all fan leaves, after stripping surface verbs and
    build-generic nouns) is corroborated by **at least one structural signal**
    (single path cluster OR identical verification anchor).

    The theme is load-bearing on purpose: the structural signals alone don't
    discriminate "same theme, N surfaces" (the #119 pathology) from "N unrelated
    modules after a contract" (cut-reason ④) — a monorepo shares one test
    command and co-locates modules under one path prefix, so verification and
    cluster coincide for unrelated work. Only a genuine shared feature name
    separates them; the structural signal then guards against a coincidental
    theme token in a truly scattered polyrepo. Independent modules named
    "결제 모듈"/"검색 모듈" share no feature token once 모듈 is stripped, so they
    stay silent even under one shared test command.
    """
    results: List[dict] = []
    by_parent: dict = {}
    for leaf in leaves:
        by_parent.setdefault(leaf["parent"], []).append(leaf)

    for parent in sorted(by_parent, key=lambda p: p or ""):
        group = by_parent[parent]
        if len(group) < 3:
            continue
        singly = [leaf for leaf in group if len(leaf["blocked_by"]) == 1]
        counts = Counter(leaf["blocked_by"][0] for leaf in singly)
        for predecessor, count in counts.items():
            if count < 3:
                continue
            fan = [leaf for leaf in singly if leaf["blocked_by"][0] == predecessor]

            token_sets = [_title_theme_tokens(leaf["title"]) for leaf in fan]
            common = set.intersection(*token_sets) if token_sets else set()
            if not common:
                continue  # no shared feature name → cannot tell same-theme from unrelated

            signals: List[str] = [f"shared_title_theme={sorted(common)}"]
            clusters = sorted({_cluster_key(p) for leaf in fan for p in leaf["affects_paths"]})
            if len(clusters) == 1:
                signals.append(f"single_path_cluster={clusters[0]}")
            anchors = {_verification_anchor(leaf["body"]) for leaf in fan}
            if len(anchors) == 1 and None not in anchors:
                signals.append("identical_verification")

            if len(signals) < 2:  # theme present but no structural corroboration
                continue

            keys = [leaf["key"] for leaf in fan]
            results.append({
                "code": "siblings_maybe_phases",
                "message": (
                    f"{len(fan)}개 형제 리프({', '.join(keys)})가 공유 선행 노드 "
                    f"{predecessor!r} 뒤로 같은 테마를 나눠 적용하는 fan-out으로 보입니다 — "
                    f"별도 리프 대신 1개 리프 + phase 체크리스트가 세리머니(worktree·closeout·"
                    f"머지엣지)를 아낍니다. 신호: {', '.join(signals)}."
                ),
                "suggested_merge": keys,
                "shared_predecessor": predecessor,
            })
    return results


def _bool_option(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on", "o"}


def review_required_from_config(config_path: Path) -> bool:
    """Read `define.review-required` from `.task-github.yml` (absent file/key = False)."""
    if not config_path.exists():
        return False
    try:
        config = task_config.load_config(config_path)
    except (OSError, ValueError) as exc:
        raise IssueTreeError("config_invalid", f"failed to read task-github config: {exc}") from exc
    findings = task_config.validate_config(config)
    errors = [finding for finding in findings if finding.get("severity") == "error"]
    if errors:
        codes = ", ".join(finding["code"] for finding in errors)
        raise IssueTreeError("config_invalid", f"invalid task-github config: {codes}")
    define = config.get("define") or {}
    return _bool_option(define.get("review-required"))


def _check_challenge_review(spec: dict, *, review_required: bool) -> None:
    """Refuse to build a tree when challenge review is required but absent/blocking.

    `review_required` comes solely from `.task-github.yml`'s `define.review-required`
    (the persistent, agent-independent source of truth, read by
    `review_required_from_config`). The spec cannot opt the gate in or out — the
    only field read off `spec.challenge_review` is `verdict`. This turns the
    challenge-review gate (DEC-2026-07-03-012207) from a SKILL.md instruction the
    executing agent could silently skip into a hard precondition the script
    itself enforces.
    """
    cr = spec.get("challenge_review")
    if cr is not None and not isinstance(cr, dict):
        raise IssueTreeError("bad_spec", "challenge_review must be an object")
    if not review_required:
        return
    if not isinstance(cr, dict):
        raise IssueTreeError(
            "challenge_review_missing",
            "define.review-required=true인데 spec.challenge_review가 없습니다 — "
            "challenge review(적대적 서브에이전트 감사) 없이 이슈 생성 불가",
        )
    verdict = cr.get("verdict")
    if verdict != "approved":
        raise IssueTreeError(
            "challenge_review_blocked",
            f"challenge review verdict={verdict!r} — blocking 없이 approved여야 이슈 생성 가능. "
            f"findings={cr.get('findings')!r}",
        )


def validate_spec(spec: dict, *, review_required: bool = False) -> dict:
    _check_challenge_review(spec, review_required=review_required)
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

    # Over-splitting is topology-independent: same-theme siblings fanning out from
    # a shared predecessor are phase candidates whether the tree is flat or stacked.
    warnings.extend(
        _detect_siblings_maybe_phases([c for c in child_out if c["key"] not in epic_keys])
    )

    for c in child_out:
        c.pop("_where", None)

    return {
        "root": root_out,
        "children": child_out,
        "strict_deps": bool(spec.get("strict_deps")),
        "epics": sorted(epic_keys),
        "warnings": warnings,
        "challenge_review": spec.get("challenge_review"),
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
        "challenge_review": spec.get("challenge_review"),
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


class GitHubProjectionProvider:
    """Small adapter kept injectable for deterministic failure/resume tests."""

    def context(self) -> tuple[str, str, str]:
        return repo_context()

    def node_id(self, owner: str, repo: str, number: int) -> str:
        return issue_node_id(owner, repo, number)

    def find_issue(self, owner: str, repo: str, marker: str) -> int | None:
        return find_issue_by_marker(owner, repo, marker)

    def issue_has_marker(self, owner: str, repo: str, number: int, marker: str) -> bool:
        return issue_has_marker(owner, repo, number, marker)

    def dependency_exists(
        self, owner: str, repo: str, child_number: int, blocker_number: int
    ) -> bool:
        return dependency_exists(owner, repo, child_number, blocker_number)

    def create_root(self, root: dict) -> int:
        return create_root_issue(root)

    def create_child(self, repo_id: str, parent_id: str, child: dict) -> int:
        return create_child_issue(repo_id, parent_id, child)

    def add_dependency(
        self, owner: str, repo: str, child_number: int, blocker_number: int
    ) -> bool:
        # DefinitionArtifact GitHub recording is all-or-none. Unlike the legacy
        # Issue-first path it never falls back to a comment for a missing edge.
        return add_dependency(
            owner, repo, child_number, blocker_number, strict=True
        )


def projection_node_marker(artifact: dict, stable_node_id: str) -> str:
    """Binding marker used to reconcile a remote create after a local failure."""
    return (
        "task-github-definition-node:v1:"
        f"{artifact['definition_id']}:{artifact['revision']}:"
        f"{artifact['digest']}:{stable_node_id}"
    )


def _with_projection_marker(issue_spec: dict, marker: str) -> dict:
    marked = dict(issue_spec)
    comment = f"<!-- {marker} -->"
    body = marked["body"].rstrip()
    marked["body"] = body if comment in body else f"{body}\n\n{comment}"
    return marked


def find_issue_by_marker(
    owner: str,
    repo: str,
    marker: str,
    *,
    gh_func: Callable = gh,
) -> int | None:
    """Find exactly one Issue carrying a DefinitionArtifact node marker."""
    raw = gh_func([
        "api", "--paginate", "--slurp",
        "-H", f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{owner}/{repo}/issues?state=all&per_page=100",
    ])
    try:
        pages = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IssueTreeError("projection_reconcile_failed", str(exc)) from exc
    if not isinstance(pages, list):
        raise IssueTreeError("projection_reconcile_failed", "issue reconciliation returned non-list JSON")
    issues = [item for page in pages for item in page] if pages and all(
        isinstance(page, list) for page in pages
    ) else pages
    matches = [
        int(issue["number"])
        for issue in issues
        if isinstance(issue, dict)
        and "pull_request" not in issue
        and marker in str(issue.get("body") or "")
    ]
    if len(matches) > 1:
        raise IssueTreeError(
            "projection_marker_ambiguous",
            f"multiple Issues carry projection marker {marker!r}: {matches}",
        )
    return matches[0] if matches else None


def issue_has_marker(
    owner: str,
    repo: str,
    number: int,
    marker: str,
    *,
    gh_func: Callable = gh,
) -> bool:
    body = gh_func([
        "api",
        "-H", f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{owner}/{repo}/issues/{number}",
        "--jq", ".body // \"\"",
    ])
    return marker in body


def dependency_exists(
    owner: str,
    repo: str,
    child_number: int,
    blocker_number: int,
    *,
    gh_func: Callable = gh,
) -> bool:
    raw = gh_func([
        "api",
        "-H", f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{owner}/{repo}/issues/{child_number}/dependencies/blocked_by",
    ])
    try:
        blockers = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IssueTreeError("projection_reconcile_failed", str(exc)) from exc
    if not isinstance(blockers, list):
        raise IssueTreeError("projection_reconcile_failed", "dependency reconciliation returned non-list JSON")
    return any(
        isinstance(blocker, dict) and str(blocker.get("number")) == str(int(blocker_number))
        for blocker in blockers
    )


def _materialize_projection_node(
    *,
    artifact: dict,
    artifact_node: dict,
    issue_spec: dict,
    parent_node_id: str | None,
    owner: str,
    repo: str,
    state: dict,
    state_path: Path,
    provider: GitHubProjectionProvider,
    create: Callable[[dict], int],
) -> None:
    """Checkpoint intent, reconcile by marker, then finish one node binding."""
    stable_id = artifact_node["node_id"]
    marker = projection_node_marker(artifact, stable_id)
    nodes = state["nodes"]
    entry = nodes.get(stable_id)
    if entry is not None and not isinstance(entry, dict):
        raise IssueTreeError("projection_state_invalid", f"node checkpoint is invalid: {stable_id}")
    if entry and entry.get("number") and entry.get("github_node_id"):
        return

    created_intent = entry is None
    if created_intent:
        entry = {
            "key": artifact_node["key"],
            "parent_node_id": parent_node_id,
            "marker": marker,
        }
        nodes[stable_id] = entry
        definition_artifact.write_json_atomic(state_path, state)
    elif entry.get("marker") not in {None, marker}:
        raise IssueTreeError("projection_state_invalid", f"node marker changed: {stable_id}")
    elif entry.get("marker") is None:
        # Old complete checkpoints were returned above. An old incomplete
        # checkpoint without a marker cannot be resumed without duplicate risk.
        raise IssueTreeError(
            "projection_marker_missing",
            f"incomplete legacy checkpoint has no reconciliation marker: {stable_id}",
        )

    checkpoint_number = entry.get("number")
    if created_intent:
        # This invocation durably wrote intent immediately before this branch,
        # so no prior remote create exists to reconcile and no pagination read
        # is needed on the normal full-projection path.
        remote_number = create(_with_projection_marker(issue_spec, marker))
    elif checkpoint_number is not None:
        if not provider.issue_has_marker(owner, repo, checkpoint_number, marker):
            raise IssueTreeError(
                "projection_reconcile_failed",
                f"checkpointed Issue #{checkpoint_number} no longer carries marker {marker!r}",
            )
        remote_number = checkpoint_number
    else:
        # A prior create may have succeeded before its number checkpoint. The
        # stable marker makes this slow pagination scan resume-only.
        remote_number = provider.find_issue(owner, repo, marker)
        if remote_number is None:
            remote_number = create(_with_projection_marker(issue_spec, marker))

    # Persist the remote number before resolving GraphQL node id. If node_id or
    # this checkpoint fails, the next run reconciles the marker and reuses it.
    entry["number"] = remote_number
    definition_artifact.write_json_atomic(state_path, state)
    entry["github_node_id"] = provider.node_id(owner, repo, remote_number)
    definition_artifact.write_json_atomic(state_path, state)


def _materialize_projection_dependency(
    *,
    edge_id: str,
    child_node_id: str,
    blocker_node_id: str,
    child_number: int,
    blocker_number: int,
    owner: str,
    repo: str,
    state: dict,
    state_path: Path,
    provider: GitHubProjectionProvider,
) -> None:
    dependencies = state["dependencies"]
    entry = dependencies.get(edge_id)
    if entry is not None and not isinstance(entry, dict):
        raise IssueTreeError("projection_state_invalid", f"dependency checkpoint is invalid: {edge_id}")
    if entry and entry.get("materialized") is True:
        return

    created_intent = entry is None
    if created_intent:
        entry = {
            "child": child_node_id,
            "blocked_by": blocker_node_id,
            "child_number": child_number,
            "blocked_by_number": blocker_number,
            "materialized": False,
        }
        dependencies[edge_id] = entry
        definition_artifact.write_json_atomic(state_path, state)
    elif (
        entry.get("child_number") != child_number
        or entry.get("blocked_by_number") != blocker_number
    ):
        raise IssueTreeError("projection_state_invalid", f"dependency numbers changed: {edge_id}")

    if created_intent or not provider.dependency_exists(
        owner, repo, child_number, blocker_number
    ):
        if not provider.add_dependency(owner, repo, child_number, blocker_number):
            raise IssueTreeError(
                "dep_create_failed",
                f"GitHub dependency was not materialized: {edge_id}",
            )
    entry["materialized"] = True
    definition_artifact.write_json_atomic(state_path, state)


def _new_projection_state(artifact: dict) -> dict:
    return {
        "schema": definition_artifact.PROJECTION_SCHEMA,
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "definition_digest": artifact["digest"],
        "owner": None,
        "repo": None,
        "nodes": {},
        "dependencies": {},
        "complete": False,
    }


def _projection_result(state: dict, artifact: dict, *, resumed: bool) -> dict:
    coverage = definition_artifact.projection_coverage(artifact, state)
    root_number = state["nodes"].get(artifact["root"]["node_id"], {}).get("number")
    return {
        "ok": True,
        "owner": state.get("owner"),
        "repo": state.get("repo"),
        "root_number": root_number,
        "definition_id": artifact["definition_id"],
        "revision": artifact["revision"],
        "definition_digest": artifact["digest"],
        "projection_complete": coverage["complete"],
        "coverage": coverage,
        "resumed": resumed,
        "parent_method": PARENT_METHOD,
        "dependency_api_version": API_VERSION,
    }


def execute_projection(
    spec: dict,
    artifact: dict,
    state_path: Path,
    *,
    provider: GitHubProjectionProvider | None = None,
) -> dict:
    """Materialize every node/edge, checkpointing after each successful write."""
    definition_artifact.validate_artifact(artifact)
    if artifact["record"] != "github":
        raise IssueTreeError(
            "record_none_forbids_github",
            "record:none forbids GitHub issue writes; choose record:github in a new revision",
        )
    resumed = state_path.exists()
    if resumed:
        try:
            state = definition_artifact.read_json(state_path)
        except definition_artifact.DefinitionError as exc:
            raise IssueTreeError(exc.code, exc.message) from exc
        coverage = definition_artifact.projection_coverage(artifact, state)
        if not coverage["binding_valid"]:
            raise IssueTreeError(
                "projection_binding_mismatch",
                "projection state is pinned to another definition revision/digest",
            )
        if coverage["complete"]:
            return _projection_result(state, artifact, resumed=True)
    else:
        state = _new_projection_state(artifact)

    provider = provider or GitHubProjectionProvider()
    owner, repo, repo_id = provider.context()
    if state.get("owner") not in {None, owner} or state.get("repo") not in {None, repo}:
        raise IssueTreeError("projection_repo_mismatch", "projection state belongs to another repository")
    state["owner"] = owner
    state["repo"] = repo
    definition_artifact.write_json_atomic(state_path, state)

    by_key = {child["key"]: child for child in artifact["children"]}
    root_id = artifact["root"]["node_id"]
    nodes = state["nodes"]
    _materialize_projection_node(
        artifact=artifact,
        artifact_node=artifact["root"],
        issue_spec=spec["root"],
        parent_node_id=None,
        owner=owner,
        repo=repo,
        state=state,
        state_path=state_path,
        provider=provider,
        create=provider.create_root,
    )

    for child_spec in _topo_order(spec["children"]):
        artifact_child = by_key[child_spec["key"]]
        parent_id = artifact_child["parent_node_id"]
        parent_github_id = nodes[parent_id]["github_node_id"]
        _materialize_projection_node(
            artifact=artifact,
            artifact_node=artifact_child,
            issue_spec=child_spec,
            parent_node_id=parent_id,
            owner=owner,
            repo=repo,
            state=state,
            state_path=state_path,
            provider=provider,
            create=lambda marked, parent_github_id=parent_github_id: provider.create_child(
                repo_id, parent_github_id, marked
            ),
        )

    for child in artifact["children"]:
        for blocker_id in child["blocked_by_node_ids"]:
            edge_id = f"{child['node_id']}>{blocker_id}"
            child_number = nodes[child["node_id"]]["number"]
            blocker_number = nodes[blocker_id]["number"]
            _materialize_projection_dependency(
                edge_id=edge_id,
                child_node_id=child["node_id"],
                blocker_node_id=blocker_id,
                child_number=child_number,
                blocker_number=blocker_number,
                owner=owner,
                repo=repo,
                state=state,
                state_path=state_path,
                provider=provider,
            )

    coverage = definition_artifact.projection_coverage(artifact, state)
    state["complete"] = coverage["complete"]
    state["coverage"] = coverage
    definition_artifact.write_json_atomic(state_path, state)
    if not coverage["complete"]:
        raise IssueTreeError("projection_incomplete", f"projection coverage is incomplete: {coverage}")
    return _projection_result(state, artifact, resumed=resumed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", help="legacy Issue-first JSON spec path")
    source.add_argument("--artifact", help="DefinitionArtifact revision path")
    parser.add_argument(
        "--projection-state",
        help="checkpoint path for resumable DefinitionArtifact GitHub projection",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-deps", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--task-config", default=".task-github.yml",
                         help="path to .task-github.yml (for define.review-required)")
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
        review_required = review_required_from_config(Path(args.task_config))
        artifact = None
        if args.artifact:
            try:
                artifact = definition_artifact.read_json(args.artifact)
                definition_artifact.validate_artifact(artifact)
                raw_spec = definition_artifact.artifact_to_issue_spec(artifact)
            except definition_artifact.DefinitionError as exc:
                raise IssueTreeError(exc.code, exc.message) from exc
        else:
            raw_spec = read_spec(Path(args.spec))
        spec = validate_spec(raw_spec, review_required=review_required)
        spec["strict_deps"] = bool(spec.get("strict_deps") or args.strict_deps)
        if args.dry_run:
            payload = build_plan(spec)
            if artifact is not None:
                payload.update({
                    "definition_id": artifact["definition_id"],
                    "revision": artifact["revision"],
                    "definition_digest": artifact["digest"],
                    "projection_requirements": definition_artifact.projection_requirements(artifact),
                })
        elif artifact is not None:
            if not args.projection_state:
                raise IssueTreeError(
                    "projection_state_required",
                    "--projection-state is required for resumable artifact recording",
                )
            payload = execute_projection(spec, artifact, Path(args.projection_state))
        else:
            # Compatibility: the historical Issue-first --spec path is unchanged.
            payload = execute(spec)
    except IssueTreeError as exc:
        emit({"ok": False, "error_code": exc.error_code, "message": exc.message},
             as_json=args.as_json)
        return 2
    emit(payload, as_json=args.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
