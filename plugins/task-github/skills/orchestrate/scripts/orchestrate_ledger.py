#!/usr/bin/env python3
"""Persistent write-through ledger for task-github orchestrate pipeline ticks."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orchestrator_ops

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
        "execution_evidence": {},
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
    payload.setdefault("execution_evidence", {})
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
        "pr_transport", "expected_review_lease", "external_review",
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


def record_execution_evidence(
    path: str | Path, issue: int, projection: dict[str, Any]
) -> dict[str, Any]:
    required = {"schema", "receipt_ref", "evidence_ref", "head", "result"}
    if not isinstance(projection, dict) or set(projection) != required:
        raise ValueError("execution evidence projection has invalid fields")
    if projection.get("schema") != "task-github.execution-evidence-ref/v1":
        raise ValueError("execution evidence projection has invalid schema")
    for name in ("receipt_ref", "evidence_ref"):
        ref = projection.get(name)
        if ref is None and name == "evidence_ref":
            continue
        id_key = "receipt_id" if name == "receipt_ref" else "evidence_id"
        if (
            not isinstance(ref, dict) or set(ref) != {id_key, "digest"}
            or not isinstance(ref.get(id_key), str) or not ref[id_key]
            or not isinstance(ref.get("digest"), str) or not ref["digest"].startswith("sha256:")
        ):
            raise ValueError(f"execution evidence {name} is invalid")
    payload = load_ledger(path)
    key = str(int(issue))
    receipt_id = projection["receipt_ref"]["receipt_id"]
    issue_evidence = payload["execution_evidence"].setdefault(key, {})
    current = issue_evidence.get(receipt_id)
    if current is not None and current != projection:
        raise ValueError("immutable execution evidence projection conflicts with ledger")
    issue_evidence[receipt_id] = dict(projection)
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


def _expected_external_review(issue: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    expected = issue.get("expected_review_lease")
    if not isinstance(expected, dict):
        return None, None
    expected = orchestrator_ops.validate_review_lease(expected)
    if expected["owner"] != "studio":
        return expected, None
    external = issue.get("external_review")
    if not isinstance(external, dict):
        raise ValueError("expected Studio review has no recorded handoff")
    if external.get("review_lease") != expected:
        raise ValueError("external review lease differs from expected review lease")
    if external.get("status") != "approved" or external.get("verdict") != "approved":
        raise ValueError("expected Studio review is not approved; closeout is forbidden")
    evidence = external.get("verdict_evidence_refs")
    if not isinstance(evidence, list) or set(expected["evidence_refs"]) - set(evidence):
        raise ValueError("expected Studio review lacks required evidence; closeout is forbidden")
    return expected, external


def _assert_review_edge_binding(
    payload: dict[str, Any],
    issue_number: int,
    lease: dict[str, Any],
) -> None:
    for number, other in (payload.get("issues") or {}).items():
        if int(number) == int(issue_number):
            continue
        other_lease = other.get("expected_review_lease") if isinstance(other, dict) else None
        if not isinstance(other_lease, dict):
            continue
        if (
            other_lease.get("lease_id") == lease["lease_id"]
            or other_lease.get("edge_id") == lease["edge_id"]
        ):
            raise ValueError(
                f"expected review lease edge is already pinned to issue #{int(number)}"
            )


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
            issue["pr_transport"] = {
                key: event.get(key) for key in ("pr", "base", "head", "head_sha")
                if event.get(key) is not None
            }
            _remove_label(issue, "in-progress")
            _add_label(issue, "in-review")
        elif kind == "expected_review_lease_pinned":
            lease = orchestrator_ops.validate_review_lease(event.get("review_lease"))
            _assert_review_edge_binding(payload, int(issue_number), lease)
            current = issue.get("expected_review_lease")
            if current is not None and current != lease:
                raise ValueError("expected review lease conflicts with the recorded review edge")
            issue["expected_review_lease"] = lease
        elif kind == "external_review_waiting":
            lease = orchestrator_ops.validate_review_lease(event.get("review_lease"))
            if lease["owner"] != "studio":
                raise ValueError("external review handoff requires owner=studio")
            expected = issue.get("expected_review_lease")
            if expected is None:
                raise ValueError("external review handoff requires an expected review lease pin")
            if expected != lease:
                raise ValueError("external review handoff differs from expected review lease")
            transport = {
                key: event.get(key) for key in ("pr", "base", "head", "head_sha")
                if event.get(key) is not None
            }
            if not all(transport.get(key) is not None for key in ("pr", "base", "head")):
                raise ValueError("external review handoff requires PR/base/head transport")
            current = issue.get("external_review")
            next_review = {
                "status": "review_waiting",
                "review_lease": lease,
                **transport,
            }
            if current and current.get("review_lease") != lease:
                raise ValueError("external review lease conflicts with the recorded review edge")
            updated_review = {**(current or {}), **next_review}
            updated_review.pop("verdict", None)
            updated_review.pop("verdict_evidence_refs", None)
            issue["external_review"] = updated_review
            issue["pr"] = int(transport["pr"])
            issue["pr_transport"] = transport
            _remove_label(issue, "in-progress")
            _add_label(issue, "in-review")
        elif kind == "external_review_verdict":
            external = issue.get("external_review")
            if not isinstance(external, dict):
                raise ValueError("external review verdict has no waiting handoff")
            lease = orchestrator_ops.validate_review_lease(event.get("review_lease"))
            if issue.get("expected_review_lease") != lease:
                raise ValueError("external review verdict differs from expected review lease")
            if external.get("review_lease") != lease:
                raise ValueError("external review verdict lease or episode does not match")
            verdict = event.get("verdict")
            if verdict not in {"approved", "changes-requested"}:
                raise ValueError("external review verdict is invalid")
            evidence_refs = list(event.get("evidence_refs") or [])
            if (
                not all(isinstance(ref, str) and ref.strip() for ref in evidence_refs)
                or len(set(evidence_refs)) != len(evidence_refs)
            ):
                raise ValueError("external review verdict evidence_refs must be a unique string list")
            missing = set(lease["evidence_refs"]) - set(evidence_refs)
            if missing:
                raise ValueError("external review verdict lacks required evidence refs")
            external["verdict"] = verdict
            external["verdict_evidence_refs"] = evidence_refs
            external["status"] = "approved" if verdict == "approved" else "changes-requested"
            if verdict == "changes-requested":
                _remove_label(issue, "in-review")
                _add_label(issue, "changes-requested")
        elif kind == "pr_merged":
            expected, _ = _expected_external_review(issue)
            if expected is not None and expected["owner"] == "studio" and issue.get("state") != "closeout_started":
                raise ValueError("expected Studio review merge cannot run before closeout_started")
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
            expected, expected_external = _expected_external_review(issue)
            external = expected_external or issue.get("external_review")
            if external and external.get("status") != "approved":
                raise ValueError("externally owned review is not approved; closeout is forbidden")
            if external:
                if kind != "ready_for_pr_closeout":
                    raise ValueError("externally owned GitHub review requires PR closeout")
                for key in ("pr", "base", "head"):
                    if event.get(key) != external.get(key):
                        raise ValueError(f"external review closeout {key} differs from approved transport")
                if expected is not None and event.get("review_lease_id") != expected["lease_id"]:
                    raise ValueError("external review closeout lease id differs from expected review lease")
            issue["state"] = "closeout_ready"
            closeout = dict(issue.get("ready_for_closeout") or {})
            closeout["mode"] = "pr" if kind == "ready_for_pr_closeout" else closeout.get("mode", "ff")
            for key in ("base", "head", "head_sha", "gear", "review_skipped", "pr", "review_lease_id"):
                if event.get(key) is not None:
                    closeout[key] = event[key]
            closeout["at"] = event.get("at")
            issue["ready_for_closeout"] = closeout
            issue.pop("closeout_started", None)
            issue.pop("closeout_failed", None)
            _remove_state_labels(issue)
        elif kind == "closeout_started":
            expected, _ = _expected_external_review(issue)
            if expected is not None and expected["owner"] == "studio" and issue.get("state") != "closeout_ready":
                raise ValueError("closeout cannot start before ready_for_closeout")
            issue["state"] = "closeout_started"
            started = dict(issue.get("closeout_started") or issue.get("ready_for_closeout") or {})
            for key in ("base", "head", "head_sha", "mode", "pr", "gear", "review_skipped", "review_lease_id"):
                if event.get(key) is not None:
                    started[key] = event[key]
            started["at"] = event.get("at")
            issue["closeout_started"] = started
            _remove_state_labels(issue)
        elif kind == "closeout_done":
            expected, _ = _expected_external_review(issue)
            if (
                expected is not None
                and expected["owner"] == "studio"
                and issue.get("state") not in {"closeout_started", "close_expected"}
            ):
                raise ValueError("closeout cannot finish before closeout_started")
            if issue.get("state") != "CLOSED":
                issue["state"] = "close_expected"
            done = dict(issue.get("closeout_done") or {})
            for key in ("base", "head", "head_sha", "sha_range", "mode", "pr", "review_lease_id"):
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
            for key in ("base", "head", "head_sha", "mode", "pr", "gear", "review_skipped", "review_lease_id", "reason", "message"):
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


def record_expected_review_lease(
    path: str | Path,
    *,
    issue: int,
    review_lease: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Pin the binding-owned review edge before plan/review/closeout.

    The pin is immutable for an issue edge. Replaying the same lease is a
    no-op; rebinding the issue to any other lease fails closed.
    """
    lease = orchestrator_ops.validate_review_lease(review_lease)
    payload = load_ledger(path)
    item = _issue(payload, issue)
    current = item.get("expected_review_lease")
    if current == lease:
        return payload, False
    if current is not None:
        raise ValueError("expected review lease conflicts with the recorded review edge")
    event = {
        "at": _now(),
        "type": "expected_review_lease_pinned",
        "issue": int(issue),
        "review_lease": lease,
    }
    payload["events"].append(event)
    apply_event(payload, event)
    return write_ledger(path, payload), True


