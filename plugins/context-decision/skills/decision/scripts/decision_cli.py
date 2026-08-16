#!/usr/bin/env python3
"""context-decision v1 semantic owner (Python 3.11+, stdlib only, write-free)."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import unicodedata
import uuid
from typing import Any, Iterable, Sequence


EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_AMBIGUOUS = 4
EXIT_CONFLICT = 5
EXIT_INTEGRITY = 6
PROTOCOL = "context-common/v2"
DECISION_INDEX = "context/decision/decision.index.md"
MAX_BRIEF_BYTES = 8 * 1024
MAX_CHECK_BYTES = 24 * 1024
MAX_CHECK_RESULT_BYTES = 32 * 1024
MAX_OMITTED_ID_SAMPLE = 8
PLACEHOLDERS = {"...", "TODO", "TBD", "해당 없음"}
ID_RE = re.compile(r"^ctx_[0-9a-f]{32}$")
LOCAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ENTRY_RE = re.compile(r"^.*<!-- context-entry (\{.*\}) -->$")
CORE_SECTIONS = ("결정", "취지", "반려대안")
ALL_SECTIONS = CORE_SECTIONS + ("근거와 제약", "트레이드오프", "재평가 조건")
REMOVED_FINGERPRINT_FIELDS = {"claim_fingerprint", "source_claim_fingerprint"}
SEMANTIC_RELATIONS = ("new", "same", "supporting", "rationale_changed", "conflict")
RELATION_ACTIONS = {
    "new": "결정이 확정되면 capture 여부를 묻는다.",
    "same": "새 DEC를 만들지 않고 기존 DEC를 인용한다.",
    "supporting": "결정 변경 없이 새 근거라면 OBS capture 여부를 검토한다.",
    "rationale_changed": "기존 취지를 유지할지 successor DEC로 바꿀지 사용자에게 묻는다.",
    "conflict": "충돌하는 Current DEC와 차이를 먼저 알리고 유지·수정·supersede 여부를 묻는다.",
}
REQUIRED_PLUGIN = {
    "marketplace": "jeis-ai-plugins",
    "plugin": "context-core",
    "selector": "context-core@jeis-ai-plugins",
    "source": "Jeis-Jw/ai-plugins",
    "provider": "Jinwuk-Lee (Jeis-Jw)",
    "required_protocol": PROTOCOL,
}
OBSERVED_PLUGIN_FIELDS = ("marketplace", "plugin", "source", "enabled", "protocol", "repository_state")
PREFLIGHT_MESSAGES = {
    "core_missing": "exact context-core가 현재 host inventory에 없다.",
    "core_source_mismatch": "동명 core의 marketplace 또는 source가 요구 좌표와 다르다.",
    "core_disabled": "exact context-core가 현재 scope에서 비활성이다.",
    "core_incompatible": "exact context-core가 context-common/v2 handshake를 통과하지 못했다.",
    "core_uninitialized": "exact core는 준비됐고 repository bootstrap이 필요하다.",
    "partial_core_init": "repository context root가 partial 또는 invalid 상태다.",
    "ready": "exact context-core와 repository가 준비됐다.",
}


class DecisionError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None, exit_code: int = EXIT_USAGE):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code

    def envelope(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def normalized_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return nfc(value)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**53 - 1:
        return value
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise DecisionError("canonical_json_invalid", "object keys must be strings")
            key = nfc(raw_key)
            if key in normalized:
                raise DecisionError("canonical_json_invalid", "NFC-normalized keys collide", {"key": key})
            normalized[key] = _canonical_value(raw_value)
        return {key: normalized[key] for key in sorted(normalized)}
    raise DecisionError("canonical_json_invalid", "unsupported canonical JSON scalar", {"type": type(value).__name__})


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical_value(value), ensure_ascii=False, separators=(",", ":"))


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_bytes(content: str) -> bytes:
    return (content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n").encode("utf-8")


def file_digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(file_bytes(content)).hexdigest()


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def new_context_id() -> str:
    return "ctx_" + uuid.uuid4().hex


def _valid_candidate_id(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"cand_[0-9a-f]{32}", value):
        return False
    parsed = uuid.UUID(hex=value[5:])
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def now_rfc3339() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _valid_context_id(value: Any) -> bool:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        return False
    parsed = uuid.UUID(hex=value[4:])
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def require_context_id(value: Any, field: str = "id") -> str:
    if not _valid_context_id(value):
        raise DecisionError("id_invalid", f"{field} must be ctx_ plus lowercase UUIDv4 hex", {"field": field})
    return value


def _canonical_slug_part(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise DecisionError("slot_invalid", f"{field} must be a string")
    folded = normalized_key(value.strip())
    output: list[str] = []
    separator = False
    for char in folded:
        if char.isalnum():
            output.append(char)
            separator = False
        elif not separator:
            output.append("-")
            separator = True
    result = "".join(output).strip("-")
    if not result or result in {".", ".."} or len(result) > maximum:
        raise DecisionError("slot_invalid", f"{field} is empty, reserved, or too long", {"field": field})
    return result


def canonical_scope(value: str) -> str:
    if not isinstance(value, str):
        raise DecisionError("scope_invalid", "scope must be a string")
    stripped = normalized_key(value.strip()).strip("/")
    if not stripped or "//" in stripped:
        raise DecisionError("scope_invalid", "scope is empty or contains an empty segment")
    raw_parts = stripped.split("/")
    if len(raw_parts) > 8:
        raise DecisionError("scope_invalid", "scope has more than eight segments")
    parts = [_canonical_slug_part(part, field="scope segment", maximum=40) for part in raw_parts]
    result = "/".join(parts)
    if len(result) > 160:
        raise DecisionError("scope_invalid", "scope exceeds 160 codepoints")
    return result


def canonical_decision_key(value: str) -> str:
    if not isinstance(value, str) or "/" in value:
        raise DecisionError("decision_key_invalid", "decision_key must not contain /")
    return _canonical_slug_part(value, field="decision_key", maximum=80)


def is_ancestor_scope(ancestor: str, descendant: str) -> bool:
    left = canonical_scope(ancestor).split("/")
    right = canonical_scope(descendant).split("/")
    return len(left) < len(right) and right[: len(left)] == left


def scopes_overlap(left: str, right: str) -> bool:
    left = canonical_scope(left)
    right = canonical_scope(right)
    return is_ancestor_scope(left, right) or is_ancestor_scope(right, left)


def natural_filename(title: str) -> str:
    title = nfc(title.strip())
    output: list[str] = []
    separator = False
    for char in title:
        if char.isalnum() or char in "-_.":
            output.append(char)
            separator = False
        elif not separator:
            output.append("-")
            separator = True
    stem = "".join(output).strip("-._")
    if not stem:
        raise DecisionError("filename_required", "title cannot produce a safe filename")
    basename = stem + ".md"
    if len(basename) > 120 or len(basename.encode("utf-8")) > 240 or basename.endswith(".index.md"):
        raise DecisionError("filename_required", "filename exceeds or violates the v1 contract")
    return basename


def _validate_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DecisionError("schema_invalid", f"{field} must be a timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        raise DecisionError("schema_invalid", f"{field} must be RFC3339-compatible") from error
    if parsed.tzinfo is None or parsed.isoformat(timespec="seconds") != value:
        raise DecisionError("schema_invalid", f"{field} must include an offset and seconds precision")
    return value


def _validate_date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DecisionError("schema_invalid", f"{field} must be YYYY-MM-DD")
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as error:
        raise DecisionError("schema_invalid", f"{field} must be a real calendar date") from error
    if parsed.isoformat() != value:
        raise DecisionError("schema_invalid", f"{field} must be canonical YYYY-MM-DD")
    return value


def _valid_frontmatter_value(value: Any, *, nested: bool = False) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, list):
        return all(isinstance(item, str) for item in value)
    if isinstance(value, dict) and not nested:
        return all(isinstance(key, str) and _valid_frontmatter_value(item, nested=True) for key, item in value.items())
    return False


def parse_document(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    if text.startswith("\ufeff") or "\r" in text.replace("\r\n", ""):
        raise DecisionError("frontmatter_unsupported", "BOM, mixed newline, and bare CR are unsupported")
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0] != "---":
        raise DecisionError("frontmatter_unsupported", "the first line must be exactly ---")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise DecisionError("frontmatter_unsupported", "closing frontmatter delimiter is missing") from error
    frontmatter: dict[str, Any] = {}
    for line in lines[1:closing]:
        if not line or ": " not in line:
            raise DecisionError("frontmatter_unsupported", "frontmatter must use KEY: JSON_VALUE lines")
        key, raw = line.split(": ", 1)
        if not FIELD_RE.fullmatch(key) or key in frontmatter:
            raise DecisionError("frontmatter_unsupported", "invalid or duplicate frontmatter key", {"key": key})
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DecisionError("frontmatter_unsupported", "frontmatter value is not compact JSON", {"key": key}) from error
        if json.dumps(value, ensure_ascii=False, separators=(",", ":")) != raw or not _valid_frontmatter_value(value):
            raise DecisionError("frontmatter_unsupported", "frontmatter value is outside the supported subset", {"key": key})
        frontmatter[key] = value
    if closing + 1 >= len(lines) or lines[closing + 1] != "":
        raise DecisionError("frontmatter_unsupported", "frontmatter must be followed by one blank line")
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    in_fence: str | None = None
    for line in lines[closing + 2 :]:
        fence = re.match(r"^\s*(```+|~~~+)", line)
        if fence:
            marker = fence.group(1)[0]
            in_fence = None if in_fence == marker else (marker if in_fence is None else in_fence)
        heading = re.fullmatch(r"## (.+)", line) if in_fence is None else None
        if heading:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            name = heading.group(1)
            if name not in ALL_SECTIONS or name in sections or (current and ALL_SECTIONS.index(name) <= ALL_SECTIONS.index(current)):
                raise DecisionError("section_schema_error", "unknown, duplicate, or out-of-order H2 section", {"section": name})
            current = name
            buffer = []
        elif current is None and line.strip():
            raise DecisionError("section_schema_error", "content before the first section is forbidden")
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    validate_decision_document(frontmatter, sections)
    return frontmatter, sections


DECISION_KEY_ORDER = (
    "schema", "id", "title", "summary", "created_at", "updated_at", "captured_from", "source_refs", "tags",
    "search_terms", "scope", "decision_key", "revisit_when", "revisit_on", "relations",
    "supersedes", "superseded_by", "retired_at", "retired_reason", "retirement_note",
)
OBSERVATION_KEY_ORDER = (
    "schema", "id", "title", "summary", "created_at", "updated_at", "captured_from", "source_refs", "tags",
    "search_terms", "kind_hint", "verified_at", "affects_paths",
    "relations", "supersedes", "superseded_by", "retired_at", "retired_reason", "retirement_note",
)


def parse_observation_document(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    if text.startswith("\ufeff") or "\r" in text.replace("\r\n", ""):
        raise DecisionError("frontmatter_unsupported", "observation bytes are unsupported")
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise DecisionError("frontmatter_unsupported", "observation frontmatter is missing")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise DecisionError("frontmatter_unsupported", "observation frontmatter delimiter is missing") from error
    frontmatter: dict[str, Any] = {}
    for line in lines[1:closing]:
        if not line or ": " not in line:
            raise DecisionError("frontmatter_unsupported", "observation frontmatter is invalid")
        key, raw = line.split(": ", 1)
        if not FIELD_RE.fullmatch(key) or key in frontmatter:
            raise DecisionError("frontmatter_unsupported", "observation frontmatter key is invalid")
        try:
            frontmatter[key] = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DecisionError("frontmatter_unsupported", "observation frontmatter value is invalid") from error
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in lines[closing + 2 :]:
        heading = re.fullmatch(r"## (.+)", line)
        if heading:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = heading.group(1)
            buffer = []
        elif current is not None:
            buffer.append(line)
        elif line.strip():
            raise DecisionError("section_schema_error", "observation content before sections is invalid")
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    removed = sorted(REMOVED_FINGERPRINT_FIELDS & set(frontmatter))
    if removed:
        raise DecisionError(
            "schema_removed_field",
            "claim fingerprint fields were removed; migrate the artifact before using this protocol",
            {"fields": removed},
            EXIT_CONFLICT,
        )
    if frontmatter.get("schema") != "context-observation/v1" or not all(frontmatter.get(key) for key in ("id", "title", "summary", "created_at", "captured_from")) or not all(sections.get(key) for key in ("관찰", "근거")):
        raise DecisionError("schema_invalid", "fallback observation is incomplete", exit_code=EXIT_CONFLICT)
    require_context_id(frontmatter["id"])
    return frontmatter, sections


def render_observation_document(frontmatter: dict[str, Any], sections: dict[str, str]) -> str:
    removed = sorted(REMOVED_FINGERPRINT_FIELDS & set(frontmatter))
    if removed:
        raise DecisionError("schema_removed_field", "claim fingerprint fields are not renderable", {"fields": removed}, EXIT_CONFLICT)
    ordered = [key for key in OBSERVATION_KEY_ORDER if key in frontmatter]
    ordered.extend(sorted(set(frontmatter) - set(ordered)))
    lines = ["---"] + [f"{key}: {json.dumps(frontmatter[key], ensure_ascii=False, separators=(',', ':'))}" for key in ordered] + ["---", ""]
    for name in ("관찰", "근거", "영향", "현재 처리", "후속 조건"):
        if name in sections:
            lines.extend([f"## {name}", "", sections[name].strip(), ""])
    return "\n".join(lines).rstrip("\n") + "\n"


def validate_decision_document(frontmatter: dict[str, Any], sections: dict[str, str]) -> None:
    removed = sorted(REMOVED_FINGERPRINT_FIELDS & set(frontmatter))
    if removed:
        raise DecisionError(
            "schema_removed_field",
            "claim fingerprint fields were removed; migrate the artifact before using this protocol",
            {"fields": removed},
            EXIT_CONFLICT,
        )
    required = ("schema", "id", "title", "summary", "created_at", "captured_from", "scope", "decision_key")
    missing = [field for field in required if field not in frontmatter]
    if missing or frontmatter.get("schema") != "context-decision/v1":
        raise DecisionError("schema_invalid", "decision frontmatter is incomplete", {"missing": missing})
    require_context_id(frontmatter["id"])
    for field, maximum in (("title", 120), ("summary", 280)):
        value = frontmatter[field]
        if not isinstance(value, str) or not value.strip() or "\n" in value or len(value) > maximum:
            raise DecisionError("schema_invalid", f"{field} is invalid")
    if frontmatter["captured_from"] not in {"conversation", "workspace", "manual", "import"}:
        raise DecisionError("schema_invalid", "captured_from is invalid")
    _validate_timestamp(frontmatter["created_at"], "created_at")
    if "retired_at" in frontmatter:
        _validate_timestamp(frontmatter["retired_at"], "retired_at")
    if "revisit_on" in frontmatter:
        _validate_date(frontmatter["revisit_on"], "revisit_on")
    if frontmatter["scope"] != canonical_scope(frontmatter["scope"]) or frontmatter["decision_key"] != canonical_decision_key(frontmatter["decision_key"]):
        raise DecisionError("slot_invalid", "stored scope and decision_key must already be canonical")
    if "verified_at" in frontmatter or "status" in frontmatter:
        raise DecisionError("schema_invalid", "DEC forbids verified_at and status")
    for name in CORE_SECTIONS:
        content = sections.get(name, "").strip()
        if not content or content in PLACEHOLDERS:
            raise DecisionError("section_schema_error", "required DEC section is missing or placeholder", {"section": name})
    unknown = set(sections) - set(ALL_SECTIONS)
    if unknown:
        raise DecisionError("section_schema_error", "unknown DEC sections are forbidden", {"sections": sorted(unknown)})
    if "retired_reason" in frontmatter:
        if frontmatter["retired_reason"] not in {"superseded", "withdrawn"} or "retired_at" not in frontmatter:
            raise DecisionError("lifecycle_invalid", "retired DEC metadata is incomplete", exit_code=EXIT_CONFLICT)
        if frontmatter["retired_reason"] == "withdrawn" and not frontmatter.get("retirement_note"):
            raise DecisionError("lifecycle_invalid", "withdrawn DEC requires retirement_note", exit_code=EXIT_CONFLICT)


def render_document(frontmatter: dict[str, Any], sections: dict[str, str]) -> str:
    validate_decision_document(frontmatter, sections)
    ordered = [key for key in DECISION_KEY_ORDER if key in frontmatter]
    ordered.extend(sorted(set(frontmatter) - set(ordered)))
    lines = ["---"]
    for key in ordered:
        value = frontmatter[key]
        if not _valid_frontmatter_value(value):
            raise DecisionError("frontmatter_unsupported", "frontmatter value is unsupported", {"key": key})
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}")
    lines.extend(["---", ""])
    for name in ALL_SECTIONS:
        if name in sections:
            lines.extend([f"## {name}", "", sections[name].strip(), ""])
    return "\n".join(lines).rstrip("\n") + "\n"


def decision_capability() -> dict[str, Any]:
    return {
        "schema": "context-owner-capability/v1",
        "owner": "context-decision",
        "kind": "decision",
        "artifact_schema": "context-decision/v1",
        "authority": "authoritative",
        "claim_surface": {"type": "agent_skill", "name": "context-decision:decision", "operation": "claim"},
        "comparison_surface": {"type": "cli", "command": "decision_cli.py check"},
        "batch_validation_surface": {"type": "cli", "command": "decision_cli.py batch validate"},
        "claim_rule": "현재 또는 미래 행동을 지배하는 명시적 선택이며 scope와 따를 의사가 있다",
        "claim_assertions": ["explicit_choice", "scope_identified", "commitment_present"],
        "lifecycle_operations": {
            "same_claim": {
                "surface": {"type": "agent_skill", "name": "context-decision:decision", "operation": "same_claim"},
                "rule": "decision-like fallback OBS의 primary claim을 새 DEC가 같은 의미로 인수한다",
                "assertions": ["same_semantic_claim"],
            }
        },
        "draft_fields": {
            "required": {
                "decision": {"type": "string", "min_chars": 1, "max_chars": 1200},
                "rationale": {"type": "string", "min_chars": 1, "max_chars": 1200},
                "rejected_alternatives": {"type": "string_list", "min_items": 1, "max_items": 8, "max_item_chars": 500},
                "decision_key": {"type": "string", "min_chars": 1, "max_chars": 80},
            },
            "optional": {
                "constraints": {"type": "string_list", "max_items": 8, "max_item_chars": 240},
                "tradeoffs": {"type": "string_list", "max_items": 8, "max_item_chars": 240},
                "revisit_when": {"type": "string_list", "max_items": 8, "max_item_chars": 240},
                "revisit_on": {"type": "date"},
            },
        },
    }


def schema_result() -> dict[str, Any]:
    return {
        "schema": "context-decision-schema/v1",
        "protocol": PROTOCOL,
        "owner": "context-decision",
        "artifact_schema": "context-decision/v1",
        "physical_write": False,
        "required_plugin": REQUIRED_PLUGIN,
        "core_sections": list(CORE_SECTIONS),
        "commands": ["init", "schema", "capabilities", "candidate prepare", "check", "draft", "capture", "search", "read", "brief", "conflicts", "supersede", "import-fallback", "withdraw", "annotate", "revisit", "batch validate", "plan validate"],
    }


def _bounded_string(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() in PLACEHOLDERS or len(value) > maximum:
        raise DecisionError("candidate_invalid", f"{field} must be a substantive string up to {maximum} codepoints", {"field": field})
    return value.strip()


def _bounded_list(value: Any, field: str, *, minimum: int = 0, maximum: int = 8, item_maximum: int = 500) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise DecisionError("candidate_invalid", f"{field} list cardinality is invalid", {"field": field})
    output = [_bounded_string(item, field, item_maximum) for item in value]
    return output


def validate_candidate(candidate: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    required = {"schema", "candidate_id", "claim_key", "title", "claim", "summary", "captured_from", "requested_kind", "specialized_kinds", "fallback_kind", "owner_inputs"}
    missing = required - set(candidate)
    if candidate.get("schema") != "context-capture-candidate/v1" or missing:
        raise DecisionError("candidate_invalid", "candidate envelope is incomplete", {"missing": sorted(missing)})
    removed = sorted(REMOVED_FINGERPRINT_FIELDS & set(candidate))
    if removed:
        raise DecisionError(
            "schema_removed_field",
            "claim fingerprint fields were removed from capture candidates",
            {"fields": removed},
            EXIT_CONFLICT,
        )
    candidate_id = candidate.get("candidate_id")
    if not _valid_candidate_id(candidate_id):
        raise DecisionError("candidate_invalid", "candidate_id must be cand_ plus lowercase UUIDv4 hex")
    if candidate.get("requested_kind") not in {None, "decision"}:
        raise DecisionError("candidate_invalid", "candidate is not routed to the decision owner")
    if "decision" not in candidate.get("specialized_kinds", []):
        raise DecisionError("candidate_invalid", "decision must be a specialized kind")
    scope = canonical_scope(candidate.get("scope_hint"))
    owner_inputs = candidate.get("owner_inputs")
    if not isinstance(owner_inputs, dict) or not isinstance(owner_inputs.get("decision"), dict):
        raise DecisionError("candidate_invalid", "candidate lacks decision owner inputs")
    values = owner_inputs["decision"]
    allowed = {"decision", "rationale", "rejected_alternatives", "decision_key", "constraints", "tradeoffs", "revisit_when", "revisit_on"}
    if set(values) - allowed:
        raise DecisionError("candidate_invalid", "decision owner input has undeclared fields", {"fields": sorted(set(values) - allowed)})
    decision = _bounded_string(values.get("decision"), "decision", 1200)
    _bounded_string(values.get("rationale"), "rationale", 1200)
    _bounded_list(values.get("rejected_alternatives"), "rejected_alternatives", minimum=1, item_maximum=500)
    key = canonical_decision_key(values.get("decision_key"))
    for field in ("constraints", "tradeoffs", "revisit_when"):
        if field in values:
            _bounded_list(values[field], field, item_maximum=240)
    if "revisit_on" in values:
        _validate_date(values["revisit_on"], "revisit_on")
    _bounded_string(candidate.get("title"), "title", 120)
    _bounded_string(candidate.get("claim"), "claim", 320)
    _bounded_string(candidate.get("summary"), "summary", 280)
    if candidate.get("captured_from") not in {"conversation", "workspace", "manual", "import"}:
        raise DecisionError("candidate_invalid", "captured_from is invalid")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 2:
        raise DecisionError("candidate_invalid", "decision candidate requires one or two caller-provided evidence items")
    for item in evidence:
        _bounded_string(item, "evidence", 240)
    if len(canonical_json(values).encode("utf-8")) > 2 * 1024:
        raise DecisionError("candidate_too_large", "decision owner input exceeds 2 KiB", exit_code=EXIT_CONFLICT)
    if normalized_key(candidate["claim"]) != normalized_key(decision):
        raise DecisionError("candidate_invalid", "candidate claim must match the decision primary claim")
    return scope, key, values


def _json_pointer(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise DecisionError("semantic_attestation_invalid", "evidence pointer must be RFC 6901")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as error:
                raise DecisionError("semantic_attestation_invalid", "evidence pointer does not resolve", {"pointer": pointer}) from error
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise DecisionError("semantic_attestation_invalid", "evidence pointer does not resolve", {"pointer": pointer})
    if current in (None, "", []):
        raise DecisionError("semantic_attestation_invalid", "evidence pointer resolves to an empty value", {"pointer": pointer})
    return current


def validate_attestation(attestation: dict[str, Any], value: dict[str, Any], operation: str, required_assertions: Sequence[str]) -> None:
    digest = canonical_digest(value)
    if (
        attestation.get("schema") != "context-semantic-attestation/v1"
        or attestation.get("operation") != operation
        or attestation.get("input_schema") != value.get("schema")
        or attestation.get("input_digest") != digest
    ):
        raise DecisionError("semantic_attestation_invalid", "attestation is not bound to the exact semantic input", exit_code=EXIT_CONFLICT)
    assertions = attestation.get("assertions")
    if not isinstance(assertions, list) or {item.get("name") for item in assertions} != set(required_assertions) or len(assertions) != len(required_assertions):
        raise DecisionError("semantic_attestation_invalid", "assertion set does not match the owner capability", exit_code=EXIT_CONFLICT)
    by_name = {item["name"]: item for item in assertions}
    for name in required_assertions:
        item = by_name[name]
        pointers = item.get("evidence_pointers")
        if item.get("value") is not True or not isinstance(pointers, list) or not 1 <= len(pointers) <= 4:
            raise DecisionError("semantic_attestation_invalid", "assertion must be true and evidence-bound", {"assertion": name}, EXIT_CONFLICT)
        for pointer in pointers:
            _json_pointer(value, pointer)
    if operation == "claim":
        required_prefixes = {
            "explicit_choice": "/owner_inputs/decision/decision",
            "scope_identified": "/scope_hint",
            "commitment_present": "/evidence/",
        }
        for name, prefix in required_prefixes.items():
            if not any(pointer == prefix or pointer.startswith(prefix) for pointer in by_name[name]["evidence_pointers"]):
                raise DecisionError("semantic_attestation_invalid", "claim assertion points at the wrong evidence", {"assertion": name}, EXIT_CONFLICT)
    if operation == "same_claim":
        pointers = [pointer for item in assertions for pointer in item["evidence_pointers"]]
        if not any(pointer.startswith("/predecessor/primary_claim") for pointer in pointers) or not any(pointer.startswith("/successor/primary_claim") for pointer in pointers):
            raise DecisionError("semantic_attestation_invalid", "same_claim must cite both primary claims", exit_code=EXIT_CONFLICT)


def _semantic_input(operation: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"operation": operation, "input_schema": value["schema"], "input_digest": canonical_digest(value), "value": value}


def _list_body(values: Sequence[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _draft_from_candidate(
    candidate: dict[str, Any],
    *,
    identifier: str | None = None,
    created_at: str | None = None,
    filename: str | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], str, str]:
    scope, key, values = validate_candidate(candidate)
    identifier = require_context_id(identifier or new_context_id())
    created_at = _validate_timestamp(created_at or now_rfc3339(), "created_at")
    decision = values["decision"].strip()
    frontmatter: dict[str, Any] = {
        "schema": "context-decision/v1",
        "id": identifier,
        "title": candidate["title"].strip(),
        "summary": candidate["summary"].strip(),
        "created_at": created_at,
        "captured_from": candidate["captured_from"],
        "scope": scope,
        "decision_key": key,
    }
    for field in ("source_refs", "tags"):
        if candidate.get(field):
            frontmatter[field] = list(candidate[field])
    if values.get("revisit_when"):
        frontmatter["revisit_when"] = list(values["revisit_when"])
    if values.get("revisit_on"):
        frontmatter["revisit_on"] = values["revisit_on"]
    if candidate.get("informed_by"):
        informed = [require_context_id(item, "informed_by") for item in candidate["informed_by"]]
        frontmatter["relations"] = {"informed_by": informed}
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)
    sections = {
        "결정": decision,
        "취지": values["rationale"].strip(),
        "반려대안": _list_body(values["rejected_alternatives"]),
    }
    if values.get("constraints"):
        sections["근거와 제약"] = _list_body(values["constraints"])
    if values.get("tradeoffs"):
        sections["트레이드오프"] = _list_body(values["tradeoffs"])
    if values.get("revisit_when"):
        sections["재평가 조건"] = _list_body(values["revisit_when"])
    content = render_document(frontmatter, sections)
    basename = filename or natural_filename(frontmatter["title"])
    if pathlib.PurePosixPath(basename).name != basename or not basename.endswith(".md") or basename.endswith(".index.md"):
        raise DecisionError("filename_invalid", "filename must be a non-reserved basename")
    return frontmatter, sections, f"context/decision/{basename}", content


def _read_preconditions_for_ack(repo: pathlib.Path | None, acknowledgements: Sequence[str]) -> list[dict[str, str]]:
    if not acknowledgements:
        return []
    if repo is None:
        raise DecisionError("conflict_ack_invalid", "acknowledged conflicts require exact read preconditions", exit_code=EXIT_CONFLICT)
    state = current_state(repo)
    output: list[dict[str, str]] = []
    for identifier in sorted(set(acknowledgements), key=lambda item: state.get(item, {}).get("path", "")):
        record = state.get(identifier)
        if record is None:
            raise DecisionError("conflict_ack_invalid", "acknowledged conflict is not current", {"id": identifier}, EXIT_CONFLICT)
        output.append({"id": identifier, "path": record["path"], "sha256": record["sha256"]})
    return output


def build_claim_result(
    candidate: dict[str, Any],
    attestation: dict[str, Any],
    *,
    identifier: str | None = None,
    created_at: str | None = None,
    filename: str | None = None,
    acknowledged_conflicts: Sequence[str] = (),
    repo: pathlib.Path | None = None,
) -> dict[str, Any]:
    validate_candidate(candidate)
    validate_attestation(attestation, candidate, "claim", decision_capability()["claim_assertions"])
    frontmatter, sections, path, content = _draft_from_candidate(candidate, identifier=identifier, created_at=created_at, filename=filename)
    del sections
    effect_id = "effect_create_decision"
    acknowledgements = sorted(set(acknowledged_conflicts))
    result = {
        "schema": "context-owner-result/v1",
        "result_type": "claim",
        "transition": "capture",
        "owner": "context-decision",
        "target_kind": "decision",
        "candidate_id": candidate["candidate_id"],
        "decision": "claim",
        "reason": "explicit accepted choice",
        "capability_digest": canonical_digest(decision_capability()),
        "semantic_inputs": [_semantic_input("claim", candidate)],
        "semantic_attestations": [attestation],
        "artifact_drafts": [{
            "effect_id": effect_id,
            "path": path,
            "content": content,
            "semantic_projection": {
                "kind": "decision",
                "primary_claim": parse_document(content)[1]["결정"],
                "supporting_context": [parse_document(content)[1]["취지"]],
            },
        }],
        "effects": [{
            "effect_id": effect_id,
            "action": "create",
            "area": "decision",
            "id": frontmatter["id"],
            "state": "current",
            "acknowledged_conflicts": acknowledgements,
        }],
        "proposed_plan": {
            "schema": "context-owner-plan/v1",
            "transition": "capture",
            "read_preconditions": _read_preconditions_for_ack(repo, acknowledgements),
            "operations": [{"op": "create", "effect_id": effect_id, "area": "decision", "path": path}],
        },
    }
    validate_owner_result(result)
    return result


def build_decline_result(candidate: dict[str, Any], reason: str, *, needs_clarification: bool = False) -> dict[str, Any]:
    validate_candidate(candidate)
    return {
        "schema": "context-owner-result/v1",
        "result_type": "claim",
        "transition": "capture",
        "owner": "context-decision",
        "target_kind": "decision",
        "candidate_id": candidate["candidate_id"],
        "decision": "needs_clarification" if needs_clarification else "decline",
        "reason": _bounded_string(reason, "reason", 500),
        "capability_digest": canonical_digest(decision_capability()),
        "semantic_inputs": [_semantic_input("claim", candidate)],
        "semantic_attestations": [],
        "artifact_drafts": [],
        "effects": [],
        "proposed_plan": None,
    }


def _input_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    inputs: dict[str, dict[str, Any]] = {}
    for item in result.get("semantic_inputs", []):
        operation = item.get("operation")
        if operation in inputs or item.get("input_schema") != item.get("value", {}).get("schema") or item.get("input_digest") != canonical_digest(item.get("value")):
            raise DecisionError("semantic_input_invalid", "semantic input schema or digest is invalid", exit_code=EXIT_CONFLICT)
        inputs[operation] = item
    return inputs


def validate_owner_result(result: dict[str, Any]) -> None:
    required = {"schema", "result_type", "transition", "owner", "target_kind", "capability_digest", "semantic_inputs", "semantic_attestations", "artifact_drafts", "effects", "proposed_plan"}
    if result.get("schema") != "context-owner-result/v1" or required - set(result):
        raise DecisionError("owner_result_invalid", "owner result envelope is incomplete", exit_code=EXIT_CONFLICT)
    if result.get("owner") != "context-decision" or result.get("target_kind") != "decision" or result.get("capability_digest") != canonical_digest(decision_capability()):
        raise DecisionError("capability_digest_mismatch", "owner/capability binding is invalid", exit_code=EXIT_CONFLICT)
    inputs = _input_map(result)
    attestations: dict[str, dict[str, Any]] = {}
    for item in result.get("semantic_attestations", []):
        operation = item.get("operation")
        if operation in attestations or operation not in inputs:
            raise DecisionError("semantic_attestation_invalid", "attestation is duplicated or unbound", exit_code=EXIT_CONFLICT)
        required_assertions = decision_capability()["claim_assertions"] if operation == "claim" else decision_capability()["lifecycle_operations"]["same_claim"]["assertions"]
        validate_attestation(item, inputs[operation]["value"], operation, required_assertions)
        attestations[operation] = item
    if result["result_type"] == "claim" and result.get("decision") != "claim":
        if result.get("decision") not in {"decline", "needs_clarification"} or result.get("artifact_drafts") or result.get("effects") or result.get("proposed_plan") is not None or "claim" not in inputs:
            raise DecisionError("owner_result_invalid", "decline/clarification must not contain a draft or plan", exit_code=EXIT_CONFLICT)
        return
    if result["result_type"] == "claim":
        if result.get("transition") != "capture" or result.get("decision") != "claim" or "claim" not in inputs or "claim" not in attestations or result.get("candidate_id") != inputs["claim"]["value"].get("candidate_id"):
            raise DecisionError("owner_result_invalid", "claim result lacks exact claim evidence", exit_code=EXIT_CONFLICT)
    elif result["result_type"] == "mutation":
        if "mutation_request" not in inputs or "mutation_request" in attestations or "decision" in result or "candidate_id" in result:
            raise DecisionError("owner_result_invalid", "mutation result is not bound to an unattested mutation request", exit_code=EXIT_CONFLICT)
        expected_inputs = {
            "decision_supersede": {"claim", "mutation_request"},
            "decision_fallback_import": {"claim", "same_claim", "mutation_request"},
            "decision_withdraw": {"mutation_request"},
            "decision_annotate": {"mutation_request"},
        }.get(result.get("transition"))
        expected_attestations = {
            "decision_supersede": {"claim"},
            "decision_fallback_import": {"claim", "same_claim"},
            "decision_withdraw": set(),
            "decision_annotate": set(),
        }.get(result.get("transition"))
        if expected_inputs is None or set(inputs) != expected_inputs or set(attestations) != expected_attestations:
            raise DecisionError("owner_result_invalid", "mutation semantic evidence set is incomplete or hidden", exit_code=EXIT_CONFLICT)
    else:
        raise DecisionError("owner_result_invalid", "unsupported owner result type", exit_code=EXIT_CONFLICT)
    plan = result.get("proposed_plan")
    if not isinstance(plan, dict) or plan.get("schema") != "context-owner-plan/v1" or plan.get("transition") != result["transition"]:
        raise DecisionError("owner_result_invalid", "owner plan does not match result transition", exit_code=EXIT_CONFLICT)
    drafts = result.get("artifact_drafts")
    effects = result.get("effects")
    operations = plan.get("operations")
    if not all(isinstance(value, list) for value in (drafts, effects, operations)):
        raise DecisionError("owner_result_invalid", "draft/effect/operation collections are invalid", exit_code=EXIT_CONFLICT)
    for collection, label in ((drafts, "draft"), (effects, "effect"), (operations, "operation")):
        ids = [item.get("effect_id") for item in collection]
        if any(not isinstance(item, str) or not LOCAL_ID_RE.fullmatch(item) for item in ids) or len(ids) != len(set(ids)):
            raise DecisionError("plan_preview_mismatch", f"{label} effect ids are invalid or duplicate", exit_code=EXIT_CONFLICT)
    if {item["effect_id"] for item in effects} != {item["effect_id"] for item in operations}:
        raise DecisionError("plan_preview_mismatch", "effects and owner operations are not 1:1", exit_code=EXIT_CONFLICT)
    draft_by_id: dict[str, tuple[dict[str, Any], dict[str, str], dict[str, Any]]] = {}
    observation_drafts: dict[str, tuple[dict[str, Any], dict[str, str], dict[str, Any]]] = {}
    for draft in drafts:
        is_observation = draft.get("path", "").startswith("context/observation/")
        frontmatter, sections = parse_observation_document(draft.get("content", "")) if is_observation else parse_document(draft.get("content", ""))
        projection = draft.get("semantic_projection")
        expected_kind = "observation" if is_observation else "decision"
        primary_section = "관찰" if is_observation else "결정"
        if (
            not isinstance(projection, dict)
            or set(projection) != {"kind", "primary_claim", "supporting_context"}
            or projection.get("kind") != expected_kind
            or projection.get("primary_claim") != sections[primary_section]
            or not isinstance(projection.get("supporting_context"), list)
            or len(projection["supporting_context"]) > 4
        ):
            raise DecisionError("plan_preview_mismatch", "draft semantic projection is invalid", exit_code=EXIT_CONFLICT)
        (observation_drafts if is_observation else draft_by_id)[draft["effect_id"]] = (frontmatter, sections, draft)
    for operation in operations:
        if operation.get("op") not in {"create", "replace", "move", "delete"}:
            raise DecisionError("plan_preview_mismatch", "owner operation is unsupported", exit_code=EXIT_CONFLICT)
        if operation["op"] != "delete" and operation["effect_id"] not in draft_by_id and operation["effect_id"] not in observation_drafts:
            raise DecisionError("plan_preview_mismatch", "non-delete operation lacks a destination draft", exit_code=EXIT_CONFLICT)
    transition = result["transition"]
    if transition == "capture" and (len(drafts) != 1 or len(effects) != 1 or effects[0].get("action") != "create"):
        raise DecisionError("plan_preview_mismatch", "capture must create exactly one current DEC", exit_code=EXIT_CONFLICT)
    if transition == "decision_supersede":
        current = [(fm, sections, draft) for fm, sections, draft in draft_by_id.values() if "/retired/" not in draft["path"]]
        history = [(fm, sections, draft) for fm, sections, draft in draft_by_id.values() if "/retired/" in draft["path"]]
        if len(current) != 1 or len(history) != 1:
            raise DecisionError("lifecycle_invalid", "supersede requires one new current and one old history draft", exit_code=EXIT_CONFLICT)
        new, _, _ = current[0]
        old, _, _ = history[0]
        if (new["scope"], new["decision_key"]) != (old["scope"], old["decision_key"]) or old.get("superseded_by") != new["id"] or old["id"] not in new.get("supersedes", []):
            raise DecisionError("lifecycle_invalid", "supersede slot and reciprocal edges are invalid", exit_code=EXIT_CONFLICT)
    if transition == "decision_withdraw":
        if len(drafts) != 1:
            raise DecisionError("lifecycle_invalid", "withdraw must contain exactly one history draft", exit_code=EXIT_CONFLICT)
        old, _, draft = next(iter(draft_by_id.values()))
        if "/retired/" not in draft["path"] or old.get("retired_reason") != "withdrawn" or "superseded_by" in old:
            raise DecisionError("lifecycle_invalid", "withdraw must retire without successor", exit_code=EXIT_CONFLICT)
    if transition == "decision_fallback_import":
        if len(draft_by_id) != 1 or len(observation_drafts) != 1:
            raise DecisionError("lifecycle_invalid", "fallback import requires one DEC current and one OBS history draft", exit_code=EXIT_CONFLICT)
        dec, _, _ = next(iter(draft_by_id.values()))
        obs, _, obs_draft = next(iter(observation_drafts.values()))
        if (
            "/retired/" not in obs_draft["path"]
            or obs.get("kind_hint") != "decision"
            or obs.get("retired_reason") != "superseded"
            or obs.get("superseded_by") != dec.get("id")
            or obs.get("id") not in dec.get("supersedes", [])
        ):
            raise DecisionError("lifecycle_invalid", "fallback import reciprocal lifecycle is invalid", exit_code=EXIT_CONFLICT)


def _extract_generated_block(text: str, block: str) -> list[str]:
    begin = f"<!-- BEGIN CONTEXT GENERATED:{block} -->"
    end = f"<!-- END CONTEXT GENERATED:{block} -->"
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) > text.index(end):
        raise DecisionError("index_stale", "decision index marker is invalid", {"block": block}, EXIT_INTEGRITY)
    inside = text.split(begin, 1)[1].split(end, 1)[0]
    return [line for line in inside.strip("\n").split("\n") if line]


def parse_decision_index(text: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise DecisionError("index_stale", "decision index frontmatter is missing", exit_code=EXIT_INTEGRITY)
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise DecisionError("index_stale", "decision index frontmatter is unterminated", exit_code=EXIT_INTEGRITY) from error
    frontmatter: dict[str, Any] = {}
    for line in lines[1:closing]:
        if ": " not in line:
            raise DecisionError("index_stale", "decision index frontmatter is malformed", exit_code=EXIT_INTEGRITY)
        key, raw = line.split(": ", 1)
        try:
            frontmatter[key] = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DecisionError("index_stale", "decision index frontmatter is malformed", exit_code=EXIT_INTEGRITY) from error
    expected = {"schema": "context-area-index/v1", "index": True, "area": "decision", "owner": "context-decision", "artifact_schema": "context-decision/v1", "authority": "authoritative"}
    if any(frontmatter.get(key) != value for key, value in expected.items()):
        raise DecisionError("index_stale", "decision index descriptor is invalid", exit_code=EXIT_INTEGRITY)
    parsed: list[list[dict[str, Any]]] = []
    for block, state in (("current", "current"), ("history", "history")):
        rows: list[dict[str, Any]] = []
        for line in _extract_generated_block(text, block):
            match = ENTRY_RE.fullmatch(line)
            if not match:
                raise DecisionError("index_stale", "decision index row is malformed", exit_code=EXIT_INTEGRITY)
            try:
                row = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise DecisionError("index_stale", "decision index row JSON is malformed", exit_code=EXIT_INTEGRITY) from error
            if row.get("state") != state or not _valid_context_id(row.get("id")):
                raise DecisionError("index_stale", "decision index row state/id is invalid", exit_code=EXIT_INTEGRITY)
            rows.append(row)
        parsed.append(rows)
    return frontmatter, parsed[0], parsed[1]


def decision_index_seed() -> str:
    return """---
