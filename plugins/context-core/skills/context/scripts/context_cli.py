#!/usr/bin/env python3
"""context-core v1 storage/index/coordinator kernel (Python 3.11+, stdlib only)."""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from typing import Any, Iterable, Iterator, Sequence


EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_AMBIGUOUS = 4
EXIT_CONFLICT = 5
EXIT_INTEGRITY = 6
PROTOCOL = "context-common/v1"
MAX_STAGE1_BYTES = 4 * 1024
MAX_SECTION_ITEM_BYTES = 2 * 1024
MAX_RECALL_BATCH_BYTES = 8 * 1024
MAX_USER_BYTES = 32 * 1024
MAX_CANDIDATE_BYTES = 16 * 1024
MAX_OWNER_INPUT_BYTES = 2 * 1024
MAX_APPROVAL_PREVIEW_BYTES = 32 * 1024
ROOT_INDEX = "context/context.index.md"
BUILTIN_AREAS = ("snapshot", "observation")
RESERVED_INDEX_PATHS = {
    ROOT_INDEX,
    "context/snapshot/snapshot.index.md",
    "context/observation/observation.index.md",
    "context/decision/decision.index.md",
}
INDEX_FIXABLE_CODES = {
    "index_content_drift",
    "index_duplicate_entry",
    "index_ghost_entry",
    "index_missing_entry",
    "index_wrong_state",
}
OWNER_RESULT_FIELDS = {
    "schema", "result_type", "transition", "owner", "target_kind", "candidate_id", "decision", "reason",
    "capability_digest", "semantic_inputs", "semantic_attestations", "artifact_drafts", "effects", "proposed_plan",
}
COMMON_KEY_ORDER = (
    "schema", "id", "title", "summary", "created_at", "updated_at", "captured_from", "source_refs", "tags",
    "search_terms", "claim_fingerprint",
)
ADDITIVE_KEY_ORDER = {
    "context-snapshot/v1": ("anchors",),
    "context-observation/v1": (
        "kind_hint", "source_claim_fingerprint", "verified_at", "affects_paths", "relations", "supersedes",
        "superseded_by", "retired_at", "retired_reason", "retirement_note",
    ),
    "context-decision/v1": (
        "scope", "decision_key", "revisit_when", "revisit_on", "relations", "supersedes", "superseded_by",
        "retired_at", "retired_reason", "retirement_note",
    ),
}
SECTION_SPECS = {
    "context-snapshot/v1": (("현재 맥락", "열린 항목", "다음 단계", "정해진 것", "참조", "capture 후보"), ("현재 맥락", "열린 항목", "다음 단계")),
    "context-observation/v1": (("관찰", "근거", "영향", "현재 처리", "후속 조건"), ("관찰", "근거")),
    "context-decision/v1": (("결정", "취지", "반려대안", "근거와 제약", "트레이드오프", "재평가 조건"), ("결정", "취지", "반려대안")),
}
PLACEHOLDERS = {"...", "TODO", "TBD", "해당 없음"}
FILENAME_FORBIDDEN = set('/\\<>:"|?*[]#^')
WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
LOCAL_ID = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
AREA_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
ROOT_ROW = re.compile(r"^.*<!-- context-area (\{.*\}) -->$")
ENTRY_ROW = re.compile(r"^.*<!-- context-entry (\{.*\}) -->$")
POLICY_BEGIN = "<!-- BEGIN context-core-policy (managed by context-core) -->"
POLICY_END = "<!-- END context-core-policy (managed by context-core) -->"
POLICY_BODY = """<!-- BEGIN context-core-policy (managed by context-core) -->
## Shared context policy

- Substantive work에서 이전 결정·관찰·handoff가 판단을 바꿀 수 있으면 scoped index-first recall을 한 번 수행한다.
- Primary 요청과 답변을 먼저 끝낸다. semantic milestone 또는 closeout당 durable candidate audit은 최대 한 번만 수행한다.
- Candidate가 있을 때만 complete artifact preview를 한 grouped proposal로 보여준다. 승인 전에는 context artifact나 index를 쓰지 않는다.
- Current DEC는 authoritative, OBS는 non-authoritative evidence, SNAP은 resume staging으로 취급한다.
<!-- END context-core-policy (managed by context-core) -->"""
POLICY_TARGETS = {"AGENTS.md", "CLAUDE.md"}


class ContextError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None, exit_code: int = EXIT_USAGE):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code

    def envelope(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


@dataclasses.dataclass(frozen=True)
class Document:
    frontmatter: dict[str, Any]
    sections: dict[str, str]


@dataclasses.dataclass(frozen=True)
class AreaIndex:
    frontmatter: dict[str, Any]
    current: list[dict[str, Any]]
    history: list[dict[str, Any]]
    text: str


@dataclasses.dataclass
class IOMetrics:
    index_opens: int = 0
    index_read_bytes: int = 0
    artifact_opens: int = 0
    artifact_read_bytes: int = 0
    artifact_directory_lists: int = 0
    artifact_stats: int = 0
    output_bytes: int = 0


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def normalized_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _canonical_slot_part(value: str, *, maximum: int) -> str:
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
    return result if result and len(result) <= maximum else ""


def _canonical_decision_scope(value: str) -> str:
    if not isinstance(value, str):
        return ""
    stripped = normalized_key(value.strip()).strip("/")
    if not stripped or "//" in stripped:
        return ""
    parts = stripped.split("/")
    if len(parts) > 8:
        return ""
    canonical = [_canonical_slot_part(part, maximum=40) for part in parts]
    result = "/".join(canonical)
    return result if all(canonical) and len(result) <= 160 else ""


def _canonical_decision_key(value: str) -> str:
    if not isinstance(value, str) or "/" in value:
        return ""
    return _canonical_slot_part(value, maximum=80)


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return nfc(value)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= (2**53 - 1):
        return value
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise ContextError("canonical_json_invalid", "object keys must be strings")
            key = nfc(raw_key)
            if key in normalized:
                raise ContextError("canonical_json_invalid", "NFC-normalized object keys collide", {"key": key})
            normalized[key] = _canonical_value(raw_value)
        return {key: normalized[key] for key in sorted(normalized)}
    raise ContextError("canonical_json_invalid", "unsupported canonical JSON scalar", {"type": type(value).__name__})


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical_value(value), ensure_ascii=False, separators=(",", ":"))


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def file_bytes(content: str) -> bytes:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return normalized.encode("utf-8")


def new_context_id() -> str:
    return "ctx_" + uuid.uuid4().hex


def new_plan_id() -> str:
    return "plan_" + uuid.uuid4().hex


def is_context_id(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"ctx_[0-9a-f]{32}", value):
        return False
    parsed = uuid.UUID(hex=value[4:])
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def _require_context_id(value: Any, field: str = "id") -> str:
    if not is_context_id(value):
        raise ContextError("id_invalid", f"{field} must be ctx_ plus lowercase UUIDv4 hex", {"field": field})
    return value


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
        raise ContextError("filename_required", "title cannot produce a safe filename")
    return validate_filename(stem + ".md")


def validate_filename(value: str) -> str:
    if not isinstance(value, str):
        raise ContextError("filename_invalid", "filename must be a string")
    value = nfc(value)
    if value.endswith(".md"):
        basename = value
    elif "." not in pathlib.PurePosixPath(value).name:
        basename = value + ".md"
    else:
        raise ContextError("filename_invalid", "filename extension must be .md", {"filename": value})
    stem = basename[:-3]
    folded = normalized_key(basename)
    folded_stem = normalized_key(stem)
    if not stem or stem in {".", ".."} or basename.endswith((" ", ".")):
        raise ContextError("filename_invalid", "filename has an invalid stem", {"filename": value})
    if any(char in FILENAME_FORBIDDEN or ord(char) < 32 or ord(char) == 127 for char in basename):
        raise ContextError("filename_invalid", "filename contains a forbidden character", {"filename": value})
    if "<!--" in folded or "-->" in folded or folded.endswith(".index.md"):
        raise ContextError("reserved_path", "artifact filename is reserved", {"filename": value}, EXIT_CONFLICT)
    if WINDOWS_RESERVED.fullmatch(folded_stem):
        raise ContextError("filename_invalid", "filename is reserved by supported filesystems", {"filename": value})
    if len(basename) > 120 or len(basename.encode("utf-8")) > 240:
        raise ContextError("filename_required", "filename exceeds the v1 limit", {"filename": value})
    return basename


def _ensure_contained(repo: pathlib.Path, relative: str) -> pathlib.Path:
    pure = pathlib.PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ContextError("path_escape", "path must be a canonical repository-relative POSIX path", {"path": relative}, EXIT_CONFLICT)
    candidate = repo.joinpath(*pure.parts)
    repo_real = repo.resolve()
    current = repo_real
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ContextError("symlink_path", "symlink path segments are not writable", {"path": relative}, EXIT_CONFLICT)
    try:
        candidate.resolve(strict=False).relative_to(repo_real)
    except ValueError as error:
        raise ContextError("path_escape", "path escapes repository root", {"path": relative}, EXIT_CONFLICT) from error
    return candidate


def resolve_artifact_path(repo: pathlib.Path, area: str, filename: str, *, existing_path: str | None = None) -> pathlib.Path:
    if not AREA_NAME.fullmatch(area):
        raise ContextError("area_invalid", "invalid area name")
    basename = validate_filename(filename)
    relative = f"context/{area}/{basename}"
    candidate = _ensure_contained(repo, relative)
    area_root = _ensure_contained(repo, f"context/{area}")
    if area_root.exists():
        key = normalized_key(basename)
        with os.scandir(area_root) as entries:
            for entry in entries:
                if entry.name == "retired" or (existing_path and f"context/{area}/{entry.name}" == existing_path):
                    continue
                if normalized_key(entry.name) == key:
                    raise ContextError("path_exists", "a collision-equivalent path already exists", {"path": relative}, EXIT_CONFLICT)
    return candidate


def claim_fingerprint(kind: str, scope: str, claim: str) -> str:
    raw = f"{kind}\n{scope}\n{claim}"
    normalized = " ".join(unicodedata.normalize("NFKC", raw).casefold().split())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _newline_normalized(text: str) -> str:
    if text.startswith("\ufeff"):
        raise ContextError("frontmatter_unsupported", "UTF-8 BOM is not supported")
    has_crlf = "\r\n" in text
    without_crlf = text.replace("\r\n", "")
    if "\r" in without_crlf or (has_crlf and "\n" in without_crlf):
        raise ContextError("frontmatter_unsupported", "mixed or bare-CR newlines are not supported")
    return text.replace("\r\n", "\n")