def record_external_review_handoff(
    path: str | Path,
    *,
    issue: int,
    pr: int,
    base: str,
    head: str,
    review_lease: dict[str, Any],
    head_sha: str | None = None,
) -> tuple[dict[str, Any], bool]:
    lease = orchestrator_ops.validate_review_lease(review_lease)
    if lease["owner"] != "studio":
        raise ValueError("external review handoff requires owner=studio")
    payload = load_ledger(path)
    item = _issue(payload, issue)
    if item.get("expected_review_lease") != lease:
        raise ValueError("external review handoff requires the exact expected review lease pin")
    current = item.get("external_review")
    semantic = {
        "status": "review_waiting",
        "review_lease": lease,
        "pr": int(pr),
        "base": base,
        "head": head,
    }
    if head_sha is not None:
        semantic["head_sha"] = head_sha
    if current:
        current_semantic = {
            key: current.get(key) for key in semantic
        }
        if current_semantic == semantic:
            return payload, False
        if current.get("review_lease") != lease:
            raise ValueError("external review handoff conflicts with the recorded lease")
        if current.get("status") == "approved":
            raise ValueError("approved external review cannot be replaced")
    event = {
        "at": _now(),
        "type": "external_review_waiting",
        "issue": int(issue),
        "pr": int(pr),
        "base": base,
        "head": head,
        "review_lease": lease,
    }
    if head_sha is not None:
        event["head_sha"] = head_sha
    payload["events"].append(event)
    apply_event(payload, event)
    return write_ledger(path, payload), True


