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
    failure_after_confirmation = False
    pass_before_confirmation = False
    seen_batches: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != {
            "batch", "result", "started_at", "finished_at",
        }:
            raise ValueError("qa_projection attempt fields differ")
        batch = attempt["batch"]
        batch_fields = {
            "schema", "candidate_ref", "source_tree_digest", "criteria_digest", "target",
            "environment_digest", "fresh_requirement_id", "expected_selectors",
            "covered_selectors", "profile_refs", "profiles_digest", "children",
            "missing_selectors", "unexpected_selectors", "failed_child_refs", "result", "digest",
        }
        if (
            not isinstance(batch, dict) or set(batch) != batch_fields
            or batch.get("schema") != "task-worker.verification-evidence-batch/v1"
            or batch.get("digest") != instance_digest(batch)
            or batch.get("candidate_ref") != candidate
            or batch.get("source_tree_digest") != qa_projection["source_tree_digest"]
            or batch.get("criteria_digest") != qa_projection["criteria_digest"]
            or batch.get("result") != attempt.get("result")
        ):
            raise ValueError("qa_projection batch differs")
        batch_digest = _digest(batch["digest"], "batch.digest")
        if batch_digest in seen_batches:
            raise ValueError("qa_projection batch is duplicated")
        seen_batches.add(batch_digest)
        _digest(batch.get("environment_digest"), "batch.environment_digest")
        _digest(batch.get("profiles_digest"), "batch.profiles_digest")
        if batch.get("profiles_digest") != "sha256:" + hashlib.sha256(
            canonical_json(batch.get("profile_refs")).encode("utf-8")
        ).hexdigest():
            raise ValueError("qa_projection profile set digest differs")
        for field in (
            "expected_selectors", "covered_selectors", "profile_refs", "children",
            "missing_selectors", "unexpected_selectors", "failed_child_refs",
        ):
            if not isinstance(batch.get(field), list):
                raise ValueError(f"qa_projection batch {field} must be a list")
        if not batch["children"] or not batch["expected_selectors"]:
            raise ValueError("qa_projection batch must preserve child and selector refs")
        started = _timestamp(attempt["started_at"], "attempt.started_at")
        finished = _timestamp(attempt["finished_at"], "attempt.finished_at")
        if finished < started:
            raise ValueError("QA attempt finish precedes start")
        if attempt["result"] != "pass":
            if finished >= confirmed_at:
                failure_after_confirmation = True
            continue
        if (
            batch["missing_selectors"] or batch["unexpected_selectors"]
            or batch["failed_child_refs"]
            or batch["expected_selectors"] != batch["covered_selectors"]
            or any(child.get("result") != "pass" for child in batch["children"])
        ):
            raise ValueError("passing QA batch contains incomplete children")
        if started <= confirmed_at:
            pass_before_confirmation = True
        passed.append(attempt)
    if failure_after_confirmation:
        return {"action": "reject", "reason": "review-reconfirmation-required"}
    if pass_before_confirmation:
        return {"action": "reject", "reason": "fresh-final-root-qa-required"}
    if qa_projection.get("result") != "pass" or len(passed) != 1:
        return {"action": "reject", "reason": "final-root-qa-required"}
    result: dict[str, Any] = {
        "schema": SCHEMA, "action": "accept", "candidate_ref": candidate,
        "reviewer_ref": reviewer_ref, "review_finding_digest": review_status["finding_digest"],
        "qa_projection_digest": qa_projection["digest"],
        "final_batch_ref": {"digest": passed[0]["batch"]["digest"]},
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
