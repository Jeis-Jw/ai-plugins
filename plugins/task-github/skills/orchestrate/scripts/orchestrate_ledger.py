#!/usr/bin/env python3
"""Persistent write-through ledger for task-github orchestrate pipeline ticks."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_LABELS = {"in-progress", "in-review", "changes-requested"}


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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_github_reads() -> dict[str, Any]:
    return {"count": 0, "reasons": [], "entries": []}


def _default() -> dict[str, Any]:
    return {
        "version": 3,
        "spawned": [],
        "failed": [],
        "issues": {},
        "prs": {},
        "events": [],
        "github_reads": _empty_github_reads(),
        "read_decisions": [],
        "merge_evidence": {},
        "gate_evidence": {},
        "preflight_evidence": {},
    }


def _int_list(value: Any) -> list[int]:
    if isinstance(value, str):
        return sorted(parse_number_set(value))
    return sorted(int(issue) for issue in value or [])


def _normalise_github_reads(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _empty_github_reads()
    entries = list(value.get("entries") or [])
    reasons = list(value.get("reasons") or [])
    if not reasons:
        reasons = [str(entry.get("reason")) for entry in entries if entry.get("reason")]
    try:
        count = int(value.get("count", 0))
    except (TypeError, ValueError):
        count = 0
    count = max(count, len(entries), len(reasons))
    return {"count": count, "reasons": reasons, "entries": entries}


def _ensure_v3(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        version = int(payload.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version < 3:
        payload["version"] = 3
    payload["github_reads"] = _normalise_github_reads(payload.get("github_reads"))
    payload.setdefault("read_decisions", [])
    payload.setdefault("merge_evidence", {})
    payload.setdefault("gate_evidence", {})
    payload.setdefault("preflight_evidence", {})
    return payload


def load_ledger(path: str | Path, *, reset_on_corrupt: bool = False) -> dict[str, Any]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return _default()
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"top-level {type(payload).__name__}, expected object")
    except (json.JSONDecodeError, ValueError) as exc:
        # A corrupt/non-object ledger (e.g. a bare list from a stale/foreign writer) used to crash
        # with `'list' object has no attribute 'get'` mid-closeout; the recovery then rewrote a
        # fresh default and silently dropped the orchestrator's merge_evidence.
        if reset_on_corrupt:
            # full rebuild-from-GitHub (record_snapshot / --reconcile-github): the corrupt local
            # content is unsalvageable, so start clean instead of bricking the documented recovery.
            return _default()
        # read/append paths: fail loud and DON'T overwrite — caller treats a LEDGER error as STOP.
        raise ValueError(
            f"ledger {ledger_path} is malformed ({exc}); reconcile GitHub first — do not overwrite it"
        ) from exc
    payload = _ensure_v3(payload)
    payload["spawned"] = _int_list(payload.get("spawned"))
    payload["failed"] = _int_list(payload.get("failed"))
    payload.setdefault("issues", {})
    payload.setdefault("prs", {})
    payload.setdefault("events", [])
    return payload


def write_ledger(path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _label_list(node: dict[str, Any]) -> list[str]:
    labels = node.get("labels") or []
    out = []
    for label in labels:
        out.append(str(label.get("name") if isinstance(label, dict) else label))
    return [label for label in out if label]


def _snapshot_issue(node: dict[str, Any], *, parent: int | None, issues: dict[str, Any]) -> None:
    children = list(node.get("children") or [])
    number = int(node["number"])
    issues[str(number)] = {
        "number": number,
        "title": node.get("title", ""),
        "state": node.get("state", ""),
        "labels": _label_list(node),
        "open_blockers": list(node.get("open_blockers") or []),
        "parent": parent,
        "children": [int(child["number"]) for child in children],
    }
    for child in children:
        _snapshot_issue(child, parent=number, issues=issues)


def _preserve_ledger_issue_state(new_issue: dict[str, Any], old_issue: dict[str, Any] | None) -> None:
    if not isinstance(old_issue, dict):
        return
    for key in (
        "pr", "merged_pr", "ff_merged", "closed_no_pr",
        "ready_for_closeout", "closeout_started", "closeout_failed", "closeout_done",
    ):
        if key in old_issue:
            new_issue[key] = old_issue[key]
    if new_issue.get("state") == "OPEN" and old_issue.get("state") in {
        "closeout_ready", "closeout_started", "closeout_failed", "close_expected",
    }:
        new_issue["state"] = old_issue["state"]


def record_snapshot(path: str | Path, tree: dict[str, Any]) -> dict[str, Any]:
    # --reconcile-github rebuild: overwrite the tree from GitHub SoT. Must survive a corrupt local
    # ledger — this IS the documented recovery for one, so it can't refuse to load it.
    payload = load_ledger(path, reset_on_corrupt=True)
    old_issues = dict(payload.get("issues") or {})
    issues: dict[str, Any] = {}
    _snapshot_issue(tree, parent=None, issues=issues)
    for number, issue in issues.items():
        _preserve_ledger_issue_state(issue, old_issues.get(number))
    payload["root"] = int(tree["number"])
    payload["snapshot_at"] = _now()
    payload["issues"] = issues
    return write_ledger(path, payload)


def record_github_read(
    path: str | Path,
    *,
    reason: str,
    operation: str,
    root: int | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not reason:
        raise ValueError("github read reason is required")
    payload = load_ledger(path)
    reads = payload["github_reads"]
    entry: dict[str, Any] = {"at": _now(), "reason": reason, "operation": operation}
    if root is not None:
        entry["root"] = int(root)
    if detail:
        entry["detail"] = dict(detail)
    reads["entries"].append(entry)
    reads["reasons"].append(reason)
    reads["count"] = len(reads["entries"])
    return write_ledger(path, payload)


def record_read_decision(
    path: str | Path,
    *,
    source: str,
    mode: str,
    root: int | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = load_ledger(path)
    entry: dict[str, Any] = {"at": _now(), "source": source, "mode": mode}
    if root is not None:
        entry["root"] = int(root)
    if result is not None:
        entry["result"] = dict(result)
    payload["read_decisions"].append(entry)
    return write_ledger(path, payload)


def record_merge_evidence(path: str | Path, issue: int, evidence: dict[str, Any]) -> dict[str, Any]:
    payload = load_ledger(path)
    payload["merge_evidence"][str(int(issue))] = {"at": _now(), **dict(evidence)}
    return write_ledger(path, payload)


def record_gate_evidence(path: str | Path, issue: int, evidence: dict[str, Any]) -> dict[str, Any]:
    payload = load_ledger(path)
    payload["gate_evidence"][str(int(issue))] = {"at": _now(), **dict(evidence)}
    return write_ledger(path, payload)


def record_preflight_evidence(path: str | Path, pr: int, evidence: dict[str, Any]) -> dict[str, Any]:
    payload = load_ledger(path)
    payload["preflight_evidence"][str(int(pr))] = {"at": _now(), **dict(evidence)}
    return write_ledger(path, payload)


def _issue(payload: dict[str, Any], number: int) -> dict[str, Any]:
    key = str(int(number))
    issue = payload.setdefault("issues", {}).setdefault(key, {"number": int(number), "labels": [], "children": []})
    issue.setdefault("number", int(number))
    issue.setdefault("labels", [])
    issue.setdefault("children", [])
    return issue


def _add_label(issue: dict[str, Any], label: str) -> None:
    labels = set(issue.get("labels") or [])
    labels.add(label)
    issue["labels"] = sorted(labels)


def _remove_label(issue: dict[str, Any], label: str) -> None:
    issue["labels"] = [item for item in issue.get("labels", []) if item != label]


def _remove_state_labels(issue: dict[str, Any]) -> None:
    issue["labels"] = [item for item in issue.get("labels", []) if item not in STATE_LABELS]


def _merge_evidence(payload: dict[str, Any], issue: int, evidence: dict[str, Any]) -> None:
    """Merge (not replace) merge_evidence for an issue.

    A re-applied event must not delete keys another writer (the orchestrator) already recorded,
    nor null out an existing non-None field with a sparser re-record. Only non-None new values,
    or keys absent from the existing entry, are written.
    """
    store = payload.setdefault("merge_evidence", {})
    existing = dict(store.get(str(int(issue))) or {})
    for key, value in evidence.items():
        if value is not None or key not in existing:
            existing[key] = value
    store[str(int(issue))] = existing


def apply_event(payload: dict[str, Any], event: dict[str, Any]) -> None:
    kind = event.get("type")
    issue_number = event.get("issue")
    if issue_number is not None:
        issue = _issue(payload, int(issue_number))
        if kind == "issue_started":
            issue["state"] = "OPEN"
            _add_label(issue, "in-progress")
        elif kind == "issue_closed":
            issue["state"] = "CLOSED"
            _remove_state_labels(issue)
        elif kind == "issue_label_added" and event.get("label"):
            _add_label(issue, str(event["label"]))
        elif kind == "issue_label_removed" and event.get("label"):
            _remove_label(issue, str(event["label"]))
        elif kind == "pr_created" and event.get("pr") is not None:
            issue["pr"] = int(event["pr"])
            _remove_label(issue, "in-progress")
            _add_label(issue, "in-review")
        elif kind == "pr_merged":
            # Idempotent: a re-applied merge event must not regress a CLOSED issue back to
            # close_expected (the thrash the orchestrator saw), and must not wipe evidence
            # keys a prior writer (e.g. the orchestrator) already recorded — merge, don't replace.
            if issue.get("state") != "CLOSED":
                issue["state"] = "close_expected"
            merged_pr = {
                "number": event.get("pr"),
                "base": event.get("base"),
                "head": event.get("head"),
            }
            for key in ("head_sha", "merge_commit_sha"):
                if event.get(key):
                    merged_pr[key] = event[key]
            issue["merged_pr"] = merged_pr
            _merge_evidence(
                payload,
                int(issue_number),
                {
                    "kind": "merged_pr",
                    "issue": int(issue_number),
                    "pr": event.get("pr"),
                    "base": event.get("base"),
                    "head": event.get("head"),
                    "head_sha": event.get("head_sha"),
                    "merge_commit_sha": event.get("merge_commit_sha"),
                    "parent_contains_child": True,
                },
            )
            _remove_state_labels(issue)
        elif kind == "ff_merged":
            # micro/normal leaf/container merged to parent via local FF (no PR).
            # Close evidence = the merged SHA range, so container merge-up can
            # validate it (orchestrator_ops.child_merge_evidence). Same no-regress rule as pr_merged.
            if issue.get("state") != "CLOSED":
                issue["state"] = "close_expected"
            ff = dict(issue.get("ff_merged") or {})
            for key, value in {"base": event.get("base"), "sha_range": event.get("sha_range")}.items():
                if value is not None or key not in ff:
                    ff[key] = value
            issue["ff_merged"] = ff
            _remove_state_labels(issue)
        elif kind in {"ready_for_closeout", "ready_for_pr_closeout"}:
            issue["state"] = "closeout_ready"
            closeout = dict(issue.get("ready_for_closeout") or {})
            closeout["mode"] = "pr" if kind == "ready_for_pr_closeout" else closeout.get("mode", "ff")
            for key in ("base", "head", "head_sha", "gear", "review_skipped", "pr"):
                if event.get(key) is not None:
                    closeout[key] = event[key]
            closeout["at"] = event.get("at")
            issue["ready_for_closeout"] = closeout
            issue.pop("closeout_started", None)
            issue.pop("closeout_failed", None)
            _remove_state_labels(issue)
        elif kind == "closeout_started":
            issue["state"] = "closeout_started"
            started = dict(issue.get("closeout_started") or issue.get("ready_for_closeout") or {})
            for key in ("base", "head", "head_sha", "mode", "pr", "gear", "review_skipped"):
                if event.get(key) is not None:
                    started[key] = event[key]
            started["at"] = event.get("at")
            issue["closeout_started"] = started
            _remove_state_labels(issue)
        elif kind == "closeout_done":
            if issue.get("state") != "CLOSED":
                issue["state"] = "close_expected"
            done = dict(issue.get("closeout_done") or {})
            for key in ("base", "head", "head_sha", "sha_range", "mode", "pr"):
                if event.get(key) is not None:
                    done[key] = event[key]
            done["at"] = event.get("at")
            issue["closeout_done"] = done
            issue.pop("ready_for_closeout", None)
            issue.pop("closeout_started", None)
            issue.pop("closeout_failed", None)
            _remove_state_labels(issue)
        elif kind == "closeout_failed":
            issue["state"] = "closeout_failed"
            failed = dict(issue.get("closeout_failed") or issue.get("closeout_started") or issue.get("ready_for_closeout") or {})
            for key in ("base", "head", "head_sha", "mode", "pr", "gear", "review_skipped", "reason", "message"):
                if event.get(key) is not None:
                    failed[key] = event[key]
            failed["at"] = event.get("at")
            issue["closeout_failed"] = failed
            issue.pop("closeout_started", None)
            _remove_state_labels(issue)

    if event.get("pr") is not None:
        pr = payload.setdefault("prs", {}).setdefault(str(int(event["pr"])), {"number": int(event["pr"])})
        if issue_number is not None:
            pr["issue"] = int(issue_number)
        if event.get("head"):
            pr["head"] = event["head"]
        if event.get("base"):
            pr["base"] = event["base"]
        if kind == "pr_created":
            pr["state"] = "OPEN"
        elif kind == "pr_merged":
            pr["state"] = "MERGED"
        elif kind == "ci_green":
            pr["checks"] = "SUCCESS"


def record_event(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    payload = load_ledger(path)
    payload.setdefault("events", [])
    event = {"at": _now(), **event}
    payload["events"].append(event)
    apply_event(payload, event)
    return write_ledger(path, payload)


def record_events(path: str | Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = load_ledger(path)
    payload.setdefault("events", [])
    for raw_event in events:
        event = {"at": _now(), **raw_event}
        payload["events"].append(event)
        apply_event(payload, event)
    return write_ledger(path, payload)


def tree_from_ledger(payload: dict[str, Any], root: int | None = None) -> dict[str, Any]:
    issues = payload.get("issues") or {}
    root = int(root if root is not None else payload.get("root"))

    def build(number: int) -> dict[str, Any]:
        issue = dict(issues[str(number)])
        children = [build(int(child)) for child in issue.get("children") or []]
        issue["children"] = children
        issue["subissues_summary"] = {
            "total": len(children),
            "completed": sum(1 for child in children if child.get("state") in {"CLOSED", "close_expected"}),
        }
        return issue

    if str(root) not in issues:
        raise ValueError(f"ledger has no issue #{root}; reconcile GitHub first")
    return build(root)


def update_ledger(
    path: str | Path,
    *,
    spawned: set[int] | None = None,
    failed: set[int] | None = None,
    completed: set[int] | None = None,
) -> dict[str, Any]:
    payload = load_ledger(path)
    spawned_set = set(payload["spawned"]) | (spawned or set())
    failed_set = set(payload["failed"]) | (failed or set())
    completed_set = completed or set()
    spawned_set -= completed_set
    failed_set -= completed_set
    payload["spawned"] = sorted(spawned_set)
    payload["failed"] = sorted(failed_set)
    for issue in spawned or set():
        apply_event(payload, {"type": "issue_started", "issue": issue})
    for issue in completed_set:
        apply_event(payload, {"type": "worker_completed", "issue": issue})
    return write_ledger(path, payload)


def compact_summary(payload: dict[str, Any], *, events_tail: int = 5) -> dict[str, Any]:
    issues = payload.get("issues") or {}

    def issue_items(state: str) -> list[dict[str, Any]]:
        out = []
        for issue in issues.values():
            if issue.get("state") != state:
                continue
            item = {"issue": int(issue["number"])}
            if state == "closeout_started":
                source = issue.get("closeout_started") or issue.get("ready_for_closeout") or {}
            elif state == "closeout_failed":
                source = issue.get("closeout_failed") or issue.get("closeout_started") or issue.get("ready_for_closeout") or {}
            else:
                source = issue.get("ready_for_closeout") or {}
            for key in ("base", "head", "head_sha", "mode", "pr", "gear", "review_skipped", "reason"):
                if source.get(key) is not None:
                    item[key] = source[key]
            out.append(item)
        return sorted(out, key=lambda item: (str(item.get("base", "")), item["issue"]))

    reads = payload.get("github_reads") or {}
    return {
        "root": payload.get("root"),
        "spawned": list(payload.get("spawned") or []),
        "failed": list(payload.get("failed") or []),
        "ready_for_closeout": issue_items("closeout_ready"),
        "running_closeout": issue_items("closeout_started"),
        "failed_closeout": issue_items("closeout_failed"),
        "events_tail": list(payload.get("events") or [])[-max(0, events_tail):],
        "github_reads": {
            "count": int(reads.get("count") or 0),
            "reasons_tail": list(reads.get("reasons") or [])[-max(0, events_tail):],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="ledger JSON path, e.g. .task-github/orchestrate/1.json")
    parser.add_argument("--spawned", default="", help="comma/space-separated issues to mark active")
    parser.add_argument("--failed", default="", help="comma/space-separated issues to mark failed")
    parser.add_argument("--completed", default="", help="comma/space-separated issues to remove from active/failed")
    parser.add_argument("--event", choices=(
        "issue_started", "pr_created", "ci_green", "pr_merged", "ff_merged", "issue_closed",
        "ready_for_closeout", "ready_for_pr_closeout", "closeout_started", "closeout_done", "closeout_failed",
    ))
    parser.add_argument("--issue", type=int)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head")
    parser.add_argument("--base")
    parser.add_argument("--head-sha", dest="head_sha")
    parser.add_argument("--sha-range", dest="sha_range")
    parser.add_argument("--gear")
    parser.add_argument("--reason")
    parser.add_argument("--message")
    parser.add_argument("--review-skipped", action="store_true")
    parser.add_argument("--merge-evidence-json")
    parser.add_argument("--gate-evidence-json")
    parser.add_argument("--preflight-evidence-json")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--events-tail", type=int, default=5)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        if args.summary:
            payload = load_ledger(args.path)
        elif args.preflight_evidence_json:
            if args.pr is None:
                raise ValueError("--pr is required with preflight evidence JSON")
            payload = record_preflight_evidence(args.path, args.pr, json.loads(args.preflight_evidence_json))
        elif args.merge_evidence_json or args.gate_evidence_json:
            if args.issue is None:
                raise ValueError("--issue is required with evidence JSON")
            if args.merge_evidence_json:
                payload = record_merge_evidence(args.path, args.issue, json.loads(args.merge_evidence_json))
            else:
                payload = record_gate_evidence(args.path, args.issue, json.loads(args.gate_evidence_json))
        elif args.event:
            event = {"type": args.event}
            for key in ("issue", "pr", "head", "base", "head_sha", "sha_range", "gear", "reason", "message"):
                value = getattr(args, key)
                if value is not None:
                    event[key] = value
            if args.review_skipped:
                event["review_skipped"] = True
            payload = record_event(args.path, event)
        else:
            payload = update_ledger(
                args.path,
                spawned=parse_number_set(args.spawned),
                failed=parse_number_set(args.failed),
                completed=parse_number_set(args.completed),
            )
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False))
        return 1

    if args.summary:
        summary = compact_summary(payload, events_tail=args.events_tail)
        print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False) if args.as_json else json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.as_json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
    else:
        print(",".join(str(issue) for issue in payload["spawned"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
