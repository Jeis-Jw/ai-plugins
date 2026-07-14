#!/usr/bin/env python3
"""Pure orchestration decisions shared by task-github orchestrate docs/tests."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

GEARS = ("micro", "normal", "major")
GEAR_RANK = {"micro": 0, "normal": 1, "major": 2}
GEAR_OPTION_KEYS = ("plan", "verify", "pr-review")
DEFAULT_GEAR_OPTIONS = {
    "micro": {"plan": False, "verify": True, "pr-review": False},
    "normal": {"plan": True, "verify": True, "pr-review": False},
    "major": {"plan": True, "verify": True, "pr-review": True},
}
REVIEW_LEASE_SCHEMA = "workflow-review-lease/v1"
REVIEW_REQUIREMENTS = {"self", "independent"}
REVIEW_LEASE_KEYS = {
    "schema", "lease_id", "owner", "provider", "episode_id", "edge_id",
    "requirement", "criteria_digest", "evidence_refs", "digest",
}


def _tagged_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_review_lease(lease: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(lease, dict) or set(lease) != REVIEW_LEASE_KEYS:
        raise ValueError("review lease fields differ from workflow-review-lease/v1")
    if lease.get("schema") != REVIEW_LEASE_SCHEMA:
        raise ValueError("review lease schema mismatch")
    if lease.get("owner") not in {"studio", "task-worker"}:
        raise ValueError("review lease owner must be studio or task-worker")
    if lease.get("provider") not in {"native", "session-review"}:
        raise ValueError("review lease provider must be native or session-review")
    if lease.get("requirement") not in REVIEW_REQUIREMENTS:
        raise ValueError("review lease requirement must be self or independent")
    for key in ("lease_id", "episode_id", "edge_id"):
        if not isinstance(lease.get(key), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", lease[key]):
            raise ValueError(f"review lease {key} must be a path-safe identifier")
    if not isinstance(lease.get("criteria_digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", lease["criteria_digest"]):
        raise ValueError("review lease criteria_digest must be tagged sha256")
    refs = lease.get("evidence_refs")
    if not isinstance(refs, list) or not all(isinstance(ref, str) and ref.strip() for ref in refs) or len(set(refs)) != len(refs):
        raise ValueError("review lease evidence_refs must be a unique string list")
    expected = _tagged_digest({key: lease[key] for key in REVIEW_LEASE_KEYS if key != "digest"})
    if lease.get("digest") != expected:
        raise ValueError("review lease digest mismatch")
    return lease


def issue_branch(number: int) -> str:
    return f"task/issue-{number}"


def issue_base_branch(*, parent_number: int | None, base_branch: str) -> str:
    return issue_branch(parent_number) if parent_number is not None else base_branch


def ensure_branch_chain(
    number: int, *, parents: dict[int, int | None], base_branch: str
) -> list[dict[str, Any]]:
    """Return the branch chain from root down to `number`, root-first.

    Each entry is {"issue": N, "branch": task/issue-N, "base": <parent branch or trunk>}.
    The last entry is `number` itself; its `base` is the worker's expected PR base.
    Callers ensure/push only the ANCESTOR branches (chain[:-1]) before spawning the
    leaf worker — the leaf branch is created by the worker's `git worktree add -b`,
    so pre-creating it here would make that add fail with "already exists".
    """
    chain: list[int] = []
    current: int | None = number
    seen: set[int] = set()
    while current is not None:
        if current in seen:
            raise ValueError(f"parent cycle detected at issue #{current}")
        seen.add(current)
        chain.append(current)
        current = parents.get(current)
    chain.reverse()
    return [
        {
            "issue": issue,
            "branch": issue_branch(issue),
            "base": issue_base_branch(parent_number=parents.get(issue), base_branch=base_branch),
        }
        for issue in chain
    ]


def _gear_name(label: str | None) -> str | None:
    if not label:
        return None
    return label.removeprefix("gear:")


def _bool_option(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "o"}:
        return True
    if text in {"0", "false", "no", "off", "x"}:
        return False
    raise ValueError(f"invalid gear option value: {value!r}")


def _gear_or_major(gear_label: str | None) -> str:
    gear = _gear_name(gear_label)
    return gear if gear in DEFAULT_GEAR_OPTIONS else "major"


def _bare_gear(value: str | None) -> str:
    """Normalize a gear value to a bare name, unknown/absent → 'micro'.

    Unlike `_gear_or_major` (used for flow gating, where ambiguity → more
    ceremony), promotion counts from the floor: an unlabeled child must not
    inflate a container's gear.
    """
    gear = _gear_name(value) if value else None
    return gear if gear in DEFAULT_GEAR_OPTIONS else "micro"


def gear_of_labels(labels: Any) -> str | None:
    """Bare gear name ('micro'|'normal'|'major') from a label list, else None."""
    for label in labels or []:
        name = label.get("name") if isinstance(label, dict) else label
        gear = _gear_name(str(name)) if name else None
        if gear in DEFAULT_GEAR_OPTIONS:
            return gear
    return None


def container_gear_promotion(child_gears: list[str | None]) -> str:
    """Cumulative container gear from child gears (DEC-2026-07-02-224910 §2).

    Base = the highest child gear. Then accumulate: ≥3 micro children promote to
    at least normal, ≥2 normal children promote to major. Unknown/absent child
    gears count as micro. A container's own gear label is ignored — its gear is a
    function of its children, decided fresh at the merge edge.
    """
    gears = [_bare_gear(g) for g in child_gears]
    if not gears:
        return "micro"
    result = max(gears, key=lambda g: GEAR_RANK[g])
    if sum(1 for g in gears if g == "micro") >= 3 and GEAR_RANK[result] < GEAR_RANK["normal"]:
        result = "normal"
    if sum(1 for g in gears if g == "normal") >= 2 and GEAR_RANK[result] < GEAR_RANK["major"]:
        result = "major"
    return result


def ff_merge_command(*, child_branch: str, parent_branch: str) -> list[str]:
    """Fast-forward the parent ref to the child branch without checkout
    (DEC-2026-07-02-224910 §3, micro/normal merge edge).

    `git fetch . <child>:<parent>` updates the parent ref in the shared git dir
    via a self-fetch refspec: git rejects a non-fast-forward ref update and
    refuses to touch a checked-out branch, so no worktree HEAD ever moves
    (preserves DEC-2026-07-02-212109). On a non-FF rejection the caller
    reverse-merges the parent into the child worktree, resolves the conflict
    leaf-side, re-verifies, and retries.
    """
    return ["git", "fetch", ".", f"{child_branch}:{parent_branch}"]


def _action_name(action: str) -> str:
    normalized = action.replace("_", "-")
    if normalized == "review":
        return "pr-review"
    if normalized not in GEAR_OPTION_KEYS:
        raise ValueError(f"unknown gear option: {action}")
    return normalized


def _options_for_gear(options: dict[str, Any] | None, gear: str) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {}
    if isinstance(options.get(gear), dict):
        return options[gear]
    if any(key in options for key in GEAR_OPTION_KEYS):
        return options
    return {}


def flow_policy(
    gear_label: str | None,
    *,
    gear_options: dict[str, Any] | None = None,
    commander_options: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Resolve plan/verify/pr-review using commander > config > defaults."""
    gear = _gear_or_major(gear_label)
    policy = dict(DEFAULT_GEAR_OPTIONS[gear])
    for source in (gear_options, commander_options):
        for key, value in _options_for_gear(source, gear).items():
            if value is None or value == "":
                continue
            policy[_action_name(key)] = _bool_option(value)
    return policy


