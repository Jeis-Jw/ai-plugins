#!/usr/bin/env python3
"""Session-review status block helpers.

The handshake is a wiki snapshot. The machine-readable state lives in the
first fenced yaml block inside the snapshot body's `## 현재 논의` section.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Optional


DISCUSSION_HEADING = "## 현재 논의"
STATUS_FENCE_RE = re.compile(r"(?:^|\n)```yaml[ \t]*\n(.*?)\n```", re.DOTALL)
KEY_VALUE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")

STRING_FIELDS = (
    "phase",
    "active_actor",
    "next_actor",
    "target_mode",
    "target_nature",
    "target_ref",
    "base_ref",
    "responding_to",
    "flow_mode",
    "self_automation",
    "recording_mode",
    "review_strength",
    "round_type",
    "review_posture",
    "lease_id",
    "reviewer_ref",
    "reviewed_ref",
    "scope_digest",
    "finding_digest",
    "lease_started_at",
    "lease_updated_at",
    "lease_target_ref",
    "lease_base_ref",
    "lease_risk",
    "fresh_fallback_reason",
)
STATUS_ORDER = (
    "phase",
    "active_actor",
    "lock_since",
    "next_actor",
    "target_mode",
    "target_nature",
    "target_ref",
    "base_ref",
    "responding_to",
    "round",
    "round_type",
    "flow_mode",
    "self_automation",
    "recording_mode",
    "review_strength",
    "review_posture",
    "blocking_count",
    "lease_id",
    "reviewer_ref",
    "reviewed_ref",
    "scope_digest",
    "finding_digest",
    "lease_started_at",
    "lease_updated_at",
    "lease_target_ref",
    "lease_base_ref",
    "lease_risk",
    "lease_expires_round",
    "fresh_required",
    "fresh_fallback_reason",
    "fresh_count",
    "reuse_count",
)
PHASE_OWNER = {
    "awaiting-review": "reviewer",
    "changes-requested": "worker",
    "approved": "worker",
    "awaiting-user-confirmation": "user",
    "completed": "none",
    "blocked": "user",
}
COMPLETE_ALLOWED_PHASES = {"approved", "awaiting-user-confirmation"}
INT_FIELDS = ("round", "blocking_count", "lease_expires_round", "fresh_count", "reuse_count")
BOOL_FIELDS = ("fresh_required",)
TARGET_NATURE_VALUES = {"code", "spec", "direction", "process", "general"}
ROUND_TYPE_VALUES = {"explore", "converge", "confirm", "review"}
REVIEW_POSTURE_VALUES = {"verify", "challenge", "co-design"}
SELF_AUTOMATION_VALUES = {"manual", "auto-rounds", "turnkey"}
RECORDING_MODE_VALUES = {"audit", "fast"}
FRESH_FALLBACK_REASONS = {
    "episode_start",
    "legacy_snapshot",
    "scope_changed",
    "ref_changed",
    "risk_changed",
    "round_expired",
    "harness_unaddressable",
}
RECEIPT_SCHEMA = "workflow-receipt/v1"
TOKEN_COVERAGE_VALUES = {"exact", "unavailable"}
DEFAULT_POSTURE_BY_TARGET_AND_ROUND = {
    "code": {
        "explore": "verify",
        "converge": "verify",
        "confirm": "verify",
        "review": "verify",
    },
    "spec": {
        "explore": "co-design",
        "converge": "challenge",
        "confirm": "verify",
        "review": "challenge",
    },
    "direction": {
        "explore": "co-design",
        "converge": "challenge",
        "confirm": "verify",
        "review": "challenge",
    },
    "process": {
        "explore": "co-design",
        "converge": "challenge",
        "confirm": "verify",
        "review": "challenge",
    },
    "general": {
        "explore": "challenge",
        "converge": "challenge",
        "confirm": "verify",
        "review": "verify",
    },
}

# Snapshot is the handshake medium (DEC-2026-06-18). The built-in writer below
# reproduces the SAME file format/location wiki-markdown uses — it is a fallback
# for workspaces without wiki-markdown installed, NOT a new bespoke format.
SNAPSHOT_DIRNAME = "snapshot"
SNAPSHOT_SECTIONS = (
    ("discussion", "현재 논의"),
    ("background", "배경"),
    ("decided", "정해진 것"),
    ("open_questions", "아직 열린 질문"),
    ("next_steps", "다음에 볼 것"),
    ("references", "관련 파일/문서"),
    ("promotion_candidates", "승격 후보"),
)
SNAPSHOT_FLAG = {
    "discussion": "--discussion",
    "background": "--background",
    "decided": "--decided",
    "open_questions": "--open-questions",
    "next_steps": "--next",
    "references": "--references",
    "promotion_candidates": "--promotion-candidates",
}


class StatusError(ValueError):
    """Raised when the handshake status is missing or violates the protocol."""


def _discussion_section(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.strip() == DISCUSSION_HEADING:
            start = index + 1
            break
    if start is None:
        raise StatusError("missing `## 현재 논의` section")

    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line.startswith("## ") and line.strip() != DISCUSSION_HEADING:
            end = index
            break
    return "".join(lines[start:end])


def _parse_scalar(key: str, raw: str) -> Any:
    value = raw.strip()
    if value in {"null", "~", ""}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    if key in INT_FIELDS:
        try:
            return int(value)
        except ValueError as exc:
            raise StatusError(f"{key} must be an integer") from exc
    if key in BOOL_FIELDS:
        if value == "true":
            return True
        if value == "false":
            return False
        raise StatusError(f"{key} must be true or false")
    if key in STRING_FIELDS:
        return str(value)
    return value


def parse_status_block(block: str) -> dict[str, Any]:
    status: dict[str, Any] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = KEY_VALUE_RE.match(line)
        if not match:
            raise StatusError(f"invalid status line: {raw_line}")
        key, raw_value = match.group(1), match.group(2)
        status[key] = _parse_scalar(key, raw_value)
    return normalize_status(status)


def normalize_status(status: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(status)
    for field in STRING_FIELDS:
        value = normalized.get(field)
        if value is not None:
            normalized[field] = str(value)
    for field in INT_FIELDS:
        if field in normalized and normalized[field] is not None \
                and not isinstance(normalized[field], int):
            normalized[field] = int(normalized[field])
    for field in BOOL_FIELDS:
        if field in normalized and normalized[field] is not None \
                and not isinstance(normalized[field], bool):
            value = normalized[field]
            if isinstance(value, str) and value.lower() in {"true", "false"}:
                normalized[field] = value.lower() == "true"
            else:
                raise StatusError(f"{field} must be a boolean")
    if normalized.get("target_nature") is None:
        if normalized.get("target_mode") == "diff":
            normalized["target_nature"] = "code"
        else:
            normalized["target_nature"] = "general"
    if normalized.get("round_type") is None:
        normalized["round_type"] = "review"
    if normalized.get("flow_mode") == "self":
        if normalized.get("self_automation") is None:
            normalized["self_automation"] = "manual"
        if normalized.get("recording_mode") is None:
            normalized["recording_mode"] = (
                "fast" if normalized.get("self_automation") == "turnkey" else "audit"
            )
    normalized = migrate_legacy_reviewer_lease(normalized)
    return normalized


def migrate_legacy_reviewer_lease(status: dict[str, Any]) -> dict[str, Any]:
    """Make a pre-lease status safe without pretending it has a reusable reviewer.

    Legacy snapshots did not identify a reviewer episode. They therefore migrate
    to an explicit fresh requirement; the next lease acquisition replaces this
    marker with a complete lease. The function is idempotent and also supports
    fast mode, where the same object is passed only in agent context.
    """
    migrated = dict(status)
    migrated.setdefault("fresh_count", 0)
    migrated.setdefault("reuse_count", 0)
    if not migrated.get("lease_id"):
        migrated.setdefault("fresh_required", True)
        migrated.setdefault("fresh_fallback_reason", "legacy_snapshot")
    return migrated


def _validate_enum(status: dict[str, Any], field: str, allowed: set[str]) -> None:
    value = status.get(field)
    if value is None:
        return
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise StatusError(f"{field} must be one of {{{choices}}}; got {value}")


def validate_review_posture_fields(status: dict[str, Any]) -> None:
    normalized = normalize_status(status)
    _validate_enum(normalized, "target_nature", TARGET_NATURE_VALUES)
    _validate_enum(normalized, "round_type", ROUND_TYPE_VALUES)
    _validate_enum(normalized, "review_posture", REVIEW_POSTURE_VALUES)


def validate_self_profile_fields(status: dict[str, Any]) -> None:
    normalized = normalize_status(status)
    _validate_enum(normalized, "self_automation", SELF_AUTOMATION_VALUES)
    _validate_enum(normalized, "recording_mode", RECORDING_MODE_VALUES)
    flow_mode = normalized.get("flow_mode")
    self_automation = normalized.get("self_automation")
    recording_mode = normalized.get("recording_mode")
    if flow_mode != "self" and self_automation is not None:
        raise StatusError("self_automation requires flow_mode self")
    if flow_mode != "self" and recording_mode == "fast":
        raise StatusError("recording_mode fast requires flow_mode self")
    if flow_mode == "separate":
        return
    if flow_mode == "self" and self_automation == "turnkey" and recording_mode != "fast":
        raise StatusError("self turnkey requires recording_mode fast")


def effective_review_posture(status: dict[str, Any]) -> str:
    normalized = normalize_status(status)
    validate_review_posture_fields(normalized)
    override = normalized.get("review_posture")
    if override:
        return str(override)
    target_nature = str(normalized["target_nature"])
    round_type = str(normalized["round_type"])
    return DEFAULT_POSTURE_BY_TARGET_AND_ROUND[target_nature][round_type]


def requires_confirm_lock_check(status: dict[str, Any]) -> bool:
    return normalize_status(status).get("round_type") == "confirm"


def status_metadata(status: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_status(status)
    validate_self_profile_fields(normalized)
    validate_reviewer_lease_fields(normalized)
    return {
        "effective_review_posture": effective_review_posture(status),
        "confirm_lock_check": requires_confirm_lock_check(status),
        "self_automation": normalized.get("self_automation"),
        "recording_mode": normalized.get("recording_mode"),
        "lease_id": normalized.get("lease_id"),
        "fresh_required": normalized["fresh_required"],
        "fresh_fallback_reason": normalized.get("fresh_fallback_reason"),
    }


def _parse_timestamp(value: str, *, field: str) -> datetime.datetime:
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise StatusError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise StatusError(f"{field} must include a timezone")
    return parsed.astimezone(datetime.timezone.utc)


def _now_timestamp(now: str | None = None) -> str:
    if now is None:
        instant = datetime.datetime.now(datetime.timezone.utc)
    else:
        instant = _parse_timestamp(now, field="now")
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_reviewer_lease_fields(status: dict[str, Any]) -> None:
    normalized = normalize_status(status)
    fresh_count = normalized.get("fresh_count")
    reuse_count = normalized.get("reuse_count")
    if fresh_count is None or int(fresh_count) < 0:
        raise StatusError("fresh_count must be a non-negative integer")
    if reuse_count is None or int(reuse_count) < 0:
        raise StatusError("reuse_count must be a non-negative integer")

    reason = normalized.get("fresh_fallback_reason")
    if reason is not None and reason not in FRESH_FALLBACK_REASONS:
        choices = ", ".join(sorted(FRESH_FALLBACK_REASONS))
        raise StatusError(
            f"fresh_fallback_reason must be one of {{{choices}}}; got {reason}"
        )

    lease_id = normalized.get("lease_id")
    if not lease_id:
        if normalized.get("fresh_required") is not True:
            raise StatusError("status without lease_id requires fresh_required true")
        if reason != "legacy_snapshot":
            raise StatusError(
                "status without lease_id requires fresh_fallback_reason legacy_snapshot"
            )
        return

    if not isinstance(normalized.get("fresh_required"), bool):
        raise StatusError("an acquired lease requires fresh_required boolean")

    required = (
        "scope_digest",
        "lease_started_at",
        "lease_updated_at",
        "lease_target_ref",
        "lease_base_ref",
        "lease_risk",
        "lease_expires_round",
    )
    missing = [field for field in required if normalized.get(field) in {None, ""}]
    if missing:
        raise StatusError(f"lease_id requires fields: {', '.join(missing)}")
    started = _parse_timestamp(str(normalized["lease_started_at"]), field="lease_started_at")
    updated = _parse_timestamp(str(normalized["lease_updated_at"]), field="lease_updated_at")
    if updated < started:
        raise StatusError("lease_updated_at must not precede lease_started_at")
    if int(normalized["lease_expires_round"]) < 1:
        raise StatusError("lease_expires_round must be >= 1")
    if int(fresh_count) < 1:
        raise StatusError("an acquired lease requires fresh_count >= 1")
    if int(reuse_count) > 0 and not normalized.get("reviewer_ref"):
        raise StatusError("reuse_count > 0 requires reviewer_ref")
    if normalized.get("fresh_required") is True and reason is None:
        raise StatusError("fresh_required true requires fresh_fallback_reason")
    if bool(normalized.get("reviewed_ref")) != bool(normalized.get("finding_digest")):
        raise StatusError("reviewed_ref and finding_digest must be recorded together")


def acquire_reviewer_lease(
    status: dict[str, Any],
    *,
    scope_digest: str | None = None,
    reviewer_ref: str | None = None,
    reviewer_addressable: bool = True,
    max_reuse_rounds: int = 2,
    now: str | None = None,
    lease_id: str | None = None,
) -> dict[str, Any]:
    """Return the one machine-valid fresh/reuse decision for this round."""
    if max_reuse_rounds < 0:
        raise StatusError("max_reuse_rounds must be >= 0")
    raw_had_lease = bool(status.get("lease_id"))
    normalized = normalize_status(status)
    round_number = int(normalized.get("round") or 0)
    target_ref = normalized.get("target_ref")
    base_ref = normalized.get("base_ref")
    risk = normalized.get("review_strength") or "normal"
    scope_digest = scope_digest or normalized.get("scope_digest")
    if round_number < 1 or not all((target_ref, base_ref, scope_digest)):
        raise StatusError("lease requires round, target_ref, base_ref and scope_digest")

    reason: str | None = None
    if not raw_had_lease:
        reason = status.get("fresh_fallback_reason") or (
            "episode_start" if round_number == 1 else "legacy_snapshot"
        )
    elif normalized.get("fresh_required"):
        reason = str(normalized.get("fresh_fallback_reason") or "legacy_snapshot")
    elif normalized.get("scope_digest") != scope_digest:
        reason = "scope_changed"
    elif (
        normalized.get("lease_target_ref") != target_ref
        or normalized.get("lease_base_ref") != base_ref
        or (reviewer_ref is not None and reviewer_ref != normalized.get("reviewer_ref"))
    ):
        reason = "ref_changed"
    elif normalized.get("lease_risk") != risk:
        reason = "risk_changed"
    elif round_number > int(normalized.get("lease_expires_round") or 0):
        reason = "round_expired"
    elif not reviewer_addressable or not normalized.get("reviewer_ref"):
        reason = "harness_unaddressable"

    timestamp = _now_timestamp(now)
    updated = dict(normalized)
    updated["round"] = round_number
    if reason is not None:
        updated.update(
            {
                "lease_id": lease_id or str(uuid.uuid4()),
                "reviewer_ref": reviewer_ref if reviewer_addressable else None,
                "reviewed_ref": None,
                "scope_digest": scope_digest,
                "finding_digest": None,
                "lease_started_at": timestamp,
                "lease_updated_at": timestamp,
                "lease_target_ref": str(target_ref),
                "lease_base_ref": str(base_ref),
                "lease_risk": str(risk),
                "lease_expires_round": round_number + max_reuse_rounds,
                "fresh_required": False,
                "fresh_fallback_reason": reason,
                "fresh_count": int(normalized.get("fresh_count") or 0) + 1,
                "reuse_count": int(normalized.get("reuse_count") or 0),
            }
        )
        decision = "fresh"
    else:
        updated.update(
            {
                "reviewed_ref": None,
                "finding_digest": None,
                "lease_updated_at": timestamp,
                "fresh_required": False,
                "fresh_fallback_reason": None,
                "reuse_count": int(normalized.get("reuse_count") or 0) + 1,
            }
        )
        decision = "reuse"
    validate_reviewer_lease_fields(updated)
    return {"decision": decision, "reason": reason, "status": updated}


def receipt_from_status(
    status: dict[str, Any],
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    tokens: int | None = None,
    token_coverage: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_status(status)
    validate_reviewer_lease_fields(normalized)
    started = _parse_timestamp(started_at, field="started_at")
    finished = _parse_timestamp(finished_at, field="finished_at")
    if not run_id.strip() or finished < started:
        raise StatusError("run_id must be set and finished_at must not precede started_at")
    coverage = token_coverage or ("unavailable" if tokens is None else "exact")
    if coverage not in TOKEN_COVERAGE_VALUES:
        raise StatusError("invalid token_coverage")
    if (tokens is None) != (coverage == "unavailable"):
        raise StatusError("unknown tokens must be null with token_coverage unavailable")
    if tokens is not None and tokens < 0:
        raise StatusError("tokens must be >= 0")
    elapsed = finished - started
    return {
        "schema": RECEIPT_SCHEMA,
        "emitter": "session-review",
        "workflow": "session-review",
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed.days * 86_400_000 + elapsed.seconds * 1_000
        + elapsed.microseconds // 1_000,
        "tokens": tokens,
        "token_coverage": coverage,
        "counters": {
            "review_rounds": int(normalized.get("round") or 0),
            "fresh_reviewers": int(normalized.get("fresh_count") or 0),
            "reviewer_reuses": int(normalized.get("reuse_count") or 0),
        },
        "quality": {
            "phase": normalized.get("phase"),
            "blocking_count": normalized.get("blocking_count"),
            "reviewed_ref": normalized.get("reviewed_ref"),
            "finding_digest": normalized.get("finding_digest"),
            "fresh_fallback_reason": normalized.get("fresh_fallback_reason"),
        },
    }


def extract_status(snapshot_text: str) -> dict[str, Any]:
    section = _discussion_section(snapshot_text)
    match = STATUS_FENCE_RE.search(section)
    if not match:
        raise StatusError("missing first fenced yaml status block in `## 현재 논의`")
    return parse_status_block(match.group(1))


def _render_scalar(key: str, value: Any) -> str:
    if value is None:
        return "null"
    if key in BOOL_FIELDS:
        return "true" if bool(value) else "false"
    if key in INT_FIELDS:
        return str(int(value))
    if key in STRING_FIELDS:
        return json.dumps(str(value), ensure_ascii=False)
    return str(value)


def render_status(status: dict[str, Any]) -> str:
    normalized = normalize_status(status)
    validate_review_posture_fields(normalized)
    validate_self_profile_fields(normalized)
    validate_reviewer_lease_fields(normalized)
    keys = [key for key in STATUS_ORDER if key in normalized]
    keys.extend(key for key in normalized if key not in STATUS_ORDER)
    return "\n".join(f"{key}: {_render_scalar(key, normalized[key])}" for key in keys) + "\n"


def validate_turn(
    status: dict[str, Any],
    *,
    actor: str,
    allowed_phases: set[str] | None = None,
) -> None:
    normalized = normalize_status(status)
    validate_lock(normalized, actor=actor)
    phase = str(normalized.get("phase"))
    if allowed_phases and phase not in allowed_phases:
        allowed = ", ".join(sorted(allowed_phases))
        raise StatusError(f"turn requires phase in {{{allowed}}}; got {phase}")

    next_actor = normalized.get("next_actor") or PHASE_OWNER.get(str(normalized.get("phase")))
    if next_actor not in {actor, "none"}:
        raise StatusError(f"next actor is {next_actor}, not {actor}")


def validate_lock(status: dict[str, Any], *, actor: str) -> None:
    active_actor = normalize_status(status).get("active_actor", "none")
    if active_actor not in {"none", actor}:
        raise StatusError(f"handshake is locked by {active_actor}")


def validate_complete(status: dict[str, Any], *, user_confirmed: bool) -> None:
    normalized = normalize_status(status)
    validate_status(normalized)
    phase = normalized.get("phase")
    if phase not in COMPLETE_ALLOWED_PHASES:
        allowed = ", ".join(sorted(COMPLETE_ALLOWED_PHASES))
        raise StatusError(f"complete requires phase in {{{allowed}}}; got {phase}")
    validate_lock(normalized, actor="worker")
    blocking = normalized.get("blocking_count")
    if blocking is None or int(blocking) != 0:
        raise StatusError(
            f"complete requires blocking_count == 0, got {blocking}")
    if not user_confirmed and not (
        normalized.get("flow_mode") == "self"
        and normalized.get("self_automation") == "turnkey"
    ):
        raise StatusError("complete requires explicit user confirmation")


def replace_status(snapshot_text: str, status: dict[str, Any]) -> str:
    section = _discussion_section(snapshot_text)
    match = STATUS_FENCE_RE.search(section)
    if not match:
        raise StatusError("missing first fenced yaml status block in `## 현재 논의`")
    section_start = snapshot_text.index(section)
    block_start = section_start + match.start(1)
    block_end = section_start + match.end(1)
    return snapshot_text[:block_start] + render_status(status).rstrip("\n") + snapshot_text[block_end:]


# ──────────────────────────────────────────────────────────────────────────
# Status consistency (#2, #6)
# ──────────────────────────────────────────────────────────────────────────
def validate_status(status: dict[str, Any]) -> None:
    """Check the written verdict is internally consistent: next_actor matches
    the phase owner, and an `approved` phase carries no blocking findings."""
    normalized = normalize_status(status)
    validate_review_posture_fields(normalized)
    validate_self_profile_fields(normalized)
    validate_reviewer_lease_fields(normalized)
    phase = str(normalized.get("phase"))
    expected = PHASE_OWNER.get(phase)
    next_actor = normalized.get("next_actor") or expected
    if expected is not None and next_actor not in {expected, "none"}:
        raise StatusError(
            f"phase '{phase}' requires next_actor '{expected}', got '{next_actor}'")
    blocking = normalized.get("blocking_count")
    if normalized.get("lease_id") and phase in {
        "approved", "awaiting-user-confirmation", "completed"
    } and not normalized.get("reviewed_ref"):
        raise StatusError(
            f"phase '{phase}' requires reviewed_ref and finding_digest"
        )
    if phase == "approved":
        if blocking is None:
            raise StatusError("phase 'approved' requires blocking_count == 0")
        if int(blocking) != 0:
            raise StatusError(
                f"phase 'approved' requires blocking_count == 0, got {blocking}")
    if phase == "changes-requested":
        if blocking is None:
            raise StatusError("phase 'changes-requested' requires blocking_count >= 1")
        if int(blocking) < 1:
            raise StatusError(
                f"phase 'changes-requested' requires blocking_count >= 1, got {blocking}")


# ──────────────────────────────────────────────────────────────────────────
# Snapshot backend — hybrid (wiki-markdown if present, else built-in) (#3, #4)
# ──────────────────────────────────────────────────────────────────────────
def resolve_wiki_cli() -> Optional[Path]:
    """Locate wiki-markdown's wiki_cli.py without depending on any harness env
    var (must work in both Claude Code and Codex). Order: explicit override →
    sibling-plugin search relative to this script → PATH → None (built-in)."""
    env = os.environ.get("SESSION_REVIEW_WIKI_CLI")
    if env is not None:
        if env.strip().lower() in {"", "none", "off", "0"}:
            return None
        candidate = Path(env).expanduser()
        return candidate if candidate.exists() else None
    for candidate in _wiki_cli_candidates():
        if candidate.exists():
            return candidate
    found = shutil.which("wiki_cli") or shutil.which("wiki_cli.py")
    return Path(found) if found else None


def _wiki_cli_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    parents = here.parents
    rel = ("wiki-markdown", "skills", "wiki", "scripts", "wiki_cli.py")
    out: list[Path] = []
    # monorepo: plugins/session-review/scripts → plugins/wiki-markdown/.../wiki_cli.py
    if len(parents) > 2:
        out.append(parents[2].joinpath(*rel))
    # installed (versioned dirs): <marketplace>/wiki-markdown/<ver>/skills/.../wiki_cli.py
    for depth in (2, 3):
        if len(parents) > depth:
            out.extend(sorted(parents[depth].glob(
                "wiki-markdown/*/skills/wiki/scripts/wiki_cli.py")))
    return out


def resolve_vault() -> Path:
    env = os.environ.get("WIKI_VAULT")
    if env:
        return Path(env).expanduser()
    return Path.cwd() / "wiki"


def _today() -> str:
    raw = os.environ.get("WIKI_NOW")
    if raw:
        return raw[:10]
    return datetime.date.today().isoformat()


def _split_frontmatter(text: str) -> tuple[Optional[str], str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5:]


def _fm_scalar(fm_text: Optional[str], key: str) -> Optional[str]:
    if not fm_text:
        return None
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.*)$", fm_text)
    return m.group(1).strip() if m else None


def _render_snapshot_frontmatter(fields: dict[str, Any], created_at: str,
                                 updated_at: Optional[str]) -> str:
    lines = ["---", f"title: {fields['title']}", f"created_at: {created_at}",
             f"summary: {fields['summary']}",
             f"tags: [{', '.join(fields.get('tags', []))}]", "type: snapshot"]
    if updated_at:
        lines.append(f"updated_at: {updated_at}")
    search_terms = fields.get("search_terms")
    if search_terms:
        lines.append(f"search_terms: [{', '.join(search_terms)}]")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _parse_snapshot_sections(body: str) -> dict[str, str]:
    header_to_attr = {h: a for a, h in SNAPSHOT_SECTIONS}
    out: dict[str, str] = {}
    current: Optional[str] = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                out[current] = "\n".join(buf).strip()
            header = line[3:].strip()
            current = header_to_attr.get(header)
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def _render_snapshot_body(section_values: dict[str, str]) -> str:
    blocks = []
    for attr, header in SNAPSHOT_SECTIONS:
        value = (section_values.get(attr) or "").strip()
        blocks.append(f"## {header}\n\n{value}\n")
    return "\n".join(blocks).rstrip() + "\n"


def _replace_h2_section(text: str, header: str, body_lines: list[str]) -> str:
    """Replace the body under an H2 header (creates it if missing). Mirrors
    wiki_cli's section replacer so the built-in index matches its format."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == header), None)
    block = [""] + (["\n".join(body_lines), ""] if body_lines else [])
    if start is None:
        if lines and lines[-1] != "":
            lines.append("")
        return "\n".join(lines + [header] + block)
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
               len(lines))
    return "\n".join(lines[: start + 1] + block + lines[end:])