def record_external_review_verdict(
    path: str | Path,
    *,
    issue: int,
    review_lease: dict[str, Any],
    verdict: str,
    evidence_refs: list[str],
) -> tuple[dict[str, Any], bool]:
    lease = orchestrator_ops.validate_review_lease(review_lease)
    if verdict not in {"approved", "changes-requested"}:
        raise ValueError("external review verdict must be approved or changes-requested")
    if (
        not isinstance(evidence_refs, list)
        or not all(isinstance(ref, str) and ref.strip() for ref in evidence_refs)
        or len(set(evidence_refs)) != len(evidence_refs)
    ):
        raise ValueError("external review verdict evidence_refs must be a unique string list")
    missing = sorted(set(lease["evidence_refs"]) - set(evidence_refs))
    if missing:
        raise ValueError(f"external review verdict lacks required evidence refs: {missing}")

    payload = load_ledger(path)
    item = _issue(payload, issue)
    if item.get("expected_review_lease") != lease:
        raise ValueError("external review verdict lease does not match the expected review lease pin")
    external = item.get("external_review")
    if not isinstance(external, dict):
        raise ValueError("external review verdict has no waiting handoff")
    if external.get("review_lease") != lease:
        raise ValueError("external review verdict lease or episode does not match")
    existing_verdict = external.get("verdict")
    existing_evidence = external.get("verdict_evidence_refs")
    if existing_verdict == verdict and existing_evidence == evidence_refs:
        return payload, False
    if existing_verdict == "approved":
        raise ValueError("approved external review verdict is immutable")

    verdict_event = {
        "at": _now(),
        "type": "external_review_verdict",
        "issue": int(issue),
        "verdict": verdict,
        "review_lease": lease,
        "evidence_refs": list(evidence_refs),
    }
    payload["events"].append(verdict_event)
    apply_event(payload, verdict_event)
    if verdict == "approved":
        transport = item.get("external_review") or external
        closeout_event = {
            "at": _now(),
            "type": "ready_for_pr_closeout",
            "issue": int(issue),
            "pr": transport.get("pr"),
            "base": transport.get("base"),
            "head": transport.get("head"),
            "head_sha": transport.get("head_sha"),
            "review_lease_id": lease["lease_id"],
        }
        payload["events"].append(closeout_event)
        apply_event(payload, closeout_event)
    return write_ledger(path, payload), True