def option_required(
    action: str,
    gear_label: str | None,
    *,
    gear_options: dict[str, Any] | None = None,
    commander_options: dict[str, Any] | None = None,
) -> bool:
    return flow_policy(
        gear_label,
        gear_options=gear_options,
        commander_options=commander_options,
    )[_action_name(action)]


def plan_required(gear_label: str | None, **kwargs: Any) -> bool:
    return option_required("plan", gear_label, **kwargs)


def verify_required(gear_label: str | None, **kwargs: Any) -> bool:
    return option_required("verify", gear_label, **kwargs)


def pr_review_required(gear_label: str | None, **kwargs: Any) -> bool:
    return option_required("pr-review", gear_label, **kwargs)


def review_required(
    review_mode: str,
    gear_label: str | None,
    *,
    gear_options: dict[str, Any] | None = None,
    commander_options: dict[str, Any] | None = None,
    review_lease: dict[str, Any] | None = None,
) -> bool:
    if review_lease is not None:
        validate_review_lease(review_lease)
        return True
    if review_mode == "skip":
        return False
    if review_mode == "all":
        return True
    if review_mode != "gear":
        raise ValueError("review_mode must be gear, all, or skip")
    return pr_review_required(
        gear_label,
        gear_options=gear_options,
        commander_options=commander_options,
    )