schema: \"context-area-index/v1\"
index: true
area: \"decision\"
owner: \"context-decision\"
artifact_schema: \"context-decision/v1\"
authority: \"authoritative\"
summary: \"결정·취지·반려대안과 현재 유효성을 관리한다.\"
search_terms: [\"결정\",\"rationale\",\"rejected alternative\"]
projection_fields: [\"scope\",\"decision_key\",\"revisit_on\"]
---

# Decision

## Current
<!-- BEGIN CONTEXT GENERATED:current -->
<!-- END CONTEXT GENERATED:current -->

## History
<!-- BEGIN CONTEXT GENERATED:history -->
<!-- END CONTEXT GENERATED:history -->
"""


def build_init_plan(preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    descriptor = {"schema": "context-owner-descriptor/v1", "owner": "context-decision", "kind": "decision", "artifact_schema": "context-decision/v1", "authority": "authoritative"}
    seed = decision_index_seed()
    parse_decision_index(seed)
    core_state = "ready" if preflight is None else preflight["observed"]["repository_state"]
    host = None if preflight is None else preflight.get("host")
    policy_target = {"codex": "AGENTS.md", "claude-code": "CLAUDE.md"}.get(host, "active_host")
    return {
        "schema": "context-decision-init-plan/v1",
        "required_plugin": dict(REQUIRED_PLUGIN),
        "core_repository_state": core_state,
        "owner_descriptor": descriptor,
        "descriptor_digest": canonical_digest(descriptor),
        "index_seed": seed,
        "index_seed_sha256": file_digest(seed),
        "bootstrap": {
            "owner": "context-core",
            "operation": "bootstrap",
            "host": host or "active_host",
            "core_init": "apply_if_absent",
            "area_register": "context-decision",
            "policy_install": policy_target,
            "index_path": DECISION_INDEX,
        },
        "phases": [
            {"phase": "core_init", "status": "pending" if core_state == "absent" else "ready"},
            {"phase": "area_register", "status": "pending"},
            {"phase": "policy_install", "status": "pending", "target": policy_target},
        ],
        "registration": {"owner": "context-core", "operation": "bootstrap", "index_path": DECISION_INDEX},
        "applied": False,
    }


def repository_root() -> pathlib.Path:
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True)
    if completed.returncode or not completed.stdout.strip():
        raise DecisionError("repository_not_found", "current directory is not in a Git worktree", exit_code=EXIT_NOT_FOUND)
    root = pathlib.Path(completed.stdout.strip()).resolve()
    try:
        pathlib.Path.cwd().resolve().relative_to(root)
    except ValueError as error:
        raise DecisionError("repository_not_found", "cwd is outside the resolved Git worktree", exit_code=EXIT_NOT_FOUND) from error
    return root


def _index(repo: pathlib.Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    path = repo / DECISION_INDEX
    if not path.is_file():
        raise DecisionError("decision_area_missing", "decision area index is missing", {"path": DECISION_INDEX}, EXIT_NOT_FOUND)
    text = path.read_text(encoding="utf-8")
    _, current, history = parse_decision_index(text)
    return text, current, history


def _record(repo: pathlib.Path, row: dict[str, Any]) -> dict[str, Any]:
    path = repo / row["path"]
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise DecisionError("index_stale", "selected DEC path is missing", {"path": row["path"]}, EXIT_INTEGRITY) from error
    frontmatter, sections = parse_document(raw.decode("utf-8"))
    if frontmatter["id"] != row["id"]:
        raise DecisionError("index_stale", "selected DEC id differs from index", {"path": row["path"]}, EXIT_INTEGRITY)
    return {"id": row["id"], "path": row["path"], "state": row["state"], "frontmatter": frontmatter, "sections": sections, "sha256": bytes_digest(raw)}


def current_state(repo: pathlib.Path) -> dict[str, dict[str, Any]]:
    _, current, _ = _index(repo)
    return {row["id"]: _record(repo, row) for row in current}


def _all_records(repo: pathlib.Path, include_history: bool = False) -> list[dict[str, Any]]:
    _, current, history = _index(repo)
    return [_record(repo, row) for row in current + (history if include_history else [])]


def _effects_and_drafts(owner_result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    validate_owner_result(owner_result)
    return owner_result["effects"], {draft["effect_id"]: draft for draft in owner_result["artifact_drafts"]}


def _overlay_owner_result(state: dict[str, dict[str, Any]], owner_result: dict[str, Any]) -> None:
    effects, drafts = _effects_and_drafts(owner_result)
    for effect in effects:
        if effect.get("area") != "decision":
            continue
        draft = drafts.get(effect["effect_id"])
        action = effect.get("action")
        identifier = effect.get("id")
        if action in {"retire", "delete"}:
            state.pop(identifier, None)
        elif action in {"create", "replace"}:
            if draft is None:
                raise DecisionError("plan_preview_mismatch", "current effect lacks a draft", exit_code=EXIT_CONFLICT)
            frontmatter, sections = parse_document(draft["content"])
            if "/retired/" in draft["path"]:
                state.pop(frontmatter["id"], None)
            else:
                state[frontmatter["id"]] = {
                    "id": frontmatter["id"], "path": draft["path"], "state": "current", "frontmatter": frontmatter,
                    "sections": sections, "sha256": file_digest(draft["content"]),
                }


def _owner_result_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if bundle.get("schema") != "context-mutation-bundle/v1" or bundle.get("approval_digest") != canonical_digest(bundle.get("approval_material")):
        raise DecisionError("prior_bundle_invalid", "prior bundle schema or approval digest is invalid", exit_code=EXIT_CONFLICT)
    plan = bundle.get("approval_material", {}).get("plan", {})
    if plan.get("owner") != "context-decision" or plan.get("source_type") != "owner_result":
        raise DecisionError("prior_bundle_invalid", "prior bundle is not a context-decision owner bundle", exit_code=EXIT_CONFLICT)
    material_id = plan.get("owner_result_material")
    material = next((item for item in bundle.get("materials", []) if item.get("material_id") == material_id), None)
    if not material or material.get("path") is not None or bytes_digest(material.get("content", "").encode("utf-8")) != plan.get("owner_result_digest"):
        raise DecisionError("prior_bundle_invalid", "prior owner result material is missing or altered", exit_code=EXIT_CONFLICT)
    try:
        owner_result = json.loads(material["content"])
    except json.JSONDecodeError as error:
        raise DecisionError("prior_bundle_invalid", "prior owner result material is not JSON", exit_code=EXIT_CONFLICT) from error
    validate_owner_result(owner_result)
    return owner_result


def _primary_draft(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    current: list[tuple[dict[str, Any], dict[str, str], dict[str, Any]]] = []
    history: list[tuple[dict[str, Any], dict[str, str], dict[str, Any]]] = []
    for draft in result["artifact_drafts"]:
        if draft.get("path", "").startswith("context/observation/"):
            continue
        frontmatter, sections = parse_document(draft["content"])
        (history if "/retired/" in draft["path"] else current).append((frontmatter, sections, draft))
    if current:
        return current[0]
    if history:
        return history[0]
    raise DecisionError("owner_result_invalid", "decision result has no DEC draft", exit_code=EXIT_CONFLICT)


def _acknowledgements(result: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    values: set[str] = set()
    for effect in result["effects"]:
        values.update(effect.get("acknowledged_conflicts", []))
    preconditions = result["proposed_plan"].get("read_preconditions", [])
    return sorted(values), preconditions


def validate_batch(repo: pathlib.Path, owner_result: dict[str, Any], prior_bundles: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    validate_owner_result(owner_result)
    base_text, _, _ = _index(repo)
    base_digest = bytes_digest(base_text.encode("utf-8"))
    state = current_state(repo)
    prior_digests: list[str] = []
    for bundle in prior_bundles:
        plan = bundle.get("approval_material", {}).get("plan", {})
        if plan.get("prior_bundle_digests") != prior_digests:
            raise DecisionError(
                "prior_bundle_order_invalid",
                "prior bundle chain does not match the exact proposal order",
                {"expected": prior_digests, "actual": plan.get("prior_bundle_digests")},
                EXIT_CONFLICT,
            )
        owner = _owner_result_from_bundle(bundle)
        _overlay_owner_result(state, owner)
        prior_digests.append(bundle["approval_digest"])
    frontmatter, sections, _ = _primary_draft(owner_result)
    transition = owner_result["transition"]
    target_ids = {target.get("id") for target in _input_map(owner_result).get("mutation_request", {}).get("value", {}).get("targets", [])}
    predecessor: dict[str, Any] | None = None
    if transition in {"decision_supersede", "decision_withdraw", "decision_annotate"}:
        predecessor_id = next(iter(target_ids), None)
        predecessor = state.get(predecessor_id)
        if predecessor is None:
            raise DecisionError("predecessor_not_current", "decision mutation predecessor is not current in virtual state", {"id": predecessor_id}, EXIT_CONFLICT)
    if transition in {"capture", "decision_fallback_import"}:
        same_slot = [record for record in state.values() if (record["frontmatter"]["scope"], record["frontmatter"]["decision_key"]) == (frontmatter["scope"], frontmatter["decision_key"])]
        if same_slot:
            raise DecisionError("decision_slot_conflict", "slot already has a current DEC", {"current": [item["id"] for item in same_slot]}, EXIT_CONFLICT)
    if transition == "decision_supersede" and predecessor and (frontmatter["scope"], frontmatter["decision_key"]) != (predecessor["frontmatter"]["scope"], predecessor["frontmatter"]["decision_key"]):
        raise DecisionError("successor_slot_mismatch", "successor must use the exact predecessor slot", exit_code=EXIT_CONFLICT)
    overlaps = [
        record for record in state.values()
        if record["id"] not in target_ids
        and record["frontmatter"]["decision_key"] == frontmatter["decision_key"]
        and scopes_overlap(record["frontmatter"]["scope"], frontmatter["scope"])
    ] if transition in {"capture", "decision_supersede", "decision_fallback_import"} else []
    acknowledged, preconditions = _acknowledgements(owner_result)
    expected_ack = sorted(record["id"] for record in overlaps)
    if acknowledged != expected_ack:
        raise DecisionError("conflict_ack_required", "all and only current overlap conflicts must be acknowledged", {"required": expected_ack, "acknowledged": acknowledged}, EXIT_CONFLICT)
    by_id = {item.get("id"): item for item in preconditions}
    for record in overlaps:
        if by_id.get(record["id"]) != {"id": record["id"], "path": record["path"], "sha256": record["sha256"]}:
            raise DecisionError("conflict_read_precondition_required", "acknowledged overlap lacks exact read precondition", {"id": record["id"]}, EXIT_CONFLICT)
    before_ids = set(state)
    _overlay_owner_result(state, owner_result)
    slots: dict[tuple[str, str], str] = {}
    for record in state.values():
        slot = (record["frontmatter"]["scope"], record["frontmatter"]["decision_key"])
        if slot in slots:
            raise DecisionError("decision_slot_conflict", "virtual current contains two DEC in one slot", {"ids": [slots[slot], record["id"]]}, EXIT_CONFLICT)
        slots[slot] = record["id"]
    del before_ids
    facts = {
        "scope": frontmatter["scope"],
        "decision_key": frontmatter["decision_key"],
        "primary_claim": sections["결정"],
        "rationale": sections["취지"],
        "acknowledged_conflicts": acknowledged,
    }
    receipt = {
        "schema": "context-owner-validation-receipt/v1",
        "owner": "context-decision",
        "kind": "decision",
        "owner_result_digest": canonical_digest(owner_result),
        "base_area_index_sha256": base_digest,
        "prior_same_area_bundle_digests": prior_digests,
        "validated_facts": facts,
        "status": "valid",
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def find_current(repo: pathlib.Path, identifier: str) -> dict[str, Any]:
    require_context_id(identifier)
    record = current_state(repo).get(identifier)
    if record is None:
        raise DecisionError("artifact_not_found", "current DEC id was not found", {"id": identifier}, EXIT_NOT_FOUND)
    return record


def _mutation_request(
    transition: str,
    requested_changes: dict[str, Any],
    targets: Sequence[dict[str, str]],
    successor_digest: str | None,
    successor_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema": "context-domain-mutation-input/v1",
        "transition": transition,
        "owner": "context-decision",
        "target_kind": "decision",
        "requested_changes": requested_changes,
        "targets": sorted(targets, key=lambda item: item["path"]),
        "successor_owner_result_digest": successor_digest,
        "successor_artifact_sha256": successor_artifact_sha256,
    }
    if len(canonical_json(value).encode("utf-8")) > 8 * 1024:
        raise DecisionError("mutation_request_too_large", "mutation request exceeds 8 KiB", exit_code=EXIT_CONFLICT)
    return value


def _history_path(path: str, identifier: str) -> str:
    pure = pathlib.PurePosixPath(path)
    return (pure.parent / "retired" / f"{pure.stem}--{identifier[4:16]}.md").as_posix()


def build_supersede_result(
    repo: pathlib.Path,
    predecessor_id: str,
    candidate: dict[str, Any],
    attestation: dict[str, Any],
    *,
    identifier: str | None = None,
    retired_at: str | None = None,
    filename: str | None = None,
    acknowledged_conflicts: Sequence[str] = (),
) -> dict[str, Any]:
    predecessor = find_current(repo, predecessor_id)
    claim = build_claim_result(candidate, attestation, identifier=identifier, created_at=retired_at, filename=filename, acknowledged_conflicts=acknowledged_conflicts, repo=repo)
    new_fm, new_sections, new_draft = _primary_draft(claim)
    old_fm = dict(predecessor["frontmatter"])
    if (new_fm["scope"], new_fm["decision_key"]) != (old_fm["scope"], old_fm["decision_key"]):
        raise DecisionError("successor_slot_mismatch", "successor candidate must explicitly use the predecessor slot", exit_code=EXIT_CONFLICT)
    timestamp = _validate_timestamp(retired_at or new_fm["created_at"], "retired_at")
    new_fm["supersedes"] = [predecessor_id]
    new_content = render_document(new_fm, new_sections)
    old_fm.update({"retired_at": timestamp, "retired_reason": "superseded", "superseded_by": new_fm["id"]})
    old_content = render_document(old_fm, predecessor["sections"])
    old_effect = "effect_retire_decision"
    new_effect = "effect_create_successor"
    new_path = new_draft["path"]
    old_history = _history_path(predecessor["path"], predecessor_id)
    request = _mutation_request(
        "decision_supersede",
        {"predecessor": predecessor_id, "successor": new_fm["id"], "acknowledged_conflicts": sorted(set(acknowledged_conflicts))},
        [{"id": predecessor_id, "path": predecessor["path"], "sha256": predecessor["sha256"]}],
        canonical_digest(claim),
    )
    result = {
        "schema": "context-owner-result/v1", "result_type": "mutation", "transition": "decision_supersede",
        "owner": "context-decision", "target_kind": "decision", "capability_digest": canonical_digest(decision_capability()),
        "semantic_inputs": claim["semantic_inputs"] + [_semantic_input("mutation_request", request)],
        "semantic_attestations": claim["semantic_attestations"],
        "artifact_drafts": [
            {"effect_id": old_effect, "path": old_history, "content": old_content, "semantic_projection": {"kind": "decision", "primary_claim": predecessor["sections"]["결정"], "supporting_context": [predecessor["sections"]["취지"]]}},
            {"effect_id": new_effect, "path": new_path, "content": new_content, "semantic_projection": {"kind": "decision", "primary_claim": new_sections["결정"], "supporting_context": [new_sections["취지"]]}},
        ],
        "effects": [
            {"effect_id": old_effect, "action": "retire", "area": "decision", "id": predecessor_id, "state": "history", "reason": "superseded", "successor": new_fm["id"]},
            {"effect_id": new_effect, "action": "create", "area": "decision", "id": new_fm["id"], "state": "current", "acknowledged_conflicts": sorted(set(acknowledged_conflicts))},
        ],
        "proposed_plan": {
            "schema": "context-owner-plan/v1", "transition": "decision_supersede",
            "read_preconditions": _read_preconditions_for_ack(repo, acknowledged_conflicts),
            "operations": [
                {"op": "move", "effect_id": old_effect, "area": "decision", "id": predecessor_id, "from_path": predecessor["path"], "to_path": old_history},
                {"op": "create", "effect_id": new_effect, "area": "decision", "path": new_path},
            ],
        },
    }
    validate_owner_result(result)
    return result


def build_fallback_import_result(
    repo: pathlib.Path,
    predecessor_id: str,
    successor_result: dict[str, Any],
    lifecycle_input: dict[str, Any],
    lifecycle_attestation: dict[str, Any],
    *,
    retired_at: str | None = None,
    acknowledged_conflicts: Sequence[str] = (),
) -> dict[str, Any]:
    """Plan an OBS-to-DEC import; context-core remains the only physical writer."""
    validate_owner_result(successor_result)
    if (
        successor_result.get("result_type") != "claim"
        or successor_result.get("transition") != "capture"
        or successor_result.get("owner") != "context-decision"
    ):
        raise DecisionError("successor_result_invalid", "fallback successor must be one complete DEC claim result", exit_code=EXIT_CONFLICT)
    validate_attestation(
        lifecycle_attestation,
        lifecycle_input,
        "same_claim",
        decision_capability()["lifecycle_operations"]["same_claim"]["assertions"],
    )
    claim_input = _input_map(successor_result).get("claim")
    if claim_input is None or lifecycle_input.get("source_candidate_digest") != claim_input["input_digest"]:
        raise DecisionError("lifecycle_input_mismatch", "lifecycle input is not bound to the successor claim", exit_code=EXIT_CONFLICT)
    predecessor = lifecycle_input.get("predecessor", {})
    successor = lifecycle_input.get("successor", {})
    if (
        lifecycle_input.get("schema") != "context-lifecycle-semantic-input/v1"
        or lifecycle_input.get("operation") != "same_claim"
        or lifecycle_input.get("transition") != "decision_fallback_import"
        or lifecycle_input.get("owner") != "context-decision"
        or predecessor.get("id") != predecessor_id
        or predecessor.get("kind") != "observation"
        or successor.get("kind") != "decision"
        or set(lifecycle_input) != {"schema", "operation", "transition", "owner", "predecessor", "successor", "source_candidate_digest"}
        or set(predecessor) != {"id", "kind", "path", "primary_claim", "artifact_sha256", "supporting_context"}
        or set(successor) != {"id", "kind", "path", "primary_claim", "artifact_sha256", "supporting_context"}
    ):
        raise DecisionError("lifecycle_input_mismatch", "fallback lifecycle envelope is invalid", exit_code=EXIT_CONFLICT)
    predecessor_path = pathlib.PurePosixPath(str(predecessor.get("path", "")))
    if (
        predecessor_path.is_absolute()
        or ".." in predecessor_path.parts
        or len(predecessor_path.parts) < 3
        or predecessor_path.parts[:2] != ("context", "observation")
        or "retired" in predecessor_path.parts
    ):
        raise DecisionError("lifecycle_input_mismatch", "fallback predecessor path is not a current OBS path", exit_code=EXIT_CONFLICT)
    source_path = repo / predecessor_path
    try:
        source_bytes = source_path.read_bytes()
        source_text = source_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DecisionError("predecessor_not_current", "fallback OBS predecessor is unavailable", exit_code=EXIT_CONFLICT) from error
    obs_fm, obs_sections = parse_observation_document(source_text)
    dec_fm, dec_sections, dec_draft = _primary_draft(successor_result)
    if predecessor_id != obs_fm["id"] or successor.get("id") != dec_fm["id"] or successor.get("path") != dec_draft["path"]:
        raise DecisionError("lifecycle_input_mismatch", "lifecycle ids or paths differ from artifact drafts", exit_code=EXIT_CONFLICT)
    if (
        predecessor.get("primary_claim") != obs_sections["관찰"]
        or predecessor.get("artifact_sha256") != bytes_digest(source_bytes)
        or successor.get("primary_claim") != dec_sections["결정"]
        or successor.get("artifact_sha256") != file_digest(dec_draft["content"])
        or obs_fm.get("kind_hint") != "decision"
        or not isinstance(predecessor.get("supporting_context"), list)
        or not isinstance(successor.get("supporting_context"), list)
        or len(predecessor["supporting_context"]) > 4
        or len(successor["supporting_context"]) > 4
        or predecessor["supporting_context"] != [line[2:].strip() for line in obs_sections["근거"].splitlines() if line.startswith("- ")][:4]
        or successor["supporting_context"] != [dec_sections["취지"]]
    ):
        raise DecisionError("fallback_semantic_input_mismatch", "fallback artifact identity or semantic projection differs", exit_code=EXIT_CONFLICT)
    if predecessor_id in dec_fm.get("relations", {}).get("informed_by", []):
        raise DecisionError("fallback_relation_conflict", "fallback import must use lifecycle edges, not informed_by", exit_code=EXIT_CONFLICT)
    timestamp = _validate_timestamp(retired_at or now_rfc3339(), "retired_at")
    dec_fm = dict(dec_fm)
    dec_fm["supersedes"] = [predecessor_id]
    dec_content = render_document(dec_fm, dec_sections)
    obs_fm = dict(obs_fm)
    obs_fm.update({"retired_at": timestamp, "retired_reason": "superseded", "superseded_by": dec_fm["id"]})
    obs_content = render_observation_document(obs_fm, obs_sections)
    obs_effect = "effect_retire_fallback_observation"
    dec_effect = "effect_create_imported_decision"
    obs_history = _history_path(predecessor_path.as_posix(), predecessor_id)
    target = {"id": predecessor_id, "path": predecessor_path.as_posix(), "sha256": bytes_digest(source_bytes)}
    acknowledgements = sorted(set(acknowledged_conflicts))
    claim_effect = next(effect for effect in successor_result["effects"] if effect["id"] == dec_fm["id"])
    successor_acknowledgements = sorted(set(claim_effect.get("acknowledged_conflicts", [])))
    if not acknowledgements:
        acknowledgements = successor_acknowledgements
    if acknowledgements != successor_acknowledgements:
        raise DecisionError("conflict_ack_invalid", "fallback import acknowledgements must equal the successor claim", exit_code=EXIT_CONFLICT)
    request = _mutation_request(
        "decision_fallback_import",
        {"predecessor": predecessor_id, "successor": dec_fm["id"], "acknowledged_conflicts": acknowledgements},
        [target],
        canonical_digest(successor_result),
        file_digest(dec_draft["content"]),
    )
    result = {
        "schema": "context-owner-result/v1",
        "result_type": "mutation",
        "transition": "decision_fallback_import",
        "owner": "context-decision",
        "target_kind": "decision",
        "capability_digest": canonical_digest(decision_capability()),
        "semantic_inputs": successor_result["semantic_inputs"] + [_semantic_input("same_claim", lifecycle_input), _semantic_input("mutation_request", request)],
        "semantic_attestations": successor_result["semantic_attestations"] + [lifecycle_attestation],
        "artifact_drafts": [
            {"effect_id": obs_effect, "path": obs_history, "content": obs_content, "semantic_projection": {"kind": "observation", "primary_claim": obs_sections["관찰"], "supporting_context": [obs_sections["근거"]]}},
            {"effect_id": dec_effect, "path": dec_draft["path"], "content": dec_content, "semantic_projection": {"kind": "decision", "primary_claim": dec_sections["결정"], "supporting_context": [dec_sections["취지"]]}},
        ],
        "effects": [
            {"effect_id": obs_effect, "action": "retire", "area": "observation", "id": predecessor_id, "state": "history", "reason": "superseded", "successor": dec_fm["id"]},
            {"effect_id": dec_effect, "action": "create", "area": "decision", "id": dec_fm["id"], "state": "current", "acknowledged_conflicts": acknowledgements},
        ],
        "proposed_plan": {
            "schema": "context-owner-plan/v1",
            "transition": "decision_fallback_import",
            "read_preconditions": [target] + _read_preconditions_for_ack(repo, acknowledgements),
            "operations": [
                {"op": "move", "effect_id": obs_effect, "area": "observation", "id": predecessor_id, "from_path": predecessor_path.as_posix(), "to_path": obs_history},
                {"op": "create", "effect_id": dec_effect, "area": "decision", "path": dec_draft["path"]},
            ],
        },
    }
    validate_owner_result(result)
    return result


def build_withdraw_result(repo: pathlib.Path, identifier: str, reason: str, *, retired_at: str | None = None) -> dict[str, Any]:
    record = find_current(repo, identifier)
    reason = _bounded_string(reason, "reason", 500)
    timestamp = _validate_timestamp(retired_at or now_rfc3339(), "retired_at")
    frontmatter = dict(record["frontmatter"])
    frontmatter.update({"retired_at": timestamp, "retired_reason": "withdrawn", "retirement_note": reason})
    frontmatter.pop("superseded_by", None)
    content = render_document(frontmatter, record["sections"])
    effect = "effect_withdraw_decision"
    path = _history_path(record["path"], identifier)
    request = _mutation_request("decision_withdraw", {"reason": reason}, [{"id": identifier, "path": record["path"], "sha256": record["sha256"]}], None)
    result = {
        "schema": "context-owner-result/v1", "result_type": "mutation", "transition": "decision_withdraw",
        "owner": "context-decision", "target_kind": "decision", "capability_digest": canonical_digest(decision_capability()),
        "semantic_inputs": [_semantic_input("mutation_request", request)], "semantic_attestations": [],
        "artifact_drafts": [{"effect_id": effect, "path": path, "content": content, "semantic_projection": {"kind": "decision", "primary_claim": record["sections"]["결정"], "supporting_context": [record["sections"]["취지"]]}}],
        "effects": [{"effect_id": effect, "action": "retire", "area": "decision", "id": identifier, "state": "history", "reason": "withdrawn"}],
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": "decision_withdraw", "read_preconditions": [], "operations": [{"op": "move", "effect_id": effect, "area": "decision", "id": identifier, "from_path": record["path"], "to_path": path}]},
    }
    validate_owner_result(result)
    return result


def build_annotate_result(
    repo: pathlib.Path,
    identifier: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    tags: Sequence[str] | None = None,
    search_terms: Sequence[str] | None = None,
    source_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    record = find_current(repo, identifier)
    frontmatter = dict(record["frontmatter"])
    changes: dict[str, Any] = {}
    for field, value, maximum in (("title", title, 120), ("summary", summary, 280)):
        if value is not None:
            changes[field] = _bounded_string(value, field, maximum)
            frontmatter[field] = changes[field]
    for field, value, maximum in (("tags", tags, 40), ("search_terms", search_terms, 40), ("source_refs", source_refs, 500)):
        if value is not None:
            changes[field] = _bounded_list(list(value), field, maximum=12, item_maximum=maximum)
            frontmatter[field] = changes[field]
    content = render_document(frontmatter, record["sections"])
    if file_bytes(content) == file_bytes((repo / record["path"]).read_text(encoding="utf-8")):
        return {"noop": True, "applied": False, "changed_paths": []}
    effect = "effect_annotate_decision"
    request = _mutation_request("decision_annotate", changes, [{"id": identifier, "path": record["path"], "sha256": record["sha256"]}], None)
    result = {
        "schema": "context-owner-result/v1", "result_type": "mutation", "transition": "decision_annotate",
        "owner": "context-decision", "target_kind": "decision", "capability_digest": canonical_digest(decision_capability()),
        "semantic_inputs": [_semantic_input("mutation_request", request)], "semantic_attestations": [],
        "artifact_drafts": [{"effect_id": effect, "path": record["path"], "content": content, "semantic_projection": {"kind": "decision", "primary_claim": record["sections"]["결정"], "supporting_context": [record["sections"]["취지"]]}}],
        "effects": [{"effect_id": effect, "action": "replace", "area": "decision", "id": identifier, "state": "current"}],
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": "decision_annotate", "read_preconditions": [], "operations": [{"op": "replace", "effect_id": effect, "area": "decision", "id": identifier, "path": record["path"]}]},
    }
    validate_owner_result(result)
    return result


def search_decisions(
    repo: pathlib.Path,
    *,
    query: str = "",
    scope: str | None = None,
    decision_key: str | None = None,
    include_history: bool = False,
    limit: int = 8,
) -> dict[str, Any]:
    if not 1 <= limit <= 20:
        raise DecisionError("usage_invalid", "limit must be in 1..20")
    _, current, history = _index(repo)
    scope_value = canonical_scope(scope) if scope else None
    key_value = canonical_decision_key(decision_key) if decision_key else None
    needle = normalized_key(query.strip())
    rows = current + (history if include_history else [])
    selected = []
    for row in rows:
        if scope_value and row.get("scope") != scope_value:
            continue
        if key_value and row.get("decision_key") != key_value:
            continue
        haystack = normalized_key(" ".join(str(row.get(field, "")) for field in ("id", "title", "summary", "path", "scope", "decision_key")) + " " + " ".join(row.get("terms", [])))
        if needle and needle not in haystack:
            continue
        item = {key: row[key] for key in ("id", "path", "title", "summary", "state", "created_at", "scope", "decision_key") if key in row}
        item["authority"] = "authoritative" if row["state"] == "current" else "historical"
        if row["state"] == "history":
            item["do_not_follow"] = True
            item["retired_reason"] = row.get("retired_reason")
        selected.append(item)
    selected.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    output = selected[:limit]
    return {"items": output, "returned": len(output), "omitted": max(0, len(selected) - len(output)), "truncated": len(selected) > len(output)}


def read_decision(repo: pathlib.Path, identifier: str, *, sections: Sequence[str] = (), max_bytes: int = MAX_BRIEF_BYTES) -> dict[str, Any]:
    require_context_id(identifier)
    if not 1 <= max_bytes <= 32 * 1024:
        raise DecisionError("usage_invalid", "max-bytes is outside the supported range")
    _, current, history = _index(repo)
    matches = [row for row in current + history if row["id"] == identifier]
    if len(matches) != 1:
        raise DecisionError("artifact_not_found", "DEC id was not found", {"id": identifier}, EXIT_NOT_FOUND)
    record = _record(repo, matches[0])
    names = list(sections) if sections else list(record["sections"])
    unknown = set(names) - set(ALL_SECTIONS)
    if unknown:
        raise DecisionError("section_schema_error", "unknown DEC section requested", {"sections": sorted(unknown)})
    selected = {name: record["sections"][name] for name in names if name in record["sections"]}
    result = {
        "artifact": {"id": identifier, "path": record["path"], "state": record["state"], "title": record["frontmatter"]["title"], "summary": record["frontmatter"]["summary"], "scope": record["frontmatter"]["scope"], "decision_key": record["frontmatter"]["decision_key"]},
        "sections": selected,
        "authority": "authoritative" if record["state"] == "current" else "historical",
        "do_not_follow": record["state"] == "history",
        "lifecycle_reason": record["frontmatter"].get("retired_reason"),
        "truncated": False,
    }
    if len(canonical_json(result).encode("utf-8")) > max_bytes:
        raise DecisionError("output_too_large", "selected DEC sections exceed max-bytes; narrow sections", exit_code=EXIT_CONFLICT)
    return result


def brief_decisions(
    repo: pathlib.Path,
    *,
    query: str | None = None,
    identifiers: Sequence[str] = (),
    include_history: bool = False,
    max_bytes: int = MAX_BRIEF_BYTES,
) -> dict[str, Any]:
    if not 1 <= max_bytes <= MAX_BRIEF_BYTES:
        raise DecisionError("usage_invalid", "decision brief max-bytes must be in 1..8192")
    if bool(query) == bool(identifiers):
        raise DecisionError("usage_invalid", "brief requires exactly one of query or id")
    if identifiers:
        require = set(identifiers)
        _, current, history = _index(repo)
        rows = [row for row in current + (history if include_history else []) if row["id"] in require]
    else:
        search = search_decisions(repo, query=query or "", include_history=include_history, limit=20)
        wanted = {item["id"] for item in search["items"]}
        _, current, history = _index(repo)
        rows = [row for row in current + (history if include_history else []) if row["id"] in wanted]
    rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
    items: list[dict[str, Any]] = []
    omitted = 0
    today = datetime.date.today()
    for row in rows:
        record = _record(repo, row)
        fm = record["frontmatter"]
        item = {
            "id": fm["id"], "title": fm["title"], "summary": fm["summary"], "scope": fm["scope"], "decision_key": fm["decision_key"],
            "state": record["state"], "authority": "authoritative" if record["state"] == "current" else "historical",
            "sections": {name: record["sections"][name] for name in CORE_SECTIONS},
            "informed_by": fm.get("relations", {}).get("informed_by", []),
            "revisit_due": bool(fm.get("revisit_on") and datetime.date.fromisoformat(fm["revisit_on"]) <= today),
        }
        if record["state"] == "history":
            item.update({"do_not_follow": True, "lifecycle_reason": fm.get("retired_reason"), "successor": fm.get("superseded_by")})
        if len(canonical_json(items + [item]).encode("utf-8")) > max_bytes:
            omitted += 1
        else:
            items.append(item)
    return {"items": items, "returned": len(items), "omitted": omitted, "truncated": omitted > 0, "max_bytes": max_bytes}


def _comparison_tokens(*values: str) -> set[str]:
    text = normalized_key(" ".join(value for value in values if value))
    return {
        token
        for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        if len(token) >= 2 and not token.isdecimal()
    }


def prepare_decision_check(
    repo: pathlib.Path,
    *,
    statement: str,
    scope: str,
    decision_key: str,
    rationale: str = "",
    query: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Prepare bounded, actual-body input for agent semantic comparison."""

    if not 1 <= limit <= 12:
        raise DecisionError("usage_invalid", "check limit must be in 1..12")
    statement = _bounded_string(statement, "statement", 1200)
    rationale = rationale.strip()
    query = query.strip()
    if rationale:
        rationale = _bounded_string(rationale, "rationale", 1200)
    if query:
        query = _bounded_string(query, "query", 280)
    scope = canonical_scope(scope)
    decision_key = canonical_decision_key(decision_key)
    _, current_rows, _ = _index(repo)
    tokens = _comparison_tokens(statement, rationale, query, scope, decision_key)

    ranked: list[tuple[int, list[str], dict[str, Any]]] = []
    mandatory_ids: set[str] = set()
    for row in current_rows:
        row_scope = row.get("scope")
        row_key = row.get("decision_key")
        score = 0
        reasons: list[str] = []
        if (row_scope, row_key) == (scope, decision_key):
            score += 100
            reasons.append("exact_slot")
            mandatory_ids.add(row["id"])
        elif row_key == decision_key and isinstance(row_scope, str) and scopes_overlap(row_scope, scope):
            score += 80
            reasons.append("scope_overlap")
            mandatory_ids.add(row["id"])
        elif row_key == decision_key:
            score += 40
            reasons.append("same_decision_key")
        elif isinstance(row_scope, str) and scopes_overlap(row_scope, scope):
            score += 20
            reasons.append("related_scope")
        haystack = normalized_key(
            " ".join(
                str(row.get(field, ""))
                for field in ("id", "title", "summary", "path", "scope", "decision_key")
            )
            + " "
            + " ".join(str(term) for term in row.get("terms", []))
        )
        hits = sorted(token for token in tokens if token in haystack)
        if hits:
            score += min(len(hits), 8)
            reasons.append("lexical:" + ",".join(hits[:4]))
        ranked.append((score, reasons, row))

    if len(mandatory_ids) > limit:
        raise DecisionError(
            "comparison_too_broad",
            "exact-slot and scope-overlap decisions exceed the check limit",
            {"required": len(mandatory_ids), "limit": limit},
            EXIT_CONFLICT,
        )
    ranked.sort(key=lambda item: (-item[0], str(item[2].get("path", "")), item[2]["id"]))
    if len(ranked) <= limit:
        selected = ranked
    else:
        selected = [item for item in ranked if item[2]["id"] in mandatory_ids]
        selected_ids = {item[2]["id"] for item in selected}
        for item in ranked:
            if len(selected) >= limit:
                break
            if item[2]["id"] in selected_ids:
                continue
            reasons = item[1] or ["bounded_sample"]
            selected.append((item[0], reasons, item[2]))
            selected_ids.add(item[2]["id"])

    proposal = {
        "statement": statement,
        "rationale": rationale or None,
        "scope": scope,
        "decision_key": decision_key,
        "query": query or None,
    }
    current: list[dict[str, Any]] = []
    for _, reasons, row in selected:
        record = _record(repo, row)
        item = {
            "id": record["id"],
            "path": record["path"],
            "sha256": record["sha256"],
            "title": record["frontmatter"]["title"],
            "summary": record["frontmatter"]["summary"],
            "scope": record["frontmatter"]["scope"],
            "decision_key": record["frontmatter"]["decision_key"],
            "sections": {name: record["sections"][name] for name in CORE_SECTIONS},
            "retrieval_reasons": reasons or ["full_current_set"],
        }
        candidate_input = {"schema": "context-decision-comparison-input/v1", "proposal": proposal, "current": [*current, item]}
        if len(canonical_json(candidate_input).encode("utf-8")) > MAX_CHECK_BYTES:
            if record["id"] in mandatory_ids:
                raise DecisionError(
                    "comparison_too_large",
                    "exact-slot or scope-overlap decision bodies exceed the check byte limit",
                    {"id": record["id"], "max_bytes": MAX_CHECK_BYTES},
                    EXIT_CONFLICT,
                )
            continue
        current.append(item)

    comparison_input = {
        "schema": "context-decision-comparison-input/v1",
        "proposal": proposal,
        "current": current,
    }
    exact = [item for item in current if (item["scope"], item["decision_key"]) == (scope, decision_key)]
    overlap = [
        item
        for item in current
        if item["decision_key"] == decision_key
        and item["scope"] != scope
        and scopes_overlap(item["scope"], scope)
    ]
    selected_ids = {item["id"] for item in current}
    omitted_count = len(current_rows) - len(current)
    omitted_id_sample = [
        row["id"] for _, _, row in ranked if row["id"] not in selected_ids
    ][:MAX_OMITTED_ID_SAMPLE]
    result = {
        "schema": "context-decision-check/v1",
        "comparison_input": comparison_input,
        "input_digest": canonical_digest(comparison_input),
        "deterministic": {
            "exact_slot": [{key: item[key] for key in ("id", "path", "sha256")} for item in exact],
            "scope_overlap": [{key: item[key] for key in ("id", "path", "sha256")} for item in overlap],
        },
        "assessment_contract": {
            "relations": list(SEMANTIC_RELATIONS),
            "required_fields": ["relation", "related_ids", "reason"],
            "actions": dict(RELATION_ACTIONS),
            "rule": "각 Current DEC의 실제 결정·취지·반려대안을 proposal과 비교한다. 문장 유사도나 hash를 의미 판정으로 사용하지 않는다.",
        },
        "retrieval": {
            "total_current": len(current_rows),
            "returned": len(current),
            "omitted": omitted_count,
            "omitted_id_sample": omitted_id_sample,
            "omitted_id_sample_truncated": omitted_count > len(omitted_id_sample),
            "full_current_set": omitted_count == 0,
            "bounded": True,
        },
        "warning": "relation=new는 조회된 Current 집합 안에서만 유효하며 전역 무충돌 증명이 아니다.",
        "physical_write": False,
    }
    result_bytes = len(canonical_json(result).encode("utf-8"))
    if result_bytes > MAX_CHECK_RESULT_BYTES:
        raise DecisionError(
            "comparison_too_large",
            "decision check result exceeds the fixed output byte limit",
            {"result_bytes": result_bytes, "max_bytes": MAX_CHECK_RESULT_BYTES},
            EXIT_CONFLICT,
        )
    return result


def conflict_candidates(
    repo: pathlib.Path,
    scope: str,
    decision_key: str,
    *,
    prior_bundles: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    scope = canonical_scope(scope)
    key = canonical_decision_key(decision_key)
    state = current_state(repo)
    for bundle in prior_bundles:
        _overlay_owner_result(state, _owner_result_from_bundle(bundle))
    exact = []
    overlaps = []
    for record in state.values():
        fm = record["frontmatter"]
        item = {"id": record["id"], "path": record["path"], "scope": fm["scope"], "decision_key": fm["decision_key"], "sha256": record["sha256"]}
        if (fm["scope"], fm["decision_key"]) == (scope, key):
            exact.append(item)
        elif fm["decision_key"] == key and scopes_overlap(fm["scope"], scope):
            overlaps.append(item)
    keyfn = lambda item: (item["path"], item["id"])
    return {"scope": scope, "decision_key": key, "exact_slot": sorted(exact, key=keyfn), "overlap": sorted(overlaps, key=keyfn)}


def revisit_decisions(repo: pathlib.Path, *, identifiers: Sequence[str] = (), due: bool = False, as_of: str | None = None) -> dict[str, Any]:
    date = datetime.date.fromisoformat(_validate_date(as_of, "as_of")) if as_of else datetime.date.today()
    wanted = set(identifiers)
    for identifier in wanted:
        require_context_id(identifier)
    _, current, _ = _index(repo)
    items = []
    for row in current:
        if wanted and row["id"] not in wanted:
            continue
        revisit_on = row.get("revisit_on")
        is_due = bool(revisit_on and datetime.date.fromisoformat(revisit_on) <= date)
        if due and not is_due:
            continue
        items.append({"id": row["id"], "path": row["path"], "title": row["title"], "revisit_on": revisit_on, "due": is_due, "proposal": "review_only"})
    return {"as_of": date.isoformat(), "items": items, "returned": len(items), "state_changed": False}


def validate_plan_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    owner_result = _owner_result_from_bundle(bundle)
    plan = bundle["approval_material"]["plan"]
    if plan.get("owner_descriptor", {}).get("kind") != "decision" or plan.get("capability_digest") != canonical_digest(decision_capability()):
        raise DecisionError("plan_invalid", "final plan owner descriptor/capability is invalid", exit_code=EXIT_CONFLICT)
    allowed_areas = {"decision", "observation"} if owner_result["transition"] == "decision_fallback_import" else {"decision"}
    if any(operation.get("role") == "artifact" and operation.get("area") not in allowed_areas for operation in plan.get("operations", [])):
        raise DecisionError("plan_invalid", "decision owner plan escapes its area", exit_code=EXIT_CONFLICT)
    validation = plan.get("owner_validation")
    if not isinstance(validation, dict) or validation.get("owner_result_digest") != canonical_digest(owner_result):
        raise DecisionError("owner_validation_required", "decision final plan requires an exact validation receipt", exit_code=EXIT_CONFLICT)
    expected = dict(validation)
    digest = expected.pop("receipt_digest", None)
    if digest != canonical_digest(expected) or validation.get("status") != "valid":
        raise DecisionError("owner_validation_invalid", "decision validation receipt digest/status is invalid", exit_code=EXIT_CONFLICT)
    return {"schema": "context-decision-plan-validation/v1", "status": "valid", "owner_result_digest": canonical_digest(owner_result), "approval_digest": bundle["approval_digest"], "physical_write": False}


def _load_json_argument(value: str, *, allow_stdin: bool = False) -> Any:
    if value == "@-":
        if not allow_stdin:
            raise DecisionError("usage_invalid", "stdin is not allowed for this argument")
        text = sys.stdin.read()
    elif value.startswith("@"):
        try:
            text = pathlib.Path(value[1:]).read_text(encoding="utf-8")
        except OSError as error:
            raise DecisionError("input_unavailable", "JSON input could not be read", {"path": value[1:]}) from error
    else:
        raise DecisionError("usage_invalid", "JSON input must use @file or @-")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise DecisionError("schema_invalid", "input is not valid JSON") from error


def _doctor_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and "ok" in value:
        if value.get("ok") is not True or not isinstance(value.get("result"), dict):
            raise DecisionError("doctor_receipt_invalid", "core doctor command receipt did not succeed", exit_code=EXIT_CONFLICT)
        value = value["result"]
    if not isinstance(value, dict):
        raise DecisionError("doctor_receipt_invalid", "core doctor receipt must be an object", exit_code=EXIT_CONFLICT)
    if not {"supported_protocols", "repository_state", "issues"}.issubset(value):
        raise DecisionError("doctor_receipt_invalid", "core doctor receipt is incomplete", exit_code=EXIT_CONFLICT)
    if "schema" in value and value.get("schema") != "context-core-doctor/v1":
        raise DecisionError("doctor_receipt_invalid", "core doctor receipt schema is incompatible", exit_code=EXIT_CONFLICT)
    if "owner" in value and value.get("owner") != "context-core":
        raise DecisionError("doctor_receipt_invalid", "core doctor receipt owner is invalid", exit_code=EXIT_CONFLICT)
    return value


def _observed_plugin(plugin: Any, doctor: dict[str, Any]) -> dict[str, Any]:
    protocols = plugin.get("protocols", []) if isinstance(plugin, dict) else []
    doctor_protocols = doctor.get("supported_protocols", [])
    if PROTOCOL in protocols and PROTOCOL in doctor_protocols:
        protocol = PROTOCOL
    elif isinstance(protocols, list) and protocols:
        protocol = protocols[0]
    elif isinstance(doctor_protocols, list) and doctor_protocols:
        protocol = doctor_protocols[0]
    else:
        protocol = None
    observed = {
        "marketplace": plugin.get("marketplace") if isinstance(plugin, dict) else None,
        "plugin": plugin.get("plugin") if isinstance(plugin, dict) else None,
        "source": plugin.get("source") if isinstance(plugin, dict) else None,
        "enabled": plugin.get("enabled") if isinstance(plugin, dict) else None,
        "protocol": protocol,
        "repository_state": doctor.get("repository_state"),
    }
    if tuple(observed) != OBSERVED_PLUGIN_FIELDS:
        raise AssertionError("preflight observed projection drift")
    return observed


def classify_core_preflight(inventory: Any, doctor_receipt: Any) -> dict[str, Any]:
    if not isinstance(inventory, dict) or not isinstance(inventory.get("plugins"), list):
        raise DecisionError("host_inventory_invalid", "host plugin inventory must contain a plugins array", exit_code=EXIT_CONFLICT)
    doctor = _doctor_result(doctor_receipt)
    plugins = inventory["plugins"]
    exact = [
        plugin for plugin in plugins
        if isinstance(plugin, dict)
        and plugin.get("marketplace") == REQUIRED_PLUGIN["marketplace"]
        and plugin.get("plugin") == REQUIRED_PLUGIN["plugin"]
    ]
    same_name = [plugin for plugin in plugins if isinstance(plugin, dict) and plugin.get("plugin") == REQUIRED_PLUGIN["plugin"]]
    if len(exact) > 1:
        raise DecisionError("host_inventory_invalid", "exact context-core coordinate is ambiguous", exit_code=EXIT_CONFLICT)
    if not exact:
        observed_plugin = same_name[0] if len(same_name) == 1 else None
        code = "core_source_mismatch" if observed_plugin is not None else "core_missing"
        return {"code": code, "observed": _observed_plugin(observed_plugin, doctor)}
    plugin = exact[0]
    observed = _observed_plugin(plugin, doctor)
    if plugin.get("source") != REQUIRED_PLUGIN["source"]:
        return {"code": "core_source_mismatch", "observed": observed}
    if plugin.get("enabled") is not True:
        return {"code": "core_disabled", "observed": observed}
    plugin_protocols = plugin.get("protocols")
    doctor_protocols = doctor.get("supported_protocols")
    if (
        not isinstance(plugin_protocols, list)
        or not isinstance(doctor_protocols, list)
        or PROTOCOL not in plugin_protocols
        or PROTOCOL not in doctor_protocols
    ):
        return {"code": "core_incompatible", "observed": observed}
    repository_state = doctor.get("repository_state")
    if repository_state == "absent":
        return {"code": "core_uninitialized", "observed": observed}
    if repository_state in {"partial", "invalid"}:
        return {"code": "partial_core_init", "observed": observed}
    if repository_state != "ready":
        raise DecisionError("doctor_receipt_invalid", "core doctor repository_state is invalid", exit_code=EXIT_CONFLICT)
    return {"code": "ready", "observed": observed}


def _manual_actions(code: str) -> list[str]:
    selector = REQUIRED_PLUGIN["selector"]
    marketplace = REQUIRED_PLUGIN["marketplace"]
    source = REQUIRED_PLUGIN["source"]
    retry = "host reload 또는 새 session 뒤 context-decision:init을 다시 실행한다."
    return {
        "core_missing": [
            f"provider marketplace {marketplace} (source {source})에서 {selector}를 사용자가 직접 설치한다.",
            "설치 scope는 사용자가 직접 선택한다.",
            retry,
        ],
        "core_source_mismatch": [
            f"source {source}의 exact {selector} 좌표를 사용자가 직접 설치한다.",
            "다른 marketplace의 동명 plugin은 충족으로 간주하지 않는다.",
            retry,
        ],
        "core_disabled": [
            f"exact {selector}를 사용자가 선택한 올바른 scope에서 직접 활성화한다.",
            retry,
        ],
        "core_incompatible": [
            f"exact {selector}를 {PROTOCOL} 호환 버전으로 사용자가 직접 업데이트한다.",
            retry,
        ],
        "core_uninitialized": [
            "context-decision:init이 installed context-core public bootstrap surface를 호출한다.",
            "같은 명시적 호출에서 core init 뒤 decision area 등록을 계속한다.",
        ],
        "partial_core_init": [
            "context-core doctor의 issue/path를 확인한다.",
            "context-core의 승인된 repair 절차로 수동 복구한다.",
            "repository_state=ready 확인 뒤 context-decision:init을 다시 실행한다.",
        ],
        "ready": [],
    }[code]


def render_core_preflight(result: dict[str, Any], host: str) -> dict[str, Any]:
    code = result.get("code")
    if host not in {"codex", "claude-code"} or code not in PREFLIGHT_MESSAGES or not isinstance(result.get("observed"), dict):
        raise DecisionError("core_preflight_invalid", "core preflight result or host is invalid", exit_code=EXIT_CONFLICT)
    return {
        "code": code,
        "host": host,
        "message": PREFLIGHT_MESSAGES[code],
        "required_plugin": dict(REQUIRED_PLUGIN),
        "observed": dict(result["observed"]),
        "manual_actions": _manual_actions(code),
        "write_policy": {"repository": "none", "host_configuration": "none"},
    }


def require_core_preflight(args: argparse.Namespace, *, allow_absent: bool = False) -> dict[str, Any]:
    host = getattr(args, "host", None)
    inventory_argument = getattr(args, "core_inventory", None)
    doctor_argument = getattr(args, "core_doctor", None)
    if host is None or inventory_argument is None or doctor_argument is None:
        raise DecisionError(
            "core_preflight_required",
            "non-static context-decision operations require host inventory and core doctor receipt",
            {"required_plugin": dict(REQUIRED_PLUGIN), "write_policy": {"repository": "none", "host_configuration": "none"}},
            EXIT_CONFLICT,
        )
    result = classify_core_preflight(_load_json_argument(inventory_argument), _load_json_argument(doctor_argument))
    rendered = render_core_preflight(result, host)
    if rendered["code"] != "ready" and not (allow_absent and rendered["code"] == "core_uninitialized"):
        details = {key: value for key, value in rendered.items() if key not in {"code", "message"}}
        raise DecisionError(rendered["code"], rendered["message"], details, EXIT_CONFLICT)
    return rendered


def _direct_candidate(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {
        "decision": args.sec_decision,
        "rationale": args.sec_rationale,
        "rejected_alternatives": args.sec_alternatives,
        "decision_key": args.decision_key,
    }
    for key, argument in (("constraints", args.sec_constraints), ("tradeoffs", args.sec_tradeoffs), ("revisit_when", args.sec_revisit)):
        if argument:
            values[key] = argument
    if args.revisit_on:
        values["revisit_on"] = args.revisit_on
    candidate = {
        "schema": "context-capture-candidate/v1", "candidate_id": args.candidate_id, "claim_key": "direct",
        "title": args.title, "claim": args.sec_decision, "summary": args.summary, "captured_from": args.captured_from,
        "requested_kind": "decision", "specialized_kinds": ["decision"], "fallback_kind": None,
        "scope_hint": args.scope, "source_refs": args.source_ref, "tags": args.tag, "evidence": args.commitment_evidence,
        "owner_inputs": {"decision": values},
    }
    if args.informed_by:
        candidate["informed_by"] = args.informed_by
    validate_candidate(candidate)
    return candidate


def _add_capture_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--decision-key", required=True)
    parser.add_argument("--captured-from", choices=("conversation", "workspace", "manual", "import"), required=True)
    parser.add_argument("--commitment-evidence", action="append", required=True)
    parser.add_argument("--sec-decision", required=True)
    parser.add_argument("--sec-rationale", required=True)
    parser.add_argument("--sec-alternatives", action="append", required=True)
    parser.add_argument("--sec-constraints", action="append", default=[])
    parser.add_argument("--sec-tradeoffs", action="append", default=[])
    parser.add_argument("--sec-revisit", action="append", default=[])
    parser.add_argument("--revisit-on")
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--informed-by", action="append", default=[])


def _add_preflight_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", choices=("codex", "claude-code"))
    parser.add_argument("--core-inventory")
    parser.add_argument("--core-doctor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decision_cli.py")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--json", action="store_true")
    for name in ("schema", "capabilities"):
        static = sub.add_parser(name)
        static.add_argument("--json", action="store_true")
    candidate = sub.add_parser("candidate")
    candidate_sub = candidate.add_subparsers(dest="candidate_command", required=True)
    prepare = candidate_sub.add_parser("prepare")
    _add_capture_arguments(prepare)
    prepare.add_argument("--json", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("--statement", required=True)
    check.add_argument("--scope", required=True)
    check.add_argument("--decision-key", required=True)
    check.add_argument("--rationale", default="")
    check.add_argument("--query", default="")
    check.add_argument("--limit", type=int, default=8)
    check.add_argument("--json", action="store_true")
    draft = sub.add_parser("draft")
    draft.add_argument("--candidate", required=True)
    draft.add_argument("--attestation", required=True)
    draft.add_argument("--json", action="store_true")
    capture = sub.add_parser("capture")
    capture.add_argument("--candidate", required=True)
    outcome = capture.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--attestation")
    outcome.add_argument("--decline-reason")
    outcome.add_argument("--needs-clarification-reason")
    capture.add_argument("--ack-conflicts", action="append", default=[])
    capture.add_argument("--json", action="store_true")
    search = sub.add_parser("search")
    search.add_argument("--query", default="")
    search.add_argument("--scope")
    search.add_argument("--decision-key")
    search.add_argument("--include-history", action="store_true")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true")
    read = sub.add_parser("read")
    read.add_argument("--id", required=True)
    read.add_argument("--section", action="append", default=[])
    read.add_argument("--max-bytes", type=int, default=MAX_BRIEF_BYTES)
    read.add_argument("--json", action="store_true")
    brief = sub.add_parser("brief")
    group = brief.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--id", action="append")
    brief.add_argument("--include-history", action="store_true")
    brief.add_argument("--max-bytes", type=int, default=MAX_BRIEF_BYTES)
    brief.add_argument("--json", action="store_true")
    conflicts = sub.add_parser("conflicts")
    conflicts.add_argument("--scope", required=True)
    conflicts.add_argument("--decision-key", required=True)
    conflicts.add_argument("--json", action="store_true")
    supersede = sub.add_parser("supersede")
    supersede.add_argument("--id", required=True)
    supersede.add_argument("--successor-candidate", required=True)
    supersede.add_argument("--attestation", required=True)
    supersede.add_argument("--ack-conflicts", action="append", default=[])
    supersede.add_argument("--json", action="store_true")
    fallback = sub.add_parser("import-fallback")
    fallback.add_argument("--id", required=True)
    fallback.add_argument("--successor-result", required=True)
    fallback.add_argument("--lifecycle-input", required=True)
    fallback.add_argument("--attestation", required=True)
    fallback.add_argument("--ack-conflicts", action="append", default=[])
    fallback.add_argument("--json", action="store_true")
    withdraw = sub.add_parser("withdraw")
    withdraw.add_argument("--id", required=True)
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--json", action="store_true")
    annotate = sub.add_parser("annotate")
    annotate.add_argument("--id", required=True)
    annotate.add_argument("--title")
    annotate.add_argument("--summary")
    annotate.add_argument("--tag", action="append")
    annotate.add_argument("--search-term", action="append")
    annotate.add_argument("--source-ref", action="append")
    annotate.add_argument("--json", action="store_true")
    revisit = sub.add_parser("revisit")
    revisit.add_argument("--due", action="store_true")
    revisit.add_argument("--id", action="append", default=[])
    revisit.add_argument("--as-of")
    revisit.add_argument("--json", action="store_true")
    batch = sub.add_parser("batch")
    batch_sub = batch.add_subparsers(dest="batch_command", required=True)
    validate = batch_sub.add_parser("validate")
    validate.add_argument("--owner-result", required=True)
    validate.add_argument("--prior-bundle", action="append", default=[])
    validate.add_argument("--json", action="store_true")
    plan = sub.add_parser("plan")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_validate = plan_sub.add_parser("validate")
    plan_validate.add_argument("--plan-bundle", required=True)
    plan_validate.add_argument("--json", action="store_true")
    for operational in (
        init, prepare, check, draft, capture, search, read, brief, conflicts, supersede,
        fallback, withdraw, annotate, revisit, validate, plan_validate,
    ):
        _add_preflight_arguments(operational)
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "schema":
        return schema_result()
    if args.command == "capabilities":
        return {"schema": "context-owner-capabilities/v1", "owners": [decision_capability()]}
    preflight = require_core_preflight(args, allow_absent=args.command == "init")
    if args.command == "init":
        return build_init_plan(preflight)
    if args.command == "candidate" and args.candidate_command == "prepare":
        return _direct_candidate(args)
    if args.command == "draft":
        candidate = _load_json_argument(args.candidate, allow_stdin=True)
        return build_claim_result(candidate, _load_json_argument(args.attestation))
    repo = repository_root()
    if args.command == "check":
        return prepare_decision_check(
            repo,
            statement=args.statement,
            scope=args.scope,
            decision_key=args.decision_key,
            rationale=args.rationale,
            query=args.query,
            limit=args.limit,
        )
    if args.command == "capture":
        candidate = _load_json_argument(args.candidate, allow_stdin=True)
        if args.decline_reason is not None:
            return build_decline_result(candidate, args.decline_reason)
        if args.needs_clarification_reason is not None:
            return build_decline_result(candidate, args.needs_clarification_reason, needs_clarification=True)
        return build_claim_result(candidate, _load_json_argument(args.attestation), acknowledged_conflicts=args.ack_conflicts, repo=repo)
    if args.command == "search":
        return search_decisions(repo, query=args.query, scope=args.scope, decision_key=args.decision_key, include_history=args.include_history, limit=args.limit)
    if args.command == "read":
        return read_decision(repo, args.id, sections=args.section, max_bytes=args.max_bytes)
    if args.command == "brief":
        return brief_decisions(repo, query=args.query, identifiers=args.id or (), include_history=args.include_history, max_bytes=args.max_bytes)
    if args.command == "conflicts":
        return conflict_candidates(repo, args.scope, args.decision_key)
    if args.command == "supersede":
        return build_supersede_result(repo, args.id, _load_json_argument(args.successor_candidate, allow_stdin=True), _load_json_argument(args.attestation), acknowledged_conflicts=args.ack_conflicts)
    if args.command == "import-fallback":
        return build_fallback_import_result(
            repo,
            args.id,
            _load_json_argument(args.successor_result, allow_stdin=True),
            _load_json_argument(args.lifecycle_input),
            _load_json_argument(args.attestation),
            acknowledged_conflicts=args.ack_conflicts,
        )
    if args.command == "withdraw":
        return build_withdraw_result(repo, args.id, args.reason)
    if args.command == "annotate":
        return build_annotate_result(repo, args.id, title=args.title, summary=args.summary, tags=args.tag, search_terms=args.search_term, source_refs=args.source_ref)
    if args.command == "revisit":
        return revisit_decisions(repo, identifiers=args.id, due=args.due, as_of=args.as_of)
    if args.command == "batch" and args.batch_command == "validate":
        return validate_batch(repo, _load_json_argument(args.owner_result, allow_stdin=True), [_load_json_argument(value) for value in args.prior_bundle])
    if args.command == "plan" and args.plan_command == "validate":
        return validate_plan_bundle(_load_json_argument(args.plan_bundle, allow_stdin=True))
    raise DecisionError("usage_invalid", "unsupported command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = dispatch(args)
        envelope = {"ok": True, "result": result}
        print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) if getattr(args, "json", False) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except DecisionError as error:
        print(json.dumps(error.envelope(), ensure_ascii=False, separators=(",", ":")))
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
