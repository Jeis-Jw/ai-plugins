#!/usr/bin/env python3
"""Pure orchestration decisions shared by task-github orchestrate docs/tests."""

from __future__ import annotations

from typing import Any

GEARS = ("micro", "normal", "major")
GEAR_RANK = {"micro": 0, "normal": 1, "major": 2}
GEAR_OPTION_KEYS = ("plan", "verify", "pr-review")
DEFAULT_GEAR_OPTIONS = {
    "micro": {"plan": False, "verify": True, "pr-review": False},
    "normal": {"plan": True, "verify": True, "pr-review": False},
    "major": {"plan": True, "verify": True, "pr-review": True},
}


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
) -> bool:
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
        return {"action": "merge"}
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


def _numbers(items: list[dict[str, Any]] | None) -> list[int]:
    return [int(item["number"]) for item in items or []]


def plan_tick(
    ready_state: dict[str, Any],
    *,
    review_tool: str | None,
    review_command: str | None = None,
    max_workers: int = 1,
    pipeline: bool = False,
) -> dict[str, Any]:
    pipeline = pipeline or max_workers > 1

    # Branch order mirrors evaluate_tree / SKILL.md: stuck and api_failure (ok:false
    # 하드 STOP) win over merge/spawn. evaluate_tree leaves done_parents/review_waiting
    # populated even when it _stop()s for stuck, so these must be gated FIRST — else a
    # stuck tick with a completed parent would auto-merge instead of STOP (부분진행금지 위반).
    if ready_state.get("stuck"):
        return {"action": "stop", "stop_reason": ready_state.get("stop_reason") or "stuck"}
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

    review_waiting = _numbers(ready_state.get("review_waiting"))
    if review_waiting:
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