def _rewrite_builtin_snapshot_index(vault: Path) -> None:
    """Keep wiki/snapshot/snapshot.md in sync — but only if it already exists
    (created by wiki init). Matches wiki_cli, which also no-ops without it."""
    idx = vault / SNAPSHOT_DIRNAME / "snapshot.md"
    if not idx.is_file():
        return
    lines = []
    for path in sorted((vault / SNAPSHOT_DIRNAME).glob("SNAP-*.md")):
        fm_text, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        lines.append(f"- [[{path.stem}]] — {_fm_scalar(fm_text, 'summary') or ''}")
    text = idx.read_text(encoding="utf-8")
    new_text = _replace_h2_section(text, "## 노트", lines)
    if new_text != text:
        idx.write_text(new_text, encoding="utf-8")


def builtin_snapshot_save(vault: Path, slug: str, fields: dict[str, Any],
                          section_values: dict[str, str], merge: bool = False) -> Path:
    path = vault / SNAPSHOT_DIRNAME / f"SNAP-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    today = _today()
    existing: dict[str, str] = {}
    if path.exists():
        prev_fm, prev_body = _split_frontmatter(path.read_text(encoding="utf-8"))
        created_at = _fm_scalar(prev_fm, "created_at") or today
        updated_at: Optional[str] = today
        if merge:
            existing = _parse_snapshot_sections(prev_body)
    else:
        created_at = today
        updated_at = None
    merged = dict(existing)
    for attr, _h in SNAPSHOT_SECTIONS:
        value = section_values.get(attr)
        if value is not None:
            merged[attr] = value
    body = _render_snapshot_body(merged)
    fm_text = _render_snapshot_frontmatter(fields, created_at, updated_at)
    path.write_text(fm_text + body, encoding="utf-8")
    _rewrite_builtin_snapshot_index(vault)
    return path


