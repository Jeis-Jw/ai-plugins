#!/usr/bin/env python3
"""AI-native wiki CLI.

Implements the wiki protocol defined by wiki/ssot/plugin_definition_v1.md:
filesystem-first, wiki/ as the default vault, basename IDs, derived indexes,
record-only relations, and retired record isolation.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


EXIT_USAGE = 2
EXIT_NO_VAULT = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_STRICT = 6

DEFAULT_VAULT = "wiki"
TASK_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+$")


@dataclass(frozen=True)
class TypeSpec:
    folder: tuple[str, ...]
    prefix: str | None
    record: bool
    relation_fields: tuple[str, ...]
    sections: tuple[str, ...]
    allow_verified_at: bool = False
    allow_affects_paths: bool = False


TYPE_SPECS: dict[str, TypeSpec] = {
    "intent": TypeSpec(("context", "intent"), "INT", True, (), ("취지", "배경")),
    "decision": TypeSpec(
        ("context", "decision"),
        "DEC",
        True,
        ("intents", "rejected_decisions", "ssot", "tasks"),
        ("결정", "취지", "배경", "고려한 대안", "트레이드오프", "재평가 조건"),
    ),
    "rejected_decision": TypeSpec(
        ("context", "rejected_decision"),
        "REJ",
        True,
        ("intents",),
        ("대안", "반려 사유", "이 대안의 취지", "재고 조건"),
    ),
    "trial_error": TypeSpec(
        ("context", "trial_error"),
        "TRI",
        True,
        ("decisions", "tasks"),
        ("교훈", "상황", "피해야 할 것", "대안 또는 우회", "현재도 유효한가"),
        allow_verified_at=True,
        allow_affects_paths=True,
    ),
    "observation": TypeSpec(
        ("context", "observation"),
        "OBS",
        True,
        ("ssot", "runbook", "decisions", "tasks"),
        ("관찰", "근거", "영향", "현재 처리", "후속 분류 조건"),
        allow_verified_at=True,
        allow_affects_paths=True,
    ),
    "ssot": TypeSpec(("ssot",), None, False, (), ("현재 상태", "취지", "구성요소"), allow_verified_at=True, allow_affects_paths=True),
    "runbook": TypeSpec(("runbook",), None, False, (), ("목적", "절차", "주의점"), allow_verified_at=True, allow_affects_paths=True),
}

BASE_INDEX_FOLDERS = (
    ("ssot",),
    ("runbook",),
    ("context", "intent"),
    ("context", "decision"),
    ("context", "rejected_decision"),
    ("context", "trial_error"),
    ("context", "observation"),
)

RELATION_ARG_TO_FIELD = {
    "intents": "intents",
    "ssot": "ssot",
    "runbook": "runbook",
    "rejected": "rejected_decisions",
    "decisions": "decisions",
    "tasks": "tasks",
}

FIXABLE_CHECKS = {"index", "retired-in-index"}


class CliError(Exception):
    def __init__(self, exit_code: int, error_code: str, message: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.error_code = error_code
        self.message = message


@dataclass
class WikiDoc:
    path: Path
    doc_id: str
    doc_type: str
    frontmatter: dict[str, Any]
    body: str
    retired: bool


def vault_path(raw: str | None) -> Path:
    path = Path(raw or DEFAULT_VAULT)
    return path if path.is_absolute() else Path.cwd() / path


def now() -> datetime:
    raw = os.environ.get("WIKI_NOW")
    if raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d-%H%M%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                if fmt == "%Y-%m-%d":
                    return parsed.replace(hour=0, minute=0, second=0)
                return parsed
            except ValueError:
                pass
        raise CliError(EXIT_USAGE, "BAD_CLOCK", f"Unsupported WIKI_NOW value: {raw}")
    return datetime.now()


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    chars: list[str] = []
    previous_dash = False
    for ch in lowered:
        if ch.isalnum():
            chars.append(ch)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "untitled"


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part.strip()) for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text

    data: dict[str, Any] = {}
    current_map: str | None = None
    for line in lines[1:end_index]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") and current_map:
            key, sep, raw_value = line.strip().partition(":")
            if sep:
                nested = data.setdefault(current_map, {})
                if isinstance(nested, dict):
                    nested[key.strip()] = parse_scalar(raw_value)
            continue
        current_map = None
        key, sep, raw_value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if raw_value.strip() == "":
            data[key] = {}
            current_map = key
        else:
            data[key] = parse_scalar(raw_value)

    body = "\n".join(lines[end_index + 1 :])
    if text.endswith("\n"):
        body += "\n"
    return data, body


def needs_quotes(value: str) -> bool:
    if value == "":
        return True
    return bool(re.search(r"[:#\[\]\{\},]|^\s|\s$", value))


def dump_scalar(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(dump_scalar(item) for item in value) + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False) if needs_quotes(value) else value
    return str(value)


def dump_frontmatter(data: dict[str, Any]) -> str:
    preferred = [
        "title",
        "created_at",
        "summary",
        "tags",
        "audience",
        "search_terms",
        "verified_at",
        "affects_paths",
        "supersedes",
        "superseded_by",
        "retired_at",
        "retired_type",
        "relations",
    ]
    keys = [key for key in preferred if key in data] + [key for key in data if key not in preferred]
    lines = ["---"]
    for key in keys:
        value = data[key]
        if isinstance(value, dict):
            if value:
                lines.append(f"{key}:")
                for nested_key, nested_value in value.items():
                    lines.append(f"  {nested_key}: {dump_scalar(nested_value)}")
            else:
                lines.append(f"{key}: {{}}")
        else:
            lines.append(f"{key}: {dump_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def read_doc(path: Path, vault: Path) -> WikiDoc:
    text = path.read_text()
    frontmatter, body = parse_frontmatter(text)
    return WikiDoc(
        path=path,
        doc_id=path.stem,
        doc_type=type_for_path(path, vault),
        frontmatter=frontmatter,
        body=body,
        retired="retired" in path.relative_to(vault).parts,
    )


def write_doc(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    path.write_text(dump_frontmatter(frontmatter) + body.lstrip("\n"))


def type_for_path(path: Path, vault: Path) -> str:
    rel = path.relative_to(vault).parts
    if not rel:
        return "unknown"
    if rel[0] in ("ssot", "runbook"):
        return rel[0]
    if len(rel) >= 3 and rel[0] == "context":
        return rel[1]
    return "unknown"


def is_index_file(path: Path, vault: Path) -> bool:
    if path == vault / "README.md":
        return True
    if path.name == f"{path.parent.name}.md":
        return True
    return False


def iter_docs(vault: Path, include_retired: bool = False) -> list[WikiDoc]:
    docs: list[WikiDoc] = []
    for path in all_markdown_paths(vault):
        if is_index_file(path, vault):
            continue
        if "sandbox" in path.relative_to(vault).parts[:1]:
            continue
        if not include_retired and is_retired_path(path, vault):
            continue
        doc_type = type_for_path(path, vault)
        if doc_type in TYPE_SPECS:
            docs.append(read_doc(path, vault))
    return docs


def require_vault(vault: Path) -> None:
    if not vault.exists():
        raise CliError(EXIT_NO_VAULT, "NO_VAULT", f"Vault does not exist: {vault}")


def folder_path(vault: Path, folder_parts: tuple[str, ...]) -> Path:
    return vault.joinpath(*folder_parts)


def index_path(vault: Path, folder_parts: tuple[str, ...]) -> Path:
    folder = folder_path(vault, folder_parts)
    return folder / f"{folder.name}.md"


def all_markdown_paths(vault: Path) -> list[Path]:
    if not vault.exists():
        return []
    return sorted(path for path in vault.rglob("*.md") if path.is_file())


def is_retired_path(path: Path, vault: Path) -> bool:
    return "retired" in path.relative_to(vault).parts


def discover_index_folders(vault: Path) -> list[tuple[str, ...]]:
    folders: set[tuple[str, ...]] = {parts for parts in BASE_INDEX_FOLDERS if folder_path(vault, parts).exists()}
    for root_name in ("ssot", "runbook"):
        root = vault / root_name
        if not root.exists():
            continue
        for folder in sorted(path for path in root.rglob("*") if path.is_dir()):
            rel = folder.relative_to(vault).parts
            if "retired" in rel or rel[0] == "sandbox":
                continue
            folders.add(tuple(rel))
    return sorted(folders)


def create_index_skeleton(path: Path) -> None:
    title = path.stem.replace("_", " ").replace("-", " ").title()
    path.write_text(f"# {title}\n\n## 노트\n")


def replace_notes_section(text: str, notes_lines: list[str]) -> str:
    replacement = "## 노트\n" + ("\n".join(notes_lines) + "\n" if notes_lines else "")
    marker = "## 노트"
    if marker not in text:
        return text.rstrip() + "\n\n" + replacement
    start = text.index(marker)
    next_match = re.search(r"\n##\s+", text[start + len(marker) :])
    if next_match:
        end = start + len(marker) + next_match.start() + 1
        return text[:start] + replacement.rstrip() + "\n\n" + text[end:]
    return text[:start] + replacement


def refresh_indexes(vault: Path) -> list[Path]:
    changed: list[Path] = []
    for folder_parts in discover_index_folders(vault):
        idx = index_path(vault, folder_parts)
        if not idx.exists():
            idx.parent.mkdir(parents=True, exist_ok=True)
            create_index_skeleton(idx)
        folder = folder_path(vault, folder_parts)
        note_paths = [
            path
            for path in sorted(folder.glob("*.md"))
            if path != idx and not is_retired_path(path, vault)
        ]
        lines = []
        for path in note_paths:
            fm, _ = parse_frontmatter(path.read_text())
            summary = fm.get("summary", "")
            lines.append(f"- [[{path.stem}]] — {summary}")
        current = idx.read_text()
        updated = replace_notes_section(current, lines)
        if updated != current:
            idx.write_text(updated)
            changed.append(idx)
    return changed


def expected_index_text(vault: Path, folder_parts: tuple[str, ...]) -> str:
    idx = index_path(vault, folder_parts)
    current = idx.read_text() if idx.exists() else f"# {idx.stem.title()}\n\n## 노트\n"
    folder = folder_path(vault, folder_parts)
    lines = []
    for path in sorted(folder.glob("*.md")):
        if path == idx or is_retired_path(path, vault):
            continue
        fm, _ = parse_frontmatter(path.read_text())
        lines.append(f"- [[{path.stem}]] — {fm.get('summary', '')}")
    return replace_notes_section(current, lines)


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    vault = vault_path(args.vault)
    created: list[str] = []
    for folder_parts in BASE_INDEX_FOLDERS:
        folder = folder_path(vault, folder_parts)
        if not folder.exists():
            created.append(str(folder))
            if not args.dry_run:
                folder.mkdir(parents=True)
    sandbox = vault / "sandbox"
    if not sandbox.exists():
        created.append(str(sandbox))
        if not args.dry_run:
            sandbox.mkdir(parents=True)
    record_folders = [spec.folder for spec in TYPE_SPECS.values() if spec.record]
    for folder_parts in record_folders:
        retired = folder_path(vault, folder_parts) / "retired"
        if not retired.exists():
            created.append(str(retired))
            if not args.dry_run:
                retired.mkdir(parents=True)
    readme = vault / "README.md"
    if not readme.exists():
        created.append(str(readme))
        if not args.dry_run:
            vault.mkdir(parents=True, exist_ok=True)
            readme.write_text(
                "# Wiki\n\n"
                "AI-native project knowledge lives here. Read indexes first, then frontmatter, then full notes only when needed.\n\n"
                "## Indexes\n"
                "- [[ssot/ssot]] — current design truth\n"
                "- [[runbook/runbook]] — operational procedures\n"
                "- [[context/intent/intent]] — durable intents\n"
                "- [[context/decision/decision]] — decisions\n"
                "- [[context/rejected_decision/rejected_decision]] — rejected alternatives\n"
                "- [[context/trial_error/trial_error]] — traps and lessons\n"
                "- [[context/observation/observation]] — observations awaiting classification\n\n"
                "## Agent Routing\n"
                "- Current state: start with `ssot/`.\n"
                "- Operational steps: start with `runbook/`.\n"
                "- Why a choice exists: inspect `context/decision/` and backlinks to intents.\n"
                "- New findings that are not decisions yet: inspect `context/observation/`.\n"
            )
    for folder_parts in BASE_INDEX_FOLDERS:
        idx = index_path(vault, folder_parts)
        if not idx.exists():
            created.append(str(idx))
            if not args.dry_run:
                idx.parent.mkdir(parents=True, exist_ok=True)
                create_index_skeleton(idx)
    changed = [] if args.dry_run else refresh_indexes(vault)
    return {"vault": str(vault), "created": created, "indexes_updated": [str(path) for path in changed]}


def find_doc(vault: Path, ref: str, include_retired: bool = True, allow_fuzzy: bool = False) -> WikiDoc:
    docs = iter_docs(vault, include_retired=include_retired)
    exact = [doc for doc in docs if doc.doc_id == ref]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise CliError(EXIT_VALIDATION, "AMBIGUOUS_REF", f"Ambiguous reference: {ref}")

    if not allow_fuzzy:
        raise CliError(EXIT_VALIDATION, "MISSING_REF", f"Reference not found: {ref}")

    slug = slugify(ref)
    matches: list[WikiDoc] = []
    for doc in docs:
        title = str(doc.frontmatter.get("title", ""))
        if doc.doc_id == slug or doc.doc_id.endswith(f"-{slug}") or slugify(title) == slug:
            matches.append(doc)
    unique = {doc.path: doc for doc in matches}
    matches = list(unique.values())
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CliError(EXIT_VALIDATION, "AMBIGUOUS_REF", f"Ambiguous reference: {ref}")
    raise CliError(EXIT_VALIDATION, "MISSING_REF", f"Reference not found: {ref}")


def validate_task_refs(values: list[str]) -> None:
    for value in values:
        if not TASK_REF_RE.match(value):
            raise CliError(EXIT_VALIDATION, "BAD_TASK_REF", f"Invalid task reference: {value}")


def basename_exists(vault: Path, basename: str) -> bool:
    return any(path.stem == basename for path in all_markdown_paths(vault))


def validate_metadata_args(args: argparse.Namespace, spec: TypeSpec) -> None:
    if args.verified_at and not spec.allow_verified_at:
        raise CliError(EXIT_USAGE, "VERIFIED_AT_NOT_ALLOWED", f"{args.type} cannot write verified_at")
    if args.affects_paths and not spec.allow_affects_paths:
        raise CliError(EXIT_USAGE, "AFFECTS_PATHS_NOT_ALLOWED", f"{args.type} cannot write affects_paths")


def relation_args(args: argparse.Namespace, allowed: tuple[str, ...], vault: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for arg_name, field_name in RELATION_ARG_TO_FIELD.items():
        values = split_csv(getattr(args, arg_name, None))
        if values and field_name not in allowed:
            raise CliError(EXIT_USAGE, "RELATION_NOT_ALLOWED", f"{args.type} cannot write relations.{field_name}")
        if not values:
            continue
        if field_name == "tasks":
            validate_task_refs(values)
            result[field_name] = values
        else:
            result[field_name] = [find_doc(vault, value, include_retired=True, allow_fuzzy=True).doc_id for value in values]
    return result


def next_record_basename(vault: Path, spec: TypeSpec, slug: str, timestamp: str) -> str:
    assert spec.prefix is not None
    base = f"{spec.prefix}-{timestamp}-{slug}"
    candidate = base
    suffix_ord = ord("b")
    while basename_exists(vault, candidate):
        candidate = f"{base}-{chr(suffix_ord)}"
        suffix_ord += 1
        if suffix_ord > ord("z"):
            candidate = f"{base}-{suffix_ord - ord('a') + 1}"
    return candidate


def body_for_type(doc_type: str) -> str:
    sections = TYPE_SPECS[doc_type].sections
    return "\n".join(f"## {section}\n" for section in sections)


def command_capture(args: argparse.Namespace) -> dict[str, Any]:
    vault = vault_path(args.vault)
    require_vault(vault)
    spec = TYPE_SPECS[args.type]
    generated_slug = slugify(args.slug or args.title)
    created_now = now()
    created_date = created_now.strftime("%Y-%m-%d")

    validate_metadata_args(args, spec)
    relations = relation_args(args, spec.relation_fields, vault)
    folder = folder_path(vault, spec.folder)
    if spec.record:
        basename = next_record_basename(vault, spec, generated_slug, created_now.strftime("%Y-%m-%d-%H%M%S"))
    else:
        basename = generated_slug
        if basename_exists(vault, basename):
            raise CliError(EXIT_CONFLICT, "LIVING_EXISTS", f"Living note already exists; update it in place: {basename}")

    frontmatter: dict[str, Any] = {
        "title": args.title,
        "created_at": created_date,
        "summary": args.summary,
        "tags": split_csv(args.tags),
    }
    if args.verified_at:
        frontmatter["verified_at"] = args.verified_at
    if args.affects_paths:
        frontmatter["affects_paths"] = split_csv(args.affects_paths)
    if args.search_terms:
        frontmatter["search_terms"] = split_csv(args.search_terms)
    if args.audience:
        frontmatter["audience"] = split_csv(args.audience)
    if relations:
        frontmatter["relations"] = relations

    path = folder / f"{basename}.md"
    if not args.dry_run:
        old_doc_for_supersede = None
        if args.supersedes:
            old_doc_for_supersede = find_doc(vault, args.supersedes, include_retired=False, allow_fuzzy=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_doc(path, frontmatter, body_for_type(args.type))
        supersede_result = None
        if old_doc_for_supersede:
            new_doc = read_doc(path, vault)
            supersede_result = supersede_doc(vault, old_doc_for_supersede, new_doc, created_date, dry_run=False)
        changed = refresh_indexes(vault)
    else:
        supersede_result = None
        changed = []
    return {
        "id": basename,
        "path": str(path),
        "type": args.type,
        "indexes_updated": [str(item) for item in changed],
        "supersede": supersede_result,
        "dry_run": bool(args.dry_run),
    }


def is_record_doc(doc: WikiDoc) -> bool:
    spec = TYPE_SPECS.get(doc.doc_type)
    return bool(spec and spec.record)


def supersede_doc(vault: Path, old_doc: WikiDoc, new_doc: WikiDoc, retired_at: str, dry_run: bool = False) -> dict[str, Any]:
    if not is_record_doc(old_doc) or not is_record_doc(new_doc):
        raise CliError(EXIT_USAGE, "NOT_RECORD", "Only active context records can participate in supersede")
    if old_doc.retired:
        raise CliError(EXIT_USAGE, "ALREADY_RETIRED", f"Record already retired: {old_doc.doc_id}")
    if new_doc.retired:
        raise CliError(EXIT_USAGE, "SUCCESSOR_RETIRED", f"Supersede successor is retired: {new_doc.doc_id}")

    new_fm = dict(new_doc.frontmatter)
    supersedes = list(new_fm.get("supersedes", []))
    if old_doc.doc_id not in supersedes:
        supersedes.append(old_doc.doc_id)
    new_fm["supersedes"] = supersedes

    old_fm = dict(old_doc.frontmatter)
    old_fm["superseded_by"] = new_doc.doc_id
    old_fm["retired_at"] = retired_at
    old_fm["retired_type"] = "superseded"
    retired_dir = old_doc.path.parent / "retired"
    retired_path = retired_dir / old_doc.path.name
    if not dry_run:
        write_doc(new_doc.path, new_fm, new_doc.body)
        retired_dir.mkdir(exist_ok=True)
        write_doc(old_doc.path, old_fm, old_doc.body)
        shutil.move(str(old_doc.path), str(retired_path))
    return {"old": old_doc.doc_id, "new": new_doc.doc_id, "retired_path": str(retired_path)}


def command_retire(args: argparse.Namespace) -> dict[str, Any]:
    vault = vault_path(args.vault)
    require_vault(vault)
    target = find_doc(vault, args.basename, include_retired=False)
    if not is_record_doc(target):
        raise CliError(EXIT_USAGE, "NOT_RECORD", "Only context records can be retired")
    if args.type == "superseded":
        if not args.superseded_by:
            raise CliError(EXIT_USAGE, "MISSING_SUPERSEDED_BY", "--superseded-by is required for superseded retire")
        replacement = find_doc(vault, args.superseded_by, include_retired=False)
        result = supersede_doc(vault, target, replacement, now().strftime("%Y-%m-%d"), dry_run=bool(args.dry_run))
    else:
        if args.superseded_by:
            raise CliError(EXIT_USAGE, "SUPERSEDED_BY_FORBIDDEN", "--superseded-by is only valid with --type superseded")
        fm = dict(target.frontmatter)
        fm["retired_at"] = now().strftime("%Y-%m-%d")
        fm["retired_type"] = "deprecated"
        retired_dir = target.path.parent / "retired"
        retired_dir.mkdir(exist_ok=True)
        retired_path = retired_dir / target.path.name
        if not args.dry_run:
            write_doc(target.path, fm, target.body)
            shutil.move(str(target.path), str(retired_path))
        result = {"old": target.doc_id, "retired_path": str(retired_path)}
    changed = [] if args.dry_run else refresh_indexes(vault)
    return {"retired": result, "indexes_updated": [str(item) for item in changed], "dry_run": bool(args.dry_run)}


def extract_section(body: str, section: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(section)}\s*$", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(body)
    return body[start:end].strip()


def doc_summary(doc: WikiDoc, include_body: bool = False, section: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": doc.doc_id,
        "type": doc.doc_type,
        "path": str(doc.path),
        "title": doc.frontmatter.get("title", ""),
        "summary": doc.frontmatter.get("summary", ""),
        "tags": doc.frontmatter.get("tags", []),
        "search_terms": doc.frontmatter.get("search_terms", []),
        "verified_at": doc.frontmatter.get("verified_at", ""),
        "retired": doc.retired,
    }
    if section:
        content = extract_section(doc.body, section)
        item["section"] = section
        item["content"] = content[:500]
        item["truncated"] = len(content) > 500
    elif include_body:
        item["body"] = doc.body
    return item


def matches_query_stage1(doc: WikiDoc, query: str | None) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            doc.doc_id,
            str(doc.frontmatter.get("title", "")),
            str(doc.frontmatter.get("summary", "")),
            " ".join(map(str, doc.frontmatter.get("tags", []))),
            " ".join(map(str, doc.frontmatter.get("search_terms", []))),
            str(doc.frontmatter.get("verified_at", "")),
        ]
    ).lower()
    return query.lower() in haystack


def matches_query_full(doc: WikiDoc, query: str | None) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            doc.doc_id,
            str(doc.frontmatter.get("title", "")),
            str(doc.frontmatter.get("summary", "")),
            " ".join(map(str, doc.frontmatter.get("tags", []))),
            " ".join(map(str, doc.frontmatter.get("search_terms", []))),
            str(doc.frontmatter.get("verified_at", "")),
            doc.body,
        ]
    ).lower()
    return query.lower() in haystack


def command_recall(args: argparse.Namespace) -> dict[str, Any]:
    vault = vault_path(args.vault)
    require_vault(vault)
    if args.read:
        docs = [find_doc(vault, ref, include_retired=args.include_retired) for ref in split_csv(args.read)]
        return {"results": [doc_summary(doc, include_body=True) for doc in docs]}
    if args.backlinks_of:
        target = find_doc(vault, args.backlinks_of, include_retired=True).doc_id
        results = []
        for doc in iter_docs(vault, include_retired=args.include_retired):
            if doc.doc_type not in ("decision", "rejected_decision", "trial_error", "observation"):
                continue
            relations = doc.frontmatter.get("relations", {})
            if not isinstance(relations, dict):
                continue
            fields = [field for field, values in relations.items() if target in ensure_list(values)]
            if fields:
                item = doc_summary(doc)
                item["relation_fields"] = fields
                results.append(item)
        return {"results": results[: args.limit]}

    docs = iter_docs(vault, include_retired=args.include_retired)
    if args.type:
        docs = [doc for doc in docs if doc.doc_type == args.type]
    if args.tag:
        docs = [doc for doc in docs if args.tag in ensure_list(doc.frontmatter.get("tags", []))]
    matcher = matches_query_stage1 if args.stage == 1 else matches_query_full
    docs = [doc for doc in docs if matcher(doc, args.query)]
    docs = docs[: args.limit]
    if args.stage == 2:
        return {"results": [doc_summary(doc, section=args.section) for doc in docs]}
    if args.stage == 3:
        return {"results": [doc_summary(doc, include_body=True) for doc in docs]}
    results = [doc_summary(doc) for doc in docs]
    serialized = json.dumps(results, ensure_ascii=False)
    truncated = False
    if len(serialized.encode("utf-8")) > 2048:
        truncated = True
        while results and len(json.dumps(results, ensure_ascii=False).encode("utf-8")) > 2048:
            results.pop()
    payload: dict[str, Any] = {"results": results, "truncated": truncated}
    if truncated:
        payload["hint"] = "Result truncated to fit Stage 1 budget. Narrow with --type, --tag, or a more specific query."
    return payload


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def all_doc_ids(vault: Path) -> set[str]:
    return {doc.doc_id for doc in iter_docs(vault, include_retired=True)}


def retired_doc_ids(vault: Path) -> set[str]:
    return {doc.doc_id for doc in iter_docs(vault, include_retired=True) if doc.retired}


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return None


def load_tag_vocabulary(vault: Path) -> set[str] | None:
    path = vault / "ssot" / "tag-vocabulary.md"
    if not path.exists():
        return None
    _, body = parse_frontmatter(path.read_text())
    match = re.search(r"^##\s+어휘\s*$", body, re.MULTILINE)
    if not match:
        return set()
    start = match.end()
    next_match = re.search(r"^##\s+", body[start:], re.MULTILINE)
    section = body[start : start + next_match.start()] if next_match else body[start:]
    tags = set()
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            tags.add(stripped[2:].strip())
    return tags


def issue(check: str, path: Path, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"check": check, "path": str(path), "message": message}
    payload.update(extra)
    return payload


def check_stale(vault: Path, days: int) -> list[dict[str, Any]]:
    cutoff = now() - timedelta(days=days)
    issues: list[dict[str, Any]] = []
    for doc in iter_docs(vault, include_retired=False):
        if doc.doc_type not in ("ssot", "runbook", "trial_error"):
            continue
        if doc.doc_type == "trial_error" and not doc.frontmatter.get("verified_at"):
            continue
        verified = parse_date(doc.frontmatter.get("verified_at"))
        if verified and verified < cutoff:
            issues.append(issue("stale", doc.path, f"Document has not been verified since {verified.date()}"))
    return issues


def check_relations(vault: Path) -> list[dict[str, Any]]:
    ids = all_doc_ids(vault)
    issues: list[dict[str, Any]] = []
    for doc in iter_docs(vault, include_retired=True):
        relations = doc.frontmatter.get("relations", {})
        if doc.doc_type in ("intent", "ssot", "runbook") and "relations" in doc.frontmatter:
            issues.append(issue("schema", doc.path, f"{doc.doc_type} must not write relations"))
        if "classified_as" in doc.frontmatter:
            issues.append(issue("schema", doc.path, "classified_as is not part of the v1 lifecycle model"))
        if not isinstance(relations, dict):
            continue
        allowed = set(TYPE_SPECS.get(doc.doc_type, TypeSpec((), None, False, (), ())).relation_fields)
        for field, values in relations.items():
            if field in ("supersedes", "superseded_by", "retired_at", "retired_type", "classified_as"):
                issues.append(issue("schema", doc.path, f"{field} must be a top-level lifecycle field, not relations.{field}"))
                continue
            if allowed and field not in allowed:
                issues.append(issue("schema", doc.path, f"{doc.doc_type} cannot write relations.{field}", field=field))
                continue
            for value in ensure_list(values):
                if field == "tasks":
                    if not TASK_REF_RE.match(str(value)):
                        issues.append(issue("task-ref", doc.path, f"Invalid task reference: {value}", target=value))
                    continue
                if str(value) not in ids:
                    issues.append(issue("broken-rel", doc.path, f"Missing relation target: {value}", field=field, target=value))
    return issues


def check_active_ref_retired(vault: Path) -> list[dict[str, Any]]:
    retired = retired_doc_ids(vault)
    issues: list[dict[str, Any]] = []
    for doc in iter_docs(vault, include_retired=False):
        relations = doc.frontmatter.get("relations", {})
        if not isinstance(relations, dict):
            continue
        for field, values in relations.items():
            if field == "tasks":
                continue
            for value in ensure_list(values):
                if value in retired:
                    issues.append(issue("active-ref-retired", doc.path, f"Active note references retired note: {value}", field=field, target=value))
    return issues


def check_supersede(vault: Path) -> list[dict[str, Any]]:
    docs = {doc.doc_id: doc for doc in iter_docs(vault, include_retired=True)}
    issues: list[dict[str, Any]] = []
    for doc in docs.values():
        superseded_by = doc.frontmatter.get("superseded_by")
        if superseded_by:
            replacement = docs.get(str(superseded_by))
            if not replacement:
                issues.append(issue("supersede", doc.path, f"Missing superseded_by target: {superseded_by}", target=superseded_by))
            elif doc.doc_id not in ensure_list(replacement.frontmatter.get("supersedes")):
                issues.append(issue("supersede", replacement.path, f"Replacement does not list supersedes: {doc.doc_id}", target=doc.doc_id))
        for old_id in ensure_list(doc.frontmatter.get("supersedes")):
            old = docs.get(str(old_id))
            if not old:
                issues.append(issue("supersede", doc.path, f"Missing supersedes target: {old_id}", target=old_id))
            elif old.frontmatter.get("superseded_by") != doc.doc_id:
                issues.append(issue("supersede", old.path, f"Old record does not point back to {doc.doc_id}", target=doc.doc_id))
    return issues


def referenced_doc_ids(vault: Path) -> set[str]:
    referenced: set[str] = set()
    for doc in iter_docs(vault, include_retired=True):
        relations = doc.frontmatter.get("relations", {})
        if isinstance(relations, dict):
            for field, values in relations.items():
                if field == "tasks":
                    continue
                for value in ensure_list(values):
                    target = str(value)
                    if target != doc.doc_id:
                        referenced.add(target)
        for field in ("supersedes", "superseded_by"):
            for value in ensure_list(doc.frontmatter.get(field)):
                target = str(value)
                if target != doc.doc_id:
                    referenced.add(target)
    return referenced


def check_orphans(vault: Path) -> list[dict[str, Any]]:
    referenced = referenced_doc_ids(vault)
    issues: list[dict[str, Any]] = []
    for doc in iter_docs(vault, include_retired=False):
        if is_record_doc(doc) and doc.doc_id not in referenced:
            issues.append(issue("orphan", doc.path, f"Record is not referenced by any other note: {doc.doc_id}"))
    return issues


def check_indexes(vault: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    retired_ids = retired_doc_ids(vault)
    for folder_parts in discover_index_folders(vault):
        idx = index_path(vault, folder_parts)
        if not idx.exists():
            issues.append(issue("index", idx, "Index file is missing"))
            continue
        expected = expected_index_text(vault, folder_parts)
        current = idx.read_text()
        if current != expected:
            issues.append(issue("index", idx, "Index is not synchronized with note summaries"))
        notes_in_index = set(re.findall(r"- \[\[([^\]]+)\]\]", current))
        for old_id in sorted(retired_ids & notes_in_index):
            issues.append(issue("retired-in-index", idx, f"Retired record remains in index: {old_id}", target=old_id))
    return issues


def check_tags(vault: Path) -> list[dict[str, Any]]:
    vocabulary = load_tag_vocabulary(vault)
    if vocabulary is None:
        return []
    issues: list[dict[str, Any]] = []
    for doc in iter_docs(vault, include_retired=True):
        for tag in ensure_list(doc.frontmatter.get("tags", [])):
            if str(tag) not in vocabulary:
                issues.append(issue("tags", doc.path, f"Tag is outside ssot/tag-vocabulary.md: {tag}", tag=tag))
    return issues


def changed_paths_from_git(vault: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=vault.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def path_matches(pattern: str, changed_path: str) -> bool:
    normalized_pattern = pattern.strip()
    normalized_path = changed_path.strip()
    if not normalized_pattern or not normalized_path:
        return False
    return fnmatch.fnmatch(normalized_path, normalized_pattern)


def check_changed_path_stale(vault: Path, changed_paths: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not changed_paths:
        return issues
    for doc in iter_docs(vault, include_retired=False):
        if doc.doc_type not in ("ssot", "runbook", "trial_error", "observation"):
            continue
        patterns = [str(item) for item in ensure_list(doc.frontmatter.get("affects_paths"))]
        if not patterns:
            continue
        matches = [path for path in changed_paths if any(path_matches(pattern, path) for pattern in patterns)]
        if matches:
            verified = parse_date(doc.frontmatter.get("verified_at"))
            if verified and verified.date() >= now().date():
                continue
            issues.append(
                issue(
                    "changed-path-stale",
                    doc.path,
                    "Changed path matches affects_paths; re-verify this note",
                    changed_paths=matches,
                )
            )
    return issues


def check_duplicate_basenames(vault: Path) -> list[dict[str, Any]]:
    by_stem: dict[str, list[Path]] = {}
    for path in all_markdown_paths(vault):
        if "sandbox" in path.relative_to(vault).parts[:1]:
            continue
        by_stem.setdefault(path.stem, []).append(path)
    issues: list[dict[str, Any]] = []
    for stem, paths in sorted(by_stem.items()):
        if len(paths) > 1:
            issues.append(
                issue(
                    "duplicate-basename",
                    paths[0],
                    f"Basename is not globally unique: {stem}",
                    basename=stem,
                    paths=[str(path) for path in paths],
                )
            )
    return issues


def is_placeholder_section(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    placeholders = {"...", "todo", "tbd", "n/a", "-", "작성 필요", "미정"}
    return stripped.lower() in placeholders


def check_empty_lesson(vault: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for doc in iter_docs(vault, include_retired=False):
        if doc.doc_type != "trial_error":
            continue
        lesson = extract_section(doc.body, "교훈")
        if is_placeholder_section(lesson):
            issues.append(issue("empty-lesson", doc.path, "trial_error has an empty or placeholder lesson section"))
    return issues


def validate_fix_arg(raw: str | None) -> list[str]:
    if raw is None:
        return []
    values = split_csv(raw)
    if not values:
        raise CliError(EXIT_USAGE, "BAD_FIX", "--fix requires one or more fix names")
    unsupported = [value for value in values if value not in FIXABLE_CHECKS]
    if unsupported:
        raise CliError(EXIT_USAGE, "BAD_FIX", f"Unsupported --fix value: {', '.join(unsupported)}")
    return values


def filter_issues_by_path(vault: Path, issues: list[dict[str, Any]], raw_path: str | None) -> list[dict[str, Any]]:
    if not raw_path:
        return issues
    scope = Path(raw_path)
    scope_abs = scope if scope.is_absolute() else vault / scope
    try:
        scope_resolved = scope_abs.resolve()
    except OSError:
        scope_resolved = scope_abs
    filtered: list[dict[str, Any]] = []
    for item in issues:
        candidates = [Path(str(item["path"]))]
        candidates.extend(Path(str(path)) for path in ensure_list(item.get("paths")))
        for candidate in candidates:
            try:
                candidate.resolve().relative_to(scope_resolved)
                filtered.append(item)
                break
            except (OSError, ValueError):
                continue
    return filtered


def command_refresh(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    vault = vault_path(args.vault)
    require_vault(vault)
    fix_names = validate_fix_arg(args.fix)
    fixed_paths = refresh_indexes(vault) if fix_names else []
    changed_paths = split_csv(args.changed_path) or changed_paths_from_git(vault)
    selected = args.check
    checks = {
        "stale": lambda: check_stale(vault, args.days),
        "supersede": lambda: check_supersede(vault),
        "broken-rel": lambda: [item for item in check_relations(vault) if item["check"] in ("broken-rel", "schema")],
        "task-ref": lambda: [item for item in check_relations(vault) if item["check"] == "task-ref"],
        "orphan": lambda: check_orphans(vault),
        "index": lambda: [item for item in check_indexes(vault) if item["check"] == "index"],
        "retired-in-index": lambda: [item for item in check_indexes(vault) if item["check"] == "retired-in-index"],
        "active-ref-retired": lambda: check_active_ref_retired(vault),
        "tags": lambda: check_tags(vault),
        "changed-path-stale": lambda: check_changed_path_stale(vault, changed_paths),
        "duplicate-basename": lambda: check_duplicate_basenames(vault),
        "empty-lesson": lambda: check_empty_lesson(vault),
    }
    names = list(checks) if selected == "all" else [selected]
    issues: list[dict[str, Any]] = []
    for name in names:
        issues.extend(checks[name]())
    issues = filter_issues_by_path(vault, issues, args.path)
    status = EXIT_STRICT if args.strict and issues else 0
    return {"issues": issues, "issue_count": len(issues), "fixed": [str(path) for path in fixed_paths]}, status


def emit(payload: dict[str, Any], json_mode: bool) -> None:
    payload = {"ok": True, **payload}
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if "id" in payload:
            print(f"Created {payload['id']}: {payload.get('path', '')}")
        elif "retired" in payload:
            print(json.dumps(payload["retired"], ensure_ascii=False))
        elif "results" in payload:
            for item in payload["results"]:
                print(f"{item['id']} — {item.get('summary', '')}")
            if payload.get("hint"):
                print(payload["hint"])
        elif "issues" in payload:
            print(f"{payload['issue_count']} issue(s)")
            for item in payload["issues"]:
                print(f"- {item['check']}: {item['path']} — {item['message']}")
        else:
            print(json.dumps(payload, ensure_ascii=False))


def emit_error(error: CliError, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps({"ok": False, "error_code": error.error_code, "message": error.message}, ensure_ascii=False))
    else:
        print(f"{error.error_code}: {error.message}", file=sys.stderr)
    return error.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wiki-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--vault")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--json", action="store_true")

    capture = subparsers.add_parser("capture")
    capture.add_argument("type", choices=sorted(TYPE_SPECS))
    capture.add_argument("--title", required=True)
    capture.add_argument("--summary", required=True)
    capture.add_argument("--tags", required=True)
    capture.add_argument("--slug")
    capture.add_argument("--intents")
    capture.add_argument("--ssot")
    capture.add_argument("--runbook")
    capture.add_argument("--rejected")
    capture.add_argument("--decisions")
    capture.add_argument("--tasks")
    capture.add_argument("--supersedes")
    capture.add_argument("--affects-paths")
    capture.add_argument("--search-terms")
    capture.add_argument("--verified-at")
    capture.add_argument("--audience")
    capture.add_argument("--vault")
    capture.add_argument("--dry-run", action="store_true")
    capture.add_argument("--json", action="store_true")

    retire = subparsers.add_parser("retire")
    retire.add_argument("basename")
    retire.add_argument("--type", required=True, choices=("deprecated", "superseded"))
    retire.add_argument("--superseded-by")
    retire.add_argument("--vault")
    retire.add_argument("--dry-run", action="store_true")
    retire.add_argument("--json", action="store_true")

    recall = subparsers.add_parser("recall")
    recall.add_argument("query", nargs="?")
    recall.add_argument("--type", choices=sorted(TYPE_SPECS))
    recall.add_argument("--tag")
    recall.add_argument("--section")
    recall.add_argument("--stage", type=int, choices=(1, 2, 3), default=1)
    recall.add_argument("--limit", type=int, default=20)
    recall.add_argument("--backlinks-of")
    recall.add_argument("--read")
    recall.add_argument("--include-retired", action="store_true")
    recall.add_argument("--vault")
    recall.add_argument("--json", action="store_true")

    refresh = subparsers.add_parser("refresh")
    refresh.add_argument(
        "--check",
        choices=(
            "stale",
            "supersede",
            "broken-rel",
            "task-ref",
            "orphan",
            "index",
            "retired-in-index",
            "active-ref-retired",
            "tags",
            "changed-path-stale",
            "duplicate-basename",
            "empty-lesson",
            "all",
        ),
        default="all",
    )
    refresh.add_argument("--days", type=int, default=90)
    refresh.add_argument("--changed-path")
    refresh.add_argument("--path")
    refresh.add_argument("--fix")
    refresh.add_argument("--strict", action="store_true")
    refresh.add_argument("--vault")
    refresh.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(getattr(args, "json", False))
    try:
        if args.command == "init":
            payload = command_init(args)
            status = 0
        elif args.command == "capture":
            payload = command_capture(args)
            status = 0
        elif args.command == "retire":
            payload = command_retire(args)
            status = 0
        elif args.command == "recall":
            payload = command_recall(args)
            status = 0
        elif args.command == "refresh":
            payload, status = command_refresh(args)
        else:
            raise CliError(EXIT_USAGE, "UNKNOWN_COMMAND", args.command)
        emit(payload, json_mode)
        return status
    except CliError as error:
        return emit_error(error, json_mode)


if __name__ == "__main__":
    raise SystemExit(main())
