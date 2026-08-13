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
MAX_USER_BYTES = 32 * 1024
ROOT_INDEX = "context/context.index.md"
BUILTIN_AREAS = ("snapshot", "observation")
RESERVED_INDEX_PATHS = {
    ROOT_INDEX,
    "context/snapshot/snapshot.index.md",
    "context/observation/observation.index.md",
    "context/decision/decision.index.md",
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
    artifact_opens: int = 0
    artifact_directory_lists: int = 0
    artifact_stats: int = 0


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def normalized_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


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
        raise ContextError("index_stale", "generated index marker is invalid", {"block": name}, EXIT_INTEGRITY)
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
            raise ContextError("index_stale", "root area row is malformed", exit_code=EXIT_INTEGRITY)
        try:
            row = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise ContextError("index_stale", "root area row JSON is malformed", exit_code=EXIT_INTEGRITY) from error
        expected = ["area", "path", "owner", "claims", "artifact_schema", "authority"]
        if list(row) != expected or row.get("claims") != [row.get("area")]:
            raise ContextError("index_stale", "root area row fields are not canonical", exit_code=EXIT_INTEGRITY)
        areas.append(row)
    if areas != sorted(areas, key=lambda row: row["area"]):
        raise ContextError("index_stale", "root area rows are not sorted", exit_code=EXIT_INTEGRITY)
    return frontmatter, areas


def parse_area_index(text: str) -> AreaIndex:
    frontmatter = _parse_index_frontmatter(text, "context-area-index/v1")
    required = ("area", "owner", "artifact_schema", "authority", "summary")
    if any(not isinstance(frontmatter.get(key), str) or not frontmatter[key] for key in required):
        raise ContextError("index_stale", "area index metadata is incomplete", exit_code=EXIT_INTEGRITY)
    history_required = frontmatter["area"] != "snapshot"
    blocks = (("current", "current"),) + (("history", "history"),) if history_required else (("current", "current"),)
    parsed: dict[str, list[dict[str, Any]]] = {"current": [], "history": []}
    for block, expected_state in blocks:
        for line in _extract_block(text, block):
            match = ENTRY_ROW.fullmatch(line)
            if not match:
                raise ContextError("index_stale", "area entry row is malformed", {"block": block}, EXIT_INTEGRITY)
            try:
                row = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise ContextError("index_stale", "area entry JSON is malformed", exit_code=EXIT_INTEGRITY) from error
            if row.get("state") != expected_state or not is_context_id(row.get("id")):
                raise ContextError("index_stale", "area entry state or id is invalid", exit_code=EXIT_INTEGRITY)
            parsed[block].append(row)
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


def _entry_from_document(repo: pathlib.Path, path: pathlib.Path, metadata: dict[str, Any], state: str) -> dict[str, Any]:
    document = parse_document(path.read_text(encoding="utf-8"))
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
                if metrics:
                    metrics.artifact_directory_lists += 1
                with os.scandir(root / "retired") as historical_entries:
                    for historical in historical_entries:
                        if historical.name.endswith(".md") and not historical.name.endswith(".index.md"):
                            yield pathlib.Path(historical.path), "history"
            elif entry.name.endswith(".md") and not entry.name.endswith(".index.md"):
                yield pathlib.Path(entry.path), "current"


def render_area_index_from_repository(repo: pathlib.Path, area: str) -> str:
    index_path = _ensure_contained(repo, f"context/{area}/{area}.index.md")
    if not index_path.is_file():
        raise ContextError("index_seed_required", "area index is missing", {"area": area}, EXIT_INTEGRITY)
    existing = index_path.read_text(encoding="utf-8")
    parsed = parse_area_index(existing)
    rows: dict[str, list[dict[str, Any]]] = {"current": [], "history": []}
    for path, state in _scan_area_paths(repo, area):
        rows[state].append(_entry_from_document(repo, path, parsed.frontmatter, state))
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
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ContextError("index_stale", "index path is missing", {"path": path.as_posix()}, EXIT_INTEGRITY) from error


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
        if metrics:
            metrics.artifact_opens += 1
        entries.append(_entry_from_document(repo, path, metadata, state))
    return entries


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
    max_bytes: int = MAX_STAGE1_BYTES,
    metrics: IOMetrics | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 20 or not 1 <= max_bytes <= MAX_USER_BYTES:
        raise ContextError("usage_invalid", "limit or max-bytes is outside the v1 range")
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
    output: list[dict[str, Any]] = []
    for row, area_row, score in candidates:
        item = {
            "id": row["id"], "kind": area_row["area"], "state": row["state"], "title": row["title"],
            "summary": row["summary"], "path": row["path"], "authority": area_row["authority"], "score": score,
        }
        for projection in area_indexes.get(area_row["area"], AreaIndex({}, [], [], "")).frontmatter.get("projection_fields", []):
            if projection in row:
                item[projection] = row[projection]
        proposed = output + [item]
        if len(canonical_json(proposed).encode("utf-8")) > max_bytes:
            break
        output.append(item)
    if pack or sections or read_ids:
        for item in output:
            path = repo / item["path"]
            try:
                if metrics:
                    metrics.artifact_opens += 1
                document = parse_document(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            selected_sections = sections or tuple(document.sections)
            item["sections"] = {name: document.sections[name] for name in selected_sections if name in document.sections}
    omitted = len(candidates) - len(output) + max(0, len(filtered) - limit)
    return {
        "items": output, "returned": len(output), "omitted": omitted, "truncated": omitted > 0,
        "index_fallback": fallback, "warnings": sorted(set(warnings)),
    }


def builtin_capability(kind: str) -> dict[str, Any]:
    if kind == "snapshot":
        return {
            "schema": "context-owner-capability/v1", "owner": "context-core", "kind": "snapshot",
            "artifact_schema": "context-snapshot/v1", "authority": "staging",
            "claim_surface": {"type": "agent_skill", "name": "context-core:snapshot", "operation": "claim"},
            "claim_rule": "사용자가 재개할 unfinished session handoff를 명시적으로 저장하려 한다",
            "claim_assertions": ["handoff_requested", "unfinished_context_present"],
            "draft_fields": {"required": {}, "optional": {}},
        }
    if kind == "observation":
        return {
            "schema": "context-owner-capability/v1", "owner": "context-core", "kind": "observation",
            "artifact_schema": "context-observation/v1", "authority": "evidence",
            "claim_surface": {"type": "agent_skill", "name": "context-core:observation", "operation": "claim"},
            "claim_rule": "나중에 조사·판단에 재사용할 수 있는 발견 또는 근거다",
            "claim_assertions": ["reusable_observation", "evidence_present"],
            "lifecycle_operations": {"same_claim": {"surface": {"type": "agent_skill", "name": "context-core:observation", "operation": "same_claim"}, "rule": "same observation claim", "assertions": ["same_semantic_claim"]}},
            "draft_fields": {"required": {}, "optional": {}},
        }
    raise ContextError("owner_unavailable", "built-in capability is unavailable", {"kind": kind}, EXIT_CONFLICT)


def capabilities_result() -> dict[str, Any]:
    return {"schema": "context-owner-capabilities/v1", "owners": [builtin_capability("snapshot"), builtin_capability("observation")]}


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


def validate_owner_result(result: dict[str, Any]) -> None:
    if result.get("schema") != "context-owner-result/v1" or not isinstance(result.get("owner"), str):
        raise ContextError("owner_result_invalid", "owner result envelope is invalid", exit_code=EXIT_CONFLICT)
    missing = {"result_type", "transition", "target_kind", "capability_digest", "semantic_inputs", "semantic_attestations", "artifact_drafts", "effects", "proposed_plan"} - set(result)
    if missing:
        raise ContextError("owner_result_invalid", "owner result required fields are missing", {"missing": sorted(missing)}, EXIT_CONFLICT)
    kind = result["target_kind"]
    if result["owner"] == "context-core":
        capability = builtin_capability(kind)
        if result["capability_digest"] != canonical_digest(capability):
            raise ContextError("capability_digest_mismatch", "owner result capability digest is stale", exit_code=EXIT_CONFLICT)
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
    if result["result_type"] == "claim":
        if result.get("decision") != "claim" or result.get("transition") != "capture" or "claim" not in inputs or "claim" not in attestations:
            raise ContextError("owner_result_invalid", "claim result lacks complete claim evidence", exit_code=EXIT_CONFLICT)
        if result.get("candidate_id") != inputs["claim"]["value"].get("candidate_id"):
            raise ContextError("claim_result_mismatch", "claim result candidate does not match embedded input", exit_code=EXIT_CONFLICT)
        if result["owner"] == "context-core":
            expected = set(builtin_capability(kind)["claim_assertions"])
            actual = {assertion["name"] for assertion in attestations["claim"]["assertions"]}
            if expected != actual:
                raise ContextError("semantic_attestation_invalid", "claim assertions do not match capability", exit_code=EXIT_CONFLICT)
    elif result["result_type"] == "mutation":
        if "mutation_request" not in inputs or "mutation_request" in attestations:
            raise ContextError("owner_result_invalid", "mutation result lacks an unattested mutation request", exit_code=EXIT_CONFLICT)
    else:
        raise ContextError("owner_result_invalid", "result_type is unsupported", exit_code=EXIT_CONFLICT)
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
    for operation in operations:
        if operation.get("op") not in {"create", "replace", "move", "delete"}:
            raise ContextError("plan_preview_mismatch", "owner operation is not allowed", exit_code=EXIT_CONFLICT)
        if operation["op"] != "delete" and operation["effect_id"] not in draft_ids:
            raise ContextError("plan_preview_mismatch", "non-delete operation lacks a complete destination draft", exit_code=EXIT_CONFLICT)


def _material(material_id: str, path: str | None, content: str) -> dict[str, Any]:
    return {"material_id": material_id, "path": path, "content": content}


def _bundle_result(preview: dict[str, Any], plan: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
    approval_material = {"preview": preview, "plan": plan}
    digest = canonical_digest(approval_material)
    bundle = {"schema": "context-mutation-bundle/v1", "approval_material": approval_material, "approval_digest": digest, "materials": materials}
    return {"bundle": bundle, "approval_preview": preview, "approval_digest": digest, "applied": False, "noop": False}


def build_init_bundle(repo: pathlib.Path) -> dict[str, Any]:
    root_path = repo / "context"
    paths = [repo / ROOT_INDEX, repo / "context/snapshot/snapshot.index.md", repo / "context/observation/observation.index.md"]
    existing = [path.is_file() for path in paths]
    if all(existing):
        _, areas = parse_root_index(paths[0].read_text(encoding="utf-8"))
        parse_area_index(paths[1].read_text(encoding="utf-8"))
        parse_area_index(paths[2].read_text(encoding="utf-8"))
        if {row["area"] for row in areas}.issuperset(BUILTIN_AREAS):
            return {"noop": True, "applied": False, "changed_paths": []}
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
                "created_at": document.frontmatter["created_at"], "terms": _terms(document.frontmatter),
            }
            del path, fake_repo
            for key in metadata.get("projection_fields", []):
                if key in document.frontmatter:
                    row[key] = document.frontmatter[key]
            if row["state"] == "history":
                row["retired_at"] = document.frontmatter["retired_at"]
                row["retired_reason"] = document.frontmatter["retired_reason"]
                if "superseded_by" in document.frontmatter:
                    row["superseded_by"] = document.frontmatter["superseded_by"]
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


def finalize_owner_result(repo: pathlib.Path, owner_result: dict[str, Any], owner_validation: dict[str, Any] | None = None, prior_bundles: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    del prior_bundles
    validate_owner_result(owner_result)
    owner = owner_result["owner"]
    area = owner_result["target_kind"]
    area_row, area_index = _area_for_owner(repo, area, owner)
    drafts = {draft["effect_id"]: draft for draft in owner_result["artifact_drafts"]}
    effects = {effect["effect_id"]: effect for effect in owner_result["effects"]}
    operations: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    owner_material_id = "material_owner_result"
    owner_content = canonical_json(owner_result)
    owner_digest = sha256_bytes(owner_content.encode("utf-8"))
    materials.append(_material(owner_material_id, None, owner_content))
    for proposed in owner_result["proposed_plan"]["operations"]:
        effect_id = proposed["effect_id"]
        effect = effects[effect_id]
        if effect.get("area") != area:
            raise ContextError("area_owner_mismatch", "owner plan touches another area", exit_code=EXIT_CONFLICT)
        operation = proposed["op"]
        draft = drafts.get(effect_id)
        if operation != "delete":
            assert draft is not None
            relative = draft["path"]
            if not relative.startswith(f"context/{area}/") or relative in RESERVED_INDEX_PATHS:
                raise ContextError("path_escape", "draft path is outside the owner area", {"path": relative}, EXIT_CONFLICT)
            _ensure_contained(repo, relative)
            document = parse_document(draft["content"])
            if document.frontmatter["schema"] != area_row["artifact_schema"] or document.frontmatter["id"] != effect.get("id"):
                raise ContextError("plan_preview_mismatch", "draft schema/id does not match effect", exit_code=EXIT_CONFLICT)
            material_id = f"material_{effect_id}"
            materials.append(_material(material_id, relative, draft["content"]))
            after = sha256_bytes(file_bytes(draft["content"]))
        if operation == "create":
            path = proposed["path"]
            if path != draft["path"]:
                raise ContextError("plan_preview_mismatch", "create path and draft differ", exit_code=EXIT_CONFLICT)
            current = repo / path
            if current.exists():
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
    index_after = _virtual_area_index(area_index, list(effects.values()), drafts)
    index_path = area_row["path"]
    index_before = sha256_bytes((repo / index_path).read_bytes())
    operations.append({"op": "index_rebuild", "derived_from": sorted(effects), "areas": [area], "include_root": False, "before_sha256": {index_path: index_before}, "after_sha256": {index_path: sha256_bytes(file_bytes(index_after))}})
    plan = {
        "schema": "context-mutation-plan/v1", "plan_id": new_plan_id(), "owner": owner, "source_type": "owner_result",
        "owner_result_digest": owner_digest, "owner_result_material": owner_material_id, "capability_digest": owner_result["capability_digest"],
        "transition": owner_result["transition"], "owner_descriptor": {"owner": owner, "kind": area, "artifact_schema": area_row["artifact_schema"], "authority": area_row["authority"]},
        "owner_validation": owner_validation, "prior_bundle_digests": [], "read_preconditions": [], "operations": operations,
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


def build_index_fix_bundle(repo: pathlib.Path) -> dict[str, Any]:
    integrity = refresh_repository(repo, strict=True)
    if integrity["ok"]:
        return {"noop": True, "applied": False, "changed_paths": []}
    non_index = [issue for issue in integrity["issues"] if not issue["code"].startswith("index_")]
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
        rendered = render_area_index_from_repository(repo, area)
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
    operations = plan.get("operations", [])
    non_index = [operation for operation in operations if operation.get("op") != "index_rebuild"]
    effect_ids = [operation.get("effect_id") for operation in non_index]
    preview_ids = [effect.get("effect_id") for effect in preview.get("effects", [])]
    if len(effect_ids) != len(set(effect_ids)):
        raise ContextError("plan_preview_mismatch", "operations and preview effects are not 1:1", exit_code=EXIT_CONFLICT)
    index_operations = [operation for operation in operations if operation.get("op") == "index_rebuild"]
    derived_ids = index_operations[0].get("derived_from", []) if len(index_operations) == 1 else []
    if (
        len(index_operations) != 1
        or len(derived_ids) != len(set(derived_ids))
        or set(effect_ids) | set(derived_ids) != set(preview_ids)
        or not set(effect_ids).issubset(set(derived_ids))
    ):
        raise ContextError("plan_preview_mismatch", "index rebuild does not cover preview effects", exit_code=EXIT_CONFLICT)
    for operation in non_index:
        if operation.get("op") not in {"file_create", "file_replace", "file_move", "file_delete"}:
            raise ContextError("plan_preview_mismatch", "physical operation is not allowed", exit_code=EXIT_CONFLICT)
        if operation.get("role") != "artifact":
            raise ContextError("plan_preview_mismatch", "file operation role is invalid", exit_code=EXIT_CONFLICT)
        material_id = operation.get("material")
        if operation["op"] != "file_delete" and operation.get("after_sha256") != operation.get("before_sha256") and material_id not in by_id:
            raise ContextError("material_digest_mismatch", "file operation material is missing", exit_code=EXIT_CONFLICT)
        if material_id:
            content = by_id[material_id]["content"]
            if sha256_bytes(file_bytes(content)) != operation["after_sha256"]:
                raise ContextError("material_digest_mismatch", "material bytes do not match after digest", {"material_id": material_id}, EXIT_CONFLICT)
    if plan.get("source_type") == "owner_result":
        owner_material = by_id.get(plan.get("owner_result_material"))
        if owner_material is None or owner_material.get("path") is not None or sha256_bytes(owner_material["content"].encode("utf-8")) != plan.get("owner_result_digest"):
            raise ContextError("material_digest_mismatch", "owner result material is invalid", exit_code=EXIT_CONFLICT)
        try:
            owner_result = json.loads(owner_material["content"])
        except json.JSONDecodeError as error:
            raise ContextError("owner_result_invalid", "owner result material is not JSON", exit_code=EXIT_CONFLICT) from error
        validate_owner_result(owner_result)
        _area_for_owner(repo, plan["owner_descriptor"]["kind"], plan["owner"])
    elif plan.get("source_type") != "core_control":
        raise ContextError("bundle_invalid", "source_type is unsupported", exit_code=EXIT_CONFLICT)
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
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".context-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(file_bytes(content))
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
        _atomic_write(path, materials[operation["material"]]["content"])
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
        if current != operation["before_sha256"] or operation.get("inbound_refs"):
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
            rendered = render_area_index_from_repository(repo, area)
            if sha256_bytes(file_bytes(rendered)) != operation["after_sha256"][relative]:
                raise ContextError("plan_preview_mismatch", "deterministic index output differs from preview", {"path": relative}, EXIT_INTEGRITY)
            _atomic_write(path, rendered)
            changed.append(relative)
    return index_paths


def apply_bundle(repo: pathlib.Path, bundle: dict[str, Any], approved_digest: str) -> dict[str, Any]:
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
    root_text, areas = _root_catalog(repo)
    issues: list[dict[str, Any]] = []
    area_names = [area["area"] for area in areas]
    claims = [claim for area in areas for claim in area["claims"]]
    if len(area_names) != len(set(area_names)) or len(claims) != len(set(claims)):
        issues.append({"code": "duplicate_area_owner", "path": ROOT_INDEX})
    seen_ids: dict[str, str] = {}
    documents: dict[str, tuple[str, dict[str, Any]]] = {}
    for area in areas:
        path = repo / area["path"]
        try:
            index = parse_area_index(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ContextError) as error:
            issues.append({"code": "index_invalid", "path": area["path"], "message": str(error)})
            continue
        actual: dict[str, dict[str, Any]] = {}
        for artifact_path, state in _scan_area_paths(repo, area["area"]):
            relative = artifact_path.relative_to(repo).as_posix()
            if artifact_path.is_symlink():
                issues.append({"code": "symlink_path", "path": relative})
                continue
            try:
                row = _entry_from_document(repo, artifact_path, index.frontmatter, state)
            except ContextError as error:
                issues.append({"code": error.code, "path": relative})
                continue
            if row["id"] in seen_ids:
                issues.append({"code": "duplicate_id", "path": relative, "other": seen_ids[row["id"]]})
            seen_ids[row["id"]] = relative
            documents[row["id"]] = (relative, parse_document(artifact_path.read_text(encoding="utf-8")).frontmatter)
            if state == "current" and any(key in documents[row["id"]][1] for key in ("retired_at", "retired_reason", "retirement_note")):
                issues.append({"code": "lifecycle_invalid", "path": relative})
            actual[row["id"]] = row
        projected = {row["id"]: row for row in index.current + index.history}
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
            if file_bytes(regenerated) != path.read_bytes() and not any(issue.get("code") in {"index_ghost_entry", "index_missing_entry", "index_content_drift"} and issue.get("path", "").startswith(f"context/{area['area']}/") for issue in issues):
                issues.append({"code": "index_content_drift", "path": area["path"]})
        except ContextError:
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
    current_slots: dict[tuple[str, str], str] = {}
    for identifier, (path, frontmatter) in documents.items():
        if frontmatter.get("schema") == "context-decision/v1" and "/retired/" not in path:
            slot = (frontmatter.get("scope", ""), frontmatter.get("decision_key", ""))
            if slot in current_slots:
                issues.append({"code": "duplicate_current_slot", "path": path, "other": current_slots[slot]})
            current_slots[slot] = path
    return {"schema": "context-integrity-result/v1", "ok": not issues, "issues": issues, "warnings": [], "root_digest": sha256_bytes(root_text.encode("utf-8"))}


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
        "commands": ["schema", "capabilities", "doctor", "init", "area register", "transaction preview", "transaction apply", "recall", "rename", "discard", "refresh"],
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="context_cli.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("schema", "capabilities", "doctor", "init"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
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
    recall.add_argument("--max-bytes", type=int, default=MAX_STAGE1_BYTES)
    recall.add_argument("--json", action="store_true")
    rename = sub.add_parser("rename")
    rename.add_argument("--id", required=True)
    rename.add_argument("--filename", required=True)
    rename.add_argument("--json", action="store_true")
    discard = sub.add_parser("discard")
    discard.add_argument("--id", required=True)
    discard.add_argument("--json", action="store_true")
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
    if args.command == "area" and args.area_command == "register":
        return build_area_register_bundle(repo, _load_json_argument(args.descriptor, allow_stdin=True), _load_text_argument(args.index_seed))
    if args.command == "transaction" and args.transaction_command == "preview":
        owner_result = _load_json_argument(args.owner_result, allow_stdin=True)
        validation = _load_json_argument(args.owner_validation) if args.owner_validation else None
        priors = [_load_json_argument(value) for value in args.prior_bundle]
        return finalize_owner_result(repo, owner_result, validation, priors)
    if args.command == "transaction" and args.transaction_command == "apply":
        return apply_bundle(repo, _load_json_argument(args.plan_bundle), args.approved_digest)
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