def builtin_snapshot_load(vault: Path, slug: str) -> dict[str, Any]:
    path = vault / SNAPSHOT_DIRNAME / f"SNAP-{slug}.md"
    if not path.exists():
        raise StatusError(f"snapshot not found: {slug} (looked at {path})")
    text = path.read_text(encoding="utf-8")
    return {"path": str(path), "text": text}


def builtin_snapshot_discard(vault: Path, slug: str) -> bool:
    path = vault / SNAPSHOT_DIRNAME / f"SNAP-{slug}.md"
    if path.exists():
        path.unlink()
        _rewrite_builtin_snapshot_index(vault)
        return True
    return False


def _run_wiki(cli: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(cli), *args],
                          text=True, capture_output=True)


def snapshot_save(vault: Path, slug: str, fields: dict[str, Any],
                  section_values: dict[str, str], merge: bool = False) -> Path:
    cli = resolve_wiki_cli()
    if cli is None:
        return builtin_snapshot_save(vault, slug, fields, section_values, merge)
    args = ["snapshot", "save", "--vault", str(vault), "--slug", slug,
            "--title", fields["title"], "--summary", fields["summary"],
            "--tags", ",".join(fields.get("tags", []))]
    if merge:
        args.append("--merge")
    for attr, _h in SNAPSHOT_SECTIONS:
        value = section_values.get(attr)
        if value is not None:
            args += [SNAPSHOT_FLAG[attr], value]
    result = _run_wiki(cli, *args)
    if result.returncode != 0:
        raise StatusError(f"wiki_cli snapshot save failed: {result.stderr.strip()}")
    return vault / SNAPSHOT_DIRNAME / f"SNAP-{slug}.md"