def _valid_yaml_value(value: Any, *, object_value: bool = False) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, list):
        return all(isinstance(item, str) for item in value)
    if isinstance(value, dict) and not object_value:
        return all(isinstance(key, str) and _valid_yaml_value(item, object_value=True) for key, item in value.items())
    return False


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], list[str], int]:
    text = _newline_normalized(text)
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise ContextError("frontmatter_unsupported", "the first line must be exactly ---")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ContextError("frontmatter_unsupported", "closing frontmatter delimiter is missing") from error
    frontmatter: dict[str, Any] = {}
    for line in lines[1:closing]:
        if not line or line.lstrip().startswith("#"):
            raise ContextError("frontmatter_unsupported", "blank lines and comments are forbidden in frontmatter")
        if ": " not in line:
            raise ContextError("frontmatter_unsupported", "frontmatter fields must be KEY: JSON_VALUE")
        key, raw = line.split(": ", 1)
        if not FIELD_KEY.fullmatch(key) or key in frontmatter:
            raise ContextError("frontmatter_unsupported", "invalid or duplicate frontmatter key", {"key": key})
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ContextError("frontmatter_unsupported", "frontmatter values must be compact JSON", {"key": key}) from error
        if compact_json(value) != raw or not _valid_yaml_value(value):
            raise ContextError("frontmatter_unsupported", "frontmatter value is outside the JSON-compatible subset", {"key": key})
        frontmatter[key] = value
    if closing + 1 >= len(lines) or lines[closing + 1] != "":
        raise ContextError("frontmatter_unsupported", "frontmatter must be followed by one blank line")
    return frontmatter, lines, closing


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ContextError("schema_invalid", f"{field} must be a timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        raise ContextError("schema_invalid", f"{field} must be RFC3339-compatible") from error
    if parsed.tzinfo is None or parsed.isoformat(timespec="seconds") != value:
        raise ContextError("schema_invalid", f"{field} must include an offset and seconds precision")


def _timestamp(value: str | None = None) -> str:
    resolved = value or datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    _validate_timestamp(resolved, "timestamp")
    return resolved


def _substantive(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() not in PLACEHOLDERS


def _string_list(value: Any, field: str, *, required: bool = False, maximum: int = 12, item_maximum: int = 500) -> list[str]:
    if not isinstance(value, list) or any(not _substantive(item) or "\n" in item or len(item) > item_maximum for item in value):
        raise ContextError("schema_invalid", f"{field} must be a substantive string list")
    if (required and not value) or len(value) > maximum:
        raise ContextError("schema_invalid", f"{field} has an invalid item count")
    return [nfc(item.strip()) for item in value]


def _validate_common_document(frontmatter: dict[str, Any]) -> None:
    required = ("schema", "id", "title", "summary", "created_at", "captured_from")
    missing = [key for key in required if key not in frontmatter]
    if missing:
        raise ContextError("schema_invalid", "required frontmatter field is missing", {"missing": missing})
    schema = frontmatter["schema"]
    if schema not in SECTION_SPECS:
        raise ContextError("schema_invalid", "unsupported artifact schema", {"schema": schema})
    _require_context_id(frontmatter["id"])
    for field, maximum in (("title", 120), ("summary", 280)):
        value = frontmatter[field]
        if not isinstance(value, str) or not value.strip() or "\n" in value or len(value) > maximum:
            raise ContextError("schema_invalid", f"{field} is invalid")
    if frontmatter["captured_from"] not in {"conversation", "workspace", "manual", "import"}:
        raise ContextError("schema_invalid", "captured_from is invalid")
    _validate_timestamp(frontmatter["created_at"], "created_at")
    for field in ("updated_at", "verified_at", "retired_at"):
        if field in frontmatter:
            _validate_timestamp(frontmatter[field], field)
    created = datetime.datetime.fromisoformat(frontmatter["created_at"])
    for field in ("updated_at", "verified_at", "retired_at"):
        if field in frontmatter and datetime.datetime.fromisoformat(frontmatter[field]) < created:
            raise ContextError("clock_invalid", f"{field} cannot precede created_at", exit_code=EXIT_CONFLICT)
    for field, maximum, item_maximum in (("tags", 12, 40), ("search_terms", 12, 40), ("source_refs", 12, 500)):
        if field in frontmatter:
            _string_list(frontmatter[field], field, maximum=maximum, item_maximum=item_maximum)
    if schema == "context-snapshot/v1":
        if "anchors" in frontmatter:
            anchors = _string_list(frontmatter["anchors"], "anchors", maximum=12, item_maximum=36)
            for identifier in anchors:
                _require_context_id(identifier, "anchors")
        forbidden = {"verified_at", "retired_at", "retired_reason", "retirement_note", "supersedes", "superseded_by"}
        if forbidden & set(frontmatter):
            raise ContextError("lifecycle_invalid", "snapshot cannot carry history or verification fields")
    if schema == "context-observation/v1":
        if frontmatter.get("kind_hint") not in {None, "decision"}:
            raise ContextError("schema_invalid", "observation kind_hint is invalid")
        fingerprint = frontmatter.get("claim_fingerprint")
        if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{24}", fingerprint)):
            raise ContextError("schema_invalid", "observation claim_fingerprint is invalid")
        if frontmatter.get("retired_reason") not in {None, "invalidated", "superseded"}:
            raise ContextError("lifecycle_invalid", "observation retired_reason is invalid")
        if frontmatter.get("retired_reason") == "invalidated" and not _substantive(frontmatter.get("retirement_note")):
            raise ContextError("lifecycle_invalid", "invalidated observation requires retirement_note")
        if frontmatter.get("retired_reason") == "invalidated" and "superseded_by" in frontmatter:
            raise ContextError("lifecycle_invalid", "invalidated observation cannot name a successor")
        if frontmatter.get("retired_reason") == "superseded":
            _require_context_id(frontmatter.get("superseded_by"), "superseded_by")
        if frontmatter.get("retired_reason") is None and any(key in frontmatter for key in ("superseded_by", "retirement_note")):
            raise ContextError("lifecycle_invalid", "observation lifecycle fields require retired_reason")
        if "supersedes" in frontmatter:
            for identifier in _string_list(frontmatter["supersedes"], "supersedes", maximum=12, item_maximum=36):
                _require_context_id(identifier, "supersedes")
    if schema == "context-decision/v1":
        for field in ("scope", "decision_key"):
            if not _substantive(frontmatter.get(field)) or "\n" in frontmatter[field]:
                raise ContextError("schema_invalid", f"decision {field} is invalid")
        if (
            frontmatter["scope"] != _canonical_decision_scope(frontmatter["scope"])
            or frontmatter["decision_key"] != _canonical_decision_key(frontmatter["decision_key"])
        ):
            raise ContextError("schema_invalid", "decision slot fields must already be canonical")
        fingerprint = frontmatter.get("claim_fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{24}", fingerprint):
            raise ContextError("schema_invalid", "decision claim_fingerprint is invalid")
        if "supersedes" in frontmatter:
            for identifier in _string_list(frontmatter["supersedes"], "supersedes", maximum=12, item_maximum=36):
                _require_context_id(identifier, "supersedes")


def parse_document(text: str) -> Document:
    frontmatter, lines, closing = _parse_frontmatter(text)
    _validate_common_document(frontmatter)
    schema = frontmatter["schema"]
    allowed, required = SECTION_SPECS[schema]
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    in_fence: str | None = None
    for line in lines[closing + 2 :]:
        fence_match = re.match(r"^\s*(```+|~~~+)", line)
        if fence_match:
            marker = fence_match.group(1)[0]
            in_fence = None if in_fence == marker else (marker if in_fence is None else in_fence)
        heading = re.fullmatch(r"## (.+)", line) if in_fence is None else None
        if heading:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            name = heading.group(1)
            if name not in allowed or name in sections or (current and allowed.index(name) <= allowed.index(current)):
                raise ContextError("section_schema_error", "unknown, duplicate, or out-of-order H2 section", {"section": name})
            current = name
            buffer = []
        else:
            if current is None and line.strip():
                raise ContextError("section_schema_error", "content before the first section is forbidden")
            if current is not None:
                buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    for name in required:
        content = sections.get(name, "").strip()
        if not content or content in PLACEHOLDERS:
            raise ContextError("section_schema_error", "required section is missing or placeholder", {"section": name})
    return Document(frontmatter=frontmatter, sections=sections)


def render_document(frontmatter: dict[str, Any], sections: dict[str, str]) -> str:
    _validate_common_document(frontmatter)
    schema = frontmatter["schema"]
    allowed, required = SECTION_SPECS[schema]
    unknown = set(sections) - set(allowed)
    if unknown:
        raise ContextError("section_schema_error", "unknown sections cannot be rendered", {"sections": sorted(unknown)})
    for name in required:
        if not sections.get(name, "").strip() or sections[name].strip() in PLACEHOLDERS:
            raise ContextError("section_schema_error", "required section is missing or placeholder", {"section": name})
    known = COMMON_KEY_ORDER + ADDITIVE_KEY_ORDER.get(schema, ())
    ordered = [key for key in known if key in frontmatter]
    ordered.extend(sorted(set(frontmatter) - set(ordered)))
    lines = ["---"]
    for key in ordered:
        value = frontmatter[key]
        if not _valid_yaml_value(value):
            raise ContextError("frontmatter_unsupported", "frontmatter value is outside the supported subset", {"key": key})
        lines.append(f"{key}: {compact_json(value)}")
    lines.extend(["---", ""])
    for name in allowed:
        if name in sections:
            lines.extend([f"## {name}", "", sections[name].strip(), ""])
    return "\n".join(lines).rstrip("\n") + "\n"


def _parse_index_frontmatter(text: str, expected_schema: str) -> dict[str, Any]:
    frontmatter, _, _ = _parse_frontmatter(text)
    if frontmatter.get("schema") != expected_schema or frontmatter.get("index") is not True:
        raise ContextError("index_stale", "index frontmatter schema is invalid", {"expected_schema": expected_schema}, EXIT_INTEGRITY)
    return frontmatter


def _extract_block(text: str, name: str) -> list[str]:
    begin = f"<!-- BEGIN CONTEXT GENERATED:{name} -->"
    end = f"<!-- END CONTEXT GENERATED:{name} -->"
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) > text.index(end):
        raise ContextError("index_marker_invalid", "generated index marker is invalid", {"block": name}, EXIT_INTEGRITY)
    inside = text.split(begin, 1)[1].split(end, 1)[0]
    return [line for line in inside.strip("\n").split("\n") if line]


def _replace_block(text: str, name: str, rows: Sequence[str]) -> str:
    begin = f"<!-- BEGIN CONTEXT GENERATED:{name} -->"
    end = f"<!-- END CONTEXT GENERATED:{name} -->"
    _extract_block(text, name)
    before, remainder = text.split(begin, 1)
    _, after = remainder.split(end, 1)
    body = "\n".join(rows)
    middle = f"{begin}\n{body + chr(10) if body else ''}{end}"
    return (before + middle + after).rstrip("\n") + "\n"


def parse_root_index(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frontmatter = _parse_index_frontmatter(text, "context-root-index/v1")
    if frontmatter.get("owner") != "context-core":
        raise ContextError("index_stale", "root index owner must be context-core", exit_code=EXIT_INTEGRITY)
    areas: list[dict[str, Any]] = []
    for line in _extract_block(text, "areas"):
        match = ROOT_ROW.fullmatch(line)
        if not match:
            raise ContextError("index_noncanonical", "root area row is malformed", exit_code=EXIT_INTEGRITY)
        try:
            row = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise ContextError("index_noncanonical", "root area row JSON is malformed", exit_code=EXIT_INTEGRITY) from error
        expected = ["area", "path", "owner", "claims", "artifact_schema", "authority"]
        if list(row) != expected or compact_json(row) != match.group(1) or row.get("claims") != [row.get("area")]:
            raise ContextError("index_noncanonical", "root area row fields are not canonical", exit_code=EXIT_INTEGRITY)
        area = row.get("area")
        path = row.get("path")
        if not isinstance(area, str) or not AREA_NAME.fullmatch(area) or not isinstance(path, str):
            raise ContextError("path_escape", "root area path is not canonical", {"path": path}, EXIT_INTEGRITY)
        pure = pathlib.PurePosixPath(path)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ContextError("path_escape", "root area path escapes its canonical location", {"path": path}, EXIT_INTEGRITY)
        if path == ROOT_INDEX or area == "context":
            raise ContextError("index_self_entry", "root index cannot catalog itself", {"path": path}, EXIT_INTEGRITY)
        if path != f"context/{area}/{area}.index.md":
            raise ContextError("reserved_index_path", "area index path is not canonical", {"path": path}, EXIT_INTEGRITY)
        if any(not isinstance(row.get(key), str) or not row[key] for key in ("owner", "artifact_schema", "authority")):
            raise ContextError("index_noncanonical", "root area descriptor is incomplete", exit_code=EXIT_INTEGRITY)
        areas.append(row)
    if areas != sorted(areas, key=lambda row: row["area"]):
        raise ContextError("index_stale", "root area rows are not sorted", exit_code=EXIT_INTEGRITY)
    return frontmatter, areas


def _parse_area_index_metadata(text: str) -> dict[str, Any]:
    frontmatter = _parse_index_frontmatter(text, "context-area-index/v1")
    required = ("area", "owner", "artifact_schema", "authority", "summary")
    if any(not isinstance(frontmatter.get(key), str) or not frontmatter[key] for key in required):
        raise ContextError("index_stale", "area index metadata is incomplete", exit_code=EXIT_INTEGRITY)
    if not AREA_NAME.fullmatch(frontmatter["area"]):
        raise ContextError("index_stale", "area index name is invalid", exit_code=EXIT_INTEGRITY)
    projection_fields = frontmatter.get("projection_fields", [])
    if (
        not isinstance(projection_fields, list)
        or len(projection_fields) > 4
        or any(not isinstance(field, str) or not FIELD_KEY.fullmatch(field) for field in projection_fields)
        or len(projection_fields) != len(set(projection_fields))
        or set(projection_fields) & {"id", "path", "title", "summary", "state", "created_at", "updated_at", "terms", "retired_at", "retired_reason", "superseded_by"}
    ):
        raise ContextError("index_noncanonical", "projection_fields are invalid", exit_code=EXIT_INTEGRITY)
    return frontmatter


def parse_area_index(text: str) -> AreaIndex:
    frontmatter = _parse_area_index_metadata(text)
    projection_fields = frontmatter.get("projection_fields", [])
    history_required = frontmatter["area"] != "snapshot"
    if not history_required and ("CONTEXT GENERATED:history" in text):
        raise ContextError("index_noncanonical", "snapshot index cannot contain history", exit_code=EXIT_INTEGRITY)
    blocks = (("current", "current"),) + (("history", "history"),) if history_required else (("current", "current"),)
    parsed: dict[str, list[dict[str, Any]]] = {"current": [], "history": []}
    seen: set[str] = set()
    for block, expected_state in blocks:
        for line in _extract_block(text, block):
            match = ENTRY_ROW.fullmatch(line)
            if not match:
                raise ContextError("index_noncanonical", "area entry row is malformed", {"block": block}, EXIT_INTEGRITY)
            try:
                row = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise ContextError("index_noncanonical", "area entry JSON is malformed", exit_code=EXIT_INTEGRITY) from error
            if row.get("state") != expected_state:
                raise ContextError("index_wrong_state", "area entry is in the wrong generated block", {"id": row.get("id")}, EXIT_INTEGRITY)
            if not is_context_id(row.get("id")):
                raise ContextError("index_noncanonical", "area entry id is invalid", exit_code=EXIT_INTEGRITY)
            if row["id"] in seen:
                raise ContextError("index_duplicate_entry", "area index contains a duplicate id", {"id": row["id"]}, EXIT_INTEGRITY)
            seen.add(row["id"])
            base = ["id", "path", "title", "summary", "state", "created_at"]
            if "updated_at" in row:
                base.append("updated_at")
            base.append("terms")
            if expected_state == "history":
                base.extend(("retired_at", "retired_reason"))
                if "superseded_by" in row:
                    base.append("superseded_by")
            base.extend(field for field in projection_fields if field in row)
            if list(row) != base or compact_json(row) != match.group(1):
                raise ContextError("index_noncanonical", "area entry fields or JSON bytes are not canonical", {"id": row["id"]}, EXIT_INTEGRITY)
            if (
                any(not isinstance(row.get(field), str) or not row[field] for field in ("path", "title", "summary", "created_at"))
                or not isinstance(row.get("terms"), list)
                or any(not isinstance(term, str) for term in row["terms"])
            ):
                raise ContextError("index_noncanonical", "area entry fields are invalid", {"id": row["id"]}, EXIT_INTEGRITY)
            path = row["path"]
            pure = pathlib.PurePosixPath(path)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise ContextError("path_escape", "area entry path is not canonical", {"path": path}, EXIT_INTEGRITY)
            if path in RESERVED_INDEX_PATHS or path.endswith(".index.md"):
                raise ContextError("index_self_entry", "reserved index cannot be an artifact row", {"path": path}, EXIT_INTEGRITY)
            prefix = f"context/{frontmatter['area']}/"
            expected_history = path.startswith(prefix + "retired/")
            if not path.startswith(prefix) or not path.endswith(".md"):
                raise ContextError("path_escape", "area entry path escapes its area", {"path": path}, EXIT_INTEGRITY)
            if expected_history != (expected_state == "history"):
                raise ContextError("index_wrong_state", "area entry path and state disagree", {"path": path}, EXIT_INTEGRITY)
            if _entry_row(row) != line:
                raise ContextError("index_noncanonical", "area entry visible row is not canonical", {"id": row["id"]}, EXIT_INTEGRITY)
            parsed[block].append(row)
        if parsed[block] != sorted(parsed[block], key=lambda row: (row["created_at"], row["id"])):
            raise ContextError("index_noncanonical", "area entry rows are not sorted", {"block": block}, EXIT_INTEGRITY)
    return AreaIndex(frontmatter=frontmatter, current=parsed["current"], history=parsed["history"], text=text)


def _markdown_escape(value: str) -> str:
    escaped = value
    for char in "\\`*_{}[]<>#|":
        escaped = escaped.replace(char, "\\" + char)
    return escaped.replace("\n", " ")


def _terms(frontmatter: dict[str, Any]) -> list[str]:
    values = list(frontmatter.get("tags", [])) + list(frontmatter.get("search_terms", []))
    selected: dict[str, str] = {}
    for value in values:
        value = nfc(value.strip())
        key = normalized_key(value)
        if value and (key not in selected or value < selected[key]):
            selected[key] = value
    return [selected[key] for key in sorted(selected)]


def _read_artifact_text(path: pathlib.Path, metrics: IOMetrics | None = None) -> str:
    if metrics:
        metrics.artifact_opens += 1
    raw = path.read_bytes()
    if metrics:
        metrics.artifact_read_bytes += len(raw)
    return raw.decode("utf-8")


def _entry_from_document(
    repo: pathlib.Path,
    path: pathlib.Path,
    metadata: dict[str, Any],
    state: str,
    metrics: IOMetrics | None = None,
) -> dict[str, Any]:
    document = parse_document(_read_artifact_text(path, metrics))
    fm = document.frontmatter
    expected_schema = metadata["artifact_schema"]
    if fm["schema"] != expected_schema:
        raise ContextError("schema_area_mismatch", "artifact schema does not match area", {"path": path.relative_to(repo).as_posix()}, EXIT_INTEGRITY)
    row: dict[str, Any] = {
        "id": fm["id"],
        "path": path.relative_to(repo).as_posix(),
        "title": fm["title"],
        "summary": fm["summary"],
        "state": state,
        "created_at": fm["created_at"],
    }
    if "updated_at" in fm:
        row["updated_at"] = fm["updated_at"]
    row["terms"] = _terms(fm)
    if state == "history":
        for key in ("retired_at", "retired_reason"):
            if key not in fm:
                raise ContextError("lifecycle_invalid", "history artifact lacks retirement metadata", {"path": row["path"]}, EXIT_INTEGRITY)
            row[key] = fm[key]
        if "superseded_by" in fm:
            row["superseded_by"] = fm["superseded_by"]
    for key in metadata.get("projection_fields", []):
        if key in fm:
            row[key] = fm[key]
    return row


def _validate_strict_lifecycle(frontmatter: dict[str, Any], state: str, path: str) -> None:
    reason = frontmatter.get("retired_reason")
    lifecycle_fields = {"retired_at", "retired_reason", "retirement_note", "superseded_by"}
    if state == "current" and lifecycle_fields & set(frontmatter):
        raise ContextError("lifecycle_invalid", "current artifact cannot carry lifecycle metadata", {"path": path}, EXIT_INTEGRITY)
    if state != "history":
        return
    if "retired_at" not in frontmatter or reason is None:
        raise ContextError("lifecycle_invalid", "history artifact lacks retirement metadata", {"path": path}, EXIT_INTEGRITY)
    allowed = {
        "context-observation/v1": {"invalidated", "superseded"},
        "context-decision/v1": {"withdrawn", "superseded"},
    }.get(frontmatter.get("schema"), set())
    if reason not in allowed:
        raise ContextError("lifecycle_invalid", "retired_reason is invalid for the artifact kind", {"path": path}, EXIT_INTEGRITY)
    if reason in {"invalidated", "withdrawn"}:
        note = frontmatter.get("retirement_note")
        if not isinstance(note, str) or not _substantive(note) or "\n" in note or len(note) > 500 or "superseded_by" in frontmatter:
            raise ContextError("lifecycle_invalid", "terminal retirement requires a note and cannot name a successor", {"path": path}, EXIT_INTEGRITY)
    if reason == "superseded":
        try:
            _require_context_id(frontmatter.get("superseded_by"), "superseded_by")
        except ContextError as error:
            raise ContextError("lifecycle_invalid", "superseded artifact requires a successor", {"path": path}, EXIT_INTEGRITY) from error


def _entry_row(row: dict[str, Any]) -> str:
    link = row["path"][:-3] if row["path"].endswith(".md") else row["path"]
    visible = f"- [[{link}]] — {_markdown_escape(row['title'])} — {_markdown_escape(row['summary'])}"
    return f"{visible} <!-- context-entry {compact_json(row)} -->"


def _area_row(row: dict[str, Any], label: str, summary: str) -> str:
    link = row["path"][:-3]
    return f"- [[{link}]] — {_markdown_escape(label)}: {_markdown_escape(summary)} <!-- context-area {compact_json(row)} -->"


def _area_label(area: str) -> str:
    return {"snapshot": "Snapshot", "observation": "Observation", "decision": "Decision"}.get(area, area.replace("-", " ").title())


def _root_seed() -> str:
    return """---
schema: \"context-root-index/v1\"
index: true
owner: \"context-core\"
summary: \"프로젝트의 공유 context 영역 catalog\"
---

# Context

## Areas
<!-- BEGIN CONTEXT GENERATED:areas -->
<!-- END CONTEXT GENERATED:areas -->
"""


def _area_seed(area: str, owner: str, artifact_schema: str, authority: str, summary: str, *, search_terms: Sequence[str] = (), projection_fields: Sequence[str] = ()) -> str:
    lines = [
        "---", 'schema: "context-area-index/v1"', "index: true", f"area: {compact_json(area)}", f"owner: {compact_json(owner)}",
        f"artifact_schema: {compact_json(artifact_schema)}", f"authority: {compact_json(authority)}", f"summary: {compact_json(summary)}",
    ]
    if search_terms:
        lines.append(f"search_terms: {compact_json(list(search_terms))}")
    if projection_fields:
        lines.append(f"projection_fields: {compact_json(list(projection_fields))}")
    lines.extend(["---", "", f"# {_area_label(area)}", "", "## Current", "<!-- BEGIN CONTEXT GENERATED:current -->", "<!-- END CONTEXT GENERATED:current -->"])
    if area != "snapshot":
        lines.extend(["", "## History", "<!-- BEGIN CONTEXT GENERATED:history -->", "<!-- END CONTEXT GENERATED:history -->"])
    return "\n".join(lines) + "\n"


def _builtin_area_specs() -> list[tuple[dict[str, Any], str, str]]:
    return [
        ({"area": "snapshot", "path": "context/snapshot/snapshot.index.md", "owner": "context-core", "claims": ["snapshot"], "artifact_schema": "context-snapshot/v1", "authority": "staging"}, "Snapshot", "session handoff staging"),
        ({"area": "observation", "path": "context/observation/observation.index.md", "owner": "context-core", "claims": ["observation"], "artifact_schema": "context-observation/v1", "authority": "evidence"}, "Observation", "비권위 발견과 근거"),
    ]


def render_root_index(seed: str, areas: Sequence[tuple[dict[str, Any], str, str]]) -> str:
    _parse_index_frontmatter(seed, "context-root-index/v1")
    rows = [_area_row(row, label, summary) for row, label, summary in sorted(areas, key=lambda item: item[0]["area"])]
    return _replace_block(seed, "areas", rows)


def _scan_area_paths(repo: pathlib.Path, area: str, metrics: IOMetrics | None = None) -> Iterator[tuple[pathlib.Path, str]]:
    root = _ensure_contained(repo, f"context/{area}")
    if metrics:
        metrics.artifact_directory_lists += 1
    if not root.is_dir():
        return
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name == "retired":
                retired = _ensure_contained(repo, f"context/{area}/retired")
                if not retired.is_dir():
                    raise ContextError("path_invalid", "retired path must be a directory", {"path": f"context/{area}/retired"}, EXIT_INTEGRITY)
                if metrics:
                    metrics.artifact_directory_lists += 1
                with os.scandir(retired) as historical_entries:
                    for historical in historical_entries:
                        if historical.name.endswith(".md") and not historical.name.endswith(".index.md"):
                            if historical.is_symlink():
                                raise ContextError("symlink_path", "artifact path cannot be a symlink", {"path": f"context/{area}/retired/{historical.name}"}, EXIT_INTEGRITY)
                            yield pathlib.Path(historical.path), "history"
            elif entry.name.endswith(".md") and not entry.name.endswith(".index.md"):
                if entry.is_symlink():
                    raise ContextError("symlink_path", "artifact path cannot be a symlink", {"path": f"context/{area}/{entry.name}"}, EXIT_INTEGRITY)
                yield pathlib.Path(entry.path), "current"


def render_area_index_from_repository(repo: pathlib.Path, area: str, *, repair_rows: bool = False) -> str:
    index_path = _ensure_contained(repo, f"context/{area}/{area}.index.md")
    if not index_path.is_file():
        raise ContextError("index_seed_required", "area index is missing", {"area": area}, EXIT_INTEGRITY)
    existing = index_path.read_text(encoding="utf-8")
    if repair_rows:
        metadata = _parse_area_index_metadata(existing)
        _extract_block(existing, "current")
        if area != "snapshot":
            _extract_block(existing, "history")
    else:
        metadata = parse_area_index(existing).frontmatter
    if metadata["area"] != area:
        raise ContextError("area_index_mismatch", "area index metadata differs from its canonical path", {"area": area}, EXIT_INTEGRITY)
    rows: dict[str, list[dict[str, Any]]] = {"current": [], "history": []}
    for path, state in _scan_area_paths(repo, area):
        rows[state].append(_entry_from_document(repo, path, metadata, state))
    for state in rows:
        rows[state].sort(key=lambda row: (row["created_at"], row["id"]))
    rendered = _replace_block(existing, "current", [_entry_row(row) for row in rows["current"]])
    if area != "snapshot":
        rendered = _replace_block(rendered, "history", [_entry_row(row) for row in rows["history"]])
    return rendered


def _read_index(path: pathlib.Path, metrics: IOMetrics | None) -> str:
    if metrics:
        metrics.index_opens += 1
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise ContextError("index_stale", "index path is missing", {"path": path.as_posix()}, EXIT_INTEGRITY) from error
    if metrics:
        metrics.index_read_bytes += len(raw)
    return raw.decode("utf-8")


def _query_tokens(query: str) -> list[str]:
    normalized = normalized_key(query)
    return re.findall(r"[\w]+", normalized, flags=re.UNICODE)


def score_entry(row: dict[str, Any], query: str) -> int:
    query_normal = normalized_key(query.strip())
    if not query_normal:
        return 0
    tokens = _query_tokens(query)
    title = normalized_key(row.get("title", ""))
    summary = normalized_key(row.get("summary", ""))
    path = normalized_key(row.get("path", ""))
    terms = [normalized_key(term) for term in row.get("terms", [])]
    score = 100 if query_normal == normalized_key(row.get("id", "")) else 0
    if query_normal and query_normal in title:
        score += 40
    if query_normal and query_normal in summary:
        score += 10
    if query_normal in terms:
        score += 12
    for token in tokens:
        if token in title.split():
            score += 8
        if token in summary.split():
            score += 3
        if token in re.findall(r"[\w]+", path):
            score += 1
    searchable = " ".join([title, summary, path, *terms])
    if tokens and all(token in searchable for token in tokens):
        score += 10
    return score


def _fallback_entries(repo: pathlib.Path, area_row: dict[str, Any], metrics: IOMetrics | None) -> list[dict[str, Any]]:
    metadata = {
        "area": area_row["area"], "owner": area_row["owner"], "artifact_schema": area_row["artifact_schema"],
        "authority": area_row["authority"], "projection_fields": [],
    }
    entries = []
    for path, state in _scan_area_paths(repo, area_row["area"], metrics):
        entries.append(_entry_from_document(repo, path, metadata, state, metrics))
    return entries


def _recall_result(items: list[dict[str, Any]], total_matches: int, fallback: bool, warnings: Sequence[str]) -> dict[str, Any]:
    omitted = max(0, total_matches - len(items))
    return {
        "items": items,
        "returned": len(items),
        "omitted": omitted,
        "truncated": omitted > 0,
        "index_fallback": fallback,
        "warnings": sorted(set(warnings)),
    }


def _expanded_item(
    item: dict[str, Any],
    document: Document,
    selected_sections: Sequence[str],
    max_bytes: int,
) -> dict[str, Any]:
    available = {name: document.sections[name] for name in selected_sections if name in document.sections}
    complete = {**item, "sections": available}
    if len(canonical_json(complete).encode("utf-8")) <= max_bytes:
        return complete

    hint = f"context recall --read {item['id']}"
    truncated: dict[str, Any] = {
        **item,
        "sections": {},
        "section_truncated": True,
        "full_read_hint": hint,
    }
    if len(canonical_json(truncated).encode("utf-8")) > max_bytes:
        return truncated
    for name, value in available.items():
        proposed_sections = {**truncated["sections"], name: value}
        proposed = {**truncated, "sections": proposed_sections}
        if len(canonical_json(proposed).encode("utf-8")) <= max_bytes:
            truncated["sections"] = proposed_sections
            continue
        low = 0
        high = len(value)
        fitted = ""
        while low <= high:
            middle = (low + high) // 2
            prefix = value[:middle].rstrip()
            candidate = (prefix + "…") if prefix else "…"
            proposal = {**truncated, "sections": {**truncated["sections"], name: candidate}}
            if len(canonical_json(proposal).encode("utf-8")) <= max_bytes:
                fitted = candidate
                low = middle + 1
            else:
                high = middle - 1
        if fitted:
            truncated["sections"] = {**truncated["sections"], name: fitted}
        break
    return truncated


def recall_repository(
    repo: pathlib.Path,
    *,
    query: str = "",
    areas: Sequence[str] = (),
    include_history: bool = False,
    facets: Sequence[tuple[str, str]] = (),
    limit: int = 8,
    pack: bool = False,
    sections: Sequence[str] = (),
    read_ids: Sequence[str] = (),
    strict_index: bool = False,
    max_bytes: int | None = None,
    metrics: IOMetrics | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 20 or (max_bytes is not None and not 1 <= max_bytes <= MAX_USER_BYTES):
        raise ContextError("usage_invalid", "limit or max-bytes is outside the v1 range")
    expanded = bool(pack or sections or read_ids)
    effective_max_bytes = (
        min(max_bytes, MAX_RECALL_BATCH_BYTES)
        if expanded and max_bytes is not None
        else MAX_RECALL_BATCH_BYTES
        if expanded
        else max_bytes
        if max_bytes is not None
        else MAX_STAGE1_BYTES
    )
    root_path = repo / ROOT_INDEX
    if not root_path.is_file():
        raise ContextError("context_root_missing", "context root index is missing", {"path": ROOT_INDEX}, EXIT_NOT_FOUND)
    root_text = _read_index(root_path, metrics)
    _, root_areas = parse_root_index(root_text)
    selected_areas = [row for row in root_areas if not areas or row["area"] in set(areas)]
    all_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    warnings: list[str] = []
    fallback = False
    area_indexes: dict[str, AreaIndex] = {}
    for area_row in selected_areas:
        index_path = repo / area_row["path"]
        try:
            area_index = parse_area_index(_read_index(index_path, metrics))
            if area_index.frontmatter["area"] != area_row["area"] or area_index.frontmatter["owner"] != area_row["owner"]:
                raise ContextError("index_stale", "area index/root catalog mismatch", exit_code=EXIT_INTEGRITY)
            area_indexes[area_row["area"]] = area_index
            rows = list(area_index.current) + (list(area_index.history) if include_history else [])
        except (ContextError, UnicodeError) as error:
            if strict_index:
                if isinstance(error, ContextError) and error.exit_code == EXIT_INTEGRITY:
                    raise error
                raise ContextError("index_stale", "area index is unreadable", {"area": area_row["area"], "cause": getattr(error, "code", type(error).__name__)}, EXIT_INTEGRITY) from error
            fallback = True
            warnings.append("area_index_invalid")
            rows = _fallback_entries(repo, area_row, metrics)
            if not include_history:
                rows = [row for row in rows if row["state"] == "current"]
        for row in rows:
            all_entries.append((row, area_row))
    if read_ids:
        wanted = set(read_ids)
        missing_selected = []
        for row, area_row in list(all_entries):
            if metrics:
                metrics.artifact_stats += 1
            if row["id"] in wanted and not (repo / row["path"]).is_file():
                missing_selected.append(area_row)
        for area_row in missing_selected:
            if strict_index:
                raise ContextError("index_stale", "selected index link is missing", {"area": area_row["area"]}, EXIT_INTEGRITY)
            fallback = True
            warnings.append("selected_link_missing")
            all_entries = [(row, owner) for row, owner in all_entries if owner["area"] != area_row["area"]]
            all_entries.extend((row, area_row) for row in _fallback_entries(repo, area_row, metrics))
        all_entries = [(row, area_row) for row, area_row in all_entries if row["id"] in wanted]
    filtered: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    for row, area_row in all_entries:
        permitted = True
        for key, expected in facets:
            actual = row.get(key)
            normalized_expected = normalized_key(expected)
            if isinstance(actual, list):
                permitted = permitted and normalized_expected in {normalized_key(str(item)) for item in actual}
            else:
                permitted = permitted and isinstance(actual, str) and normalized_key(actual) == normalized_expected
        score = score_entry(row, query)
        if permitted and (not query or score > 0):
            filtered.append((row, area_row, score))
    filtered.sort(key=lambda item: item[0]["id"])
    filtered.sort(key=lambda item: item[0]["created_at"], reverse=True)
    filtered.sort(key=lambda item: item[2], reverse=True)
    candidates = filtered[:limit]
    stage1_items: list[dict[str, Any]] = []
    for row, area_row, score in candidates:
        item = {
            "id": row["id"], "kind": area_row["area"], "state": row["state"], "title": row["title"],
            "summary": row["summary"], "path": row["path"], "authority": area_row["authority"], "score": score,
        }
        for projection in area_indexes.get(area_row["area"], AreaIndex({}, [], [], "")).frontmatter.get("projection_fields", []):
            if projection in row:
                item[projection] = row[projection]
        stage1_items.append(item)
    total_matches = len(filtered)
    output: list[dict[str, Any]] = []
    if expanded:
        for item in stage1_items:
            minimum = {
                **item,
                "sections": {},
                "section_truncated": True,
                "full_read_hint": f"context recall --read {item['id']}",
            }
            if len(canonical_json(_recall_result(output + [minimum], total_matches, fallback, warnings)).encode("utf-8")) > effective_max_bytes:
                break
            path = repo / item["path"]
            try:
                document = parse_document(_read_artifact_text(path, metrics))
            except FileNotFoundError:
                continue
            selected_sections = sections or tuple(document.sections)
            result_with_placeholder = _recall_result(output + [{}], total_matches, fallback, warnings)
            result_overhead = len(canonical_json(result_with_placeholder).encode("utf-8")) - len(canonical_json({}).encode("utf-8"))
            item_budget = min(MAX_SECTION_ITEM_BYTES, effective_max_bytes - result_overhead)
            expanded_item = _expanded_item(item, document, selected_sections, item_budget)
            if len(canonical_json(_recall_result(output + [expanded_item], total_matches, fallback, warnings)).encode("utf-8")) > effective_max_bytes:
                raise ContextError("recall_budget_internal", "expanded recall item did not fit its calculated byte budget", exit_code=EXIT_INTEGRITY)
            output.append(expanded_item)
    else:
        output = stage1_items
        while output and len(canonical_json(_recall_result(output, total_matches, fallback, warnings)).encode("utf-8")) > effective_max_bytes:
            output.pop()
    result = _recall_result(output, total_matches, fallback, warnings)
    if metrics:
        metrics.output_bytes += len(canonical_json(result).encode("utf-8"))
    return result


def builtin_capability(kind: str) -> dict[str, Any]:
    if kind == "snapshot":
        return {
            "schema": "context-owner-capability/v1", "owner": "context-core", "kind": "snapshot",
            "artifact_schema": "context-snapshot/v1", "authority": "staging",
            "claim_surface": {"type": "agent_skill", "name": "context-core:snapshot", "operation": "claim"},
            "claim_rule": "사용자가 재개할 unfinished session handoff를 명시적으로 저장하려 한다",
            "claim_assertions": ["handoff_requested", "unfinished_context_present"],
            "draft_fields": {
                "required": {
                    "current_context": {"type": "string", "min_chars": 1, "max_chars": 1200},
                    "open_items": {"type": "string_list", "min_items": 1, "max_items": 8, "max_item_chars": 240},
                    "next_steps": {"type": "string_list", "min_items": 1, "max_items": 8, "max_item_chars": 240},
                },
                "optional": {
                    "decided": {"type": "string_list", "max_items": 8, "max_item_chars": 240},
                    "refs": {"type": "string_list", "max_items": 8, "max_item_chars": 500},
                    "capture_candidates": {"type": "string_list", "max_items": 8, "max_item_chars": 240},
                    "anchors": {"type": "string_list", "format": "context_id", "max_items": 12, "max_item_chars": 36},
                },
            },
        }
    if kind == "observation":
        return {
            "schema": "context-owner-capability/v1", "owner": "context-core", "kind": "observation",
            "artifact_schema": "context-observation/v1", "authority": "evidence",
            "claim_surface": {"type": "agent_skill", "name": "context-core:observation", "operation": "claim"},
            "claim_rule": "나중에 조사·판단에 재사용할 수 있는 발견 또는 근거다",
            "claim_assertions": ["reusable_observation", "evidence_present"],
            "lifecycle_operations": {"same_claim": {"surface": {"type": "agent_skill", "name": "context-core:observation", "operation": "same_claim"}, "rule": "successor OBS가 predecessor OBS의 같은 관찰 claim을 교정하거나 더 정확히 인수한다", "assertions": ["same_semantic_claim"]}},
            "draft_fields": {
                "required": {
                    "observation": {"type": "string", "min_chars": 1, "max_chars": 1200},
                    "evidence": {"type": "string_list", "min_items": 1, "max_items": 4, "max_item_chars": 500},
                },
                "optional": {
                    "impact": {"type": "string", "max_chars": 800},
                    "current_handling": {"type": "string", "max_chars": 800},
                    "followup_conditions": {"type": "string_list", "max_items": 8, "max_item_chars": 240},
                },
            },
        }
    raise ContextError("owner_unavailable", "built-in capability is unavailable", {"kind": kind}, EXIT_CONFLICT)


def capabilities_result() -> dict[str, Any]:
    return {"schema": "context-owner-capabilities/v1", "owners": [builtin_capability("snapshot"), builtin_capability("observation")]}


def _capability_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("schema") == "context-owner-capabilities/v1":
        owners = value.get("owners")
    elif isinstance(value, list):
        owners = value
    else:
        raise ContextError("capability_invalid", "capabilities must use context-owner-capabilities/v1", exit_code=EXIT_CONFLICT)
    if not isinstance(owners, list):
        raise ContextError("capability_invalid", "capability owners must be an array", exit_code=EXIT_CONFLICT)
    output: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for capability in owners:
        if not isinstance(capability, dict) or capability.get("schema") != "context-owner-capability/v1":
            raise ContextError("capability_invalid", "owner capability envelope is invalid", exit_code=EXIT_CONFLICT)
        owner = capability.get("owner")
        kind = capability.get("kind")
        surface = capability.get("claim_surface")
        if (
            not isinstance(owner, str)
            or not isinstance(kind, str)
            or not isinstance(capability.get("artifact_schema"), str)
            or capability.get("authority") not in {"staging", "evidence", "authoritative"}
            or not isinstance(surface, dict)
            or surface.get("type") != "agent_skill"
            or surface.get("operation") != "claim"
            or not isinstance(surface.get("name"), str)
        ):
            raise ContextError("capability_invalid", "owner capability identity or host surface is invalid", exit_code=EXIT_CONFLICT)
        identity = (owner, kind)
        if identity in identities or any(item["kind"] == kind for item in output):
            raise ContextError("owner_conflict", "more than one capability claims a kind", {"kind": kind}, EXIT_CONFLICT)
        identities.add(identity)
        output.append(capability)
    return output


def validate_candidate_batch(batch: Any, capabilities: Any) -> list[dict[str, Any]]:
    if isinstance(batch, dict) and batch.get("schema") == "context-capture-batch/v1":
        candidates = batch.get("candidates")
        if batch.get("audit_count", 1) != 1:
            raise ContextError("audit_repeated", "a semantic milestone may be audited at most once", exit_code=EXIT_CONFLICT)
    else:
        candidates = batch
    if not isinstance(candidates, list):
        raise ContextError("candidate_invalid", "candidate batch must be an array")
    if len(candidates) > 8:
        raise ContextError("candidate_batch_too_large", "candidate batch exceeds the v1 count budget", {"maximum": 8}, EXIT_CONFLICT)
    if len(canonical_json(candidates).encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise ContextError("candidate_batch_too_large", "candidate batch exceeds 16 KiB", exit_code=EXIT_CONFLICT)
    capability_by_kind = {item["kind"]: item for item in _capability_list(capabilities)}
    required = {
        "schema", "candidate_id", "claim_key", "title", "claim", "summary", "captured_from", "requested_kind",
        "specialized_kinds", "fallback_kind", "owner_inputs",
    }
    candidate_ids: set[str] = set()
    claim_keys: set[str] = set()
    semantic_claims: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("schema") != "context-capture-candidate/v1" or required - set(candidate):
            raise ContextError("candidate_invalid", "candidate envelope is incomplete", exit_code=EXIT_CONFLICT)
        identifier = candidate.get("candidate_id")
        claim_key = candidate.get("claim_key")
        if not isinstance(identifier, str) or not re.fullmatch(r"cand_[0-9a-f]{32}", identifier):
            raise ContextError("candidate_invalid", "candidate_id is invalid")
        if not isinstance(claim_key, str) or not LOCAL_ID.fullmatch(claim_key):
            raise ContextError("candidate_invalid", "claim_key is invalid")
        if identifier in candidate_ids:
            raise ContextError("candidate_invalid", "candidate_id is duplicated", {"candidate_id": identifier}, EXIT_CONFLICT)
        normalized_claim = normalized_key(candidate.get("claim", "").strip())
        if claim_key in claim_keys or normalized_claim in semantic_claims:
            raise ContextError("duplicate_claim", "one semantic claim may appear only once in an audit batch", {"claim_key": claim_key}, EXIT_CONFLICT)
        candidate_ids.add(identifier)
        claim_keys.add(claim_key)
        semantic_claims.add(normalized_claim)
        if not _substantive(candidate.get("title")) or len(candidate["title"]) > 120 or "\n" in candidate["title"]:
            raise ContextError("candidate_invalid", "candidate title is invalid")
        if not _substantive(candidate.get("claim")) or len(candidate["claim"]) > 320:
            raise ContextError("candidate_invalid", "candidate claim is invalid")
        if not _substantive(candidate.get("summary")) or len(candidate["summary"]) > 280 or "\n" in candidate["summary"]:
            raise ContextError("candidate_invalid", "candidate summary is invalid")
        if candidate.get("captured_from") not in {"conversation", "workspace", "manual", "import"}:
            raise ContextError("candidate_invalid", "candidate provenance is invalid")
        requested = candidate.get("requested_kind")
        specialized = candidate.get("specialized_kinds")
        fallback = candidate.get("fallback_kind")
        if requested is not None and not isinstance(requested, str):
            raise ContextError("candidate_invalid", "requested_kind must be a string or null")
        if not isinstance(specialized, list) or len(specialized) > 2 or len(specialized) != len(set(specialized)) or not all(isinstance(item, str) for item in specialized):
            raise ContextError("candidate_invalid", "specialized_kinds is invalid")
        if fallback not in {None, "observation", "snapshot"}:
            raise ContextError("candidate_invalid", "fallback_kind is invalid")
        evidence = candidate.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > 2 or any(not _substantive(item) or len(item) > 240 for item in evidence):
            raise ContextError("candidate_invalid", "candidate evidence is invalid")
        owner_inputs = candidate.get("owner_inputs")
        if not isinstance(owner_inputs, dict):
            raise ContextError("candidate_invalid", "owner_inputs must be an object")
        relevant = set(specialized) | ({requested} if requested else set()) | ({fallback} if fallback else set())
        if set(owner_inputs) - relevant:
            raise ContextError("candidate_invalid", "owner_inputs contains an unrouted kind", {"kinds": sorted(set(owner_inputs) - relevant)})
        for kind, owner_input in owner_inputs.items():
            if len(canonical_json(owner_input).encode("utf-8")) > MAX_OWNER_INPUT_BYTES:
                raise ContextError("candidate_too_large", "owner input exceeds 2 KiB", {"kind": kind}, EXIT_CONFLICT)
            capability = capability_by_kind.get(kind)
            if capability is not None and capability["owner"] == "context-core":
                _validate_owner_inputs(kind, owner_input)
    return candidates


def _claim_result_map(results: Any) -> dict[tuple[str, str], dict[str, Any]]:
    if isinstance(results, dict) and results.get("schema") == "context-owner-results/v1":
        values = results.get("results")
    else:
        values = results
    if not isinstance(values, list):
        raise ContextError("owner_result_invalid", "claim results must be an array", exit_code=EXIT_CONFLICT)
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for result in values:
        if not isinstance(result, dict):
            raise ContextError("owner_result_invalid", "claim result is not an object", exit_code=EXIT_CONFLICT)
        key = (result.get("candidate_id"), result.get("target_kind"))
        if not all(isinstance(item, str) for item in key) or key in output:
            raise ContextError("owner_conflict", "claim result is duplicated for candidate/kind", exit_code=EXIT_CONFLICT)
        output[key] = result
    return output


def route_candidates(batch: Any, capabilities: Any, claim_results: Any) -> dict[str, Any]:
    candidates = validate_candidate_batch(batch, capabilities)
    capability_by_kind = {item["kind"]: item for item in _capability_list(capabilities)}
    results = _claim_result_map(claim_results)
    routes: list[dict[str, Any]] = []
    for candidate in candidates:
        requested = candidate["requested_kind"]
        ordered = [requested] if requested else list(candidate["specialized_kinds"])
        available = [kind for kind in ordered if kind in capability_by_kind]
        if requested and not available:
            routes.append({"candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "owner_unavailable", "reason": "requested_owner_unavailable"})
            continue
        evaluated: list[tuple[str, dict[str, Any]]] = []
        for kind in available:
            result = results.get((candidate["candidate_id"], kind))
            if result is None:
                continue
            capability = capability_by_kind[kind]
            embedded = next((item for item in result.get("semantic_inputs", []) if item.get("operation") == "claim"), None)
            if (
                result.get("schema") != "context-owner-result/v1"
                or result.get("result_type") != "claim"
                or result.get("owner") != capability["owner"]
                or result.get("capability_digest") != canonical_digest(capability)
                or embedded is None
                or embedded.get("value") != candidate
                or embedded.get("input_digest") != canonical_digest(candidate)
            ):
                raise ContextError("claim_result_mismatch", "host-collected owner result differs from candidate/capability", exit_code=EXIT_CONFLICT)
            validate_owner_result(result, capability)
            evaluated.append((kind, result))
        clarifications = [(kind, result) for kind, result in evaluated if result.get("decision") == "needs_clarification"]
        claims = [(kind, result) for kind, result in evaluated if result.get("decision") == "claim"]
        if clarifications:
            kind, result = clarifications[0]
            routes.append({"candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "needs_clarification", "owner": result["owner"], "target_kind": kind, "reason": result["reason"]})
            continue
        if len(claims) > 1:
            routes.append({"candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "owner_conflict", "reason": "multiple_specialized_owners_claimed"})
            continue
        if len(claims) == 1:
            kind, result = claims[0]
            reason = "requested_owner" if requested else ("fallback_owner" if kind == candidate.get("fallback_kind") else "specialized_owner")
            routes.append({
                "candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "proposed",
                "owner": result["owner"], "target_kind": kind, "authority": capability_by_kind[kind]["authority"],
                "reason": reason, "owner_result_digest": canonical_digest(result),
            })
            continue
        if requested:
            declined = next((result for _, result in evaluated if result.get("decision") == "decline"), None)
            routes.append({"candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "skipped", "reason": "owner_decline" if declined else "owner_unavailable"})
            continue
        if available and len(evaluated) != len(available):
            routes.append({"candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "owner_unavailable", "reason": "specialized_owner_result_missing"})
            continue
        fallback = candidate.get("fallback_kind")
        fallback_result = results.get((candidate["candidate_id"], fallback)) if fallback else None
        if fallback and fallback in capability_by_kind and fallback_result is not None:
            capability = capability_by_kind[fallback]
            embedded = next((item for item in fallback_result.get("semantic_inputs", []) if item.get("operation") == "claim"), None)
            if fallback_result.get("owner") != capability["owner"] or fallback_result.get("capability_digest") != canonical_digest(capability) or embedded is None or embedded.get("value") != candidate:
                raise ContextError("claim_result_mismatch", "fallback result differs from candidate/capability", exit_code=EXIT_CONFLICT)
            validate_owner_result(fallback_result, capability)
            if fallback_result.get("decision") == "claim":
                routes.append({
                    "candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "proposed",
                    "owner": fallback_result["owner"], "target_kind": fallback, "authority": capability["authority"],
                    "reason": "fallback_owner", "owner_result_digest": canonical_digest(fallback_result),
                })
                continue
        routes.append({"candidate_id": candidate["candidate_id"], "claim_key": candidate["claim_key"], "status": "skipped", "reason": "no_owner_claim"})
    return {
        "schema": "context-route-result/v1", "routes": routes,
        "conflicts": [item for item in routes if item["status"] in {"owner_conflict", "duplicate_claim"}],
        "skipped": [item for item in routes if item["status"] == "skipped"],
        "router_owner_process_invocations": 0, "cache_probe_count": 0, "alternate_runtime_count": 0,
    }


def _validate_owner_inputs(kind: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextError("candidate_invalid", "owner input must be an object")
    capability = builtin_capability(kind)
    fields = capability["draft_fields"]
    allowed = set(fields["required"]) | set(fields["optional"])
    missing = set(fields["required"]) - set(value)
    extra = set(value) - allowed
    if missing or extra:
        raise ContextError("candidate_invalid", "owner input fields differ from capability", {"missing": sorted(missing), "extra": sorted(extra)})
    normalized: dict[str, Any] = {}
    for name, raw in value.items():
        spec = fields["required"].get(name) or fields["optional"][name]
        if spec["type"] == "string":
            if not _substantive(raw) or len(raw) > spec["max_chars"]:
                raise ContextError("candidate_invalid", f"owner input {name} is not substantive")
            normalized[name] = nfc(raw.strip())
        elif spec["type"] == "string_list":
            items = _string_list(
                raw,
                name,
                required=bool(spec.get("min_items")),
                maximum=spec["max_items"],
                item_maximum=spec["max_item_chars"],
            )
            if spec.get("format") == "context_id":
                for identifier in items:
                    _require_context_id(identifier, name)
            normalized[name] = items
        else:
            raise ContextError("candidate_invalid", "unsupported capability field type", {"field": name})
    return normalized


def direct_candidate(
    kind: str,
    *,
    title: str,
    summary: str,
    captured_from: str,
    owner_inputs: dict[str, Any],
    source_refs: Sequence[str] = (),
    tags: Sequence[str] = (),
    search_terms: Sequence[str] = (),
    kind_hint: str | None = None,
) -> dict[str, Any]:
    if kind not in BUILTIN_AREAS:
        raise ContextError("owner_unavailable", "direct candidate kind is unavailable", {"kind": kind}, EXIT_CONFLICT)
    if not _substantive(title) or "\n" in title or len(title) > 120:
        raise ContextError("candidate_invalid", "candidate title is invalid")
    if not _substantive(summary) or "\n" in summary or len(summary) > 280:
        raise ContextError("candidate_invalid", "candidate summary is invalid")
    if captured_from not in {"conversation", "workspace", "manual", "import"}:
        raise ContextError("candidate_invalid", "candidate captured_from is invalid")
    if kind_hint is not None and (kind != "observation" or kind_hint != "decision"):
        raise ContextError("candidate_invalid", "kind_hint is only supported for decision-like observations")
    normalized_inputs = _validate_owner_inputs(kind, owner_inputs)
    primary = normalized_inputs["current_context" if kind == "snapshot" else "observation"]
    candidate: dict[str, Any] = {
        "schema": "context-capture-candidate/v1",
        "candidate_id": "cand_" + uuid.uuid4().hex,
        "claim_key": "direct",
        "title": nfc(title.strip()),
        "claim": primary,
        "summary": nfc(summary.strip()),
        "captured_from": captured_from,
        "requested_kind": kind,
        "specialized_kinds": [kind],
        "fallback_kind": None,
        "source_refs": _string_list(list(source_refs), "source_refs", maximum=12, item_maximum=500),
        "tags": _string_list(list(tags), "tags", maximum=12, item_maximum=40),
        "search_terms": _string_list(list(search_terms), "search_terms", maximum=12, item_maximum=40),
        "owner_inputs": {kind: normalized_inputs},
    }
    if kind_hint is not None:
        candidate["kind_hint"] = kind_hint
    if len(canonical_json(candidate).encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise ContextError("candidate_too_large", "candidate exceeds the v1 byte budget", exit_code=EXIT_CONFLICT)
    return candidate


def _validate_attestation(attestation: dict[str, Any], operation: str, input_value: dict[str, Any], expected_assertions: set[str]) -> None:
    if (
        not isinstance(attestation, dict)
        or attestation.get("schema") != "context-semantic-attestation/v1"
        or attestation.get("operation") != operation
        or attestation.get("input_schema") != input_value.get("schema")
        or attestation.get("input_digest") != canonical_digest(input_value)
    ):
        raise ContextError("semantic_attestation_invalid", "attestation is not bound to the exact semantic input", exit_code=EXIT_CONFLICT)
    assertions = attestation.get("assertions")
    if not isinstance(assertions, list) or {item.get("name") for item in assertions} != expected_assertions:
        raise ContextError("semantic_attestation_invalid", "attestation assertions differ from the owner capability", exit_code=EXIT_CONFLICT)
    for assertion in assertions:
        pointers = assertion.get("evidence_pointers")
        if assertion.get("value") is not True or not isinstance(pointers, list) or not 1 <= len(pointers) <= 4:
            raise ContextError("semantic_attestation_invalid", "attestation assertion is invalid", exit_code=EXIT_CONFLICT)
        for pointer in pointers:
            _json_pointer(input_value, pointer)
    if operation == "same_claim":
        pointers = {pointer for assertion in assertions for pointer in assertion["evidence_pointers"]}
        if not {"/predecessor/primary_claim", "/successor/primary_claim"}.issubset(pointers):
            raise ContextError("semantic_attestation_invalid", "same_claim must cite both primary claims", exit_code=EXIT_CONFLICT)


def _list_section(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _list_section_matches(value: str | None, items: Sequence[str]) -> bool:
    if not isinstance(value, str):
        return False
    actual = [line[2:].strip() if line.startswith("- ") else line.strip() for line in value.splitlines() if line.strip()]
    return actual == list(items)


def _validate_claim_draft(kind: str, candidate: dict[str, Any], draft: dict[str, Any]) -> None:
    owner_inputs = _validate_owner_inputs(kind, candidate.get("owner_inputs", {}).get(kind))
    document = parse_document(draft.get("content", ""))
    frontmatter = document.frontmatter
    if (
        frontmatter.get("schema") != builtin_capability(kind)["artifact_schema"]
        or frontmatter.get("title") != candidate.get("title")
        or frontmatter.get("summary") != candidate.get("summary")
        or frontmatter.get("captured_from") != candidate.get("captured_from")
        or frontmatter.get("source_refs", []) != candidate.get("source_refs", [])
        or frontmatter.get("tags", []) != candidate.get("tags", [])
        or frontmatter.get("search_terms", []) != candidate.get("search_terms", [])
    ):
        raise ContextError("claim_result_mismatch", "claim draft envelope differs from embedded candidate", exit_code=EXIT_CONFLICT)
    if kind == "snapshot":
        expected = {
            "현재 맥락": owner_inputs["current_context"],
            "열린 항목": owner_inputs["open_items"],
            "다음 단계": owner_inputs["next_steps"],
        }
        optional = (("decided", "정해진 것"), ("refs", "참조"), ("capture_candidates", "capture 후보"))
        if frontmatter.get("anchors", []) != owner_inputs.get("anchors", []):
            raise ContextError("claim_result_mismatch", "snapshot anchors differ from embedded candidate", exit_code=EXIT_CONFLICT)
    else:
        primary = owner_inputs["observation"]
        expected = {"관찰": primary, "근거": owner_inputs["evidence"]}
        optional = (("impact", "영향"), ("current_handling", "현재 처리"), ("followup_conditions", "후속 조건"))
        if frontmatter.get("claim_fingerprint") != claim_fingerprint("observation", "", primary):
            raise ContextError("claim_result_mismatch", "observation fingerprint differs from embedded candidate", exit_code=EXIT_CONFLICT)
        if frontmatter.get("kind_hint") != candidate.get("kind_hint"):
            raise ContextError("claim_result_mismatch", "observation kind_hint differs from embedded candidate", exit_code=EXIT_CONFLICT)
        expected_source = claim_fingerprint("decision", candidate.get("scope_hint", ""), candidate["claim"]) if candidate.get("kind_hint") == "decision" else None
        if frontmatter.get("source_claim_fingerprint") != expected_source:
            raise ContextError("claim_result_mismatch", "observation source fingerprint differs from embedded candidate", exit_code=EXIT_CONFLICT)
    for field, section in optional:
        value = owner_inputs.get(field)
        if value:
            expected[section] = value
    if set(document.sections) != set(expected) or any(
        not (_list_section_matches(document.sections.get(section), value) if isinstance(value, list) else document.sections.get(section) == value)
        for section, value in expected.items()
    ):
        raise ContextError("claim_result_mismatch", "claim draft sections differ from embedded owner inputs", exit_code=EXIT_CONFLICT)


def draft_owner_result(
    candidate: dict[str, Any],
    attestation: dict[str, Any],
    *,
    filename: str | None = None,
    identifier: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if candidate.get("schema") != "context-capture-candidate/v1" or candidate.get("requested_kind") not in BUILTIN_AREAS:
        raise ContextError("candidate_invalid", "direct candidate envelope is invalid")
    kind = candidate["requested_kind"]
    if candidate.get("specialized_kinds") != [kind] or candidate.get("fallback_kind") is not None:
        raise ContextError("candidate_invalid", "direct candidate routing fields are invalid")
    inputs = candidate.get("owner_inputs")
    if not isinstance(inputs, dict) or set(inputs) != {kind}:
        raise ContextError("candidate_invalid", "candidate owner_inputs must contain only the target kind")
    owner_inputs = _validate_owner_inputs(kind, inputs[kind])
    capability = builtin_capability(kind)
    _validate_attestation(attestation, "claim", candidate, set(capability["claim_assertions"]))
    created_at = _timestamp(now)
    identifier = identifier or new_context_id()
    _require_context_id(identifier)
    relative = f"context/{kind}/{validate_filename(filename) if filename else natural_filename(candidate['title'])}"
    frontmatter: dict[str, Any] = {
        "schema": capability["artifact_schema"],
        "id": identifier,
        "title": candidate["title"],
        "summary": candidate["summary"],
        "created_at": created_at,
        "captured_from": candidate["captured_from"],
    }
    for field in ("source_refs", "tags", "search_terms"):
        if candidate.get(field):
            frontmatter[field] = list(candidate[field])
    if kind == "snapshot":
        frontmatter["updated_at"] = created_at
        if owner_inputs.get("anchors"):
            frontmatter["anchors"] = owner_inputs["anchors"]
        sections = {
            "현재 맥락": owner_inputs["current_context"],
            "열린 항목": _list_section(owner_inputs["open_items"]),
            "다음 단계": _list_section(owner_inputs["next_steps"]),
        }
        optional_sections = (("decided", "정해진 것"), ("refs", "참조"), ("capture_candidates", "capture 후보"))
    else:
        primary_claim = owner_inputs["observation"]
        frontmatter["claim_fingerprint"] = claim_fingerprint("observation", "", primary_claim)
        if candidate.get("kind_hint") == "decision":
            frontmatter["kind_hint"] = "decision"
            frontmatter["source_claim_fingerprint"] = claim_fingerprint("decision", candidate.get("scope_hint", ""), candidate["claim"])
        sections = {"관찰": primary_claim, "근거": _list_section(owner_inputs["evidence"])}
        optional_sections = (("impact", "영향"), ("current_handling", "현재 처리"), ("followup_conditions", "후속 조건"))
    for field, section in optional_sections:
        value = owner_inputs.get(field)
        if value:
            sections[section] = _list_section(value) if isinstance(value, list) else value
    content = render_document(frontmatter, sections)
    effect_id = f"effect_create_{kind}"
    supporting = owner_inputs.get("evidence", owner_inputs.get("open_items", []))[:4]
    projection = {
        "kind": kind,
        "primary_claim": next(iter(sections.values())),
        "claim_fingerprint": frontmatter.get("claim_fingerprint"),
        "supporting_context": supporting,
    }
    return {
        "schema": "context-owner-result/v1",
        "result_type": "claim",
        "transition": "capture",
        "owner": "context-core",
        "target_kind": kind,
        "candidate_id": candidate["candidate_id"],
        "decision": "claim",
        "reason": "explicit direct capture",
        "capability_digest": canonical_digest(capability),
        "semantic_inputs": [{"operation": "claim", "input_schema": candidate["schema"], "input_digest": canonical_digest(candidate), "value": candidate}],
        "semantic_attestations": [attestation],
        "artifact_drafts": [{"effect_id": effect_id, "path": relative, "content": content, "semantic_projection": projection}],
        "effects": [{"effect_id": effect_id, "action": "create", "area": kind, "id": identifier, "state": "current"}],
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": "capture", "operations": [{"op": "create", "effect_id": effect_id, "area": kind, "path": relative}]},
    }


def _json_pointer(value: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ContextError("semantic_attestation_invalid", "evidence pointer must be RFC 6901")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as error:
                raise ContextError("semantic_attestation_invalid", "evidence pointer does not resolve", {"pointer": pointer}) from error
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ContextError("semantic_attestation_invalid", "evidence pointer does not resolve", {"pointer": pointer})
    if current in (None, "", []):
        raise ContextError("semantic_attestation_invalid", "evidence pointer resolves to an empty value", {"pointer": pointer})
    return current


def validate_owner_result(result: dict[str, Any], capability: dict[str, Any] | None = None) -> None:
    if result.get("schema") != "context-owner-result/v1" or not isinstance(result.get("owner"), str):
        raise ContextError("owner_result_invalid", "owner result envelope is invalid", exit_code=EXIT_CONFLICT)
    missing = {"result_type", "transition", "target_kind", "capability_digest", "semantic_inputs", "semantic_attestations", "artifact_drafts", "effects", "proposed_plan"} - set(result)
    if missing:
        raise ContextError("owner_result_invalid", "owner result required fields are missing", {"missing": sorted(missing)}, EXIT_CONFLICT)
    kind = result["target_kind"]
    if result["owner"] == "context-core":
        capability = builtin_capability(kind)
    if capability is not None:
        if result.get("owner") != capability.get("owner") or kind != capability.get("kind") or result["capability_digest"] != canonical_digest(capability):
            raise ContextError("capability_digest_mismatch", "owner result capability digest is stale", exit_code=EXIT_CONFLICT)
    elif not isinstance(result.get("capability_digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", result["capability_digest"]):
        raise ContextError("capability_digest_mismatch", "owner result capability digest is invalid", exit_code=EXIT_CONFLICT)
    inputs: dict[str, dict[str, Any]] = {}
    for item in result["semantic_inputs"]:
        operation = item.get("operation")
        if operation in inputs or item.get("input_schema") != item.get("value", {}).get("schema") or item.get("input_digest") != canonical_digest(item.get("value")):
            raise ContextError("semantic_input_invalid", "semantic input schema or digest is invalid", exit_code=EXIT_CONFLICT)
        inputs[operation] = item
    attestations: dict[str, dict[str, Any]] = {}
    for attestation in result["semantic_attestations"]:
        operation = attestation.get("operation")
        semantic_input = inputs.get(operation)
        if operation in attestations or semantic_input is None or attestation.get("schema") != "context-semantic-attestation/v1" or attestation.get("input_digest") != semantic_input["input_digest"]:
            raise ContextError("semantic_attestation_invalid", "semantic attestation is not bound to its input", exit_code=EXIT_CONFLICT)
        names: set[str] = set()
        for assertion in attestation.get("assertions", []):
            name = assertion.get("name")
            pointers = assertion.get("evidence_pointers", [])
            if name in names or assertion.get("value") is not True or not 1 <= len(pointers) <= 4:
                raise ContextError("semantic_attestation_invalid", "attestation assertion is invalid", exit_code=EXIT_CONFLICT)
            names.add(name)
            for pointer in pointers:
                _json_pointer(semantic_input["value"], pointer)
        attestations[operation] = attestation
    if result["result_type"] == "claim" and result.get("decision") in {"decline", "needs_clarification"}:
        if (
            result.get("transition") != "capture"
            or set(inputs) != {"claim"}
            or attestations
            or result.get("artifact_drafts")
            or result.get("effects")
            or result.get("proposed_plan") is not None
            or result.get("candidate_id") != inputs["claim"]["value"].get("candidate_id")
        ):
            raise ContextError("owner_result_invalid", "decline/clarification must contain only the exact claim input", exit_code=EXIT_CONFLICT)
        return
    if result["result_type"] == "claim":
        if result.get("decision") != "claim" or result.get("transition") != "capture" or "claim" not in inputs or "claim" not in attestations:
            raise ContextError("owner_result_invalid", "claim result lacks complete claim evidence", exit_code=EXIT_CONFLICT)
        if result.get("candidate_id") != inputs["claim"]["value"].get("candidate_id"):
            raise ContextError("claim_result_mismatch", "claim result candidate does not match embedded input", exit_code=EXIT_CONFLICT)
        if capability is not None:
            expected = set(capability["claim_assertions"])
            actual = {assertion["name"] for assertion in attestations["claim"]["assertions"]}
            if expected != actual:
                raise ContextError("semantic_attestation_invalid", "claim assertions do not match capability", exit_code=EXIT_CONFLICT)
            _validate_attestation(attestations["claim"], "claim", inputs["claim"]["value"], expected)
    elif result["result_type"] == "mutation":
        if "mutation_request" not in inputs or "mutation_request" in attestations:
            raise ContextError("owner_result_invalid", "mutation result lacks an unattested mutation request", exit_code=EXIT_CONFLICT)
        required_inputs = {
            "snapshot_update": {"mutation_request"},
            "observation_annotate": {"mutation_request"},
            "observation_reverify": {"mutation_request"},
            "observation_invalidate": {"mutation_request"},
            "discard": {"mutation_request"},
            "rename": {"mutation_request"},
            "observation_supersede": {"claim", "same_claim", "mutation_request"},
            "decision_fallback_import": {"claim", "same_claim", "mutation_request"},
        }.get(result["transition"])
        if required_inputs is not None and set(inputs) != required_inputs:
            raise ContextError("owner_result_invalid", "mutation semantic input set is incomplete", {"expected": sorted(required_inputs)}, EXIT_CONFLICT)
        if result["transition"] == "observation_supersede":
            if set(attestations) != {"claim", "same_claim"}:
                raise ContextError("semantic_attestation_invalid", "observation supersede requires claim and same_claim attestations", exit_code=EXIT_CONFLICT)
            _validate_attestation(attestations["claim"], "claim", inputs["claim"]["value"], set(builtin_capability("observation")["claim_assertions"]))
            _validate_attestation(attestations["same_claim"], "same_claim", inputs["same_claim"]["value"], {"same_semantic_claim"})
        if result["transition"] == "decision_fallback_import" and set(attestations) != {"claim", "same_claim"}:
            raise ContextError("semantic_attestation_invalid", "fallback import requires claim and same_claim attestations", exit_code=EXIT_CONFLICT)
    else:
        raise ContextError("owner_result_invalid", "result_type is unsupported", exit_code=EXIT_CONFLICT)
    if "claim" in inputs and result["owner"] == "context-core":
        create_ids = {effect.get("effect_id") for effect in result.get("effects", []) if effect.get("action") == "create"}
        claim_drafts = [draft for draft in result.get("artifact_drafts", []) if draft.get("effect_id") in create_ids]
        if len(claim_drafts) != 1:
            raise ContextError("claim_result_mismatch", "embedded claim must bind exactly one create draft", exit_code=EXIT_CONFLICT)
        _validate_claim_draft(kind, inputs["claim"]["value"], claim_drafts[0])
    plan = result["proposed_plan"]
    if plan.get("schema") != "context-owner-plan/v1" or plan.get("transition") != result["transition"]:
        raise ContextError("owner_result_invalid", "owner plan does not match result transition", exit_code=EXIT_CONFLICT)
    drafts = result["artifact_drafts"]
    effects = result["effects"]
    operations = plan.get("operations", [])
    for collection, label in ((drafts, "draft"), (effects, "effect"), (operations, "operation")):
        ids = [item.get("effect_id") for item in collection]
        if any(not LOCAL_ID.fullmatch(str(item)) for item in ids) or len(ids) != len(set(ids)):
            raise ContextError("plan_preview_mismatch", f"{label} effect ids are invalid or duplicate", exit_code=EXIT_CONFLICT)
    effect_ids = {item["effect_id"] for item in effects}
    operation_ids = {item["effect_id"] for item in operations}
    if effect_ids != operation_ids:
        raise ContextError("plan_preview_mismatch", "effects and operations are not 1:1", exit_code=EXIT_CONFLICT)
    draft_ids = {item["effect_id"] for item in drafts}
    for draft in drafts:
        document = parse_document(draft.get("content", ""))
        projection = draft.get("semantic_projection")
        if not isinstance(projection, dict) or set(projection) != {"kind", "primary_claim", "claim_fingerprint", "supporting_context"}:
            raise ContextError("owner_result_invalid", "draft semantic projection is invalid", exit_code=EXIT_CONFLICT)
        draft_kind = {
            "context-snapshot/v1": "snapshot",
            "context-observation/v1": "observation",
            "context-decision/v1": "decision",
        }.get(document.frontmatter.get("schema"))
        if draft_kind != kind and not (
            result["transition"] == "decision_fallback_import"
            and kind == "decision"
            and draft_kind == "observation"
        ):
            raise ContextError("owner_result_invalid", "draft kind escapes the owner transition", exit_code=EXIT_CONFLICT)
        primary_name = {"snapshot": "현재 맥락", "observation": "관찰", "decision": "결정"}.get(draft_kind)
        if (
            primary_name is None
            or projection["kind"] != draft_kind
            or projection["primary_claim"] != document.sections[primary_name]
            or projection["claim_fingerprint"] != document.frontmatter.get("claim_fingerprint")
            or not isinstance(projection["supporting_context"], list)
            or len(projection["supporting_context"]) > 4
        ):
            raise ContextError("owner_result_invalid", "draft semantic projection differs from artifact content", exit_code=EXIT_CONFLICT)
    for operation in operations:
        if operation.get("op") not in {"create", "replace", "move", "delete"}:
            raise ContextError("plan_preview_mismatch", "owner operation is not allowed", exit_code=EXIT_CONFLICT)
        if operation["op"] != "delete" and operation["effect_id"] not in draft_ids:
            raise ContextError("plan_preview_mismatch", "non-delete operation lacks a complete destination draft", exit_code=EXIT_CONFLICT)


def _material(material_id: str, path: str | None, content: str) -> dict[str, Any]:
    return {"material_id": material_id, "path": path, "content": content}


def _bundle_result(preview: dict[str, Any], plan: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
    if len(canonical_json(preview).encode("utf-8")) > MAX_APPROVAL_PREVIEW_BYTES:
        raise ContextError("approval_preview_too_large", "grouped approval preview exceeds 32 KiB; split the candidates", exit_code=EXIT_CONFLICT)
    approval_material = {"preview": preview, "plan": plan}
    digest = canonical_digest(approval_material)
    bundle = {"schema": "context-mutation-bundle/v1", "approval_material": approval_material, "approval_digest": digest, "materials": materials}
    return {"bundle": bundle, "approval_preview": preview, "approval_digest": digest, "applied": False, "noop": False}


def _capture_bundle(repo: pathlib.Path, owner_result: dict[str, Any]) -> dict[str, Any]:
    draft = owner_result["artifact_drafts"][0]
    area = owner_result["target_kind"]
    destination = resolve_artifact_path(repo, area, pathlib.PurePosixPath(draft["path"]).name)
    if destination.relative_to(repo).as_posix() != draft["path"]:
        raise ContextError("path_escape", "owner draft path is not canonical", exit_code=EXIT_CONFLICT)
    identifier = owner_result["effects"][0]["id"]
    try:
        _find_artifact(repo, identifier)
    except ContextError as error:
        if error.code != "artifact_not_found":
            raise
    else:
        raise ContextError("duplicate_id", "owner draft id already exists", {"id": identifier}, EXIT_CONFLICT)
    return finalize_owner_result(repo, owner_result)


def build_snapshot_save_bundle(
    repo: pathlib.Path,
    candidate: dict[str, Any],
    attestation: dict[str, Any],
    *,
    filename: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if candidate.get("requested_kind") != "snapshot":
        raise ContextError("candidate_invalid", "snapshot save requires a snapshot candidate")
    return _capture_bundle(repo, draft_owner_result(candidate, attestation, filename=filename, now=now))


def build_observation_capture_bundle(
    repo: pathlib.Path,
    candidate: dict[str, Any],
    attestation: dict[str, Any],
    *,
    filename: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if candidate.get("requested_kind") != "observation":
        raise ContextError("candidate_invalid", "observation capture requires an observation candidate")
    return _capture_bundle(repo, draft_owner_result(candidate, attestation, filename=filename, now=now))


def _semantic_projection(kind: str, document: Document) -> dict[str, Any]:
    primary_name = "현재 맥락" if kind == "snapshot" else "관찰"
    supporting_name = "열린 항목" if kind == "snapshot" else "근거"
    supporting = [line[2:].strip() for line in document.sections.get(supporting_name, "").splitlines() if line.startswith("- ")][:4]
    return {
        "kind": kind,
        "primary_claim": document.sections[primary_name],
        "claim_fingerprint": document.frontmatter.get("claim_fingerprint"),
        "supporting_context": supporting,
    }


def _mutation_request(
    transition: str,
    kind: str,
    requested_changes: dict[str, Any],
    targets: Sequence[tuple[pathlib.Path, Document]],
    repo: pathlib.Path,
    *,
    successor_owner_result_digest: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "context-domain-mutation-input/v1",
        "transition": transition,
        "owner": "context-core",
        "target_kind": kind,
        "requested_changes": requested_changes,
        "targets": sorted(
            (
                {
                    "id": document.frontmatter["id"],
                    "path": path.relative_to(repo).as_posix(),
                    "sha256": sha256_bytes(path.read_bytes()),
                }
                for path, document in targets
            ),
            key=lambda item: item["path"],
        ),
        "successor_owner_result_digest": successor_owner_result_digest,
    }


def _mutation_result(
    kind: str,
    transition: str,
    request: dict[str, Any],
    drafts: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    *,
    extra_inputs: Sequence[dict[str, Any]] = (),
    attestations: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    inputs = list(extra_inputs) + [{"operation": "mutation_request", "input_schema": request["schema"], "input_digest": canonical_digest(request), "value": request}]
    return {
        "schema": "context-owner-result/v1",
        "result_type": "mutation",
        "transition": transition,
        "owner": "context-core",
        "target_kind": kind,
        "capability_digest": canonical_digest(builtin_capability(kind)),
        "semantic_inputs": inputs,
        "semantic_attestations": list(attestations),
        "artifact_drafts": drafts,
        "effects": effects,
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": transition, "operations": operations},
    }


def _artifact_in_area(repo: pathlib.Path, identifier: str, area: str, *, current_only: bool = False) -> tuple[pathlib.Path, Document]:
    found_area, path, document = _find_artifact(repo, identifier)
    if found_area != area or (current_only and "/retired/" in path.relative_to(repo).as_posix()):
        raise ContextError("artifact_state_invalid", f"artifact is not a current {area}", {"id": identifier}, EXIT_CONFLICT)
    return path, document


def _validate_update_values(
    *,
    title: str | None,
    summary: str | None,
    tags: Sequence[str] | None,
    search_terms: Sequence[str] | None,
    source_refs: Sequence[str] | None,
    anchors: Sequence[str] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if title is not None:
        if not _substantive(title) or "\n" in title or len(title) > 120:
            raise ContextError("schema_invalid", "title is invalid")
        values["title"] = nfc(title.strip())
    if summary is not None:
        if not _substantive(summary) or "\n" in summary or len(summary) > 280:
            raise ContextError("schema_invalid", "summary is invalid")
        values["summary"] = nfc(summary.strip())
    for field, raw, maximum, item_maximum in (
        ("tags", tags, 12, 40),
        ("search_terms", search_terms, 12, 40),
        ("source_refs", source_refs, 12, 500),
        ("anchors", anchors, 12, 36),
    ):
        if raw is not None:
            values[field] = _string_list(list(raw), field, maximum=maximum, item_maximum=item_maximum)
    for identifier in values.get("anchors", []):
        _require_context_id(identifier, "anchors")
    return values


def build_snapshot_update_bundle(
    repo: pathlib.Path,
    identifier: str,
    *,
    merge: bool = False,
    sections: dict[str, str] | None = None,
    title: str | None = None,
    summary: str | None = None,
    tags: Sequence[str] | None = None,
    search_terms: Sequence[str] | None = None,
    source_refs: Sequence[str] | None = None,
    anchors: Sequence[str] | None = None,
    clear: Sequence[str] = (),
    now: str | None = None,
) -> dict[str, Any]:
    path, document = _artifact_in_area(repo, identifier, "snapshot", current_only=True)
    sections = dict(sections or {})
    allowed, required = SECTION_SPECS["context-snapshot/v1"]
    if set(sections) - set(allowed):
        raise ContextError("section_schema_error", "snapshot update contains an unknown section")
    if not merge and not set(required).issubset(sections):
        raise ContextError("snapshot_full_update_required", "full snapshot update requires all required sections", {"required": list(required)})
    for name, content in sections.items():
        if name in required and not _substantive(content):
            raise ContextError("section_schema_error", "required snapshot section is not substantive", {"section": name})
    clear_set = set(clear)
    if clear_set - {"anchors", "tags", "search_terms", "source_refs"}:
        raise ContextError("usage_invalid", "snapshot clear target is invalid")
    updates = _validate_update_values(title=title, summary=summary, tags=tags, search_terms=search_terms, source_refs=source_refs, anchors=anchors)
    frontmatter = dict(document.frontmatter)
    for field in clear_set:
        frontmatter.pop(field, None)
    frontmatter.update(updates)
    if merge:
        next_sections = dict(document.sections)
        next_sections.update(sections)
    else:
        next_sections = {name: sections[name] for name in required}
        next_sections.update({name: sections[name] for name in allowed if name not in required and name in sections})
        for field in ("anchors", "tags", "search_terms", "source_refs"):
            if field not in updates and field not in clear_set:
                frontmatter.pop(field, None)
    comparison_frontmatter = dict(frontmatter)
    comparison_frontmatter["updated_at"] = document.frontmatter["updated_at"]
    comparison_content = render_document(comparison_frontmatter, next_sections)
    current_content = render_document(document.frontmatter, document.sections)
    if file_bytes(comparison_content) == file_bytes(current_content):
        return {"noop": True, "applied": False, "changed_paths": []}
    frontmatter["updated_at"] = _timestamp(now)
    after_content = render_document(frontmatter, next_sections)
    relative = path.relative_to(repo).as_posix()
    request = _mutation_request(
        "snapshot_update",
        "snapshot",
        {"merge": merge, "sections": sections, "metadata": updates, "clear": sorted(clear_set)},
        [(path, document)],
        repo,
    )
    effect_id = "effect_update_snapshot"
    result = _mutation_result(
        "snapshot",
        "snapshot_update",
        request,
        [{"effect_id": effect_id, "path": relative, "content": after_content, "semantic_projection": _semantic_projection("snapshot", Document(frontmatter, next_sections))}],
        [{"effect_id": effect_id, "action": "replace", "area": "snapshot", "id": identifier, "state": "current"}],
        [{"op": "replace", "effect_id": effect_id, "area": "snapshot", "id": identifier, "path": relative}],
    )
    return finalize_owner_result(repo, result)


def _read_artifact(repo: pathlib.Path, identifier: str, area: str, sections: Sequence[str] = ()) -> dict[str, Any]:
    path, document = _artifact_in_area(repo, identifier, area)
    selected = sections or tuple(document.sections)
    result: dict[str, Any] = {
        "artifact": dict(document.frontmatter),
        "path": path.relative_to(repo).as_posix(),
        "sections": {name: document.sections[name] for name in selected if name in document.sections},
        "authority": "staging" if area == "snapshot" else "evidence",
        "truncated": False,
    }
    if area == "snapshot":
        result["use_as"] = "resume_context"
        anchors = document.frontmatter.get("anchors", [])
        warnings: list[str] = []
        if not anchors:
            freshness = "authority_unknown"
        else:
            freshness = "anchored"
            for anchor in anchors:
                try:
                    _, anchor_path, _ = _find_artifact(repo, anchor)
                    if "/retired/" in anchor_path.relative_to(repo).as_posix():
                        freshness = "anchor_changed"
                except ContextError:
                    freshness = "anchor_changed"
            if freshness == "anchor_changed":
                warnings.append("anchor_changed")
        result.update({"freshness": freshness, "warnings": warnings})
    else:
        result["use_as"] = "investigate_or_support"
        result["state"] = "history" if "/retired/" in result["path"] else "current"
    return result


def snapshot_load(repo: pathlib.Path, identifier: str, sections: Sequence[str] = ()) -> dict[str, Any]:
    return _read_artifact(repo, identifier, "snapshot", sections)


def snapshot_list(repo: pathlib.Path, limit: int = 8) -> dict[str, Any]:
    return recall_repository(repo, areas=["snapshot"], limit=limit)


def snapshot_search(repo: pathlib.Path, query: str, limit: int = 8) -> dict[str, Any]:
    return recall_repository(repo, query=query, areas=["snapshot"], limit=limit)


def build_snapshot_discard_bundle(repo: pathlib.Path, identifier: str) -> dict[str, Any]:
    path, _ = _artifact_in_area(repo, identifier, "snapshot", current_only=True)
    del path
    return build_discard_bundle(repo, identifier)


def build_init_bundle(repo: pathlib.Path) -> dict[str, Any]:
    root_path = repo / "context"
    paths = [repo / ROOT_INDEX, repo / "context/snapshot/snapshot.index.md", repo / "context/observation/observation.index.md"]
    existing = [path.is_file() for path in paths]
    if all(existing):
        try:
            _, areas = parse_root_index(paths[0].read_text(encoding="utf-8"))
            rows = {row["area"]: row for row in areas}
            expected = {item[0]["area"]: item[0] for item in _builtin_area_specs()}
            indexes = {
                "snapshot": parse_area_index(paths[1].read_text(encoding="utf-8")),
                "observation": parse_area_index(paths[2].read_text(encoding="utf-8")),
            }
            descriptors_match = all(
                rows.get(area) == descriptor
                and {
                    "area": indexes[area].frontmatter["area"],
                    "path": f"context/{area}/{area}.index.md",
                    "owner": indexes[area].frontmatter["owner"],
                    "claims": [area],
                    "artifact_schema": indexes[area].frontmatter["artifact_schema"],
                    "authority": indexes[area].frontmatter["authority"],
                } == descriptor
                for area, descriptor in expected.items()
            )
            integrity = refresh_repository(repo, strict=True)
            if descriptors_match and integrity["ok"]:
                return {"noop": True, "applied": False, "changed_paths": []}
        except (ContextError, OSError, UnicodeError):
            pass
        raise ContextError("partial_core_init", "context root is partially initialized", exit_code=EXIT_CONFLICT)
    allowed_empty = {root_path, root_path / "snapshot", root_path / "observation", root_path / "observation/retired"}
    present_files = [path for path in root_path.rglob("*") if path.is_file()] if root_path.exists() else []
    present_nonempty = [path for path in root_path.rglob("*") if path.is_dir() and path not in allowed_empty and any(path.iterdir())] if root_path.exists() else []
    if any(existing) or present_files or present_nonempty:
        raise ContextError("partial_core_init", "context root is partially initialized", exit_code=EXIT_CONFLICT)
    snapshot = _area_seed("snapshot", "context-core", "context-snapshot/v1", "staging", "session handoff staging", search_terms=("handoff", "resume"))
    observation = _area_seed("observation", "context-core", "context-observation/v1", "evidence", "비권위 발견과 근거", search_terms=("observation", "evidence"))
    root = render_root_index(_root_seed(), _builtin_area_specs())
    contents = {ROOT_INDEX: root, "context/snapshot/snapshot.index.md": snapshot, "context/observation/observation.index.md": observation}
    materials = [_material(f"seed_{path.split('/')[-2] if path != ROOT_INDEX else 'root'}", path, content) for path, content in contents.items()]
    material_ids = {material["path"]: material["material_id"] for material in materials}
    before = {path: None for path in contents}
    after = {path: sha256_bytes(file_bytes(content)) for path, content in contents.items()}
    effect_id = "effect_core_init"
    plan = {
        "schema": "context-mutation-plan/v1", "plan_id": new_plan_id(), "owner": "context-core", "source_type": "core_control",
        "transition": "core_init", "owner_descriptor": {"owner": "context-core", "kind": "storage", "artifact_schema": "context-common/v1"},
        "control_input": {"schema": "context-core-control/v1", "transition": "core_init", "seed_digests": {path: sha256_bytes(file_bytes(contents[path])) for path in sorted(contents)}},
        "prior_bundle_digests": [], "read_preconditions": [],
        "operations": [{"op": "index_rebuild", "derived_from": [effect_id], "areas": ["observation", "snapshot"], "include_root": True, "before_sha256": before, "after_sha256": after, "seed_materials": material_ids}],
    }
    preview = {"schema": "context-approval-preview/v1", "owner": "context-core", "candidate_id": None, "artifacts": [], "effects": [{"effect_id": effect_id, "action": "initialize_core", "paths": sorted(contents)}]}
    return _bundle_result(preview, plan, materials)


def _root_catalog(repo: pathlib.Path) -> tuple[str, list[dict[str, Any]]]:
    path = repo / ROOT_INDEX
    if not path.is_file():
        raise ContextError("context_root_missing", "context root index is missing", {"path": ROOT_INDEX}, EXIT_NOT_FOUND)
    text = path.read_text(encoding="utf-8")
    _, rows = parse_root_index(text)
    return text, rows


def build_area_register_bundle(repo: pathlib.Path, descriptor: dict[str, Any], index_seed: str | None) -> dict[str, Any]:
    if index_seed is None:
        raise ContextError("index_seed_required", "area registration requires a complete index seed", exit_code=EXIT_CONFLICT)
    owner = descriptor.get("owner")
    area = descriptor.get("kind")
    schema = descriptor.get("artifact_schema")
    authority = descriptor.get("authority")
    if not all(isinstance(value, str) and value for value in (owner, area, schema, authority)) or not AREA_NAME.fullmatch(area):
        raise ContextError("owner_descriptor_invalid", "area owner descriptor is invalid", exit_code=EXIT_CONFLICT)
    seed_index = parse_area_index(index_seed)
    if seed_index.current or seed_index.history:
        raise ContextError("index_seed_invalid", "area seed generated blocks must be empty", exit_code=EXIT_CONFLICT)
    fm = seed_index.frontmatter
    if (fm["area"], fm["owner"], fm["artifact_schema"], fm["authority"]) != (area, owner, schema, authority):
        raise ContextError("index_seed_invalid", "area seed does not match descriptor", exit_code=EXIT_CONFLICT)
    root_text, rows = _root_catalog(repo)
    if any(row["area"] == area or area in row["claims"] for row in rows):
        existing = next(row for row in rows if row["area"] == area)
        path = repo / existing["path"]
        if existing["owner"] == owner and path.is_file():
            parse_area_index(path.read_text(encoding="utf-8"))
            return {"noop": True, "applied": False, "changed_paths": []}
        raise ContextError("duplicate_area_owner", "area or claim is already owned", exit_code=EXIT_CONFLICT)
    area_path = f"context/{area}/{area}.index.md"
    row = {"area": area, "path": area_path, "owner": owner, "claims": [area], "artifact_schema": schema, "authority": authority}
    specs: list[tuple[dict[str, Any], str, str]] = []
    for existing in rows:
        index = parse_area_index((repo / existing["path"]).read_text(encoding="utf-8"))
        specs.append((existing, _area_label(existing["area"]), index.frontmatter["summary"]))
    specs.append((row, _area_label(area), fm["summary"]))
    root_after = render_root_index(root_text, specs)
    contents = {ROOT_INDEX: root_after, area_path: index_seed}
    materials = [_material("material_root_index", ROOT_INDEX, root_after), _material("seed_area_index", area_path, index_seed)]
    effect_id = "effect_register_area"
    plan = {
        "schema": "context-mutation-plan/v1", "plan_id": new_plan_id(), "owner": owner, "source_type": "core_control", "transition": "area_register",
        "owner_descriptor": descriptor, "control_input": {"schema": "context-core-control/v1", "transition": "area_register", "descriptor_digest": canonical_digest(descriptor), "seed_digests": {area_path: sha256_bytes(file_bytes(index_seed))}},
        "prior_bundle_digests": [], "read_preconditions": [],
        "operations": [{"op": "index_rebuild", "derived_from": [effect_id], "areas": [area], "include_root": True, "before_sha256": {ROOT_INDEX: sha256_bytes((repo / ROOT_INDEX).read_bytes()), area_path: None}, "after_sha256": {path: sha256_bytes(file_bytes(content)) for path, content in contents.items()}, "seed_materials": {area_path: "seed_area_index"}}],
    }
    preview = {"schema": "context-approval-preview/v1", "owner": owner, "candidate_id": None, "artifacts": [], "effects": [{"effect_id": effect_id, "action": "register_area", "area": area, "path": area_path}]}
    return _bundle_result(preview, plan, materials)


def build_policy_bundle(repo: pathlib.Path, target: str) -> dict[str, Any]:
    if target not in POLICY_TARGETS or pathlib.PurePosixPath(target).name != target:
        raise ContextError("policy_target_invalid", "policy target must be exact repository-root AGENTS.md or CLAUDE.md", {"target": target}, EXIT_CONFLICT)
    path = _ensure_contained(repo, target)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ContextError("policy_file_unsupported", "policy target must be a regular root file", {"target": target}, EXIT_CONFLICT)
    before_bytes: bytes | None = path.read_bytes() if path.exists() else None
    before = before_bytes.decode("utf-8") if before_bytes is not None else ""
    if "\r\n" in before and before.replace("\r\n", "").find("\n") >= 0:
        raise ContextError("policy_file_unsupported", "mixed newlines are not supported", {"target": target}, EXIT_CONFLICT)
    if before.count(POLICY_BEGIN) != before.count(POLICY_END) or before.count(POLICY_BEGIN) > 1:
        raise ContextError("policy_marker_invalid", "policy marker must be absent or one balanced pair", {"target": target}, EXIT_CONFLICT)
    newline = "\r\n" if "\r\n" in before else "\n"
    policy_body = POLICY_BODY.replace("\n", newline)
    if POLICY_BEGIN in before:
        start = before.index(POLICY_BEGIN)
        end = before.index(POLICY_END, start) + len(POLICY_END)
        after = before[:start] + policy_body + before[end:]
    elif before:
        separator = "" if before.endswith(newline + newline) else (newline if before.endswith(newline) else newline + newline)
        after = before + separator + policy_body + newline
    else:
        after = policy_body + newline
    if after == before:
        return {"noop": True, "applied": False, "changed_paths": []}
    effect_id = "effect_install_policy"
    material_id = "material_policy"
    before_digest = sha256_bytes(before_bytes) if before_bytes is not None else None
    after_digest = sha256_bytes(after.encode("utf-8"))
    operation = {
        "op": "file_replace" if before_bytes is not None else "file_create",
        "effect_id": effect_id,
        "role": "policy",
        "path": target,
        "before_sha256": before_digest,
        "after_sha256": after_digest,
        "material": material_id,
    }
    plan = {
        "schema": "context-mutation-plan/v1", "plan_id": new_plan_id(), "owner": "context-core", "source_type": "core_control",
        "transition": "policy_install", "owner_descriptor": {"owner": "context-core", "kind": "policy", "artifact_schema": "context-policy/v1"},
        "control_input": {
            "schema": "context-core-control/v1", "transition": "policy_install", "target": target,
            "before_sha256": before_digest, "outside_bytes_sha256": sha256_bytes((before[:before.find(POLICY_BEGIN)] + before[before.find(POLICY_END) + len(POLICY_END):]).encode("utf-8")) if POLICY_BEGIN in before else sha256_bytes(before.encode("utf-8")),
        },
        "prior_bundle_digests": [], "read_preconditions": [], "operations": [operation],
    }
    preview = {
        "schema": "context-approval-preview/v1", "owner": "context-core", "candidate_id": None,
        "artifacts": [{"effect_id": effect_id, "path": target, "content": after}],
        "effects": [{"effect_id": effect_id, "action": "install_policy", "path": target}],
    }
    return _bundle_result(preview, plan, [_material(material_id, target, after)])


def _area_for_owner(repo: pathlib.Path, area: str, owner: str) -> tuple[dict[str, Any], AreaIndex]:
    _, rows = _root_catalog(repo)
    matches = [row for row in rows if row["area"] == area]
    if len(matches) != 1 or matches[0]["owner"] != owner:
        raise ContextError("area_owner_mismatch", "owner is not authorized for target area", {"owner": owner, "area": area}, EXIT_CONFLICT)
    parsed = parse_area_index((repo / matches[0]["path"]).read_text(encoding="utf-8"))
    return matches[0], parsed


def _virtual_area_index(index: AreaIndex, effects: Sequence[dict[str, Any]], drafts: dict[str, dict[str, Any]]) -> str:
    current = {row["id"]: dict(row) for row in index.current}
    history = {row["id"]: dict(row) for row in index.history}
    metadata = index.frontmatter
    for effect in effects:
        identifier = effect.get("id")
        action = effect.get("action")
        if action in {"create", "replace", "rename", "retire", "move"}:
            draft = drafts.get(effect["effect_id"])
            if draft is None:
                raise ContextError("plan_preview_mismatch", "effect lacks destination draft", exit_code=EXIT_CONFLICT)
            document = parse_document(draft["content"])
            path = pathlib.Path("/") / draft["path"]
            fake_repo = pathlib.Path("/")
            row = {
                "id": document.frontmatter["id"], "path": draft["path"], "title": document.frontmatter["title"],
                "summary": document.frontmatter["summary"], "state": "history" if "/retired/" in draft["path"] else "current",
                "created_at": document.frontmatter["created_at"],
            }
            if "updated_at" in document.frontmatter:
                row["updated_at"] = document.frontmatter["updated_at"]
            row["terms"] = _terms(document.frontmatter)
            del path, fake_repo
            if row["state"] == "history":
                row["retired_at"] = document.frontmatter["retired_at"]
                row["retired_reason"] = document.frontmatter["retired_reason"]
                if "superseded_by" in document.frontmatter:
                    row["superseded_by"] = document.frontmatter["superseded_by"]
            for key in metadata.get("projection_fields", []):
                if key in document.frontmatter:
                    row[key] = document.frontmatter[key]
            if row["state"] == "history":
                current.pop(identifier, None)
                history[identifier] = row
            else:
                history.pop(identifier, None)
                current[identifier] = row
        elif action == "delete":
            current.pop(identifier, None)
            history.pop(identifier, None)
        else:
            raise ContextError("plan_preview_mismatch", "effect action is unsupported", {"action": action}, EXIT_CONFLICT)
    current_rows = sorted(current.values(), key=lambda row: (row["created_at"], row["id"]))
    history_rows = sorted(history.values(), key=lambda row: (row["created_at"], row["id"]))
    text = _replace_block(index.text, "current", [_entry_row(row) for row in current_rows])
    if metadata["area"] != "snapshot":
        text = _replace_block(text, "history", [_entry_row(row) for row in history_rows])
    return text


def _bundle_owner_result(bundle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if bundle.get("schema") != "context-mutation-bundle/v1" or bundle.get("approval_digest") != canonical_digest(bundle.get("approval_material")):
        raise ContextError("prior_bundle_invalid", "prior bundle digest is invalid", exit_code=EXIT_CONFLICT)
    plan = bundle["approval_material"].get("plan", {})
    material = next((item for item in bundle.get("materials", []) if item.get("material_id") == plan.get("owner_result_material")), None)
    if plan.get("source_type") != "owner_result" or material is None or material.get("path") is not None:
        raise ContextError("prior_bundle_invalid", "prior bundle lacks owner result material", exit_code=EXIT_CONFLICT)
    try:
        result = json.loads(material["content"])
    except json.JSONDecodeError as error:
        raise ContextError("prior_bundle_invalid", "prior owner result is not JSON", exit_code=EXIT_CONFLICT) from error
    if canonical_json(result) != material["content"] or sha256_bytes(material["content"].encode("utf-8")) != plan.get("owner_result_digest"):
        raise ContextError("prior_bundle_invalid", "prior owner result material changed", exit_code=EXIT_CONFLICT)
    validate_owner_result(result)
    return plan, result


def _validate_owner_validation(
    owner_result: dict[str, Any],
    validation: dict[str, Any] | None,
    area_index: AreaIndex,
    same_area_prior_digests: Sequence[str],
) -> None:
    requires = owner_result["owner"] != "context-core"
    if not requires and validation is None:
        return
    if not isinstance(validation, dict):
        raise ContextError("owner_validation_required", "addon owner result requires a batch validation receipt", exit_code=EXIT_CONFLICT)
    expected = dict(validation)
    receipt_digest = expected.pop("receipt_digest", None)
    if (
        validation.get("schema") != "context-owner-validation-receipt/v1"
        or validation.get("owner") != owner_result["owner"]
        or validation.get("kind") != owner_result["target_kind"]
        or validation.get("owner_result_digest") != canonical_digest(owner_result)
        or validation.get("base_area_index_sha256") != sha256_bytes(area_index.text.encode("utf-8"))
        or validation.get("prior_same_area_bundle_digests") != list(same_area_prior_digests)
        or validation.get("status") != "valid"
        or receipt_digest != canonical_digest(expected)
    ):
        raise ContextError("owner_validation_invalid", "owner validation receipt is stale or malformed", exit_code=EXIT_CONFLICT)


def finalize_owner_result(repo: pathlib.Path, owner_result: dict[str, Any], owner_validation: dict[str, Any] | None = None, prior_bundles: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    validate_owner_result(owner_result)
    owner = owner_result["owner"]
    primary_area = owner_result["target_kind"]
    area_row, physical_area_index = _area_for_owner(repo, primary_area, owner)
    prior_digests: list[str] = []
    same_area_prior_digests: list[str] = []
    virtual_text = physical_area_index.text
    for prior in prior_bundles:
        prior_plan, prior_result = _bundle_owner_result(prior)
        if prior_plan.get("prior_bundle_digests") != prior_digests:
            raise ContextError("prior_bundle_order_invalid", "prior bundle chain differs from exact proposal order", exit_code=EXIT_CONFLICT)
        prior_digest = prior["approval_digest"]
        prior_digests.append(prior_digest)
        if primary_area in {effect.get("area") for effect in prior_result.get("effects", [])}:
            prior_effects = [effect for effect in prior_result["effects"] if effect.get("area") == primary_area]
            prior_drafts = {draft["effect_id"]: draft for draft in prior_result["artifact_drafts"] if any(effect["effect_id"] == draft["effect_id"] for effect in prior_effects)}
            virtual_index = AreaIndex(physical_area_index.frontmatter, parse_area_index(virtual_text).current, parse_area_index(virtual_text).history, virtual_text)
            virtual_text = _virtual_area_index(virtual_index, prior_effects, prior_drafts)
            same_area_prior_digests.append(prior_digest)
    _validate_owner_validation(owner_result, owner_validation, physical_area_index, same_area_prior_digests)
    read_preconditions = owner_result["proposed_plan"].get("read_preconditions", [])
    if len({item.get("path") for item in read_preconditions}) != len(read_preconditions):
        raise ContextError("read_precondition_invalid", "owner read preconditions contain duplicate paths", exit_code=EXIT_CONFLICT)
    for precondition in read_preconditions:
        if set(precondition) != {"id", "path", "sha256"}:
            raise ContextError("read_precondition_invalid", "owner read precondition shape is invalid", exit_code=EXIT_CONFLICT)
        target = _ensure_contained(repo, precondition["path"])
        if not target.is_file() or sha256_bytes(target.read_bytes()) != precondition["sha256"]:
            raise ContextError("precondition_changed", "owner read precondition is stale", {"path": precondition["path"]}, EXIT_CONFLICT)
    area_indexes: dict[str, AreaIndex] = {primary_area: AreaIndex(physical_area_index.frontmatter, parse_area_index(virtual_text).current, parse_area_index(virtual_text).history, virtual_text)}
    for area in sorted({effect.get("area") for effect in owner_result["effects"] if isinstance(effect.get("area"), str)} - {primary_area}):
        if owner_result["transition"] != "decision_fallback_import" or area != "observation" or owner != "context-decision":
            raise ContextError("area_owner_mismatch", "cross-owner area is not allowlisted", {"area": area}, EXIT_CONFLICT)
        _, area_indexes[area] = _area_for_owner(repo, area, "context-core")
    drafts = {draft["effect_id"]: draft for draft in owner_result["artifact_drafts"]}
    effects = {effect["effect_id"]: effect for effect in owner_result["effects"]}
    operations: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    owner_material_id = "material_owner_result"
    owner_content = canonical_json(owner_result)
    owner_digest = sha256_bytes(owner_content.encode("utf-8"))
    materials.append(_material(owner_material_id, None, owner_content))
    vacated_paths = {
        operation["from_path"]
        for operation in owner_result["proposed_plan"]["operations"]
        if operation.get("op") == "move"
    }
    for proposed in owner_result["proposed_plan"]["operations"]:
        effect_id = proposed["effect_id"]
        effect = effects[effect_id]
        area = effect.get("area")
        if area not in area_indexes:
            raise ContextError("area_owner_mismatch", "owner plan touches an unauthorized area", exit_code=EXIT_CONFLICT)
        authorized_owner = owner if area == primary_area else "context-core"
        area_record, _ = _area_for_owner(repo, area, authorized_owner)
        operation = proposed["op"]
        draft = drafts.get(effect_id)
        if operation != "delete":
            assert draft is not None
            relative = draft["path"]
            if not relative.startswith(f"context/{area}/") or relative in RESERVED_INDEX_PATHS:
                raise ContextError("path_escape", "draft path is outside the owner area", {"path": relative}, EXIT_CONFLICT)
            _ensure_contained(repo, relative)
            document = parse_document(draft["content"])
            if document.frontmatter["schema"] != area_record["artifact_schema"] or document.frontmatter["id"] != effect.get("id"):
                raise ContextError("plan_preview_mismatch", "draft schema/id does not match effect", exit_code=EXIT_CONFLICT)
            material_id = f"material_{effect_id}"
            materials.append(_material(material_id, relative, draft["content"]))
            after = sha256_bytes(file_bytes(draft["content"]))
        if operation == "create":
            path = proposed["path"]
            if path != draft["path"]:
                raise ContextError("plan_preview_mismatch", "create path and draft differ", exit_code=EXIT_CONFLICT)
            current = repo / path
            if current.exists() and path not in vacated_paths:
                raise ContextError("path_exists", "create target already exists", {"path": path}, EXIT_CONFLICT)
            operations.append({"op": "file_create", "effect_id": effect_id, "role": "artifact", "area": area, "path": path, "before_sha256": None, "after_sha256": after, "material": material_id})
        elif operation == "replace":
            path = proposed["path"]
            target = repo / path
            if not target.is_file():
                raise ContextError("artifact_not_found", "replace target is missing", {"path": path}, EXIT_NOT_FOUND)
            operations.append({"op": "file_replace", "effect_id": effect_id, "role": "artifact", "area": area, "id": effect["id"], "path": path, "before_sha256": sha256_bytes(target.read_bytes()), "after_sha256": after, "material": material_id})
        elif operation == "move":
            source = proposed["from_path"]
            destination = proposed["to_path"]
            if destination != draft["path"]:
                raise ContextError("plan_preview_mismatch", "move destination and draft differ", exit_code=EXIT_CONFLICT)
            source_path = repo / source
            if not source_path.is_file() or (repo / destination).exists():
                raise ContextError("precondition_changed", "move start state is unavailable", exit_code=EXIT_CONFLICT)
            before = sha256_bytes(source_path.read_bytes())
            move: dict[str, Any] = {"op": "file_move", "effect_id": effect_id, "role": "artifact", "area": area, "id": effect["id"], "from_path": source, "to_path": destination, "before_sha256": before, "destination_before_sha256": None, "after_sha256": after}
            if after != before:
                move["material"] = material_id
            else:
                materials = [item for item in materials if item["material_id"] != material_id]
            operations.append(move)
        elif operation == "delete":
            path = proposed["path"]
            target = repo / path
            if not target.is_file():
                raise ContextError("artifact_not_found", "delete target is missing", {"path": path}, EXIT_NOT_FOUND)
            operations.append({"op": "file_delete", "effect_id": effect_id, "role": "artifact", "area": area, "id": effect["id"], "path": path, "before_sha256": sha256_bytes(target.read_bytes()), "inbound_refs": []})
        else:
            raise ContextError("plan_preview_mismatch", "unsupported owner operation", exit_code=EXIT_CONFLICT)
    touched_areas = sorted(area_indexes)
    index_before: dict[str, str] = {}
    index_after: dict[str, str] = {}
    for area in touched_areas:
        matching_effects = [effect for effect in effects.values() if effect.get("area") == area]
        matching_drafts = {key: value for key, value in drafts.items() if any(effect["effect_id"] == key for effect in matching_effects)}
        index = area_indexes[area]
        path = f"context/{area}/{area}.index.md"
        index_before[path] = sha256_bytes(index.text.encode("utf-8"))
        index_after[path] = sha256_bytes(file_bytes(_virtual_area_index(index, matching_effects, matching_drafts)))
    operations.append({"op": "index_rebuild", "derived_from": sorted(effects), "areas": touched_areas, "include_root": False, "before_sha256": index_before, "after_sha256": index_after})
    plan = {
        "schema": "context-mutation-plan/v1", "plan_id": new_plan_id(), "owner": owner, "source_type": "owner_result",
        "owner_result_digest": owner_digest, "owner_result_material": owner_material_id, "capability_digest": owner_result["capability_digest"],
        "transition": owner_result["transition"], "owner_descriptor": {"owner": owner, "kind": primary_area, "artifact_schema": area_row["artifact_schema"], "authority": area_row["authority"]},
        "owner_validation": owner_validation, "prior_bundle_digests": prior_digests,
        "read_preconditions": owner_result["proposed_plan"].get("read_preconditions", []), "operations": operations,
    }
    preview = {"schema": "context-approval-preview/v1", "owner": owner, "candidate_id": owner_result.get("candidate_id"), "artifacts": [{"effect_id": draft["effect_id"], "path": draft["path"], "content": draft["content"]} for draft in owner_result["artifact_drafts"]], "effects": owner_result["effects"]}
    return _bundle_result(preview, plan, materials)


def _find_artifact(repo: pathlib.Path, identifier: str) -> tuple[str, pathlib.Path, Document]:
    _require_context_id(identifier)
    _, areas = _root_catalog(repo)
    found: list[tuple[str, pathlib.Path, Document]] = []
    for area in areas:
        for path, _ in _scan_area_paths(repo, area["area"]):
            try:
                document = parse_document(path.read_text(encoding="utf-8"))
            except ContextError:
                continue
            if document.frontmatter["id"] == identifier:
                found.append((area["area"], path, document))
    if not found:
        raise ContextError("artifact_not_found", "artifact id was not found", {"id": identifier}, EXIT_NOT_FOUND)
    if len(found) > 1:
        raise ContextError("duplicate_id", "artifact id is duplicated", {"id": identifier}, EXIT_INTEGRITY)
    return found[0]


def build_rename_bundle(repo: pathlib.Path, identifier: str, filename: str) -> dict[str, Any]:
    area, source, document = _find_artifact(repo, identifier)
    relative_source = source.relative_to(repo).as_posix()
    destination = resolve_artifact_path(repo, area, filename, existing_path=relative_source)
    relative_destination = destination.relative_to(repo).as_posix()
    capability = builtin_capability(area)
    request = {"schema": "context-domain-mutation-input/v1", "transition": "rename", "owner": "context-core", "target_kind": area, "requested_changes": {"filename": destination.name}, "targets": [{"id": identifier, "path": relative_source, "sha256": sha256_bytes(source.read_bytes())}], "successor_owner_result_digest": None}
    request_digest = canonical_digest(request)
    effect_id = "effect_rename_artifact"
    result = {
        "schema": "context-owner-result/v1", "result_type": "mutation", "transition": "rename", "owner": "context-core", "target_kind": area,
        "capability_digest": canonical_digest(capability),
        "semantic_inputs": [{"operation": "mutation_request", "input_schema": request["schema"], "input_digest": request_digest, "value": request}],
        "semantic_attestations": [],
        "artifact_drafts": [{"effect_id": effect_id, "path": relative_destination, "content": render_document(document.frontmatter, document.sections), "semantic_projection": {"kind": area, "primary_claim": next(iter(document.sections.values())), "claim_fingerprint": document.frontmatter.get("claim_fingerprint"), "supporting_context": []}}],
        "effects": [{"effect_id": effect_id, "action": "rename", "area": area, "id": identifier, "state": "history" if "/retired/" in relative_source else "current"}],
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": "rename", "operations": [{"op": "move", "effect_id": effect_id, "area": area, "id": identifier, "from_path": relative_source, "to_path": relative_destination}]},
    }
    return finalize_owner_result(repo, result)


def _inbound_refs(repo: pathlib.Path, identifier: str, excluded_path: pathlib.Path) -> list[str]:
    refs: list[str] = []
    _, areas = _root_catalog(repo)
    for area in areas:
        for path, _ in _scan_area_paths(repo, area["area"]):
            if path == excluded_path:
                continue
            try:
                document = parse_document(path.read_text(encoding="utf-8"))
            except ContextError:
                continue
            frontmatter = document.frontmatter
            relation_values: list[str] = []
            for key in ("anchors", "supersedes", "superseded_by"):
                value = frontmatter.get(key, [])
                relation_values.extend(value if isinstance(value, list) else [value])
            for value in frontmatter.get("relations", {}).values() if isinstance(frontmatter.get("relations"), dict) else []:
                relation_values.extend(value if isinstance(value, list) else [value])
            if identifier in relation_values:
                refs.append(path.relative_to(repo).as_posix())
    return sorted(refs)


def build_discard_bundle(repo: pathlib.Path, identifier: str) -> dict[str, Any]:
    area, source, document = _find_artifact(repo, identifier)
    if area not in BUILTIN_AREAS:
        raise ContextError("owner_unavailable", "discard requires the semantic area owner", {"area": area}, EXIT_CONFLICT)
    relative = source.relative_to(repo).as_posix()
    inbound = _inbound_refs(repo, identifier, source)
    if inbound:
        raise ContextError("inbound_reference", "artifact has inbound internal references", {"paths": inbound}, EXIT_CONFLICT)
    capability = builtin_capability(area)
    request = {
        "schema": "context-domain-mutation-input/v1", "transition": "discard", "owner": "context-core", "target_kind": area,
        "requested_changes": {}, "targets": [{"id": identifier, "path": relative, "sha256": sha256_bytes(source.read_bytes())}],
        "successor_owner_result_digest": None,
    }
    effect_id = "effect_discard_artifact"
    result = {
        "schema": "context-owner-result/v1", "result_type": "mutation", "transition": "discard", "owner": "context-core", "target_kind": area,
        "capability_digest": canonical_digest(capability),
        "semantic_inputs": [{"operation": "mutation_request", "input_schema": request["schema"], "input_digest": canonical_digest(request), "value": request}],
        "semantic_attestations": [], "artifact_drafts": [],
        "effects": [{"effect_id": effect_id, "action": "delete", "area": area, "id": identifier, "state": "history" if "/retired/" in relative else "current"}],
        "proposed_plan": {"schema": "context-owner-plan/v1", "transition": "discard", "operations": [{"op": "delete", "effect_id": effect_id, "area": area, "id": identifier, "path": relative}]},
    }
    del document
    return finalize_owner_result(repo, result)


def observation_read(repo: pathlib.Path, identifier: str, sections: Sequence[str] = ()) -> dict[str, Any]:
    return _read_artifact(repo, identifier, "observation", sections)


def observation_search(repo: pathlib.Path, query: str = "", *, include_history: bool = False, limit: int = 8) -> dict[str, Any]:
    return recall_repository(repo, query=query, areas=["observation"], include_history=include_history, limit=limit)


def build_observation_annotate_bundle(
    repo: pathlib.Path,
    identifier: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    tags: Sequence[str] | None = None,
    search_terms: Sequence[str] | None = None,
    source_refs: Sequence[str] | None = None,
    related: Sequence[str] | None = None,
    clear: Sequence[str] = (),
) -> dict[str, Any]:
    path, document = _artifact_in_area(repo, identifier, "observation", current_only=True)
    clear_set = set(clear)
    if clear_set - {"tags", "search_terms", "source_refs", "related"}:
        raise ContextError("usage_invalid", "observation clear target is invalid")
    updates = _validate_update_values(title=title, summary=summary, tags=tags, search_terms=search_terms, source_refs=source_refs)
    if related is not None:
        updates["related"] = _string_list(list(related), "related", maximum=12, item_maximum=36)
        for target in updates["related"]:
            _require_context_id(target, "related")
    frontmatter = dict(document.frontmatter)
    for field in clear_set - {"related"}:
        frontmatter.pop(field, None)
    relations = dict(frontmatter.get("relations", {}))
    if "related" in clear_set:
        relations.pop("related", None)
    if "related" in updates:
        if updates["related"]:
            relations["related"] = updates.pop("related")
        else:
            relations.pop("related", None)
    if relations:
        frontmatter["relations"] = relations
    else:
        frontmatter.pop("relations", None)
    frontmatter.update(updates)
    after = render_document(frontmatter, document.sections)
    if file_bytes(after) == path.read_bytes():
        return {"noop": True, "applied": False, "changed_paths": []}
    relative = path.relative_to(repo).as_posix()
    requested = {"metadata": updates, "clear": sorted(clear_set), "related": relations.get("related")}
    request = _mutation_request("observation_annotate", "observation", requested, [(path, document)], repo)
    effect_id = "effect_annotate_observation"
    result = _mutation_result(
        "observation",
        "observation_annotate",
        request,
        [{"effect_id": effect_id, "path": relative, "content": after, "semantic_projection": _semantic_projection("observation", Document(frontmatter, document.sections))}],
        [{"effect_id": effect_id, "action": "replace", "area": "observation", "id": identifier, "state": "current"}],
        [{"op": "replace", "effect_id": effect_id, "area": "observation", "id": identifier, "path": relative}],
    )
    return finalize_owner_result(repo, result)


def build_observation_reverify_bundle(repo: pathlib.Path, identifier: str, verified_at: str, evidence_ref: str) -> dict[str, Any]:
    path, document = _artifact_in_area(repo, identifier, "observation", current_only=True)
    _validate_timestamp(verified_at, "verified_at")
    if datetime.datetime.fromisoformat(verified_at) < datetime.datetime.fromisoformat(document.frontmatter["created_at"]):
        raise ContextError("clock_invalid", "verified_at cannot precede created_at", exit_code=EXIT_CONFLICT)
    if not _substantive(evidence_ref) or "\n" in evidence_ref or len(evidence_ref) > 500:
        raise ContextError("schema_invalid", "evidence_ref is invalid")
    frontmatter = dict(document.frontmatter)
    refs = list(frontmatter.get("source_refs", []))
    if evidence_ref not in refs:
        refs.append(evidence_ref)
    frontmatter["source_refs"] = refs
    frontmatter["verified_at"] = verified_at
    after = render_document(frontmatter, document.sections)
    if file_bytes(after) == path.read_bytes():
        return {"noop": True, "applied": False, "changed_paths": []}
    relative = path.relative_to(repo).as_posix()
    request = _mutation_request(
        "observation_reverify",
        "observation",
        {"verified_at": verified_at, "evidence_ref": evidence_ref},
        [(path, document)],
        repo,
    )
    effect_id = "effect_reverify_observation"
    result = _mutation_result(
        "observation",
        "observation_reverify",
        request,
        [{"effect_id": effect_id, "path": relative, "content": after, "semantic_projection": _semantic_projection("observation", Document(frontmatter, document.sections))}],
        [{"effect_id": effect_id, "action": "replace", "area": "observation", "id": identifier, "state": "current"}],
        [{"op": "replace", "effect_id": effect_id, "area": "observation", "id": identifier, "path": relative}],
    )
    return finalize_owner_result(repo, result)


def _history_path(path: pathlib.Path, identifier: str, repo: pathlib.Path) -> str:
    stem = path.stem
    return f"context/observation/retired/{stem}--{identifier[4:16]}.md"


def build_observation_invalidate_bundle(repo: pathlib.Path, identifier: str, reason: str, *, now: str | None = None) -> dict[str, Any]:
    path, document = _artifact_in_area(repo, identifier, "observation", current_only=True)
    if not _substantive(reason) or "\n" in reason or len(reason) > 500:
        raise ContextError("schema_invalid", "invalidation reason must be one substantive line")
    retired_at = _timestamp(now)
    frontmatter = dict(document.frontmatter)
    frontmatter.update({"retired_at": retired_at, "retired_reason": "invalidated", "retirement_note": reason.strip()})
    destination = _history_path(path, identifier, repo)
    if (repo / destination).exists():
        raise ContextError("history_path_collision", "deterministic history path already exists", {"path": destination}, EXIT_INTEGRITY)
    after = render_document(frontmatter, document.sections)
    source = path.relative_to(repo).as_posix()
    request = _mutation_request("observation_invalidate", "observation", {"reason": reason.strip(), "retired_at": retired_at}, [(path, document)], repo)
    effect_id = "effect_invalidate_observation"
    result = _mutation_result(
        "observation",
        "observation_invalidate",
        request,
        [{"effect_id": effect_id, "path": destination, "content": after, "semantic_projection": _semantic_projection("observation", Document(frontmatter, document.sections))}],
        [{"effect_id": effect_id, "action": "retire", "area": "observation", "id": identifier, "state": "history", "reason": "invalidated"}],
        [{"op": "move", "effect_id": effect_id, "area": "observation", "id": identifier, "from_path": source, "to_path": destination}],
    )
    return finalize_owner_result(repo, result)


def prepare_lifecycle_input(repo: pathlib.Path, transition: str, predecessor_id: str, successor_result: dict[str, Any]) -> dict[str, Any]:
    if transition not in {"observation_supersede", "decision_fallback_import"}:
        raise ContextError("lifecycle_transition_invalid", "unsupported lifecycle transition", {"transition": transition}, EXIT_CONFLICT)
    validate_owner_result(successor_result)
    expected_owner = "context-core" if transition == "observation_supersede" else "context-decision"
    expected_kind = "observation" if transition == "observation_supersede" else "decision"
    if (
        successor_result.get("result_type") != "claim"
        or successor_result.get("owner") != expected_owner
        or successor_result.get("target_kind") != expected_kind
        or len(successor_result.get("artifact_drafts", [])) != 1
    ):
        raise ContextError("successor_result_invalid", "lifecycle successor must be one complete claim result from the transition owner", exit_code=EXIT_CONFLICT)
    predecessor_path, predecessor = _artifact_in_area(repo, predecessor_id, "observation", current_only=True)
    successor_draft = successor_result["artifact_drafts"][0]
    successor_document = parse_document(successor_draft["content"])
    projection = successor_draft["semantic_projection"]
    claim_input = next(item for item in successor_result["semantic_inputs"] if item["operation"] == "claim")
    if transition == "decision_fallback_import":
        if predecessor.frontmatter.get("kind_hint") != "decision" or predecessor.frontmatter.get("source_claim_fingerprint") != successor_document.frontmatter.get("claim_fingerprint"):
            raise ContextError("fallback_fingerprint_mismatch", "decision-like OBS source fingerprint must equal the DEC claim fingerprint", exit_code=EXIT_CONFLICT)
    value = {
        "schema": "context-lifecycle-semantic-input/v1",
        "operation": "same_claim",
        "transition": transition,
        "owner": expected_owner,
        "predecessor": {
            "id": predecessor_id,
            "kind": "observation",
            "path": predecessor_path.relative_to(repo).as_posix(),
            "primary_claim": predecessor.sections["관찰"],
            "claim_fingerprint": predecessor.frontmatter["claim_fingerprint"],
            "supporting_context": _semantic_projection("observation", predecessor)["supporting_context"],
        },
        "successor": {
            "id": successor_document.frontmatter["id"],
            "kind": expected_kind,
            "path": successor_draft["path"],
            "primary_claim": projection["primary_claim"],
            "claim_fingerprint": projection["claim_fingerprint"],
            "supporting_context": projection["supporting_context"],
        },
        "source_candidate_digest": claim_input["input_digest"],
    }
    if len(canonical_json(value).encode("utf-8")) > 4 * 1024:
        raise ContextError("lifecycle_input_too_large", "lifecycle semantic input exceeds 4 KiB", exit_code=EXIT_CONFLICT)
    return value


def build_observation_supersede_bundle(
    repo: pathlib.Path,
    predecessor_id: str,
    successor_result: dict[str, Any],
    lifecycle_input: dict[str, Any],
    lifecycle_attestation: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    expected_input = prepare_lifecycle_input(repo, "observation_supersede", predecessor_id, successor_result)
    if canonical_json(lifecycle_input) != canonical_json(expected_input):
        raise ContextError("lifecycle_input_mismatch", "lifecycle input is not the exact prepared current input", exit_code=EXIT_CONFLICT)
    _validate_attestation(lifecycle_attestation, "same_claim", lifecycle_input, {"same_semantic_claim"})
    predecessor_path, predecessor = _artifact_in_area(repo, predecessor_id, "observation", current_only=True)
    successor_draft = successor_result["artifact_drafts"][0]
    successor_document = parse_document(successor_draft["content"])
    successor_id = successor_document.frontmatter["id"]
    if successor_id == predecessor_id:
        raise ContextError("successor_result_invalid", "successor id must differ from predecessor", exit_code=EXIT_CONFLICT)
    try:
        _find_artifact(repo, successor_id)
    except ContextError as error:
        if error.code != "artifact_not_found":
            raise
    else:
        raise ContextError("duplicate_id", "successor id already exists", {"id": successor_id}, EXIT_CONFLICT)
    destination = successor_draft["path"]
    existing_destination = repo / destination
    if existing_destination.exists() and existing_destination != predecessor_path:
        raise ContextError("path_exists", "successor path already exists", {"path": destination}, EXIT_CONFLICT)
    retired_at = _timestamp(now)
    predecessor_frontmatter = dict(predecessor.frontmatter)
    predecessor_frontmatter.update({"superseded_by": successor_id, "retired_at": retired_at, "retired_reason": "superseded"})
    predecessor_history_path = _history_path(predecessor_path, predecessor_id, repo)
    if (repo / predecessor_history_path).exists():
        raise ContextError("history_path_collision", "deterministic history path already exists", {"path": predecessor_history_path}, EXIT_INTEGRITY)
    successor_frontmatter = dict(successor_document.frontmatter)
    successor_frontmatter["supersedes"] = list(dict.fromkeys([*successor_frontmatter.get("supersedes", []), predecessor_id]))
    predecessor_after = render_document(predecessor_frontmatter, predecessor.sections)
    successor_after = render_document(successor_frontmatter, successor_document.sections)
    successor_result_digest = canonical_digest(successor_result)
    request = _mutation_request(
        "observation_supersede",
        "observation",
        {"predecessor": predecessor_id, "successor": successor_id, "retired_at": retired_at},
        [(predecessor_path, predecessor)],
        repo,
        successor_owner_result_digest=successor_result_digest,
    )
    retire_effect = "effect_retire_observation"
    create_effect = "effect_create_observation"
    source = predecessor_path.relative_to(repo).as_posix()
    claim_input = next(item for item in successor_result["semantic_inputs"] if item["operation"] == "claim")
    claim_attestation = next(item for item in successor_result["semantic_attestations"] if item["operation"] == "claim")
    lifecycle_semantic_input = {"operation": "same_claim", "input_schema": lifecycle_input["schema"], "input_digest": canonical_digest(lifecycle_input), "value": lifecycle_input}
    result = _mutation_result(
        "observation",
        "observation_supersede",
        request,
        [
            {"effect_id": retire_effect, "path": predecessor_history_path, "content": predecessor_after, "semantic_projection": _semantic_projection("observation", Document(predecessor_frontmatter, predecessor.sections))},
            {"effect_id": create_effect, "path": destination, "content": successor_after, "semantic_projection": _semantic_projection("observation", Document(successor_frontmatter, successor_document.sections))},
        ],
        [
            {"effect_id": retire_effect, "action": "retire", "area": "observation", "id": predecessor_id, "state": "history", "reason": "superseded", "successor": successor_id},
            {"effect_id": create_effect, "action": "create", "area": "observation", "id": successor_id, "state": "current", "predecessor": predecessor_id},
        ],
        [
            {"op": "move", "effect_id": retire_effect, "area": "observation", "id": predecessor_id, "from_path": source, "to_path": predecessor_history_path},
            {"op": "create", "effect_id": create_effect, "area": "observation", "path": destination},
        ],
        extra_inputs=[claim_input, lifecycle_semantic_input],
        attestations=[claim_attestation, lifecycle_attestation],
    )
    return finalize_owner_result(repo, result)


def build_observation_discard_bundle(repo: pathlib.Path, identifier: str) -> dict[str, Any]:
    _artifact_in_area(repo, identifier, "observation")
    return build_discard_bundle(repo, identifier)


def build_index_fix_bundle(repo: pathlib.Path) -> dict[str, Any]:
    integrity = refresh_repository(repo, strict=True)
    if integrity["ok"]:
        return {"noop": True, "applied": False, "changed_paths": []}
    non_index = [issue for issue in integrity["issues"] if issue["code"] not in INDEX_FIXABLE_CODES]
    if non_index:
        raise ContextError("integrity_not_fixable", "only derived index drift can be fixed automatically", {"issues": non_index}, EXIT_INTEGRITY)
    _, catalog = _root_catalog(repo)
    affected = sorted({
        area["area"]
        for area in catalog
        if any(issue.get("path", "").startswith(f"context/{area['area']}/") for issue in integrity["issues"])
    })
    before: dict[str, str | None] = {}
    after: dict[str, str] = {}
    for area in affected:
        relative = f"context/{area}/{area}.index.md"
        path = repo / relative
        before[relative] = _digest_or_none(path)
        rendered = render_area_index_from_repository(repo, area, repair_rows=True)
        after[relative] = sha256_bytes(file_bytes(rendered))
    plan = {
        "schema": "context-mutation-plan/v1", "plan_id": new_plan_id(), "owner": "context-core", "source_type": "core_control",
        "transition": "index_fix", "owner_descriptor": {"owner": "context-core", "kind": "storage", "artifact_schema": PROTOCOL},
        "control_input": {"schema": "context-core-control/v1", "transition": "index_fix", "issue_digest": canonical_digest(integrity["issues"])},
        "prior_bundle_digests": [], "read_preconditions": [],
        "operations": [{"op": "index_rebuild", "derived_from": [], "areas": affected, "include_root": False, "before_sha256": before, "after_sha256": after}],
    }
    preview = {"schema": "context-approval-preview/v1", "owner": "context-core", "candidate_id": None, "artifacts": [], "effects": [], "index_diffs": integrity["issues"]}
    return _bundle_result(preview, plan, [])


def _core_control_error(message: str) -> None:
    raise ContextError("plan_preview_mismatch", message, exit_code=EXIT_CONFLICT)


def _require_exact_fields(value: Any, fields: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        _core_control_error(f"{label} fields differ from the core control contract")


def _valid_plan_id(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"plan_[0-9a-f]{32}", value):
        return False
    parsed = uuid.UUID(hex=value[5:])
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def _validate_index_material(
    operation: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    relative: str,
    material_id: str,
) -> None:
    material = by_id.get(material_id)
    if (
        material is None
        or set(material) != {"material_id", "path", "content"}
        or material.get("path") != relative
        or operation["after_sha256"].get(relative) != sha256_bytes(file_bytes(material.get("content", "")))
    ):
        _core_control_error("index material path or digest is not canonical")


def _validate_core_init_control(
    plan: dict[str, Any],
    preview: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    operation: dict[str, Any],
) -> None:
    descriptor = {"owner": "context-core", "kind": "storage", "artifact_schema": PROTOCOL}
    contents = {
        ROOT_INDEX: render_root_index(_root_seed(), _builtin_area_specs()),
        "context/snapshot/snapshot.index.md": _area_seed(
            "snapshot", "context-core", "context-snapshot/v1", "staging", "session handoff staging",
            search_terms=("handoff", "resume"),
        ),
        "context/observation/observation.index.md": _area_seed(
            "observation", "context-core", "context-observation/v1", "evidence", "비권위 발견과 근거",
            search_terms=("observation", "evidence"),
        ),
    }
    material_ids = {
        ROOT_INDEX: "seed_root",
        "context/snapshot/snapshot.index.md": "seed_snapshot",
        "context/observation/observation.index.md": "seed_observation",
    }
    control = plan["control_input"]
    _require_exact_fields(control, {"schema", "transition", "seed_digests"}, "core_init control input")
    expected_digests = {path: sha256_bytes(file_bytes(contents[path])) for path in sorted(contents)}
    if (
        plan["owner"] != "context-core"
        or plan["owner_descriptor"] != descriptor
        or control != {
            "schema": "context-core-control/v1",
            "transition": "core_init",
            "seed_digests": expected_digests,
        }
        or set(by_id) != set(material_ids.values())
        or set(operation) != {
            "op", "derived_from", "areas", "include_root", "before_sha256", "after_sha256", "seed_materials",
        }
        or operation["op"] != "index_rebuild"
        or operation["derived_from"] != ["effect_core_init"]
        or operation["areas"] != ["observation", "snapshot"]
        or operation["include_root"] is not True
        or operation["before_sha256"] != {path: None for path in contents}
        or operation["after_sha256"] != expected_digests
        or operation["seed_materials"] != material_ids
        or preview["owner"] != "context-core"
        or preview["candidate_id"] is not None
        or preview["artifacts"] != []
        or preview["effects"] != [{
            "effect_id": "effect_core_init", "action": "initialize_core", "paths": sorted(contents),
        }]
    ):
        _core_control_error("core_init plan differs from its exact allowlist")
    for relative, content in contents.items():
        _validate_index_material(operation, by_id, relative, material_ids[relative])
        if by_id[material_ids[relative]]["content"] != content:
            _core_control_error("core_init seed content is not the canonical built-in seed")


def _validate_area_register_control(
    repo: pathlib.Path,
    plan: dict[str, Any],
    preview: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    operation: dict[str, Any],
) -> None:
    descriptor = plan["owner_descriptor"]
    _require_exact_fields(
        descriptor,
        {"schema", "owner", "kind", "artifact_schema", "authority"},
        "area_register owner descriptor",
    )
    owner = descriptor.get("owner")
    area = descriptor.get("kind")
    if (
        descriptor.get("schema") != "context-owner-descriptor/v1"
        or not all(isinstance(descriptor.get(key), str) and descriptor[key] for key in ("owner", "kind", "artifact_schema", "authority"))
        or not AREA_NAME.fullmatch(str(area))
    ):
        _core_control_error("area_register owner descriptor is invalid")
    area_path = f"context/{area}/{area}.index.md"
    control = plan["control_input"]
    _require_exact_fields(
        control,
        {"schema", "transition", "descriptor_digest", "seed_digests"},
        "area_register control input",
    )
    if set(by_id) != {"material_root_index", "seed_area_index"}:
        _core_control_error("area_register materials differ from the exact allowlist")
    seed = by_id["seed_area_index"]
    root_material = by_id["material_root_index"]
    _require_exact_fields(seed, {"material_id", "path", "content"}, "area_register seed material")
    _require_exact_fields(root_material, {"material_id", "path", "content"}, "area_register root material")
    try:
        seed_index = parse_area_index(seed["content"])
        _, root_rows = parse_root_index(root_material["content"])
    except ContextError as error:
        raise ContextError("plan_preview_mismatch", "area_register material is not a valid canonical index", exit_code=EXIT_CONFLICT) from error
    expected_row = {
        "area": area,
        "path": area_path,
        "owner": owner,
        "claims": [area],
        "artifact_schema": descriptor["artifact_schema"],
        "authority": descriptor["authority"],
    }
    metadata = seed_index.frontmatter
    if (
        seed_index.current
        or seed_index.history
        or (metadata["area"], metadata["owner"], metadata["artifact_schema"], metadata["authority"])
        != (area, owner, descriptor["artifact_schema"], descriptor["authority"])
        or [row for row in root_rows if row["area"] == area] != [expected_row]
    ):
        _core_control_error("area_register descriptor, seed, and root row differ")
    specs: list[tuple[dict[str, Any], str, str]] = []
    for row in root_rows:
        index = seed_index if row["area"] == area else parse_area_index((repo / row["path"]).read_text(encoding="utf-8"))
        fm = index.frontmatter
        if (fm["area"], fm["owner"], fm["artifact_schema"], fm["authority"]) != (
            row["area"], row["owner"], row["artifact_schema"], row["authority"],
        ):
            _core_control_error("area_register root and area metadata differ")
        specs.append((row, _area_label(row["area"]), fm["summary"]))
    if render_root_index(root_material["content"], specs) != root_material["content"]:
        _core_control_error("area_register root generated bytes are not canonical")
    current_root_digest = _digest_or_none(repo / ROOT_INDEX)
    if current_root_digest == operation.get("before_sha256", {}).get(ROOT_INDEX):
        current_root = (repo / ROOT_INDEX).read_text(encoding="utf-8")
        _, current_rows = parse_root_index(current_root)
        if (
            root_rows != sorted([*current_rows, expected_row], key=lambda row: row["area"])
            or root_material["content"] != render_root_index(current_root, specs)
        ):
            _core_control_error("area_register root material does not add exactly one area")
    seed_digest = sha256_bytes(file_bytes(seed["content"]))
    if (
        plan["owner"] != owner
        or control != {
            "schema": "context-core-control/v1",
            "transition": "area_register",
            "descriptor_digest": canonical_digest(descriptor),
            "seed_digests": {area_path: seed_digest},
        }
        or set(operation) != {
            "op", "derived_from", "areas", "include_root", "before_sha256", "after_sha256", "seed_materials",
        }
        or operation["op"] != "index_rebuild"
        or operation["derived_from"] != ["effect_register_area"]
        or operation["areas"] != [area]
        or operation["include_root"] is not True
        or set(operation["before_sha256"]) != {ROOT_INDEX, area_path}
        or operation["before_sha256"].get(area_path) is not None
        or set(operation["after_sha256"]) != {ROOT_INDEX, area_path}
        or operation["seed_materials"] != {area_path: "seed_area_index"}
        or root_material["path"] != ROOT_INDEX
        or seed["path"] != area_path
        or preview["owner"] != owner
        or preview["candidate_id"] is not None
        or preview["artifacts"] != []
        or preview["effects"] != [{
            "effect_id": "effect_register_area", "action": "register_area", "area": area, "path": area_path,
        }]
    ):
        _core_control_error("area_register plan differs from its exact allowlist")
    _validate_index_material(operation, by_id, ROOT_INDEX, "material_root_index")
    _validate_index_material(operation, by_id, area_path, "seed_area_index")


def _validate_policy_control(
    repo: pathlib.Path,
    plan: dict[str, Any],
    preview: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    operation: dict[str, Any],
) -> None:
    descriptor = {"owner": "context-core", "kind": "policy", "artifact_schema": "context-policy/v1"}
    control = plan["control_input"]
    _require_exact_fields(
        control,
        {"schema", "transition", "target", "before_sha256", "outside_bytes_sha256"},
        "policy_install control input",
    )
    target = control.get("target")
    if set(by_id) != {"material_policy"}:
        _core_control_error("policy_install material differs from the exact allowlist")
    material = by_id["material_policy"]
    _require_exact_fields(material, {"material_id", "path", "content"}, "policy material")
    content = material["content"]
    newline = "\r\n" if "\r\n" in content else "\n"
    if "\r\n" in content and "\n" in content.replace("\r\n", ""):
        _core_control_error("policy material has mixed newlines")
    expected_block = POLICY_BODY.replace("\n", newline)
    start = content.find(POLICY_BEGIN)
    end = content.find(POLICY_END, start) + len(POLICY_END)
    if content.count(POLICY_BEGIN) != 1 or content.count(POLICY_END) != 1 or content[start:end] != expected_block:
        _core_control_error("policy material managed block is not canonical")
    current = _ensure_contained(repo, str(target)) if target in POLICY_TARGETS else repo
    current_digest = _digest_or_none(current) if target in POLICY_TARGETS else None
    if current_digest == operation.get("before_sha256"):
        before = current.read_text(encoding="utf-8") if current_digest is not None else ""
        outside = (
            before[:before.find(POLICY_BEGIN)] + before[before.find(POLICY_END) + len(POLICY_END):]
            if POLICY_BEGIN in before
            else before
        )
        if control.get("outside_bytes_sha256") != sha256_bytes(outside.encode("utf-8")):
            _core_control_error("policy control input does not bind marker-external bytes")
        before_newline = "\r\n" if "\r\n" in before else "\n"
        policy_body = POLICY_BODY.replace("\n", before_newline)
        if POLICY_BEGIN in before:
            before_start = before.index(POLICY_BEGIN)
            before_end = before.index(POLICY_END, before_start) + len(POLICY_END)
            expected_content = before[:before_start] + policy_body + before[before_end:]
        elif before:
            separator = "" if before.endswith(before_newline * 2) else (before_newline if before.endswith(before_newline) else before_newline * 2)
            expected_content = before + separator + policy_body + before_newline
        else:
            expected_content = policy_body + before_newline
        if content != expected_content:
            _core_control_error("policy material changes marker-external bytes")
    expected_op = "file_replace" if operation.get("before_sha256") is not None else "file_create"
    if (
        plan["owner"] != "context-core"
        or plan["owner_descriptor"] != descriptor
        or control.get("schema") != "context-core-control/v1"
        or control.get("transition") != "policy_install"
        or target not in POLICY_TARGETS
        or control.get("before_sha256") != operation.get("before_sha256")
        or set(operation) != {"op", "effect_id", "role", "path", "before_sha256", "after_sha256", "material"}
        or operation["op"] != expected_op
        or operation["effect_id"] != "effect_install_policy"
        or operation["role"] != "policy"
        or operation["path"] != target
        or operation["material"] != "material_policy"
        or operation["after_sha256"] != sha256_bytes(content.encode("utf-8"))
        or material["path"] != target
        or preview["owner"] != "context-core"
        or preview["candidate_id"] is not None
        or preview["artifacts"] != [{
            "effect_id": "effect_install_policy", "path": target, "content": content,
        }]
        or preview["effects"] != [{
            "effect_id": "effect_install_policy", "action": "install_policy", "path": target,
        }]
    ):
        _core_control_error("policy_install plan differs from its exact allowlist")


def _validate_index_fix_control(
    repo: pathlib.Path,
    plan: dict[str, Any],
    preview: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    operation: dict[str, Any],
) -> None:
    descriptor = {"owner": "context-core", "kind": "storage", "artifact_schema": PROTOCOL}
    control = plan["control_input"]
    _require_exact_fields(control, {"schema", "transition", "issue_digest"}, "index_fix control input")
    issues = preview.get("index_diffs")
    areas = operation.get("areas")
    expected_paths = {f"context/{area}/{area}.index.md" for area in areas} if isinstance(areas, list) else set()
    if (
        not isinstance(issues, list)
        or not issues
        or any(not isinstance(issue, dict) or issue.get("code") not in INDEX_FIXABLE_CODES for issue in issues)
        or not isinstance(areas, list)
        or not areas
        or areas != sorted(set(areas))
        or any(not AREA_NAME.fullmatch(str(area)) for area in areas)
        or any(not any(issue.get("path", "").startswith(f"context/{area}/") for issue in issues) for area in areas)
    ):
        _core_control_error("index_fix issue and area set is invalid")
    if (
        plan["owner"] != "context-core"
        or plan["owner_descriptor"] != descriptor
        or control != {
            "schema": "context-core-control/v1",
            "transition": "index_fix",
            "issue_digest": canonical_digest(issues),
        }
        or by_id
        or set(operation) != {"op", "derived_from", "areas", "include_root", "before_sha256", "after_sha256"}
        or operation["op"] != "index_rebuild"
        or operation["derived_from"] != []
        or operation["include_root"] is not False
        or set(operation["before_sha256"]) != expected_paths
        or set(operation["after_sha256"]) != expected_paths
        or preview["owner"] != "context-core"
        or preview["candidate_id"] is not None
        or preview["artifacts"] != []
        or preview["effects"] != []
    ):
        _core_control_error("index_fix plan differs from its exact allowlist")
    current = {relative: _digest_or_none(repo / relative) for relative in expected_paths}
    before = operation["before_sha256"]
    after = operation["after_sha256"]
    if any(current[path] not in {before[path], after[path]} for path in expected_paths):
        _core_control_error("index_fix repository state differs from the approved transition")
    if all(current[path] == before[path] for path in expected_paths):
        actual_issues = refresh_repository(repo, strict=True)["issues"]
        if issues != actual_issues:
            _core_control_error("index_fix control input does not bind the current integrity issues")
        _, catalog = _root_catalog(repo)
        actual_areas = sorted({
            row["area"]
            for row in catalog
            if any(issue.get("path", "").startswith(f"context/{row['area']}/") for issue in actual_issues)
        })
        if areas != actual_areas:
            _core_control_error("index_fix area set differs from the current integrity issues")
    for area in areas:
        relative = f"context/{area}/{area}.index.md"
        rendered = render_area_index_from_repository(repo, area, repair_rows=True)
        if operation["after_sha256"][relative] != sha256_bytes(file_bytes(rendered)):
            _core_control_error("index_fix after digest is not the deterministic repository projection")


def _validate_core_control_bundle(
    repo: pathlib.Path,
    plan: dict[str, Any],
    preview: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    non_index: list[dict[str, Any]],
    index_operations: list[dict[str, Any]],
) -> None:
    _require_exact_fields(
        plan,
        {
            "schema", "plan_id", "owner", "source_type", "transition", "owner_descriptor", "control_input",
            "prior_bundle_digests", "read_preconditions", "operations",
        },
        "core control plan",
    )
    transition = plan.get("transition")
    expected_preview_fields = {"schema", "owner", "candidate_id", "artifacts", "effects"}
    if transition == "index_fix":
        expected_preview_fields.add("index_diffs")
    _require_exact_fields(preview, expected_preview_fields, "core control preview")
    if (
        plan.get("schema") != "context-mutation-plan/v1"
        or plan.get("source_type") != "core_control"
        or transition not in {"core_init", "area_register", "policy_install", "index_fix"}
        or not _valid_plan_id(plan.get("plan_id"))
        or plan.get("prior_bundle_digests") != []
        or plan.get("read_preconditions") != []
        or preview.get("schema") != "context-approval-preview/v1"
        or not isinstance(preview.get("artifacts"), list)
        or not isinstance(preview.get("effects"), list)
        or any(set(material) != {"material_id", "path", "content"} for material in by_id.values())
    ):
        _core_control_error("core control envelope differs from the exact allowlist")
    if transition == "policy_install":
        if index_operations or len(non_index) != 1:
            _core_control_error("policy_install permits exactly one policy file operation")
        _validate_policy_control(repo, plan, preview, by_id, non_index[0])
        return
    if non_index or len(index_operations) != 1:
        _core_control_error(f"{transition} permits exactly one index_rebuild operation")
    operation = index_operations[0]
    if transition == "core_init":
        _validate_core_init_control(plan, preview, by_id, operation)
    elif transition == "area_register":
        _validate_area_register_control(repo, plan, preview, by_id, operation)
    else:
        _validate_index_fix_control(repo, plan, preview, by_id, operation)


def _validate_bundle(repo: pathlib.Path, bundle: dict[str, Any], approved_digest: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if bundle.get("schema") != "context-mutation-bundle/v1":
        raise ContextError("bundle_invalid", "mutation bundle schema is invalid", exit_code=EXIT_CONFLICT)
    actual = canonical_digest(bundle.get("approval_material"))
    if approved_digest != bundle.get("approval_digest") or actual != bundle.get("approval_digest"):
        raise ContextError("approval_digest_mismatch", "approved digest does not match the immutable final bundle", exit_code=EXIT_CONFLICT)
    materials = bundle.get("materials", [])
    by_id = {item.get("material_id"): item for item in materials}
    if len(by_id) != len(materials) or any(not LOCAL_ID.fullmatch(str(key)) for key in by_id):
        raise ContextError("plan_preview_mismatch", "material ids are invalid or duplicate", exit_code=EXIT_CONFLICT)
    plan = bundle["approval_material"].get("plan", {})
    preview = bundle["approval_material"].get("preview", {})
    if plan.get("schema") != "context-mutation-plan/v1" or preview.get("schema") != "context-approval-preview/v1":
        raise ContextError("bundle_invalid", "approval material is incomplete", exit_code=EXIT_CONFLICT)
    plan_operations = plan.get("operations", [])
    for precondition in plan.get("read_preconditions", []):
        if set(precondition) != {"id", "path", "sha256"}:
            raise ContextError("read_precondition_invalid", "final plan read precondition shape is invalid", exit_code=EXIT_CONFLICT)
        target = _ensure_contained(repo, precondition["path"])
        completed_move = next(
            (
                operation
                for operation in plan_operations
                if operation.get("op") == "file_move"
                and operation.get("id") == precondition["id"]
                and operation.get("from_path") == precondition["path"]
                and not target.exists()
                and _digest_or_none(_ensure_contained(repo, operation["to_path"])) == operation.get("after_sha256")
            ),
            None,
        )
        if completed_move is None and (not target.is_file() or sha256_bytes(target.read_bytes()) != precondition["sha256"]):
            raise ContextError("precondition_changed", "final plan read precondition is stale", {"path": precondition["path"]}, EXIT_CONFLICT)
    operations = plan_operations
    non_index = [operation for operation in operations if operation.get("op") != "index_rebuild"]
    effect_ids = [operation.get("effect_id") for operation in non_index]
    preview_ids = [effect.get("effect_id") for effect in preview.get("effects", [])]
    preview_artifacts = {artifact.get("effect_id"): artifact for artifact in preview.get("artifacts", [])}
    if len(preview_artifacts) != len(preview.get("artifacts", [])):
        raise ContextError("plan_preview_mismatch", "preview artifact effect ids are duplicate", exit_code=EXIT_CONFLICT)
    if len(effect_ids) != len(set(effect_ids)):
        raise ContextError("plan_preview_mismatch", "operations and preview effects are not 1:1", exit_code=EXIT_CONFLICT)
    index_operations = [operation for operation in operations if operation.get("op") == "index_rebuild"]
    derived_ids = index_operations[0].get("derived_from", []) if len(index_operations) == 1 else []
    if plan.get("transition") == "policy_install":
        if index_operations or len(non_index) != 1 or set(effect_ids) != set(preview_ids):
            raise ContextError("plan_preview_mismatch", "policy install must contain one visible file operation", exit_code=EXIT_CONFLICT)
    elif (
        len(index_operations) != 1
        or len(derived_ids) != len(set(derived_ids))
        or set(effect_ids) | set(derived_ids) != set(preview_ids)
        or not set(effect_ids).issubset(set(derived_ids))
    ):
        raise ContextError("plan_preview_mismatch", "index rebuild does not cover preview effects", exit_code=EXIT_CONFLICT)
    for operation in non_index:
        if operation.get("op") not in {"file_create", "file_replace", "file_move", "file_delete"}:
            raise ContextError("plan_preview_mismatch", "physical operation is not allowed", exit_code=EXIT_CONFLICT)
        role = operation.get("role")
        if role not in {"artifact", "policy"}:
            raise ContextError("plan_preview_mismatch", "file operation role is invalid", exit_code=EXIT_CONFLICT)
        if role == "policy" and (plan.get("transition") != "policy_install" or operation.get("path") not in POLICY_TARGETS or "area" in operation):
            raise ContextError("policy_target_invalid", "policy operation escapes the repository-root allowlist", exit_code=EXIT_CONFLICT)
        if role == "artifact" and not isinstance(operation.get("area"), str):
            raise ContextError("plan_preview_mismatch", "artifact operation lacks area", exit_code=EXIT_CONFLICT)
        material_id = operation.get("material")
        if operation["op"] != "file_delete" and operation.get("after_sha256") != operation.get("before_sha256") and material_id not in by_id:
            raise ContextError("material_digest_mismatch", "file operation material is missing", exit_code=EXIT_CONFLICT)
        if material_id:
            content = by_id[material_id]["content"]
            material_bytes = content.encode("utf-8") if role == "policy" else file_bytes(content)
            if sha256_bytes(material_bytes) != operation["after_sha256"]:
                raise ContextError("material_digest_mismatch", "material bytes do not match after digest", {"material_id": material_id}, EXIT_CONFLICT)
        artifact = preview_artifacts.get(operation["effect_id"])
        if operation["op"] == "file_delete":
            if artifact is not None:
                raise ContextError("plan_preview_mismatch", "delete operation must not hide a destination draft", exit_code=EXIT_CONFLICT)
        else:
            expected_path = operation.get("to_path", operation.get("path"))
            if artifact is None or artifact.get("path") != expected_path:
                raise ContextError("plan_preview_mismatch", "physical destination differs from grouped preview", exit_code=EXIT_CONFLICT)
            artifact_bytes = artifact.get("content", "").encode("utf-8") if role == "policy" else file_bytes(artifact.get("content", ""))
            if sha256_bytes(artifact_bytes) != operation.get("after_sha256"):
                raise ContextError("plan_preview_mismatch", "preview content differs from exact apply bytes", exit_code=EXIT_CONFLICT)
    if plan.get("source_type") == "owner_result":
        owner_material = by_id.get(plan.get("owner_result_material"))
        if owner_material is None or owner_material.get("path") is not None or sha256_bytes(owner_material["content"].encode("utf-8")) != plan.get("owner_result_digest"):
            raise ContextError("material_digest_mismatch", "owner result material is invalid", exit_code=EXIT_CONFLICT)
        try:
            owner_result = json.loads(owner_material["content"])
        except json.JSONDecodeError as error:
            raise ContextError("owner_result_invalid", "owner result material is not JSON", exit_code=EXIT_CONFLICT) from error
        validate_owner_result(owner_result)
        if canonical_json(owner_result) != owner_material["content"]:
            raise ContextError("owner_result_invalid", "owner result material is not canonical JSON", exit_code=EXIT_CONFLICT)
        if (
            owner_result["transition"] != plan.get("transition")
            or owner_result["owner"] != plan.get("owner")
            or owner_result["capability_digest"] != plan.get("capability_digest")
        ):
            raise ContextError("plan_preview_mismatch", "final plan is not bound to its owner result", exit_code=EXIT_CONFLICT)
        _area_for_owner(repo, plan["owner_descriptor"]["kind"], plan["owner"])
        validation = plan.get("owner_validation")
        if owner_result["owner"] != "context-core":
            if not isinstance(validation, dict):
                raise ContextError("owner_validation_required", "addon final plan lacks an owner validation receipt", exit_code=EXIT_CONFLICT)
            receipt_body = dict(validation)
            receipt_digest = receipt_body.pop("receipt_digest", None)
            if (
                validation.get("schema") != "context-owner-validation-receipt/v1"
                or validation.get("owner") != owner_result["owner"]
                or validation.get("kind") != owner_result["target_kind"]
                or validation.get("owner_result_digest") != canonical_digest(owner_result)
                or validation.get("status") != "valid"
                or receipt_digest != canonical_digest(receipt_body)
            ):
                raise ContextError("owner_validation_invalid", "addon owner validation receipt is altered", exit_code=EXIT_CONFLICT)
        request_inputs = [item for item in owner_result["semantic_inputs"] if item.get("operation") == "mutation_request"]
        if request_inputs:
            request = request_inputs[0]["value"]
            for target in request["targets"]:
                matching_operations = [
                    operation
                    for operation in non_index
                    if operation.get("from_path", operation.get("path")) == target["path"]
                    and operation.get("id") == target["id"]
                    and operation.get("before_sha256") == target["sha256"]
                ]
                if len(matching_operations) != 1:
                    raise ContextError("plan_preview_mismatch", "mutation target is not exact in the physical plan", {"path": target["path"]}, EXIT_CONFLICT)
        if owner_result["transition"] == "observation_supersede":
            inputs = {item["operation"]: item["value"] for item in owner_result["semantic_inputs"]}
            lifecycle = inputs["same_claim"]
            request = inputs["mutation_request"]
            drafts = {draft["effect_id"]: draft for draft in owner_result["artifact_drafts"]}
            effects = {effect["effect_id"]: effect for effect in owner_result["effects"]}
            create_effects = [effect for effect in effects.values() if effect.get("action") == "create"]
            retire_effects = [effect for effect in effects.values() if effect.get("action") == "retire"]
            if len(create_effects) != 1 or len(retire_effects) != 1:
                raise ContextError("plan_preview_mismatch", "observation supersede must contain one create and one retire", exit_code=EXIT_CONFLICT)
            created = parse_document(drafts[create_effects[0]["effect_id"]]["content"])
            retired = parse_document(drafts[retire_effects[0]["effect_id"]]["content"])
            successor_id = created.frontmatter["id"]
            predecessor_id = retired.frontmatter["id"]
            predecessor_target = request["targets"][0] if len(request["targets"]) == 1 else {}
            if (
                lifecycle["source_candidate_digest"] != next(item["input_digest"] for item in owner_result["semantic_inputs"] if item["operation"] == "claim")
                or lifecycle["predecessor"]["id"] != predecessor_id
                or lifecycle["predecessor"]["path"] != predecessor_target.get("path")
                or lifecycle["predecessor"]["primary_claim"] != retired.sections["관찰"]
                or lifecycle["predecessor"]["claim_fingerprint"] != retired.frontmatter["claim_fingerprint"]
                or lifecycle["successor"]["id"] != successor_id
                or lifecycle["successor"]["path"] != drafts[create_effects[0]["effect_id"]]["path"]
                or lifecycle["successor"]["primary_claim"] != created.sections["관찰"]
                or lifecycle["successor"]["claim_fingerprint"] != created.frontmatter["claim_fingerprint"]
                or request["requested_changes"].get("predecessor") != predecessor_id
                or request["requested_changes"].get("successor") != successor_id
                or retired.frontmatter.get("superseded_by") != successor_id
                or predecessor_id not in created.frontmatter.get("supersedes", [])
            ):
                raise ContextError("lifecycle_input_mismatch", "supersede lifecycle inputs and reciprocal artifact edges differ", exit_code=EXIT_CONFLICT)
        if owner_result["transition"] == "decision_fallback_import":
            inputs = {item["operation"]: item["value"] for item in owner_result["semantic_inputs"]}
            lifecycle = inputs["same_claim"]
            request = inputs["mutation_request"]
            drafts = {draft["effect_id"]: draft for draft in owner_result["artifact_drafts"]}
            dec_effects = [effect for effect in owner_result["effects"] if effect.get("action") == "create" and effect.get("area") == "decision"]
            obs_effects = [effect for effect in owner_result["effects"] if effect.get("action") == "retire" and effect.get("area") == "observation"]
            if len(dec_effects) != 1 or len(obs_effects) != 1:
                raise ContextError("plan_preview_mismatch", "fallback import must create one DEC and retire one OBS", exit_code=EXIT_CONFLICT)
            created = parse_document(drafts[dec_effects[0]["effect_id"]]["content"])
            retired = parse_document(drafts[obs_effects[0]["effect_id"]]["content"])
            target = request["targets"][0] if len(request.get("targets", [])) == 1 else {}
            if (
                lifecycle.get("source_candidate_digest") != next(item["input_digest"] for item in owner_result["semantic_inputs"] if item["operation"] == "claim")
                or lifecycle.get("predecessor", {}).get("kind") != "observation"
                or lifecycle.get("successor", {}).get("kind") != "decision"
                or lifecycle.get("predecessor", {}).get("id") != retired.frontmatter["id"]
                or lifecycle.get("predecessor", {}).get("path") != target.get("path")
                or lifecycle.get("predecessor", {}).get("primary_claim") != retired.sections["관찰"]
                or lifecycle.get("successor", {}).get("id") != created.frontmatter["id"]
                or lifecycle.get("successor", {}).get("path") != drafts[dec_effects[0]["effect_id"]]["path"]
                or lifecycle.get("successor", {}).get("primary_claim") != created.sections["결정"]
                or retired.frontmatter.get("kind_hint") != "decision"
                or retired.frontmatter.get("source_claim_fingerprint") != created.frontmatter.get("claim_fingerprint")
                or retired.frontmatter.get("superseded_by") != created.frontmatter["id"]
                or retired.frontmatter["id"] not in created.frontmatter.get("supersedes", [])
                or retired.frontmatter["id"] in created.frontmatter.get("relations", {}).get("informed_by", [])
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(request.get("successor_owner_result_digest")))
            ):
                raise ContextError("lifecycle_input_mismatch", "fallback import lifecycle and exact claim fingerprint differ", exit_code=EXIT_CONFLICT)
    elif plan.get("source_type") != "core_control":
        raise ContextError("bundle_invalid", "source_type is unsupported", exit_code=EXIT_CONFLICT)
    else:
        _validate_core_control_bundle(repo, plan, preview, by_id, non_index, index_operations)
    return plan, by_id


@contextlib.contextmanager
def _root_lock(repo: pathlib.Path) -> Iterator[None]:
    lock_root = pathlib.Path(tempfile.gettempdir()) / "context-core-locks"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(lock_root, 0o700)
    name = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_root / name, flags, 0o600)
    try:
        mode = os.fstat(fd).st_mode & 0o777
        if mode & 0o022:
            raise ContextError("lock_unsafe", "lock file is group/other writable", exit_code=EXIT_CONFLICT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_write(path: pathlib.Path, content: str) -> None:
    _atomic_write_bytes(path, file_bytes(content))


def _atomic_write_bytes(path: pathlib.Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".context-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        with contextlib.suppress(OSError):
            parent_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_path)


def _digest_or_none(path: pathlib.Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def _apply_file_operation(repo: pathlib.Path, operation: dict[str, Any], materials: dict[str, dict[str, Any]], changed: list[str]) -> None:
    op = operation["op"]
    if op in {"file_create", "file_replace"}:
        path = _ensure_contained(repo, operation["path"])
        current = _digest_or_none(path)
        if current == operation["after_sha256"]:
            return
        if current != operation["before_sha256"]:
            raise ContextError("precondition_changed", "file precondition changed", {"path": operation["path"]}, EXIT_CONFLICT)
        if op == "file_replace" and operation.get("role") == "artifact" and parse_document(path.read_text(encoding="utf-8")).frontmatter["id"] != operation.get("id"):
            raise ContextError("precondition_changed", "replace target id changed", {"path": operation["path"]}, EXIT_CONFLICT)
        content = materials[operation["material"]]["content"]
        if operation.get("role") == "policy":
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            _atomic_write_bytes(path, content.encode("utf-8"))
        else:
            _atomic_write(path, content)
        changed.append(operation["path"])
    elif op == "file_move":
        source = _ensure_contained(repo, operation["from_path"])
        destination = _ensure_contained(repo, operation["to_path"])
        source_digest = _digest_or_none(source)
        destination_digest = _digest_or_none(destination)
        before = operation["before_sha256"]
        after = operation["after_sha256"]
        material = operation.get("material")
        if source_digest is None and destination_digest == after:
            return
        if source_digest == before and parse_document(source.read_text(encoding="utf-8")).frontmatter["id"] != operation.get("id"):
            raise ContextError("precondition_changed", "move source id changed", {"path": operation["from_path"]}, EXIT_CONFLICT)
        if material is None:
            if source_digest != before or destination_digest is not None:
                raise ContextError("precondition_changed", "rename state is invalid", exit_code=EXIT_CONFLICT)
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.replace(source, destination)
        else:
            if source_digest == before and destination_digest is None:
                _atomic_write(destination, materials[material]["content"])
                destination_digest = after
            if source_digest == before and destination_digest == after:
                os.unlink(source)
            else:
                raise ContextError("precondition_changed", "changed-move state is invalid", exit_code=EXIT_CONFLICT)
        changed.extend([operation["from_path"], operation["to_path"]])
    elif op == "file_delete":
        path = _ensure_contained(repo, operation["path"])
        current = _digest_or_none(path)
        if current is None:
            return
        inbound = _inbound_refs(repo, operation["id"], path)
        target_id = parse_document(path.read_text(encoding="utf-8")).frontmatter["id"] if current == operation["before_sha256"] else None
        if current != operation["before_sha256"] or target_id != operation["id"] or operation.get("inbound_refs") or inbound:
            raise ContextError("precondition_changed", "delete precondition changed", exit_code=EXIT_CONFLICT)
        os.unlink(path)
        changed.append(operation["path"])


def _apply_index_operation(repo: pathlib.Path, plan: dict[str, Any], operation: dict[str, Any], materials: dict[str, dict[str, Any]], changed: list[str]) -> list[str]:
    index_paths = sorted(operation["after_sha256"])
    transition = plan["transition"]
    if transition in {"core_init", "area_register"}:
        if transition == "core_init":
            retired = _ensure_contained(repo, "context/observation/retired")
            if retired.exists() and (not retired.is_dir() or retired.is_symlink()):
                raise ContextError("precondition_changed", "observation retired path is not a safe directory", exit_code=EXIT_CONFLICT)
            retired.mkdir(mode=0o755, parents=True, exist_ok=True)
        by_path = {material["path"]: material for material in materials.values() if material.get("path")}
        for relative in index_paths:
            path = _ensure_contained(repo, relative)
            current = _digest_or_none(path)
            if current == operation["after_sha256"][relative]:
                continue
            if current != operation["before_sha256"][relative] or relative not in by_path:
                raise ContextError("precondition_changed", "index precondition changed", {"path": relative}, EXIT_CONFLICT)
            _atomic_write(path, by_path[relative]["content"])
            changed.append(relative)
    else:
        for area in operation["areas"]:
            relative = f"context/{area}/{area}.index.md"
            path = repo / relative
            current = _digest_or_none(path)
            expected_before = operation["before_sha256"].get(relative)
            if current == operation["after_sha256"].get(relative):
                continue
            if current != expected_before:
                raise ContextError("precondition_changed", "area index precondition changed", {"path": relative}, EXIT_CONFLICT)
            rendered = render_area_index_from_repository(repo, area, repair_rows=True)
            if sha256_bytes(file_bytes(rendered)) != operation["after_sha256"][relative]:
                raise ContextError("plan_preview_mismatch", "deterministic index output differs from preview", {"path": relative}, EXIT_INTEGRITY)
            _atomic_write(path, rendered)
            changed.append(relative)
    return index_paths


def apply_bundle(repo: pathlib.Path, bundle: dict[str, Any], approved_digest: str, *, approval_source: str = "user") -> dict[str, Any]:
    if approval_source != "user":
        raise ContextError("approval_required", "autonomous audit or maintenance cannot apply a durable mutation", exit_code=EXIT_CONFLICT)
    plan, materials = _validate_bundle(repo, bundle, approved_digest)
    changed: list[str] = []
    index_paths: list[str] = []
    with _root_lock(repo):
        plan, materials = _validate_bundle(repo, bundle, approved_digest)
        for operation in plan["operations"]:
            if operation["op"] == "index_rebuild":
                index_paths = _apply_index_operation(repo, plan, operation, materials, changed)
            else:
                _apply_file_operation(repo, operation, materials, changed)
    return {"applied": True, "plan_id": plan["plan_id"], "approval_digest": approved_digest, "changed_paths": sorted(set(changed)), "index_paths": index_paths, "warnings": []}


def refresh_repository(repo: pathlib.Path, *, strict: bool = False) -> dict[str, Any]:
    del strict
    issues: list[dict[str, Any]] = []
    root_text = ""
    root_valid = False
    try:
        root_path = _ensure_contained(repo, ROOT_INDEX)
        root_text = root_path.read_text(encoding="utf-8")
        _, areas = parse_root_index(root_text)
        root_valid = True
    except FileNotFoundError:
        issues.append({"code": "index_missing", "path": ROOT_INDEX})
        areas = []
    except (OSError, UnicodeError) as error:
        issues.append({"code": "index_invalid", "path": ROOT_INDEX, "message": str(error)})
        areas = []
    except ContextError as error:
        issues.append({"code": error.code, "path": error.details.get("path", ROOT_INDEX), "message": error.message})
        areas = []
    if not root_valid:
        return {
            "schema": "context-integrity-result/v1",
            "ok": not issues,
            "issues": sorted(issues, key=canonical_json),
            "warnings": [],
            "root_digest": sha256_bytes(root_text.encode("utf-8")),
        }
    area_names = [area["area"] for area in areas]
    claims = [claim for area in areas for claim in area["claims"]]
    for area in sorted(set(BUILTIN_AREAS) - set(area_names)):
        issues.append({"code": "reserved_index_missing", "path": f"context/{area}/{area}.index.md", "area": area})
    if len(area_names) != len(set(area_names)):
        issues.append({"code": "duplicate_area_owner", "path": ROOT_INDEX})
    if len(claims) != len(set(claims)):
        issues.append({"code": "duplicate_claim_owner", "path": ROOT_INDEX})
    seen_ids: dict[str, str] = {}
    documents: dict[str, tuple[str, dict[str, Any]]] = {}
    root_specs: list[tuple[dict[str, Any], str, str]] = []
    for area in areas:
        index_valid = True
        index_text: str | None = None
        try:
            path = _ensure_contained(repo, area["path"])
            index_text = path.read_text(encoding="utf-8")
            index = parse_area_index(index_text)
        except FileNotFoundError:
            issues.append({"code": "index_missing", "path": area["path"]})
            continue
        except (OSError, UnicodeError) as error:
            issues.append({"code": "index_invalid", "path": area["path"], "message": str(error)})
            continue
        except ContextError as error:
            issues.append({"code": error.code, "path": error.details.get("path", area["path"]), "message": error.message})
            if index_text is None:
                continue
            try:
                metadata = _parse_area_index_metadata(index_text)
            except ContextError:
                continue
            index = AreaIndex(frontmatter=metadata, current=[], history=[], text=index_text)
            index_valid = False
        metadata = index.frontmatter
        root_specs.append((area, _area_label(area["area"]), metadata["summary"]))
        if (
            metadata["area"],
            metadata["owner"],
            metadata["artifact_schema"],
            metadata["authority"],
        ) != (
            area["area"],
            area["owner"],
            area["artifact_schema"],
            area["authority"],
        ):
            issues.append({"code": "area_index_mismatch", "path": area["path"]})
        actual: dict[str, dict[str, Any]] = {}
        try:
            for artifact_path, state in _scan_area_paths(repo, area["area"]):
                relative = artifact_path.relative_to(repo).as_posix()
                try:
                    row = _entry_from_document(repo, artifact_path, metadata, state)
                    document = parse_document(artifact_path.read_text(encoding="utf-8"))
                    _validate_strict_lifecycle(document.frontmatter, state, relative)
                except (OSError, UnicodeError) as error:
                    issues.append({"code": "artifact_invalid", "path": relative, "message": str(error)})
                    continue
                except ContextError as error:
                    issues.append({"code": error.code, "path": relative})
                    continue
                if row["id"] in seen_ids:
                    issues.append({"code": "duplicate_id", "path": relative, "other": seen_ids[row["id"]]})
                else:
                    seen_ids[row["id"]] = relative
                    documents[row["id"]] = (relative, document.frontmatter)
                actual[row["id"]] = row
        except ContextError as error:
            issues.append({"code": error.code, "path": error.details.get("path", f"context/{area['area']}")})
        projected = {row["id"]: row for row in index.current + index.history} if index_valid else {}
        for identifier in sorted(set(projected) - set(actual)):
            issues.append({"code": "index_ghost_entry", "path": projected[identifier]["path"], "id": identifier})
        for identifier in sorted(set(actual) - set(projected)):
            issues.append({"code": "index_missing_entry", "path": actual[identifier]["path"], "id": identifier})
        for identifier in sorted(set(actual) & set(projected)):
            if actual[identifier] != projected[identifier]:
                code = "index_ghost_entry" if actual[identifier]["path"] != projected[identifier]["path"] else "index_content_drift"
                issues.append({"code": code, "path": projected[identifier]["path"], "actual_path": actual[identifier]["path"], "id": identifier})
                if code == "index_ghost_entry":
                    issues.append({"code": "index_missing_entry", "path": actual[identifier]["path"], "id": identifier})
        try:
            regenerated = render_area_index_from_repository(repo, area["area"])
            if file_bytes(regenerated) != path.read_bytes() and not any(
                issue.get("code") in INDEX_FIXABLE_CODES
                and issue.get("path", "").startswith(f"context/{area['area']}/")
                for issue in issues
            ):
                issues.append({"code": "index_content_drift", "path": area["path"]})
        except ContextError:
            pass
    if len(root_specs) == len(areas) and len(area_names) == len(set(area_names)):
        try:
            regenerated_root = render_root_index(root_text, root_specs)
            if file_bytes(regenerated_root) != (repo / ROOT_INDEX).read_bytes():
                issues.append({"code": "root_index_drift", "path": ROOT_INDEX})
        except (ContextError, OSError):
            pass
    for identifier, (path, frontmatter) in documents.items():
        refs: list[str] = []
        for key in ("anchors", "supersedes", "superseded_by"):
            value = frontmatter.get(key, [])
            refs.extend(value if isinstance(value, list) else [value])
        relations = frontmatter.get("relations", {})
        if isinstance(relations, dict):
            for value in relations.values():
                refs.extend(value if isinstance(value, list) else [value])
        for target in refs:
            if isinstance(target, str) and target.startswith("ctx_") and target not in documents:
                issues.append({"code": "broken_internal_ref", "path": path, "id": identifier, "target": target})
        retired = "/retired/" in path
        reason = frontmatter.get("retired_reason")
        if retired and reason == "superseded":
            successor_id = frontmatter.get("superseded_by")
            successor = documents.get(successor_id)
            if successor is not None and identifier not in successor[1].get("supersedes", []):
                issues.append({"code": "supersede_edge_missing", "path": path, "id": identifier, "target": successor_id})
        if retired and reason == "invalidated" and "superseded_by" in frontmatter:
            issues.append({"code": "lifecycle_invalid", "path": path, "id": identifier})
        if not retired and ("retired_at" in frontmatter or reason is not None or "superseded_by" in frontmatter):
            issues.append({"code": "lifecycle_invalid", "path": path, "id": identifier})
        for predecessor_id in frontmatter.get("supersedes", []):
            predecessor = documents.get(predecessor_id)
            if predecessor is not None and predecessor[1].get("superseded_by") != identifier:
                issues.append({"code": "supersede_edge_missing", "path": path, "id": identifier, "target": predecessor_id})
            if predecessor is not None and predecessor[1].get("schema") != frontmatter.get("schema"):
                allowed_fallback = (
                    predecessor[1].get("schema") == "context-observation/v1"
                    and frontmatter.get("schema") == "context-decision/v1"
                    and predecessor[1].get("kind_hint") == "decision"
                    and predecessor[1].get("source_claim_fingerprint") == frontmatter.get("claim_fingerprint")
                )
                if not allowed_fallback:
                    issues.append({"code": "illegal_cross_kind_predecessor", "path": path, "id": identifier, "target": predecessor_id})
    successor_edges = {
        identifier: frontmatter["superseded_by"]
        for identifier, (_, frontmatter) in documents.items()
        if frontmatter.get("retired_reason") == "superseded" and isinstance(frontmatter.get("superseded_by"), str)
    }
    states: dict[str, int] = {}

    def visit(identifier: str, trail: list[str]) -> None:
        state = states.get(identifier, 0)
        if state == 1:
            start = trail.index(identifier) if identifier in trail else 0
            cycle = trail[start:] + [identifier]
            issues.append({"code": "lifecycle_cycle", "path": documents[identifier][0], "ids": cycle})
            return
        if state == 2:
            return
        states[identifier] = 1
        successor = successor_edges.get(identifier)
        if successor in documents:
            visit(successor, [*trail, identifier])
        states[identifier] = 2

    for identifier in sorted(successor_edges):
        if states.get(identifier, 0) == 0:
            visit(identifier, [])
    current_slots: dict[tuple[str, str], str] = {}
    for identifier, (path, frontmatter) in documents.items():
        if frontmatter.get("schema") == "context-decision/v1" and "/retired/" not in path:
            slot = (
                _canonical_decision_scope(frontmatter.get("scope", "")),
                _canonical_decision_key(frontmatter.get("decision_key", "")),
            )
            if slot in current_slots:
                issues.append({"code": "duplicate_current_slot", "path": path, "other": current_slots[slot]})
            current_slots[slot] = path
    return {
        "schema": "context-integrity-result/v1",
        "ok": not issues,
        "issues": sorted(issues, key=canonical_json),
        "warnings": [],
        "root_digest": sha256_bytes(root_text.encode("utf-8")),
    }


def doctor_repository(repo: pathlib.Path) -> dict[str, Any]:
    root = repo / "context"
    root_index = repo / ROOT_INDEX
    if not root.exists() or not root_index.exists():
        return {"schema": "context-core-doctor/v1", "owner": "context-core", "supported_protocols": [PROTOCOL], "repository_state": "absent", "root": "context/", "issues": []}
    try:
        result = refresh_repository(repo, strict=True)
    except ContextError as error:
        return {"schema": "context-core-doctor/v1", "owner": "context-core", "supported_protocols": [PROTOCOL], "repository_state": "partial", "root": "context/", "issues": [{"code": error.code, "path": error.details.get("path")}]}
    return {"schema": "context-core-doctor/v1", "owner": "context-core", "supported_protocols": [PROTOCOL], "repository_state": "ready" if result["ok"] else "invalid", "root": "context/", "issues": result["issues"]}


def schema_result() -> dict[str, Any]:
    return {
        "schema": "context-core-schema/v1", "protocol": PROTOCOL, "storage_root": "context/", "root_override": False,
        "id": "ctx_<lowercase-uuidv4-hex>", "json_success": {"ok": True, "result": {}},
        "json_error": {"ok": False, "error": {"code": "string", "message": "string", "details": {}}},
        "exit_codes": {"usage_schema_filename": 2, "not_found": 3, "ambiguous": 4, "conflict": 5, "integrity_index": 6},
        "commands": [
            "schema", "capabilities", "doctor", "init", "draft", "lifecycle prepare", "area register",
            "transaction preview", "transaction apply", "recall", "snapshot save/update/list/search/load/discard",
            "observation capture/read/search/annotate/reverify/invalidate/supersede/discard", "rename", "discard", "refresh",
        ],
    }


def _repository_root() -> pathlib.Path:
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True)
    if completed.returncode or not completed.stdout.strip():
        raise ContextError("repository_not_found", "current directory is not in a Git worktree", exit_code=EXIT_NOT_FOUND)
    root = pathlib.Path(completed.stdout.strip()).resolve()
    cwd = pathlib.Path.cwd().resolve()
    try:
        cwd.relative_to(root)
    except ValueError as error:
        raise ContextError("repository_not_found", "cwd is outside the resolved Git worktree", exit_code=EXIT_NOT_FOUND) from error
    return root


def _load_json_argument(value: str, *, allow_stdin: bool = False) -> Any:
    if value == "@-":
        if not allow_stdin:
            raise ContextError("usage_invalid", "stdin is not supported for this argument")
        text = sys.stdin.read()
    elif value.startswith("@"):
        text = pathlib.Path(value[1:]).read_text(encoding="utf-8")
    else:
        raise ContextError("usage_invalid", "JSON input must use @file or @-")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ContextError("schema_invalid", "input is not valid JSON") from error


def _load_text_argument(value: str) -> str:
    if not value.startswith("@") or value == "@-":
        raise ContextError("usage_invalid", "text input must use @file")
    return pathlib.Path(value[1:]).read_text(encoding="utf-8")


def _load_body_argument(value: str) -> str:
    if value.startswith("@@"):
        return value[1:]
    if value == "@-":
        return sys.stdin.read()
    if value.startswith("@"):
        return pathlib.Path(value[1:]).read_text(encoding="utf-8")
    return value


def _direct_attestation(value: dict[str, Any], candidate: dict[str, Any], kind: str) -> dict[str, Any]:
    normalized = dict(value)
    normalized.setdefault("schema", "context-semantic-attestation/v1")
    normalized.setdefault("operation", "claim")
    normalized.setdefault("input_schema", candidate["schema"])
    normalized.setdefault("input_digest", canonical_digest(candidate))
    _validate_attestation(normalized, "claim", candidate, set(builtin_capability(kind)["claim_assertions"]))
    return normalized


def _section_arguments(args: argparse.Namespace, mapping: Sequence[tuple[str, str]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for argument, section in mapping:
        value = getattr(args, argument, None)
        if value is not None:
            output[section] = _load_body_argument(value)
    return output


def _body_to_items(value: str) -> list[str]:
    body = _load_body_argument(value).strip()
    if not body:
        return []
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if all(line.startswith("- ") for line in lines):
        return [line[2:].strip() for line in lines]
    return [body]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="context_cli.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("schema", "capabilities", "doctor", "init"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
    draft = sub.add_parser("draft")
    draft.add_argument("--kind", choices=BUILTIN_AREAS, required=True)
    draft.add_argument("--candidate", required=True)
    draft.add_argument("--attestation", required=True)
    draft.add_argument("--json", action="store_true")
    lifecycle = sub.add_parser("lifecycle")
    lifecycle_sub = lifecycle.add_subparsers(dest="lifecycle_command", required=True)
    prepare = lifecycle_sub.add_parser("prepare")
    prepare.add_argument("--transition", choices=("observation_supersede", "decision_fallback_import"), required=True)
    prepare.add_argument("--predecessor", required=True)
    prepare.add_argument("--successor-result", required=True)
    prepare.add_argument("--json", action="store_true")
    area = sub.add_parser("area")
    area_sub = area.add_subparsers(dest="area_command", required=True)
    register = area_sub.add_parser("register")
    register.add_argument("--descriptor", required=True)
    register.add_argument("--index-seed", required=True)
    register.add_argument("--json", action="store_true")
    transaction = sub.add_parser("transaction")
    transaction_sub = transaction.add_subparsers(dest="transaction_command", required=True)
    preview = transaction_sub.add_parser("preview")
    preview.add_argument("--owner-result", required=True)
    preview.add_argument("--owner-validation")
    preview.add_argument("--prior-bundle", action="append", default=[])
    preview.add_argument("--json", action="store_true")
    apply = transaction_sub.add_parser("apply")
    apply.add_argument("--plan-bundle", required=True)
    apply.add_argument("--approved-digest", required=True)
    apply.add_argument("--json", action="store_true")
    candidate_parser = sub.add_parser("candidate")
    candidate_sub = candidate_parser.add_subparsers(dest="candidate_command", required=True)
    route = candidate_sub.add_parser("route")
    route.add_argument("--batch", required=True)
    route.add_argument("--capabilities", required=True)
    route.add_argument("--claim-results", required=True)
    route.add_argument("--json", action="store_true")
    policy = sub.add_parser("policy")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    policy_preview = policy_sub.add_parser("preview")
    policy_preview.add_argument("--target", choices=tuple(sorted(POLICY_TARGETS)), required=True)
    policy_preview.add_argument("--json", action="store_true")
    recall = sub.add_parser("recall")
    recall.add_argument("--query", default="")
    recall.add_argument("--area", action="append", default=[])
    recall.add_argument("--include-history", action="store_true")
    recall.add_argument("--facet", action="append", default=[])
    recall.add_argument("--limit", type=int, default=8)
    recall.add_argument("--pack", action="store_true")
    recall.add_argument("--section", action="append", default=[])
    recall.add_argument("--read", action="append", default=[])
    recall.add_argument("--strict-index", action="store_true")
    recall.add_argument("--max-bytes", type=int)
    recall.add_argument("--json", action="store_true")
    rename = sub.add_parser("rename")
    rename.add_argument("--id", required=True)
    rename.add_argument("--filename", required=True)
    rename.add_argument("--json", action="store_true")
    discard = sub.add_parser("discard")
    discard.add_argument("--id", required=True)
    discard.add_argument("--json", action="store_true")
    snapshot = sub.add_parser("snapshot")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)
    snapshot_save = snapshot_sub.add_parser("save")
    snapshot_save.add_argument("--title", required=True)
    snapshot_save.add_argument("--summary", required=True)
    snapshot_save.add_argument("--filename")
    snapshot_save.add_argument("--captured-from", choices=("conversation", "workspace", "manual", "import"), required=True)
    snapshot_save.add_argument("--attestation", required=True)
    snapshot_save.add_argument("--sec-context", required=True)
    snapshot_save.add_argument("--sec-open-items", required=True)
    snapshot_save.add_argument("--sec-next-steps", required=True)
    snapshot_save.add_argument("--sec-decided")
    snapshot_save.add_argument("--sec-refs")
    snapshot_save.add_argument("--sec-candidates")
    snapshot_save.add_argument("--anchor", action="append", default=[])
    snapshot_save.add_argument("--source-ref", action="append", default=[])
    snapshot_save.add_argument("--tag", action="append", default=[])
    snapshot_save.add_argument("--search-term", action="append", default=[])
    snapshot_save.add_argument("--json", action="store_true")
    snapshot_update = snapshot_sub.add_parser("update")
    snapshot_update.add_argument("--id", required=True)
    snapshot_update.add_argument("--title")
    snapshot_update.add_argument("--summary")
    snapshot_update.add_argument("--merge", action="store_true")
    snapshot_update.add_argument("--sec-context")
    snapshot_update.add_argument("--sec-open-items")
    snapshot_update.add_argument("--sec-next-steps")
    snapshot_update.add_argument("--sec-decided")
    snapshot_update.add_argument("--sec-refs")
    snapshot_update.add_argument("--sec-candidates")
    snapshot_update.add_argument("--anchor", action="append")
    snapshot_update.add_argument("--source-ref", action="append")
    snapshot_update.add_argument("--tag", action="append")
    snapshot_update.add_argument("--search-term", action="append")
    snapshot_update.add_argument("--clear", action="append", default=[])
    snapshot_update.add_argument("--json", action="store_true")
    for name in ("list", "search", "load", "discard"):
        command = snapshot_sub.add_parser(name)
        if name in {"load", "discard"}:
            command.add_argument("--id", required=True)
        if name == "search":
            command.add_argument("--query", required=True)
        if name in {"list", "search"}:
            command.add_argument("--limit", type=int, default=8)
        if name == "load":
            command.add_argument("--section", action="append", default=[])
        command.add_argument("--json", action="store_true")
    observation = sub.add_parser("observation")
    observation_sub = observation.add_subparsers(dest="observation_command", required=True)
    observation_capture = observation_sub.add_parser("capture")
    observation_capture.add_argument("--title", required=True)
    observation_capture.add_argument("--summary", required=True)
    observation_capture.add_argument("--filename")
    observation_capture.add_argument("--captured-from", choices=("conversation", "workspace", "manual", "import"), required=True)
    observation_capture.add_argument("--attestation", required=True)
    observation_capture.add_argument("--sec-observation", required=True)
    observation_capture.add_argument("--sec-evidence", required=True)
    observation_capture.add_argument("--sec-impact")
    observation_capture.add_argument("--sec-handling")
    observation_capture.add_argument("--sec-followup")
    observation_capture.add_argument("--kind-hint", choices=("decision",))
    observation_capture.add_argument("--source-ref", action="append", default=[])
    observation_capture.add_argument("--tag", action="append", default=[])
    observation_capture.add_argument("--search-term", action="append", default=[])
    observation_capture.add_argument("--json", action="store_true")
    observation_read = observation_sub.add_parser("read")
    observation_read.add_argument("--id", required=True)
    observation_read.add_argument("--section", action="append", default=[])
    observation_read.add_argument("--json", action="store_true")
    observation_search_parser = observation_sub.add_parser("search")
    observation_search_parser.add_argument("--query", default="")
    observation_search_parser.add_argument("--include-history", action="store_true")
    observation_search_parser.add_argument("--limit", type=int, default=8)
    observation_search_parser.add_argument("--json", action="store_true")
    annotate = observation_sub.add_parser("annotate")
    annotate.add_argument("--id", required=True)
    annotate.add_argument("--title")
    annotate.add_argument("--summary")
    annotate.add_argument("--tag", action="append")
    annotate.add_argument("--search-term", action="append")
    annotate.add_argument("--source-ref", action="append")
    annotate.add_argument("--related", action="append")
    annotate.add_argument("--clear", action="append", default=[])
    annotate.add_argument("--json", action="store_true")
    reverify = observation_sub.add_parser("reverify")
    reverify.add_argument("--id", required=True)
    reverify.add_argument("--verified-at", required=True)
    reverify.add_argument("--evidence-ref", required=True)
    reverify.add_argument("--json", action="store_true")
    invalidate = observation_sub.add_parser("invalidate")
    invalidate.add_argument("--id", required=True)
    invalidate.add_argument("--reason", required=True)
    invalidate.add_argument("--json", action="store_true")
    supersede = observation_sub.add_parser("supersede")
    supersede.add_argument("--id", required=True)
    supersede.add_argument("--successor-result", required=True)
    supersede.add_argument("--lifecycle-input", required=True)
    supersede.add_argument("--lifecycle-attestation", required=True)
    supersede.add_argument("--json", action="store_true")
    observation_discard = observation_sub.add_parser("discard")
    observation_discard.add_argument("--id", required=True)
    observation_discard.add_argument("--json", action="store_true")
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--level", choices=("integrity", "hygiene", "all"), default="integrity")
    refresh.add_argument("--strict", action="store_true")
    refresh.add_argument("--fix", choices=("index",))
    refresh.add_argument("--json", action="store_true")
    return parser


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "schema":
        return schema_result()
    if args.command == "capabilities":
        return capabilities_result()
    repo = _repository_root()
    if args.command == "doctor":
        return doctor_repository(repo)
    if args.command == "init":
        return build_init_bundle(repo)
    if args.command == "draft":
        candidate = _load_json_argument(args.candidate, allow_stdin=True)
        if candidate.get("requested_kind") != args.kind:
            raise ContextError("candidate_invalid", "draft kind differs from embedded candidate")
        return draft_owner_result(
            candidate,
            _load_json_argument(args.attestation),
        )
    if args.command == "lifecycle" and args.lifecycle_command == "prepare":
        value = prepare_lifecycle_input(repo, args.transition, args.predecessor, _load_json_argument(args.successor_result, allow_stdin=True))
        return {"input": value, "input_digest": canonical_digest(value), "applied": False}
    if args.command == "area" and args.area_command == "register":
        return build_area_register_bundle(repo, _load_json_argument(args.descriptor, allow_stdin=True), _load_text_argument(args.index_seed))
    if args.command == "transaction" and args.transaction_command == "preview":
        owner_result = _load_json_argument(args.owner_result, allow_stdin=True)
        validation = _load_json_argument(args.owner_validation) if args.owner_validation else None
        priors = [_load_json_argument(value) for value in args.prior_bundle]
        return finalize_owner_result(repo, owner_result, validation, priors)
    if args.command == "transaction" and args.transaction_command == "apply":
        return apply_bundle(repo, _load_json_argument(args.plan_bundle), args.approved_digest)
    if args.command == "candidate" and args.candidate_command == "route":
        return route_candidates(
            _load_json_argument(args.batch, allow_stdin=True),
            _load_json_argument(args.capabilities),
            _load_json_argument(args.claim_results),
        )
    if args.command == "policy" and args.policy_command == "preview":
        return build_policy_bundle(repo, args.target)
    if args.command == "recall":
        facets = []
        for value in args.facet:
            if "=" not in value:
                raise ContextError("usage_invalid", "facet must be KEY=VALUE")
            facets.append(tuple(value.split("=", 1)))
        return recall_repository(repo, query=args.query, areas=args.area, include_history=args.include_history, facets=facets, limit=args.limit, pack=args.pack, sections=args.section, read_ids=args.read, strict_index=args.strict_index, max_bytes=args.max_bytes)
    if args.command == "rename":
        return build_rename_bundle(repo, args.id, args.filename)
    if args.command == "discard":
        return build_discard_bundle(repo, args.id)
    if args.command == "snapshot":
        if args.snapshot_command == "save":
            owner_inputs: dict[str, Any] = {
                "current_context": _load_body_argument(args.sec_context),
                "open_items": _body_to_items(args.sec_open_items),
                "next_steps": _body_to_items(args.sec_next_steps),
            }
            for argument, field in (("sec_decided", "decided"), ("sec_refs", "refs"), ("sec_candidates", "capture_candidates")):
                value = getattr(args, argument)
                if value is not None:
                    owner_inputs[field] = _body_to_items(value)
            if args.anchor:
                owner_inputs["anchors"] = args.anchor
            candidate = direct_candidate(
                "snapshot",
                title=args.title,
                summary=args.summary,
                captured_from=args.captured_from,
                owner_inputs=owner_inputs,
                source_refs=args.source_ref,
                tags=args.tag,
                search_terms=args.search_term,
            )
            attestation = _direct_attestation(_load_json_argument(args.attestation), candidate, "snapshot")
            return build_snapshot_save_bundle(repo, candidate, attestation, filename=args.filename)
        if args.snapshot_command == "update":
            sections = _section_arguments(args, (
                ("sec_context", "현재 맥락"), ("sec_open_items", "열린 항목"), ("sec_next_steps", "다음 단계"),
                ("sec_decided", "정해진 것"), ("sec_refs", "참조"), ("sec_candidates", "capture 후보"),
            ))
            return build_snapshot_update_bundle(
                repo,
                args.id,
                merge=args.merge,
                sections=sections,
                title=args.title,
                summary=args.summary,
                tags=args.tag,
                search_terms=args.search_term,
                source_refs=args.source_ref,
                anchors=args.anchor,
                clear=args.clear,
            )
        if args.snapshot_command == "list":
            return snapshot_list(repo, args.limit)
        if args.snapshot_command == "search":
            return snapshot_search(repo, args.query, args.limit)
        if args.snapshot_command == "load":
            return snapshot_load(repo, args.id, args.section)
        if args.snapshot_command == "discard":
            return build_snapshot_discard_bundle(repo, args.id)
    if args.command == "observation":
        if args.observation_command == "capture":
            owner_inputs = {
                "observation": _load_body_argument(args.sec_observation),
                "evidence": _body_to_items(args.sec_evidence),
            }
            if args.sec_impact is not None:
                owner_inputs["impact"] = _load_body_argument(args.sec_impact)
            if args.sec_handling is not None:
                owner_inputs["current_handling"] = _load_body_argument(args.sec_handling)
            if args.sec_followup is not None:
                owner_inputs["followup_conditions"] = _body_to_items(args.sec_followup)
            candidate = direct_candidate(
                "observation",
                title=args.title,
                summary=args.summary,
                captured_from=args.captured_from,
                owner_inputs=owner_inputs,
                source_refs=args.source_ref,
                tags=args.tag,
                search_terms=args.search_term,
                kind_hint=args.kind_hint,
            )
            attestation = _direct_attestation(_load_json_argument(args.attestation), candidate, "observation")
            return build_observation_capture_bundle(repo, candidate, attestation, filename=args.filename)
        if args.observation_command == "read":
            return observation_read(repo, args.id, args.section)
        if args.observation_command == "search":
            return observation_search(repo, args.query, include_history=args.include_history, limit=args.limit)
        if args.observation_command == "annotate":
            return build_observation_annotate_bundle(
                repo,
                args.id,
                title=args.title,
                summary=args.summary,
                tags=args.tag,
                search_terms=args.search_term,
                source_refs=args.source_ref,
                related=args.related,
                clear=args.clear,
            )
        if args.observation_command == "reverify":
            return build_observation_reverify_bundle(repo, args.id, args.verified_at, args.evidence_ref)
        if args.observation_command == "invalidate":
            return build_observation_invalidate_bundle(repo, args.id, args.reason)
        if args.observation_command == "supersede":
            return build_observation_supersede_bundle(
                repo,
                args.id,
                _load_json_argument(args.successor_result, allow_stdin=True),
                _load_json_argument(args.lifecycle_input),
                _load_json_argument(args.lifecycle_attestation),
            )
        if args.observation_command == "discard":
            return build_observation_discard_bundle(repo, args.id)
    if args.command == "refresh":
        if args.fix:
            return build_index_fix_bundle(repo)
        result = refresh_repository(repo, strict=args.strict)
        if args.strict and not result["ok"]:
            raise ContextError("integrity_failed", "strict integrity found blocking issues", {"issues": result["issues"]}, EXIT_INTEGRITY)
        return result
    raise ContextError("usage_invalid", "unsupported command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = _dispatch(args)
        envelope = {"ok": True, "result": result}
        print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) if getattr(args, "json", False) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ContextError as error:
        print(json.dumps(error.envelope(), ensure_ascii=False, separators=(",", ":")), file=sys.stdout)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
