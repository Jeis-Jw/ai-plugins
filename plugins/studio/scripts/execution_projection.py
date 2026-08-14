#!/usr/bin/env python3
"""Pure Studio projection over canonical session-review and task-worker results."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


SCHEMA = "studio.final-candidate-projection/v1"
QA_SCHEMA = "task-worker.final-qa-projection/v1"
STATUS_FIELDS = frozenset((
    "phase", "active_actor", "lock_since", "next_actor", "target_mode",
    "target_nature", "target_ref", "base_ref", "responding_to", "round",
    "round_type", "flow_mode", "self_automation", "recording_mode",
    "review_strength", "review_posture", "blocking_count", "lease_id",
    "reviewer_ref", "reviewed_ref", "scope_digest", "finding_digest",
    "lease_started_at", "lease_updated_at", "lease_target_ref", "lease_base_ref",
    "lease_risk", "lease_expires_round", "fresh_required",
    "fresh_fallback_reason", "fresh_count", "reuse_count",
))
REQUIRED_STATUS_FIELDS = STATUS_FIELDS - {"review_posture"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def instance_digest(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "digest"}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{field} must be a sha256 digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a sha256 digest") from exc
    return value


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _validate_review(status: Any, candidate: str, reviewer_ref: str) -> datetime:
    if not isinstance(status, dict) or not REQUIRED_STATUS_FIELDS.issubset(status):
        raise ValueError("review_status is not a complete canonical session-review status")
    if set(status) - STATUS_FIELDS:
        raise ValueError("review_status contains unknown fields")
    if not isinstance(status.get("round"), int) or status["round"] < 1:
        raise ValueError("review_status round must be positive")
    for field in ("blocking_count", "lease_expires_round", "fresh_count", "reuse_count"):
        if not isinstance(status.get(field), int) or status[field] < 0:
            raise ValueError(f"review_status {field} must be non-negative")
    for field in ("scope_digest", "finding_digest"):
        _digest(status.get(field), field)
    started = _timestamp(status.get("lease_started_at"), "lease_started_at")
    confirmed = _timestamp(status.get("lease_updated_at"), "lease_updated_at")
    if confirmed < started:
        raise ValueError("review lease update precedes lease start")
    if status.get("reviewer_ref") != reviewer_ref:
        raise ValueError("review confirmation is not from the original addressable reviewer")
    if (
        status.get("phase") != "approved" or status.get("blocking_count") != 0
        or status.get("active_actor") != "none" or status.get("next_actor") != "worker"
        or status.get("round_type") != "confirm" or status.get("review_strength") != "hard"
        or status.get("reviewed_ref") != candidate
        or not status.get("lease_id") or status.get("fresh_required") is not False
        or status.get("lease_target_ref") != status.get("target_ref")
        or status.get("lease_base_ref") != status.get("base_ref")
    ):
        raise ValueError("review_status is not the required hard-review confirmation")
    return confirmed


def _combine_final_candidate(
    review_status: dict[str, Any], qa_projection: dict[str, Any], reviewer_ref: str,
) -> dict[str, Any]:
    if not isinstance(reviewer_ref, str) or not reviewer_ref:
        raise ValueError("reviewer_ref must identify the original addressable reviewer")
    if (
        not isinstance(qa_projection, dict)
        or set(qa_projection) != {
            "schema", "candidate_ref", "source_tree_digest", "criteria_digest",
            "attempts", "result", "digest",
        }
        or qa_projection.get("schema") != QA_SCHEMA
    ):
        raise ValueError("qa_projection is not canonical task-worker final QA")
    if qa_projection.get("digest") != instance_digest(qa_projection):
        raise ValueError("qa_projection digest differs")
    candidate = qa_projection.get("candidate_ref")
    if not isinstance(candidate, str) or not candidate:
        raise ValueError("qa_projection candidate_ref must be non-empty")
    _digest(qa_projection.get("source_tree_digest"), "source_tree_digest")
    _digest(qa_projection.get("criteria_digest"), "criteria_digest")
    confirmed_at = _validate_review(review_status, candidate, reviewer_ref)
    attempts = qa_projection.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("qa_projection attempts must be a list")
    passed = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != {
            "receipt_ref", "evidence_ref", "result", "started_at", "finished_at",
        }:
            raise ValueError("qa_projection attempt fields differ")
        receipt_ref = attempt["receipt_ref"]
        if not isinstance(receipt_ref, dict) or set(receipt_ref) != {"receipt_id", "digest"}:
            raise ValueError("qa_projection receipt_ref fields differ")
        if not isinstance(receipt_ref["receipt_id"], str) or not receipt_ref["receipt_id"]:
            raise ValueError("qa_projection receipt_id must be non-empty")
        _digest(receipt_ref["digest"], "receipt_ref.digest")
        started = _timestamp(attempt["started_at"], "attempt.started_at")
        finished = _timestamp(attempt["finished_at"], "attempt.finished_at")
        if finished < started:
            raise ValueError("QA attempt finish precedes start")
        if attempt["result"] != "pass":
            if attempt["evidence_ref"] is not None:
                raise ValueError("failed QA attempt cannot claim passing evidence")
            if finished >= confirmed_at:
                return {"action": "reject", "reason": "review-reconfirmation-required"}
            continue
        evidence_ref = attempt["evidence_ref"]
        if not isinstance(evidence_ref, dict) or set(evidence_ref) != {"evidence_id", "digest"}:
            raise ValueError("passing QA evidence_ref fields differ")
        if not isinstance(evidence_ref["evidence_id"], str) or not evidence_ref["evidence_id"]:
            raise ValueError("qa_projection evidence_id must be non-empty")
        _digest(evidence_ref["digest"], "evidence_ref.digest")
        if started <= confirmed_at:
            return {"action": "reject", "reason": "fresh-final-root-qa-required"}
        passed.append(attempt)
    if qa_projection.get("result") != "pass" or len(passed) != 1:
        return {"action": "reject", "reason": "final-root-qa-required"}
    result: dict[str, Any] = {
        "schema": SCHEMA, "action": "accept", "candidate_ref": candidate,
        "reviewer_ref": reviewer_ref, "review_finding_digest": review_status["finding_digest"],
        "qa_projection_digest": qa_projection["digest"],
        "receipt_ref": passed[0]["receipt_ref"], "evidence_ref": passed[0]["evidence_ref"],
    }
    result["digest"] = instance_digest(result)
    return result


def project_final_candidate(
    review_status: dict[str, Any], final_qa_request: dict[str, Any], reviewer_ref: str,
    *, task_worker_projector: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Resolve task-worker refs through its canonical projector, then combine."""
    if (
        not isinstance(final_qa_request, dict) or set(final_qa_request) != {"final_qa"}
        or not isinstance(final_qa_request["final_qa"], dict)
    ):
        raise ValueError("final_qa_request must contain only final_qa refs")
    if not callable(task_worker_projector):
        raise ValueError("task_worker_projector is required")
    qa_projection = task_worker_projector(final_qa_request)
    return _combine_final_candidate(review_status, qa_projection, reviewer_ref)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-status", required=True)
    parser.add_argument("--final-qa-request", required=True)
    parser.add_argument("--task-worker-cli", required=True)
    parser.add_argument("--reviewer-ref", required=True)
    args = parser.parse_args()
    try:
        task_worker_cli = Path(args.task_worker_cli).resolve(strict=True)
        request_path = Path(args.final_qa_request).resolve(strict=True)

        def task_worker_projector(request: dict[str, Any]) -> dict[str, Any]:
            completed = subprocess.run(
                [sys.executable, str(task_worker_cli), "execution-evaluate", "--request", str(request_path)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            if completed.returncode != 0:
                raise ValueError("task-worker rejected final QA refs")
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("task-worker returned invalid JSON") from exc
            if payload.get("ok") is not True or not isinstance(payload.get("decision"), dict):
                raise ValueError("task-worker did not return a final QA projection")
            return payload["decision"]

        final_qa_request = json.loads(request_path.read_text(encoding="utf-8"))
        if set(final_qa_request) != {"final_qa"}:
            raise ValueError("final_qa_request must contain only final_qa")
        result = project_final_candidate(
            json.loads(Path(args.review_status).read_text(encoding="utf-8")),
            final_qa_request, args.reviewer_ref,
            task_worker_projector=task_worker_projector,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "projection": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