def snapshot_load(vault: Path, slug: str) -> dict[str, Any]:
    cli = resolve_wiki_cli()
    if cli is None:
        return builtin_snapshot_load(vault, slug)
    result = _run_wiki(cli, "snapshot", "load", slug, "--vault", str(vault), "--json")
    if result.returncode != 0:
        raise StatusError(f"wiki_cli snapshot load failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    return {"path": payload["path"], "text": payload["text"]}


def snapshot_discard(vault: Path, slug: str) -> bool:
    cli = resolve_wiki_cli()
    if cli is None:
        return builtin_snapshot_discard(vault, slug)
    result = _run_wiki(cli, "snapshot", "discard", slug, "--vault", str(vault))
    if result.returncode != 0:
        raise StatusError(f"wiki_cli snapshot discard failed: {result.stderr.strip()}")
    return True


def set_status(vault: Path, slug: str, status: dict[str, Any]) -> Path:
    """Rewrite the status block in place (works under either backend, since both
    store the same file). Rejects an inconsistent status before writing."""
    validate_status(status)
    loaded = snapshot_load(vault, slug)
    new_text = replace_status(loaded["text"], status)
    path = Path(loaded["path"])
    path.write_text(new_text, encoding="utf-8")
    return path


def _status_text(args: argparse.Namespace) -> str:
    """Resolve snapshot text from --slug (via backend) or a literal --file."""
    if getattr(args, "slug", None):
        return snapshot_load(_vault_arg(args), args.slug)["text"]
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    raise StatusError("provide --slug, --file or --status-json")


def _status_input(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve a status object from --status-json (fast mode), --slug or --file."""
    raw = getattr(args, "status_json", None)
    if raw:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise StatusError("--status-json must be a JSON object")
        return value
    return extract_status(_status_text(args))


def cmd_status(args: argparse.Namespace) -> int:
    status = _status_input(args)
    payload = {"ok": True, "status": status, **status_metadata(status)}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_validate_turn(args: argparse.Namespace) -> int:
    validate_turn(_status_input(args), actor=args.actor,
                  allowed_phases=parse_phase_args(args.phase))
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def cmd_validate_complete(args: argparse.Namespace) -> int:
    validate_complete(_status_input(args), user_confirmed=args.user_confirmed)
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    status = json.loads(args.status_json)
    body = render_status(status)
    if getattr(args, "fenced", False):
        print("```yaml\n" + body.rstrip("\n") + "\n```")
    else:
        print(body, end="")
    return 0


def _parse_tags(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t.strip() for t in raw.split(",") if t.strip()]


def _vault_arg(args: argparse.Namespace) -> Path:
    return Path(args.vault).expanduser() if getattr(args, "vault", None) else resolve_vault()


def cmd_snapshot_save(args: argparse.Namespace) -> int:
    vault = _vault_arg(args)
    title, summary, tags = args.title, args.summary, args.tags
    # nit #1: a --merge that only touches sections/status need not re-supply
    # frontmatter — backfill any omitted field from the existing snapshot.
    if title is None or summary is None or tags is None:
        if not args.merge:
            raise StatusError("--title/--summary/--tags are required for a new snapshot")
        fm_text, _ = _split_frontmatter(snapshot_load(vault, args.slug)["text"])
        title = title or _fm_scalar(fm_text, "title")
        summary = summary or _fm_scalar(fm_text, "summary")
        tags = tags if tags is not None else (_fm_scalar(fm_text, "tags") or "")
        if not title or not summary or not _parse_tags(tags):
            raise StatusError("could not backfill --title/--summary/--tags from the existing snapshot")
    fields = {"title": title, "summary": summary, "tags": _parse_tags(tags)}
    sections = {attr: getattr(args, attr) for attr, _h in SNAPSHOT_SECTIONS
                if getattr(args, attr) is not None}
    path = snapshot_save(vault, args.slug, fields, sections, merge=args.merge)
    print(json.dumps({"ok": True, "path": str(path), "slug": args.slug}, ensure_ascii=False))
    return 0


def cmd_snapshot_load(args: argparse.Namespace) -> int:
    loaded = snapshot_load(_vault_arg(args), args.slug)
    print(json.dumps({"ok": True, **loaded}, ensure_ascii=False))
    return 0


def cmd_snapshot_discard(args: argparse.Namespace) -> int:
    discarded = snapshot_discard(_vault_arg(args), args.slug)
    print(json.dumps({"ok": True, "discarded": discarded}, ensure_ascii=False))
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    status = json.loads(args.status_json)
    path = set_status(_vault_arg(args), args.slug, status)
    print(json.dumps({"ok": True, "path": str(path)}, ensure_ascii=False))
    return 0


def cmd_validate_status(args: argparse.Namespace) -> int:
    validate_status(_status_input(args))
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def _lease_output(args: argparse.Namespace, status: dict[str, Any], **extra: Any) -> int:
    payload: dict[str, Any] = {"ok": True, **extra, "status": status}
    if getattr(args, "slug", None):
        path = set_status(_vault_arg(args), args.slug, status)
        payload["path"] = str(path)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_lease_acquire(args: argparse.Namespace) -> int:
    status = _status_input(args)
    result = acquire_reviewer_lease(
        status,
        scope_digest=args.scope_digest,
        reviewer_ref=args.reviewer_ref,
        reviewer_addressable=not args.reviewer_unaddressable,
        max_reuse_rounds=args.max_reuse_rounds,
        now=args.now,
        lease_id=args.lease_id,
    )
    return _lease_output(
        args,
        result["status"],
        decision=result["decision"],
        reason=result["reason"],
    )


def cmd_emit_receipt(args: argparse.Namespace) -> int:
    receipt = receipt_from_status(
        _status_input(args),
        run_id=args.run_id,
        started_at=args.started_at,
        finished_at=args.finished_at,
        tokens=args.tokens,
        token_coverage=args.token_coverage,
    )
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


def parse_phase_args(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    phases = {
        token.strip()
        for value in values
        for token in value.split(",")
        if token.strip()
    }
    return phases or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="session-review status helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="read a snapshot status block")
    p_status.add_argument("--file")
    p_status.add_argument("--slug")
    p_status.add_argument("--vault")
    p_status.add_argument("--status-json", help="context-only status JSON for fast mode")
    p_status.set_defaults(func=cmd_status)

    p_turn = sub.add_parser("validate-turn", help="validate actor ownership and lock")
    p_turn.add_argument("--file")
    p_turn.add_argument("--slug")
    p_turn.add_argument("--vault")
    p_turn.add_argument("--status-json", help="context-only status JSON for fast mode")
    p_turn.add_argument("--actor", required=True, choices=("worker", "reviewer"))
    p_turn.add_argument("--phase", action="append", help="allowed phase; repeat or comma-separate")
    p_turn.set_defaults(func=cmd_validate_turn)

    p_complete = sub.add_parser("validate-complete", help="validate complete gate")
    p_complete.add_argument("--file")
    p_complete.add_argument("--slug")
    p_complete.add_argument("--vault")
    p_complete.add_argument("--status-json", help="context-only status JSON for fast mode")
    p_complete.add_argument("--user-confirmed", action="store_true")
    p_complete.set_defaults(func=cmd_validate_complete)

    p_render = sub.add_parser("render", help="render a status json object as a yaml status block")
    p_render.add_argument("--status-json", required=True)
    p_render.add_argument("--fenced", action="store_true",
                          help="wrap output in a ```yaml fence (ready to embed in --discussion)")
    p_render.set_defaults(func=cmd_render)

    p_save = sub.add_parser("snapshot-save", help="save a handshake snapshot (wiki backend or built-in)")
    p_save.add_argument("--vault")
    p_save.add_argument("--slug", required=True)
    p_save.add_argument("--title", help="required for a new snapshot; reused from existing on --merge")
    p_save.add_argument("--summary", help="required for a new snapshot; reused from existing on --merge")
    p_save.add_argument("--tags", help="comma-separated; required for a new snapshot, reused on --merge")
    p_save.add_argument("--merge", action="store_true")
    for _attr, _h in SNAPSHOT_SECTIONS:
        p_save.add_argument(SNAPSHOT_FLAG[_attr], dest=_attr, default=None)
    p_save.set_defaults(func=cmd_snapshot_save)

    p_load = sub.add_parser("snapshot-load", help="load a handshake snapshot")
    p_load.add_argument("--vault")
    p_load.add_argument("--slug", required=True)
    p_load.add_argument("--json", action="store_true",
                        help="accepted for parity; output is always JSON")
    p_load.set_defaults(func=cmd_snapshot_load)

    p_discard = sub.add_parser("snapshot-discard", help="discard a handshake snapshot")
    p_discard.add_argument("--vault")
    p_discard.add_argument("--slug", required=True)
    p_discard.set_defaults(func=cmd_snapshot_discard)

    p_set = sub.add_parser("set-status", help="rewrite the status block of a snapshot in place")
    p_set.add_argument("--vault")
    p_set.add_argument("--slug", required=True)
    p_set.add_argument("--status-json", required=True)
    p_set.set_defaults(func=cmd_set_status)

    p_vstatus = sub.add_parser("validate-status", help="check status block self-consistency")
    p_vstatus.add_argument("--vault")
    p_vstatus.add_argument("--slug")
    p_vstatus.add_argument("--file")
    p_vstatus.add_argument("--status-json", help="context-only status JSON for fast mode")
    p_vstatus.set_defaults(func=cmd_validate_status)

    def add_lease_source(command: argparse.ArgumentParser) -> None:
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--slug", help="audit snapshot slug; updates persist in place")
        source.add_argument(
            "--status-json",
            help="context-only status JSON for fast mode; no snapshot is read or written",
        )
        command.add_argument("--vault")

    p_acquire = sub.add_parser(
        "lease-acquire",
        help="acquire a fresh reviewer or reuse a valid reviewer episode lease",
    )
    add_lease_source(p_acquire)
    p_acquire.add_argument("--scope-digest")
    p_acquire.add_argument("--reviewer-ref")
    p_acquire.add_argument("--reviewer-unaddressable", action="store_true")
    p_acquire.add_argument("--max-reuse-rounds", type=int, default=2)
    p_acquire.add_argument("--now")
    p_acquire.add_argument("--lease-id", help="test/harness supplied id; UUID by default")
    p_acquire.set_defaults(func=cmd_lease_acquire)

    p_receipt = sub.add_parser(
        "emit-receipt", help="emit a binding workflow receipt schema v1 object"
    )
    add_lease_source(p_receipt)
    p_receipt.add_argument("--run-id", required=True)
    p_receipt.add_argument("--started-at", required=True)
    p_receipt.add_argument("--finished-at", required=True)
    p_receipt.add_argument("--tokens", type=int)
    p_receipt.add_argument(
        "--token-coverage", choices=tuple(sorted(TOKEN_COVERAGE_VALUES))
    )
    p_receipt.set_defaults(func=cmd_emit_receipt)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StatusError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
