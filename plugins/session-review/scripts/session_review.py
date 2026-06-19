#!/usr/bin/env python3
"""Session-review status block helpers.

The handshake is a wiki snapshot. The machine-readable state lives in the
first fenced yaml block inside the snapshot body's `## 현재 논의` section.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DISCUSSION_HEADING = "## 현재 논의"
STATUS_FENCE_RE = re.compile(r"(?:^|\n)```yaml[ \t]*\n(.*?)\n```", re.DOTALL)
KEY_VALUE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")

STRING_FIELDS = (
    "phase",
    "active_actor",
    "next_actor",
    "target_mode",
    "target_ref",
    "base_ref",
    "responding_to",
    "flow_mode",
    "review_strength",
)
STATUS_ORDER = (
    "phase",
    "active_actor",
    "lock_since",
    "next_actor",
    "target_mode",
    "target_ref",
    "base_ref",
    "responding_to",
    "round",
    "flow_mode",
    "review_strength",
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
    if key == "round":
        try:
            return int(value)
        except ValueError as exc:
            raise StatusError("round must be an integer") from exc
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
    if "round" in normalized and not isinstance(normalized["round"], int):
        normalized["round"] = int(normalized["round"])
    return normalized


def extract_status(snapshot_text: str) -> dict[str, Any]:
    section = _discussion_section(snapshot_text)
    match = STATUS_FENCE_RE.search(section)
    if not match:
        raise StatusError("missing first fenced yaml status block in `## 현재 논의`")
    return parse_status_block(match.group(1))


def _render_scalar(key: str, value: Any) -> str:
    if value is None:
        return "null"
    if key == "round":
        return str(int(value))
    if key in STRING_FIELDS:
        return json.dumps(str(value), ensure_ascii=False)
    return str(value)


def render_status(status: dict[str, Any]) -> str:
    normalized = normalize_status(status)
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
    phase = normalized.get("phase")
    if phase not in COMPLETE_ALLOWED_PHASES:
        allowed = ", ".join(sorted(COMPLETE_ALLOWED_PHASES))
        raise StatusError(f"complete requires phase in {{{allowed}}}; got {phase}")
    validate_lock(normalized, actor="worker")
    if not user_confirmed:
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


def cmd_status(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    payload = {"ok": True, "status": extract_status(text)}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_validate_turn(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    validate_turn(extract_status(text), actor=args.actor, allowed_phases=parse_phase_args(args.phase))
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def cmd_validate_complete(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    validate_complete(extract_status(text), user_confirmed=args.user_confirmed)
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    status = json.loads(args.status_json)
    print(render_status(status), end="")
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
    p_status.add_argument("--file", required=True)
    p_status.set_defaults(func=cmd_status)

    p_turn = sub.add_parser("validate-turn", help="validate actor ownership and lock")
    p_turn.add_argument("--file", required=True)
    p_turn.add_argument("--actor", required=True, choices=("worker", "reviewer"))
    p_turn.add_argument("--phase", action="append", help="allowed phase; repeat or comma-separate")
    p_turn.set_defaults(func=cmd_validate_turn)

    p_complete = sub.add_parser("validate-complete", help="validate complete gate")
    p_complete.add_argument("--file", required=True)
    p_complete.add_argument("--user-confirmed", action="store_true")
    p_complete.set_defaults(func=cmd_validate_complete)

    p_render = sub.add_parser("render", help="render a status json object as fenced-yaml body")
    p_render.add_argument("--status-json", required=True)
    p_render.set_defaults(func=cmd_render)
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