def _pr_field(pr: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in pr:
            return pr[name]
    return None


def classify_pr_recovery(*, head: str, expected_base: str, prs: list[dict[str, Any]]) -> dict[str, Any]:
    exact = [
        pr for pr in prs
        if _pr_field(pr, "head", "headRefName") == head
        and _pr_field(pr, "base", "baseRefName") == expected_base
    ]
    for pr in exact:
        state = str(_pr_field(pr, "state") or "").upper()
        if state == "OPEN":
            return {"action": "reuse_open", "pr": pr["number"]}
        if state == "MERGED":
            return {"action": "ensure_issue_closed", "pr": pr["number"]}

    for pr in prs:
        state = str(_pr_field(pr, "state") or "").upper()
        if _pr_field(pr, "head", "headRefName") == head and state == "OPEN":
            return {"action": "stop", "stop_reason": "state_mismatch", "pr": pr["number"]}
    return {"action": "create"}


def child_merge_evidence(children: list[dict[str, Any]], *, expected_base: str) -> dict[str, Any]:
    """Each child must show it landed on `expected_base`. Three valid shapes:

    - ``closed_no_pr: True`` — closed with no code change (revert/no-op).
    - ``merged_pr: {base}`` — major leaf/container merged via PR (DEC-…-212109).
    - ``ff_merged: {base, sha_range}`` — micro/normal local FF merge, no PR
      (DEC-…-224910 §3): the SHA range is the close evidence that replaces a
      merged PR, so a bare flag is not enough — the range must be present.
    """
    missing: list[int] = []
    for child in children:
        if child.get("closed_no_pr") is True:
            continue
        ff = child.get("ff_merged")
        if (
            isinstance(ff, dict)
            and _pr_field(ff, "base", "baseRefName") == expected_base
            and ff.get("sha_range")
        ):
            continue
        pr = child.get("merged_pr")
        if isinstance(pr, dict) and _pr_field(pr, "base", "baseRefName") == expected_base:
            continue
        missing.append(int(child["number"]))
    if missing:
        return {"ok": False, "stop_reason": "state_mismatch", "missing": missing}
    return {"ok": True, "missing": []}


def canonical_path_list(paths: Any) -> list[str]:
    out: set[str] = set()
    for raw in paths or []:
        path = str(raw).strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        path = path.strip("/")
        if path:
            out.add(path)
    return sorted(out)


def path_list_hash(paths: Any) -> str:
    payload = json.dumps(canonical_path_list(paths), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def drift_surface_hash_matches(*, evidence_hash: str | None, current_hash: str | None) -> bool:
    return bool(evidence_hash) and evidence_hash == current_hash


def _evidence_for_issue(source: dict[str, Any] | None, number: int) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    value = source.get(str(number), source.get(number))
    return dict(value) if isinstance(value, dict) else None


def project_child_merge_evidence(
    child: dict[str, Any],
    *,
    merge_evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    number = int(child["number"])
    projected = _evidence_for_issue(merge_evidence, number)
    if projected is None and isinstance(child.get("merge_evidence"), dict):
        projected = dict(child["merge_evidence"])
    if projected is not None:
        projected.setdefault("kind", projected.get("type", "merge"))
        return projected

    pr = child.get("merged_pr")
    if isinstance(pr, dict):
        return {
            "kind": "merged_pr",
            "pr": pr.get("number") or pr.get("pr"),
            "base": _pr_field(pr, "base", "baseRefName"),
            "head_sha": _pr_field(pr, "head_sha", "headRefOid"),
            "merge_commit_sha": _pr_field(pr, "merge_commit_sha", "mergeCommitOid"),
            "parent_contains_child": True,
        }

    ff = child.get("ff_merged")
    if isinstance(ff, dict):
        return {
            "kind": "ff_merged",
            "base": _pr_field(ff, "base", "baseRefName"),
            "sha_range": ff.get("sha_range"),
            "parent_contains_child": bool(ff.get("sha_range")),
        }

    if child.get("closed_no_pr") is True:
        return {"kind": "closed_no_pr", "parent_contains_child": True}
    return None


def _project_gate_evidence(
    child: dict[str, Any],
    *,
    gate_evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    number = int(child["number"])
    projected = _evidence_for_issue(gate_evidence, number)
    if projected is None and isinstance(child.get("gate_evidence"), dict):
        projected = dict(child["gate_evidence"])
    return projected


def _fallback_paths(child: dict[str, Any], gate: dict[str, Any] | None = None) -> list[str]:
    if gate and gate.get("changed_paths") is not None:
        return canonical_path_list(gate.get("changed_paths"))
    return canonical_path_list(child.get("changed_paths"))


def _uncanonical_paths(value: Any) -> bool:
    return list(value or []) != canonical_path_list(value)


def _head_pin(gate: dict[str, Any]) -> str | None:
    if gate.get("pr_head_sha"):
        return str(gate["pr_head_sha"])
    pr_head = gate.get("pr_head")
    if isinstance(pr_head, dict):
        value = _pr_field(pr_head, "head_sha", "headRefOid", "oid")
        return str(value) if value else None
    return None


def _tool_version_reason(
    evidence_versions: Any,
    current_versions: dict[str, str],
    *,
    evidence_policy_token: str | None,
    current_policy_token: str | None,
) -> str | None:
    if not isinstance(evidence_versions, dict):
        return "missing_tool_versions"
    for name, expected in sorted(current_versions.items()):
        actual = evidence_versions.get(name)
        if actual == expected and actual != "unknown":
            continue
        if (
            actual == "unknown"
            and expected == "unknown"
            and evidence_policy_token
            and evidence_policy_token == current_policy_token
        ):
            continue
        if actual is None:
            return "missing_tool_version"
        return "tool_version_mismatch"
    return None


def validate_child_gate_evidence(
    child: dict[str, Any],
    *,
    expected_base: str,
    current_gate_version: str,
    current_tool_versions: dict[str, str],
    current_drift_surface_hash: str,
    expected_pr_head_sha: str | None = None,
    current_tool_version_policy_token: str | None = None,
    merge_evidence: dict[str, Any] | None = None,
    gate_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merge = project_child_merge_evidence(child, merge_evidence=merge_evidence)
    gate = _project_gate_evidence(child, gate_evidence=gate_evidence)
    paths = _fallback_paths(child, gate)

    if not merge:
        return {"ok": False, "reason": "missing_merge_evidence", "paths": paths}
    if merge.get("kind") != "closed_no_pr":
        if _pr_field(merge, "base", "baseRefName") != expected_base:
            return {"ok": False, "reason": "base_mismatch", "paths": paths}
        if merge.get("parent_contains_child") is not True and merge.get("sha_range_in_parent") is not True:
            return {"ok": False, "reason": "parent_inclusion_missing", "paths": paths}

    if not gate:
        return {"ok": False, "reason": "missing_gate_evidence", "paths": paths}
    if _uncanonical_paths(gate.get("changed_paths")) or _uncanonical_paths(gate.get("checked_paths")):
        return {"ok": False, "reason": "noncanonical_paths", "paths": paths}
    if gate.get("changed_paths_hash") != path_list_hash(gate.get("changed_paths")):
        return {"ok": False, "reason": "changed_paths_hash_mismatch", "paths": paths}
    if gate.get("checked_paths_hash") != path_list_hash(gate.get("checked_paths")):
        return {"ok": False, "reason": "checked_paths_hash_mismatch", "paths": paths}
    if gate.get("gate_version") != current_gate_version:
        return {"ok": False, "reason": "gate_version_mismatch", "paths": paths}

    version_reason = _tool_version_reason(
        gate.get("tool_versions"),
        current_tool_versions,
        evidence_policy_token=gate.get("tool_version_policy_token"),
        current_policy_token=current_tool_version_policy_token,
    )
    if version_reason:
        return {"ok": False, "reason": version_reason, "paths": paths}

    if not drift_surface_hash_matches(
        evidence_hash=gate.get("drift_surface_hash"),
        current_hash=current_drift_surface_hash,
    ):
        return {"ok": False, "reason": "drift_surface_hash_mismatch", "paths": paths}
    if gate.get("changed_path_stale_issues") or gate.get("changed-path-stale_issues"):
        return {"ok": False, "reason": "changed_path_stale_issues", "paths": paths}
    if expected_pr_head_sha is not None and _head_pin(gate) != expected_pr_head_sha:
        return {"ok": False, "reason": "pr_head_pin_mismatch", "paths": paths}
    return {"ok": True, "paths": paths, "merge_evidence": merge, "gate_evidence": gate}


def scoped_changed_path_stale_targets(
    *,
    parent_paths: list[str],
    children: list[dict[str, Any]],
    expected_base: str,
    current_gate_version: str,
    current_tool_versions: dict[str, str],
    current_drift_surface_hash: str,
    expected_pr_heads: dict[int, str] | None = None,
    current_tool_version_policy_token: str | None = None,
    merge_evidence: dict[str, Any] | None = None,
    gate_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parent = canonical_path_list(parent_paths)
    target_paths: set[str] = set(parent)
    reused: list[int] = []
    fallback: list[dict[str, Any]] = []
    parent_set = set(parent)

    for child in children:
        number = int(child["number"])
        result = validate_child_gate_evidence(
            child,
            expected_base=expected_base,
            current_gate_version=current_gate_version,
            current_tool_versions=current_tool_versions,
            current_drift_surface_hash=current_drift_surface_hash,
            expected_pr_head_sha=(expected_pr_heads or {}).get(number),
            current_tool_version_policy_token=current_tool_version_policy_token,
            merge_evidence=merge_evidence,
            gate_evidence=gate_evidence,
        )
        paths = canonical_path_list(result.get("paths"))
        reason = result.get("reason")
        if result.get("ok") and parent_set.intersection(paths):
            reason = "parent_overlap"
        if reason:
            target_paths.update(paths)
            fallback.append({"issue": number, "reason": reason, "paths": paths})
        else:
            reused.append(number)

    return {
        "target_paths": sorted(target_paths),
        "reused": reused,
        "fallback": fallback,
        "full_fallback": bool(fallback),
    }


def resolve_review_tool(
    *,
    enabled: bool,
    directive_tool: str | None = None,
    config_tool: str | None = None,
) -> dict[str, Any]:
    """Pick the reviewer for a gate that is off by default (DEC-2026-07-03-012207).

    Two axes: enabled gates on/off; when on, the tool resolves by precedence
    directive > config > harness (the same commander > config > default cascade
    as orchestrate's flow options). The terminal is 'harness' — a built-in
    fresh-context challenge subagent — NOT a STOP: define's challenge runs where
    the human is already present (co-design), so an absent tool degrades to the
    built-in rather than halting. (This is the deliberate divergence from
    orchestrate, whose absent-tool review STOPs at a PR gate.)
    """
    if not enabled:
        return {"mode": "off", "tool": None}
    tool = (directive_tool or "").strip() or (config_tool or "").strip() or None
    if tool:
        return {"mode": "tool", "tool": tool}
    return {"mode": "harness", "tool": None}


def compose_tool_command(tool: str | None, command: str | None = None, extra: str | None = None) -> str | None:
    if not tool:
        return None
    parts = [f"/{tool}"]
    if command:
        parts.append(command.strip())
    if extra:
        parts.append(extra.strip())
    return " ".join(part for part in parts if part)


def review_verdict_action(
    review_result: dict[str, Any],
    *,
    round_number: int,
    round_cap: int,
) -> dict[str, Any]:
    verdict = str(review_result.get("verdict") or "").lower()
    if verdict == "approved":
        return {"action": "ready_for_pr_closeout"}
    if verdict == "changes-requested":
        if round_number >= round_cap:
            return {"action": "stop", "stop_reason": "human_gate_review"}
        return {
            "action": "respawn_worker",
            "feedback": list(review_result.get("findings") or []),
            "next_round": round_number + 1,
        }
    return {"action": "stop", "stop_reason": "human_gate_review"}


def conflict_action(*, auto_conflict: bool, ambiguity: bool) -> dict[str, str]:
    if auto_conflict and not ambiguity:
        return {"action": "spawn_conflict_agent"}
    return {"action": "stop", "stop_reason": "merge_conflict"}


def worker_feedback_handoff(*, issue: int, pr: int, branch: str, feedback: list[str]) -> dict[str, Any]:
    prompt = "\n".join([
        f"task-github rework for issue #{issue}",
        f"PR: #{pr}",
        f"branch: {branch}",
        "feedback:",
        *[f"- {item}" for item in feedback],
        "",
        "Run start/run/done for this issue. Do not merge; return PR/report to orchestrator.",
    ])
    return {"issue": issue, "pr": pr, "branch": branch, "feedback": feedback, "prompt": prompt}


def external_review_handoff(item: dict[str, Any], permit: dict[str, Any]) -> dict[str, Any]:
    """Preserve GitHub transport while returning reviewer ownership to Studio."""
    if permit.get("schema") != "task-worker.review-permit/v1":
        raise ValueError("task-worker review permit schema mismatch")
    lease = validate_review_lease(permit.get("review_lease"))
    if permit.get("dispatch_reviewer") is not False or lease["owner"] != "studio":
        raise ValueError("external review handoff requires a Studio-owned skip permit")
    required = ("number", "pr", "base", "head")
    missing = [key for key in required if item.get(key) is None]
    if missing:
        raise ValueError(f"external review handoff lacks GitHub transport: {missing}")
    return {
        "schema": "task-github.external-review-handoff/v1",
        "status": "externally-owned",
        "issue": int(item["number"]),
        "pr": int(item["pr"]),
        "base": item["base"],
        "head": item["head"],
        "review_lease": lease,
    }


def review_permit_action(
    expected_review_lease: dict[str, Any],
    permit: dict[str, Any] | None,
) -> str:
    """Fence one pinned review edge before any reviewer dispatch.

    The ledger expectation is the authority. A permit is only a point-in-time
    proof that task-worker still resolves that exact edge to the same owner.
    """
    expected = validate_review_lease(expected_review_lease)
    if not isinstance(permit, dict):
        raise ValueError("review_permit_required")
    if permit.get("schema") != "task-worker.review-permit/v1":
        raise ValueError("review_permit_mismatch")
    try:
        actual = validate_review_lease(permit.get("review_lease"))
    except ValueError as exc:
        raise ValueError("review_permit_mismatch") from exc
    if actual != expected:
        raise ValueError("review_permit_mismatch")
    if expected["owner"] == "studio":
        if (
            permit.get("status") != "externally-owned"
            or permit.get("dispatch_reviewer") is not False
            or permit.get("action") != "skip"
        ):
            raise ValueError("review_permit_mismatch")
        return "external"
    if (
        permit.get("status") != "task-worker-owned"
        or permit.get("dispatch_reviewer") is not True
        or permit.get("action") != "dispatch"
    ):
        raise ValueError("review_permit_mismatch")
    return "local"


def _numbers(items: list[dict[str, Any]] | None) -> list[int]:
    return [int(item["number"]) for item in items or []]


def _base_key(item: dict[str, Any]) -> str | None:
    return item.get("base") or item.get("base_branch")


def select_closeout_jobs(
    ready: list[dict[str, Any]] | None,
    running: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Pick at most one closeout job per BASE_BRANCH.

    The ledger is the queue; closeout agents are one-shot jobs. Running bases
    are locked, and ready items for unlocked bases are selected FIFO by their
    ledger timestamp.
    """
    locked = {_base_key(item) for item in running or [] if _base_key(item)}
    selected: list[dict[str, Any]] = []
    selected_bases: set[str] = set()
    for item in sorted(ready or [], key=lambda value: str(value.get("at") or "")):
        base = _base_key(item)
        if not base or base in locked or base in selected_bases:
            continue
        selected.append(item)
        selected_bases.add(base)
    return selected


def plan_tick(
    ready_state: dict[str, Any],
    *,
    review_tool: str | None,
    review_command: str | None = None,
    max_workers: int = 1,
    pipeline: bool = False,
    review_permits: dict[int | str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pipeline = pipeline or max_workers > 1

    # Branch order mirrors evaluate_tree / SKILL.md: stuck and api_failure (ok:false
    # 하드 STOP) win over merge/spawn. evaluate_tree leaves done_parents/review_waiting
    # populated even when it _stop()s for stuck, so these must be gated FIRST — else a
    # stuck tick with a completed parent would auto-merge instead of STOP (부분진행금지 위반).
    if ready_state.get("stuck"):
        return {"action": "stop", "stop_reason": ready_state.get("stop_reason") or "stuck"}
    if ready_state.get("closeout_failed"):
        return {
            "action": "stop",
            "stop_reason": "closeout_failed",
            "issues": _numbers(ready_state.get("closeout_failed")),
        }
    if ready_state.get("ok") is False and ready_state.get("stop_reason") not in (None, "human_gate_review"):
        return {"action": "stop", "stop_reason": ready_state.get("stop_reason")}

    done_parents = _numbers(ready_state.get("done_parents"))
    if done_parents:
        return {"action": "merge_done_parents", "issues": done_parents}

    container_done = ready_state.get("container_done")
    if container_done:
        action = {"action": "merge_container", "issue": int(container_done["number"])}
        # Merge-edge ceremony follows the container's cumulative gear (computed by
        # evaluate_tree), not its own label: major → PR+review, else local FF.
        if container_done.get("gear"):
            action["gear"] = container_done["gear"]
        return action

    closeout_jobs = select_closeout_jobs(
        ready_state.get("closeout_ready"),
        ready_state.get("closeout_running"),
    )
    if closeout_jobs:
        action = {
            "action": "dispatch_closeout_workers",
            "issues": _numbers(closeout_jobs),
            "base_branches": {int(item["number"]): _base_key(item) for item in closeout_jobs},
            "closeout_modes": {int(item["number"]): item.get("mode", "ff") for item in closeout_jobs},
            "prs": {int(item["number"]): item.get("pr") for item in closeout_jobs if item.get("pr") is not None},
            "ledger_update": "closeout_started",
            "ledger_required": True,
            "retick_on": "closeout_completion",
        }
        ready = _numbers(ready_state.get("ready"))
        if pipeline and ready:
            return {
                "action": "pipeline",
                "actions": [
                    action,
                    {
                        "action": "dispatch_background_workers",
                        "issues": ready[:max(1, max_workers)],
                        "ledger_update": "spawned",
                        "retick_on": "worker_completion",
                    },
                ],
                "ledger_required": True,
                "retick_on": "any_lane_completion",
            }
        return action

    review_items = list(ready_state.get("review_waiting") or [])
    review_waiting = _numbers(review_items)
    if review_waiting:
        external_handoffs = []
        local_items = []
        for item in review_items:
            permit = (review_permits or {}).get(int(item["number"])) or (review_permits or {}).get(str(item["number"]))
            expected = item.get("expected_review_lease")
            if not isinstance(expected, dict):
                # No pinned lease is the standalone contract. Ignore stray
                # permits and preserve the existing local review flow.
                local_items.append(item)
                continue
            try:
                permit_action = review_permit_action(expected, permit)
            except ValueError as exc:
                reason = str(exc)
                if reason not in {"review_permit_required", "review_permit_mismatch"}:
                    reason = "review_permit_mismatch"
                return {
                    "action": "stop",
                    "stop_reason": reason,
                    "issues": [int(item["number"])],
                }
            if permit_action == "external":
                external_handoffs.append(external_review_handoff(item, permit))
            else:
                local_items.append(item)
        if external_handoffs and not local_items:
            return {
                "action": "handoff_external_reviews",
                "status": "externally-owned",
                "issues": [item["issue"] for item in external_handoffs],
                "handoffs": external_handoffs,
                "ledger_update": "external_review_waiting",
                "ledger_required": True,
            }
        if external_handoffs:
            command = compose_tool_command(review_tool, review_command)
            if not command:
                return {
                    "action": "stop",
                    "stop_reason": "human_gate_review",
                    "issues": _numbers(local_items),
                    "external_handoffs": external_handoffs,
                }
            return {
                "action": "pipeline",
                "actions": [
                    {
                        "action": "handoff_external_reviews",
                        "status": "externally-owned",
                        "issues": [item["issue"] for item in external_handoffs],
                        "handoffs": external_handoffs,
                        "ledger_update": "external_review_waiting",
                    },
                    {
                        "action": "dispatch_background_reviews",
                        "issues": _numbers(local_items),
                        "command": command,
                        "retick_on": "review_completion",
                    },
                ],
                "ledger_required": True,
                "retick_on": "any_lane_completion",
            }
        command = compose_tool_command(review_tool, review_command)
        if command and not pipeline:
            return {"action": "call_review_tool", "issues": review_waiting, "command": command}
        if command:
            actions: list[dict[str, Any]] = [{
                "action": "dispatch_background_reviews",
                "issues": review_waiting,
                "command": command,
                "retick_on": "review_completion",
            }]
            ready = _numbers(ready_state.get("ready"))
            if ready:
                actions.append({
                    "action": "dispatch_background_workers",
                    "issues": ready[:max(1, max_workers)],
                    "ledger_update": "spawned",
                    "retick_on": "worker_completion",
                })
            return {
                "action": "pipeline",
                "actions": actions,
                "ledger_required": True,
                "retick_on": "any_lane_completion",
            }
        return {"action": "stop", "stop_reason": "human_gate_review"}

    if ready_state.get("ok") is False:
        return {"action": "stop", "stop_reason": ready_state.get("stop_reason") or "stuck"}

    ready = _numbers(ready_state.get("ready"))
    if ready:
        if pipeline:
            return {
                "action": "dispatch_background_workers",
                "issues": ready[:max(1, max_workers)],
                "ledger_update": "spawned",
                "ledger_required": True,
                "retick_on": "worker_completion",
            }
        return {"action": "spawn_workers", "issues": ready[:max(1, max_workers)]}
    return {"action": "stop", "stop_reason": "no_progress"}