def record_events(path: str | Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = load_ledger(path)
    payload.setdefault("events", [])
    for raw_event in events:
        event = {"at": _now(), **raw_event}
        payload["events"].append(event)
        apply_event(payload, event)
    return write_ledger(path, payload)


def record_closeout_success(path: str | Path, issue: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = load_ledger(path)
    issue = int(issue)
    payload["spawned"] = [number for number in payload["spawned"] if int(number) != issue]
    payload["failed"] = [number for number in payload["failed"] if int(number) != issue]
    payload.setdefault("events", [])
    for raw_event in [*events, {"type": "worker_completed", "issue": issue}]:
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
    external_reviews = []
    for issue in issues.values():
        external = issue.get("external_review")
        if not isinstance(external, dict):
            continue
        lease = external.get("review_lease") or {}
        external_reviews.append({
            "issue": int(issue["number"]),
            "status": external.get("status"),
            "pr": external.get("pr"),
            "base": external.get("base"),
            "head": external.get("head"),
            "lease_id": lease.get("lease_id"),
            "episode_id": lease.get("episode_id"),
            "edge_id": lease.get("edge_id"),
            "evidence_refs": lease.get("evidence_refs", []),
        })
    expected_reviews = []
    for issue in issues.values():
        lease = issue.get("expected_review_lease")
        if not isinstance(lease, dict):
            continue
        expected_reviews.append({
            "issue": int(issue["number"]),
            "owner": lease.get("owner"),
            "lease_id": lease.get("lease_id"),
            "episode_id": lease.get("episode_id"),
            "edge_id": lease.get("edge_id"),
        })
    return {
        "root": payload.get("root"),
        "spawned": list(payload.get("spawned") or []),
        "failed": list(payload.get("failed") or []),
        "ready_for_closeout": issue_items("closeout_ready"),
        "running_closeout": issue_items("closeout_started"),
        "failed_closeout": issue_items("closeout_failed"),
        "external_reviews": sorted(external_reviews, key=lambda item: item["issue"]),
        "expected_reviews": sorted(expected_reviews, key=lambda item: item["issue"]),
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
    parser.add_argument("--review-lease-id")
    parser.add_argument("--review-lease-json")
    parser.add_argument("--expected-review-lease-json")
    parser.add_argument("--review-verdict", choices=("approved", "changes-requested"))
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--merge-evidence-json")
    parser.add_argument("--gate-evidence-json")
    parser.add_argument("--preflight-evidence-json")
    parser.add_argument("--execution-evidence-json")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--events-tail", type=int, default=5)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        if args.summary:
            payload = load_ledger(args.path)
        elif args.execution_evidence_json:
            if args.issue is None:
                raise ValueError("--issue is required with execution evidence JSON")
            payload = record_execution_evidence(
                args.path, args.issue, json.loads(args.execution_evidence_json)
            )
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
        elif args.expected_review_lease_json:
            if args.issue is None:
                raise ValueError("--issue is required with expected review lease JSON")
            payload, _ = record_expected_review_lease(
                args.path,
                issue=args.issue,
                review_lease=json.loads(args.expected_review_lease_json),
            )
        elif args.review_lease_json:
            if args.issue is None:
                raise ValueError("--issue is required with review lease JSON")
            lease = json.loads(args.review_lease_json)
            if args.review_verdict:
                payload, _ = record_external_review_verdict(
                    args.path,
                    issue=args.issue,
                    review_lease=lease,
                    verdict=args.review_verdict,
                    evidence_refs=args.evidence_ref,
                )
            else:
                if args.pr is None or args.base is None or args.head is None:
                    raise ValueError("--pr, --base, and --head are required for external review handoff")
                payload, _ = record_external_review_handoff(
                    args.path,
                    issue=args.issue,
                    pr=args.pr,
                    base=args.base,
                    head=args.head,
                    head_sha=args.head_sha,
                    review_lease=lease,
                )
        elif args.event:
            event = {"type": args.event}
            for key in (
                "issue", "pr", "head", "base", "head_sha", "sha_range", "gear",
                "reason", "message", "review_lease_id",
            ):
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
