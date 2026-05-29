#!/usr/bin/env python3
"""wiki_cli — AI-native wiki CLI (stdlib only).

Single-file CLI implementing the wiki plugin design at
wiki/ssot/plugin_definition_v1.md. Subcommands: init, capture, retire,
complete, reopen, recall, refresh. See SKILL.md and rules/knowledge-protocol.md.
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
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def _nfc(s):
    """Normalize text to NFC.

    The vault's basename equality semantics rely on byte-level matching;
    macOS / external tools may hand us NFD ('가' as 'ㄱ+ㅏ' separate code
    points) while users type NFC. Normalize at every input boundary —
    slugs, friendly refs, file basenames read off disk — so resolver
    comparisons stay consistent.
    """
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s

# ──────────────────────────────────────────────────────────────────────────
# Exit codes (§13.0)
# ──────────────────────────────────────────────────────────────────────────
EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_NO_VAULT = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_STRICT = 6

# ──────────────────────────────────────────────────────────────────────────
# Type registry (§3·§6·§7·§8·§11)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TypeSpec:
    folder: Tuple[str, ...]
    prefix: Optional[str]
    is_record: bool
    allowed_relations: Tuple[str, ...]
    sections: Tuple[str, ...]
    allow_verified_at: bool = False
    allow_affects_paths: bool = False
    is_time_stale: bool = False
    is_path_stale: bool = False
    is_hub: bool = False
    is_living: bool = False
    is_task: bool = False


TYPE_SPECS: "dict[str, TypeSpec]" = {
    "intent": TypeSpec(
        folder=("context", "intent"),
        prefix="INT", is_record=True,
        allowed_relations=(),
        sections=("취지", "배경"),
        is_hub=True,
    ),
    "decision": TypeSpec(
        folder=("context", "decision"),
        prefix="DEC", is_record=True,
        allowed_relations=("intents", "rejected_decisions", "ssot", "tasks"),
        sections=("결정", "취지", "배경", "고려한 대안", "트레이드오프", "재평가 조건"),
    ),
    "rejected_decision": TypeSpec(
        folder=("context", "rejected_decision"),
        prefix="REJ", is_record=True,
        allowed_relations=("intents",),
        sections=("대안", "반려 사유", "이 대안의 취지", "재고 조건"),
    ),
    "trial_error": TypeSpec(
        folder=("context", "trial_error"),
        prefix="TRI", is_record=True,
        allowed_relations=("decisions", "tasks"),
        sections=("교훈", "상황", "피해야 할 것", "대안 또는 우회", "현재도 유효한가"),
        allow_verified_at=True,
        allow_affects_paths=True,
        is_time_stale=True,
        is_path_stale=True,
    ),
    "observation": TypeSpec(
        folder=("context", "observation"),
        prefix="OBS", is_record=True,
        allowed_relations=("ssot", "runbook", "decisions", "tasks"),
        sections=("관찰", "근거", "영향", "현재 처리", "후속 분류 조건"),
        allow_verified_at=True,
        allow_affects_paths=True,
        is_path_stale=True,
    ),
    "ssot": TypeSpec(
        folder=("ssot",),
        prefix=None, is_record=False,
        allowed_relations=(),
        sections=("현재 상태", "취지", "구성요소"),
        allow_verified_at=True,
        allow_affects_paths=True,
        is_time_stale=True,
        is_path_stale=True,
        is_hub=True,
        is_living=True,
    ),
    "runbook": TypeSpec(
        folder=("runbook",),
        prefix=None, is_record=False,
        allowed_relations=(),
        sections=("목적", "절차", "주의점"),
        allow_verified_at=True,
        allow_affects_paths=True,
        is_time_stale=True,
        is_path_stale=True,
        is_hub=True,
        is_living=True,
    ),
    "task": TypeSpec(
        folder=("task",),
        prefix="TASK", is_record=False,
        allowed_relations=("intents", "decisions", "ssot", "tasks"),
        sections=("개요", "근거", "범위와 완료 기준"),
        is_task=True,
    ),
}

# Cross-cutting category tuples — derived from TYPE_SPECS so adding a new type
# only requires editing TypeSpec flags above. Order preserves intent/decision/…
# CONTEXT_RECORD_TYPES historically lists intent last (after the others);
# preserved here for stable error-message output.
HUB_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.is_hub)
LIVING_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.is_living)
RECORD_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.is_record)
CONTEXT_RECORD_TYPES: Tuple[str, ...] = tuple(
    [t for t, s in TYPE_SPECS.items() if s.is_record and s.folder[:1] == ("context",) and t != "intent"]
    + (["intent"] if TYPE_SPECS["intent"].is_record else [])
)
VERIFIED_AT_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.allow_verified_at)
AFFECTS_PATHS_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.allow_affects_paths)
TIME_STALE_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.is_time_stale)
PATH_STALE_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.is_path_stale)
TASK_TYPES: Tuple[str, ...] = tuple(t for t, s in TYPE_SPECS.items() if s.is_task)

# Relation sub-key → expected target doc_type (used by capture + refresh schema).
# `tasks` is external; not in this map.
RELATION_TARGET_TYPES = {
    "intents": "intent",
    "rejected_decisions": "rejected_decision",
    "decisions": "decision",
    "ssot": "ssot",
    "runbook": "runbook",
}

# Fields forbidden in frontmatter (v1 §7, §17 반려).
FORBIDDEN_FIELDS = ("id", "status", "classified_as")
LIFECYCLE_FIELDS = ("supersedes", "superseded_by", "retired_at", "retired_type")

# Init-time seed: the standard folders that always exist after `init`.
INIT_INDEX_FOLDERS: List[Tuple[str, ...]] = [
    ("ssot",), ("runbook",),
    ("context", "intent"), ("context", "decision"),
    ("context", "rejected_decision"), ("context", "trial_error"),
    ("context", "observation"),
    ("task",),
]
CONTEXT_FOLDERS: List[Tuple[str, ...]] = [
    ("context", "intent"), ("context", "decision"),
    ("context", "rejected_decision"), ("context", "trial_error"),
    ("context", "observation"),
]
LIVING_FOLDER_NAMES = ("ssot", "runbook")
INDEX_HEADER = "## 노트"

TASK_REF_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+#\d+$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Placeholder pattern: angle-bracketed instruction text or pure whitespace.
PLACEHOLDER_RE = re.compile(r"^\s*(<[^>]+>\s*)+$")
# Scalar placeholder: single `<...>` wrapper, used by both schema check and
# capture-time input validation so a value rejected by one is rejected by both.
PLACEHOLDER_SCALAR_RE = re.compile(r"^\s*<[^>]+>\s*$")

FIX_WHITELIST = ("index", "retired-in-index")


# ──────────────────────────────────────────────────────────────────────────
# Module-level validators (shared by capture + refresh schema + stale checks)
# ──────────────────────────────────────────────────────────────────────────
def _is_valid_iso_date(v) -> bool:
    """Strict YYYY-MM-DD: regex enforces the literal shape (strptime alone
    accepts '2026-1-1'), then strptime validates the calendar.

    Shared by `refresh --check schema` AND `--check stale/changed-path-stale`
    AND capture-time `--verified-at` validation so all three paths agree on
    what counts as a valid date.
    """
    if not isinstance(v, str) or not ISO_DATE_RE.match(v):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _is_placeholder_value(v) -> bool:
    """Detect template placeholder scalars like '<some hint>'.

    Shared by `refresh --check schema` (post-hoc detection) and `capture`
    (input rejection) so a placeholder rejected by one is rejected by both.
    """
    return isinstance(v, str) and bool(PLACEHOLDER_SCALAR_RE.match(v))


def _is_index_file(parts: Tuple[str, ...], path: Path) -> bool:
    """Folder-index identity by NFC-normalized basename equality.

    Raw `path.stem == parts[-1]` breaks when one side is NFC and the other
    NFD (e.g. NFC folder name '가입' with NFD index file '가입.md'). Compare
    in NFC so a folder's own index is always recognized as an index — never
    leaks into iter_active_docs() or find_doc_anywhere() relation lookups.
    """
    return _nfc(path.stem) == _nfc(parts[-1])


# ──────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────
class CliError(Exception):
    def __init__(self, exit_code: int, error_code: str, message: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.error_code = error_code
        self.message = message


# ──────────────────────────────────────────────────────────────────────────
# (a) Frontmatter I/O — stdlib-only YAML subset (§7)
# ──────────────────────────────────────────────────────────────────────────
def split_frontmatter(text: str) -> Tuple[Optional[str], str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5:]


def _strip_inline_comment(s: str) -> str:
    """Strip a trailing ` # ...` comment from a YAML scalar/inline-list value.

    - For inline lists `[...]`: only strip ` #` AFTER the closing `]`.
    - For scalars: strip the first ` #` (space + hash) and everything after.
    A bare `#` not preceded by whitespace is left intact (so `owner/repo#42`
    survives).
    """
    s = s.rstrip()
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            return s
        head = s[:end + 1]
        tail = s[end + 1:]
        m = re.match(r"\s+#.*$", tail)
        return head if m else s
    m = re.search(r"\s+#", s)
    return s[:m.start()].rstrip() if m else s


def _parse_inline_list(s: str) -> list:
    s = s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return [s]
    inner = s[1:-1].strip()
    if not inner:
        return []
    return [tok.strip() for tok in inner.split(",")]


def parse_frontmatter(fm_text: str) -> dict:
    """Parse the constrained YAML subset: scalars, inline lists `[a, b]`,
    block lists (`- item`), and a single nested `relations:` map.
    Tolerates human edits of both list styles."""
    result: dict = {}
    if not fm_text:
        return result
    lines = fm_text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if line.startswith(" "):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2)
        if rest:
            rest = _strip_inline_comment(rest)
            if rest.startswith("[") and rest.endswith("]"):
                result[key] = _parse_inline_list(rest)
            else:
                result[key] = rest
            i += 1
            continue
        # rest empty → block continuation
        if key == "relations":
            rel: dict = {}
            j = i + 1
            while j < n:
                sub = lines[j]
                sstrip = sub.strip()
                if not sstrip or sstrip.startswith("#"):
                    j += 1
                    continue
                if sub.startswith("  ") and not sub.startswith("    "):
                    sm = re.match(r"^  ([A-Za-z_][A-Za-z0-9_\-]*):\s*(.*)$", sub)
                    if not sm:
                        break
                    sk, sv = sm.group(1), sm.group(2)
                    if sv:
                        rel[sk] = _parse_inline_list(_strip_inline_comment(sv))
                        j += 1
                    else:
                        items: list = []
                        k = j + 1
                        while k < n and lines[k].startswith("    -"):
                            items.append(lines[k].strip()[1:].strip())
                            k += 1
                        rel[sk] = items
                        j = k
                else:
                    break
            result[key] = rel
            i = j
            continue
        # top-level block list (e.g., audience:\n  - human)
        items = []
        j = i + 1
        while j < n and lines[j].startswith(" ") and lines[j].lstrip().startswith("- "):
            items.append(lines[j].lstrip()[2:].strip())
            j += 1
        result[key] = items
        i = j
    return result


def _yaml_scalar(v) -> str:
    return str(v)


def serialize_frontmatter(fm: dict) -> str:
    """Emit canonical YAML subset (write side).
    - Scalars: `key: value` unquoted.
    - Lists: inline `key: [a, b]`. Empty list → key omitted.
    - relations: nested block with 2-space indent; empty sublists filtered;
      if all sublists empty, key omitted.
    - Insertion order preserved (Python dict 3.7+).
    """
    lines = ["---"]
    for key, value in fm.items():
        if key == "relations":
            if not isinstance(value, dict):
                continue
            subs = [(k, v) for k, v in value.items() if v]
            if not subs:
                continue
            lines.append("relations:")
            for sk, sv in subs:
                if isinstance(sv, list):
                    lines.append(f"  {sk}: [{', '.join(_yaml_scalar(x) for x in sv)}]")
                else:
                    lines.append(f"  {sk}: {_yaml_scalar(sv)}")
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}: [{', '.join(_yaml_scalar(x) for x in value)}]")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


@dataclass
class WikiDoc:
    path: Path
    doc_id: str
    doc_type: str
    frontmatter: dict
    body: str
    retired: bool
    done: bool = False


def doc_type_from_path(vault: Path, path: Path) -> Optional[str]:
    """Map a vault-relative path to its wiki type.

    Supports nested ssot/runbook (any depth under `ssot/` or `runbook/`).
    `retired/` segments are ignored. context/<type>/... is fixed by type.
    """
    try:
        rel = path.relative_to(vault).parts
    except ValueError:
        return None
    rel = tuple(p for p in rel if p not in ("retired", "done"))
    if not rel:
        return None
    head = rel[0]
    if head == "task":
        return "task"
    if head in LIVING_FOLDER_NAMES:
        return head
    if head == "context" and len(rel) >= 2:
        sub = rel[1]
        for t, spec in TYPE_SPECS.items():
            if spec.folder == ("context", sub):
                return t
    return None


def read_doc(vault: Path, path: Path) -> WikiDoc:
    text = path.read_text(encoding="utf-8")
    fm_text, body = split_frontmatter(text)
    fm = parse_frontmatter(fm_text or "")
    _rel_parts = path.relative_to(vault).parts
    return WikiDoc(
        path=path,
        doc_id=_nfc(path.stem),  # NFC-normalize so by_id lookups match NFC refs
        doc_type=doc_type_from_path(vault, path) or "",
        frontmatter=fm,
        body=body,
        retired="retired" in _rel_parts,
        done="done" in _rel_parts,
    )


def write_doc(path: Path, fm: dict, body: str, dry_run: bool = False) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_frontmatter(fm) + body, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────
# (b) ids / slugs / time
# ──────────────────────────────────────────────────────────────────────────
def now() -> datetime:
    raw = os.environ.get("WIKI_NOW")
    if raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d-%H%M%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        raise CliError(EXIT_USAGE, "wiki_now_format", f"unparseable WIKI_NOW={raw!r}")
    return datetime.now()


def slugify(title: str) -> str:
    """Kebab-case slug preserving Unicode alphanumerics (한글 포함).
    Non-alnum runs become a single '-'. ASCII letters are lowercased.
    Input is NFC-normalized for resolver consistency."""
    title = _nfc(title)
    chars: List[str] = []
    for ch in title:
        if ch.isalnum():
            chars.append(ch.lower())
        else:
            chars.append("-")
    s = re.sub(r"-+", "-", "".join(chars)).strip("-")
    return s


def sanitize_slug(s: str) -> str:
    """Validate a user-supplied --slug against the kebab-case contract.

    Same character set as auto-generated slugs (Unicode alnum + `-`):
    - non-empty
    - cannot start/end with `-`
    - no `--` runs
    - no `.` (also no `..`)
    - no whitespace / path separators / control chars
    Enforced by requiring `slugify(s) == s` (slugify is the canonical form).
    """
    if not s:
        raise CliError(EXIT_USAGE, "empty_slug", "slug cannot be empty")
    s = _nfc(s)
    canonical = slugify(s)
    if canonical != s:
        raise CliError(
            EXIT_USAGE, "bad_slug",
            f"--slug {s!r}는 kebab-case 계약을 어김 "
            f"(Unicode alnum + '-'만, '-'로 시작/끝 금지, '--'/'.' 금지). "
            f"정규화 결과: {canonical!r}")
    return s


def record_basename(type_name: str, dt: datetime, slug: str) -> str:
    prefix = TYPE_SPECS[type_name].prefix
    return f"{prefix}-{dt.strftime('%Y-%m-%d-%H%M%S')}-{slug}"


def unique_basename(folder: Path, basename: str) -> str:
    """Append -b, -c, ... on collision; timestamp never altered (§5).

    Checks every lifecycle location a basename can occupy: the folder root
    (active), `retired/` (all types), and `done/` (task only). Missing the
    `done/` check would let a completed task share a basename with a freshly
    captured one (same timestamp+slug), violating global basename uniqueness."""
    candidate = basename
    idx = 1
    while ((folder / f"{candidate}.md").exists()
           or (folder / "retired" / f"{candidate}.md").exists()
           or (folder / "done" / f"{candidate}.md").exists()):
        idx += 1
        if idx > 26:
            raise CliError(EXIT_CONFLICT, "basename_overflow",
                           f"too many collisions for {basename}")
        candidate = f"{basename}-{chr(ord('a') + idx - 1)}"
    return candidate


# ──────────────────────────────────────────────────────────────────────────
# (c) vault / paths / discovery (§6, §10, §14.2)
# ──────────────────────────────────────────────────────────────────────────
def resolve_vault(arg: Optional[str]) -> Path:
    if arg:
        p = Path(arg)
        return p if p.is_absolute() else (Path.cwd() / p)
    return Path.cwd() / "wiki"


def ensure_vault(vault: Path) -> None:
    if not vault.is_dir():
        raise CliError(EXIT_NO_VAULT, "vault_missing", f"vault not found: {vault}")


def folder_dir(vault: Path, type_name: str) -> Path:
    return vault.joinpath(*TYPE_SPECS[type_name].folder)


def index_path(vault: Path, folder_parts: Tuple[str, ...]) -> Path:
    """Canonical NFC index path for a folder — used when *creating* a new
    index file. The filename is NFC-normalized even if the folder name on
    disk is NFD so generation is always canonical. To find an *existing*
    index that may have been stored as NFD by an external tool, use
    find_index_file()."""
    return vault.joinpath(*folder_parts) / f"{_nfc(folder_parts[-1])}.md"


def find_index_file(vault: Path, folder_parts: Tuple[str, ...]) -> Optional[Path]:
    """Locate the existing index file for a folder, regardless of NFC/NFD
    normalization of its filename. Returns None if no index exists yet.

    Selection is **deterministic** when more than one candidate matches
    (a corrupted vault with both NFC and NFD index files in the same
    folder — `duplicate-basename` flags this separately but the choice
    must be stable):

      1) The canonical NFC filename (`f"{_nfc(parts[-1])}.md"`) wins,
         so refresh always reads/writes the same file regardless of
         filesystem iteration order.
      2) Otherwise, sort by `str(path)` lexicographically.

    Use `find_index_file(...) or index_path(...)` when you want to fall
    back to the canonical NFC path (e.g. for creation)."""
    folder = vault.joinpath(*folder_parts)
    if not folder.is_dir():
        return None
    candidates = [p for p in folder.iterdir()
                  if p.is_file() and p.suffix == ".md"
                  and _is_index_file(folder_parts, p)]
    if not candidates:
        return None
    canonical_name = f"{_nfc(folder_parts[-1])}.md"
    candidates.sort(key=lambda p: (p.name != canonical_name, str(p)))
    return candidates[0]


def retired_subdir(folder: Path) -> Path:
    return folder / "retired"


def _discover_living_folders(vault: Path, root_name: str) -> List[Tuple[str, ...]]:
    """Recurse under ssot/ or runbook/. Each folder containing at least one
    `.md` (other than its own index) is treated as an independent index folder.
    The root itself is always included if it exists. `retired/` is skipped.
    """
    root = vault / root_name
    if not root.is_dir():
        return []
    out: List[Tuple[str, ...]] = []
    for current, dirnames, filenames in os.walk(root):
        # Skip any `retired/` subtree (defensive — ssot/runbook normally have none).
        dirnames[:] = [d for d in dirnames if d != "retired"]
        # Stable iteration order.
        dirnames.sort()
        cur_path = Path(current)
        try:
            parts = cur_path.relative_to(vault).parts
        except ValueError:
            continue
        # Always include the root.
        if cur_path == root:
            out.append(parts)
            continue
        # Include a nested folder if it has any .md (root index counts —
        # an "empty" index folder is still a valid index folder).
        if any(name.endswith(".md") for name in filenames):
            out.append(parts)
    return out


def discover_index_folders(vault: Path) -> List[Tuple[str, ...]]:
    """Return all folders that own an index file (§10).

    - context/* folders are fixed (5 record types).
    - ssot/, runbook/ are discovered recursively.
    Order: ssot subtree, runbook subtree, then context types in stable order.
    """
    out: List[Tuple[str, ...]] = []
    out.extend(_discover_living_folders(vault, "ssot"))
    out.extend(_discover_living_folders(vault, "runbook"))
    for parts in CONTEXT_FOLDERS:
        if vault.joinpath(*parts).is_dir():
            out.append(parts)
    # task is a flat top-level index folder; its done/ and retired/ subdirs
    # are lifecycle locations, not nested index folders (iter_active is
    # non-recursive, so they don't leak into the active set).
    if vault.joinpath("task").is_dir():
        out.append(("task",))
    return out


def iter_active_docs(vault: Path, parts: Tuple[str, ...]) -> List[Path]:
    folder = vault.joinpath(*parts)
    if not folder.is_dir():
        return []
    # NFC-normalized comparison so a folder index stored in NFD doesn't
    # leak in as a "note" (which would then be reachable as a relation
    # target via find_doc_anywhere's fallback).
    out = [c for c in folder.iterdir()
           if c.is_file() and c.suffix == ".md" and not _is_index_file(parts, c)]
    return sorted(out, key=lambda p: p.name)


def iter_retired_docs(vault: Path, parts: Tuple[str, ...]) -> List[Path]:
    folder = vault.joinpath(*parts) / "retired"
    if not folder.is_dir():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix == ".md"],
                  key=lambda p: p.name)


def iter_done_docs(vault: Path, parts: Tuple[str, ...]) -> List[Path]:
    """Completed task docs under `<folder>/done/`. Only the task folder ever
    has a `done/` subdir; every other folder returns []. Done tasks are
    terminal — excluded from active-only checks, but still part of the graph
    (validated by refresh, reachable by find_doc_anywhere / backlinks)."""
    folder = vault.joinpath(*parts) / "done"
    if not folder.is_dir():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix == ".md"],
                  key=lambda p: p.name)


def iter_all_docs(vault: Path, include_retired: bool = True) -> Iterable[Path]:
    for parts in discover_index_folders(vault):
        yield from iter_active_docs(vault, parts)
        if include_retired:
            yield from iter_retired_docs(vault, parts)
            yield from iter_done_docs(vault, parts)


def iter_every_md(vault: Path) -> Iterable[Path]:
    """Walk the entire vault for any .md (used by duplicate-basename)."""
    if not vault.is_dir():
        return
    for current, _dirnames, filenames in os.walk(vault):
        for name in filenames:
            if name.endswith(".md"):
                yield Path(current) / name


def find_doc_anywhere(vault: Path, basename: str,
                      include_indexes: bool = False) -> Optional[Path]:
    """Resolve a basename to its on-disk path (active or retired).

    Args:
      basename: Looked up in NFC form. Filenames stored as NFD (older macOS
        HFS+ / external tools) are still found via a fallback that
        NFC-normalizes each candidate's stem.
      include_indexes: Default False. Folder index files (`ssot/ssot.md`,
        `context/decision/decision.md`) are derived projections and **never**
        valid relation targets — keep False from relation resolvers and
        backlink scans. Pass True only when the caller's question is "is
        this basename in use anywhere?" (e.g. living-slug conflict check on
        capture) — otherwise `capture ssot --slug ssot` would silently
        overwrite the index.

    Search order:
      1) Fast path: direct path lookup using the NFC basename.
      2) Fallback: scan iter_all_docs() (notes only) by NFC-normalized stem
         — catches NFD on-disk filenames.
      3) Index scan (only when include_indexes=True): scan each discovered
         folder's own index file by NFC-normalized stem.
    """
    basename = _nfc(basename)
    # 1) Fast path: direct path lookup.
    for parts in discover_index_folders(vault):
        # NFC-compare folder name → basename so the index-skip works even
        # when the on-disk folder name is NFD and basename is NFC
        # (raw `parts[-1] == basename` would silently miss).
        if _nfc(parts[-1]) == basename and not include_indexes:
            continue
        cand = vault.joinpath(*parts) / f"{basename}.md"
        if cand.is_file():
            # Defense in depth: even if the fast path finds something,
            # refuse to hand back a folder index file when caller didn't
            # opt in (covers NFD folder + NFC index filename combos where
            # the OS resolves the path but it's still semantically an
            # index, not a note).
            if not include_indexes and _is_index_file(parts, cand):
                continue
            return cand
        ret = vault.joinpath(*parts) / "retired" / f"{basename}.md"
        if ret.is_file():
            return ret
        dn = vault.joinpath(*parts) / "done" / f"{basename}.md"
        if dn.is_file():
            return dn
    # 2) NFD fallback for notes (iter_all_docs already excludes index files).
    for p in iter_all_docs(vault, include_retired=True):
        if _nfc(p.stem) == basename:
            return p
    # 3) Index scan when explicitly allowed (living-slug collision check).
    # Iterate each folder rather than relying on a direct `index_path` lookup
    # so an NFD-stored index file is still detected via NFC-normalized stem.
    if include_indexes:
        for parts in discover_index_folders(vault):
            folder = vault.joinpath(*parts)
            if not folder.is_dir():
                continue
            for p in folder.iterdir():
                if (p.is_file() and p.suffix == ".md"
                        and _is_index_file(parts, p)
                        and _nfc(p.stem) == basename):
                    return p
    return None


# ──────────────────────────────────────────────────────────────────────────
# (d) relations / resolver
# ──────────────────────────────────────────────────────────────────────────
def resolve_friendly(vault: Path, ref: str, *, allow_fuzzy: bool = True) -> str:
    """Resolve a wiki-doc ref to a full basename.

    1) exact basename match (active or retired).
    2) if allow_fuzzy: slug-fragment match against record basenames.
    Ambiguous/missing → CliError(EXIT_VALIDATION, ...).

    allow_fuzzy=False makes this behave like find_doc_anywhere but raises
    structured errors — call from contexts where exact-id matching is desired
    yet uniform error semantics matter (e.g., `recall --read` without `--fuzzy`).
    Input is NFC-normalized; on-disk basenames are NFC-normalized in read_doc.
    """
    ref = _nfc(ref)
    if find_doc_anywhere(vault, ref) is not None:
        return ref
    if not allow_fuzzy:
        raise CliError(EXIT_VALIDATION, "ref_missing", f"reference not found: {ref}")
    pattern = re.compile(r"^[A-Z]{3}-\d{4}-\d{2}-\d{2}-\d{6}-" + re.escape(ref) + r"$")
    candidates = [_nfc(p.stem) for p in iter_all_docs(vault, include_retired=True)
                  if pattern.match(_nfc(p.stem))]
    if not candidates:
        raise CliError(EXIT_VALIDATION, "ref_missing", f"reference not found: {ref}")
    if len(candidates) > 1:
        raise CliError(EXIT_VALIDATION, "ref_ambiguous",
                       f"reference '{ref}' matches {len(candidates)}: {', '.join(candidates)}")
    return candidates[0]


def validate_task_ref(s: str) -> None:
    if not TASK_REF_RE.match(s):
        raise CliError(EXIT_VALIDATION, "task_format",
                       f"invalid task ref (expected owner/repo#N): {s}")


def parse_csv(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [tok.strip() for tok in s.split(",") if tok.strip()]


# ──────────────────────────────────────────────────────────────────────────
# (e) index (§14.2) — per-folder, non-recursive note collection
# ──────────────────────────────────────────────────────────────────────────
def derive_index_lines(vault: Path, parts: Tuple[str, ...]) -> List[str]:
    out = []
    for p in iter_active_docs(vault, parts):
        d = read_doc(vault, p)
        out.append(f"- [[{d.doc_id}]] — {d.frontmatter.get('summary', '')}")
    return out


def _replace_section(text: str, header: str, new_body_lines: List[str]) -> str:
    """Replace the body under an H2 header. Idempotent; preserves siblings."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.rstrip() == header:
            start = i
            break
    if start is None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(header)
        new_section = [""]
        if new_body_lines:
            new_section.append("\n".join(new_body_lines))
            new_section.append("")
        return "\n".join(lines + new_section)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    new_section = [""]
    if new_body_lines:
        new_section.append("\n".join(new_body_lines))
        new_section.append("")
    return "\n".join(lines[: start + 1] + new_section + lines[end:])


def rewrite_index(vault: Path, parts: Tuple[str, ...]) -> bool:
    """Rewrite a single folder's index. Returns True if file content changed.
    Locates the existing index via find_index_file so NFD-stored indexes
    are updated in place rather than left stale next to a phantom NFC path."""
    idx = find_index_file(vault, parts)
    if idx is None or not idx.is_file():
        return False
    text = idx.read_text(encoding="utf-8")
    new_text = _replace_section(text, INDEX_HEADER, derive_index_lines(vault, parts))
    if new_text != text:
        idx.write_text(new_text, encoding="utf-8")
        return True
    return False


def refresh_all_indexes(vault: Path) -> List[Tuple[str, ...]]:
    """Rewrite every discovered folder's index. Returns the folders touched."""
    changed: List[Tuple[str, ...]] = []
    for parts in discover_index_folders(vault):
        if rewrite_index(vault, parts):
            changed.append(parts)
    return changed


# ──────────────────────────────────────────────────────────────────────────
# (f) backlinks (§14.3)
# ──────────────────────────────────────────────────────────────────────────
def find_backlinks(vault: Path, target: str, include_retired: bool = False) -> List[WikiDoc]:
    matches: List[WikiDoc] = []
    paths: List[Path] = []
    for parts in discover_index_folders(vault):
        paths.extend(iter_active_docs(vault, parts))
        # done tasks are a valid TERMINAL state, not retired/invalid: a
        # completed unit of work is exactly what "what did this decision
        # spawn?" should surface, so include it by default. Only retired
        # (wrong / superseded) docs stay behind the --include-retired opt-in.
        paths.extend(iter_done_docs(vault, parts))
        if include_retired:
            paths.extend(iter_retired_docs(vault, parts))
    for p in paths:
        d = read_doc(vault, p)
        rel = d.frontmatter.get("relations")
        if not isinstance(rel, dict):
            continue
        for k, v in rel.items():
            if k == "tasks":
                continue
            if isinstance(v, list) and target in v:
                matches.append(d)
                break
    matches.sort(key=lambda d: d.doc_id)
    return matches


# ──────────────────────────────────────────────────────────────────────────
# (g) Subcommand handlers
# ──────────────────────────────────────────────────────────────────────────
ROOT_README_TEMPLATE = """---
title: Wiki
created_at: {today}
summary: AI-native wiki — context(intent/decision/rejected_decision/trial_error/observation)와 ssot/runbook을 결정 그래프로 관리.
tags: [meta]
audience: [human, agent]
---

# Wiki

이 vault는 1인 개발자 + AI 에이전트가 프로젝트의 **취지·결정·반려 대안·시행착오·관찰**과 **현재 상태(SSOT)·운영 절차(Runbook)**를 축적·조회하는 정본 저장소다.

## 폴더 인덱스

- [[ssot/ssot]] — 현재 유효한 설계 정본 (living)
- [[runbook/runbook]] — 운영 절차 (living)
- [[context/intent/intent]] — 취지 (record)
- [[context/decision/decision]] — 결정 (record)
- [[context/rejected_decision/rejected_decision]] — 반려된 대안 (record)
- [[context/trial_error/trial_error]] — 시행착오 (record)
- [[context/observation/observation]] — 관찰 (record, 분류 전 임시)
- [[task/task]] — 작업 (제3 범주: 결정·취지 ↔ 이슈 브릿지, 활성/done)

## 에이전트 탐색 힌트

- "왜 이렇게 결정했나요?" → `context/decision/`, 거기서 `relations.intents`로 취지 추적
- "이 취지 어떻게 다뤄왔나?" → `context/intent/`의 백링크 (decisions=승 / rejected=패)
- "현재 어떻게 동작하나?" → `ssot/`
- "이건 어떻게 운영하나?" → `runbook/`
- "이 함정 또 안 밟으려면?" → `context/trial_error/`
- "이거 발견했는데 어디로 분류할지 모르겠다" → `context/observation/`
- "어떤 결정으로 무슨 작업? / 이 작업의 근거?" → `task/` (결정·취지 ↔ 이슈 브릿지)
- 검색: `wiki:recall <query>` (Stage 1 frontmatter scan)
- 점검: `wiki:refresh` (무결성 리포트)
"""

INDEX_FILE_DESC = {
    ("ssot",): ("SSOT — 현재 유효한 설계 정본",
                "주제 단위로 제자리 갱신되는 현재 상태(living)."),
    ("runbook",): ("Runbook — 운영 절차",
                   "현재 운영 절차(living)."),
    ("context", "intent"): ("Intents — 취지",
                            "상황이 바뀌어도 유지돼야 하는 원칙(record). 결정·반려가 이 취지를 가리킨다."),
    ("context", "decision"): ("Decisions — 결정",
                              "결정·취지·트레이드오프·재평가 조건(record)."),
    ("context", "rejected_decision"): ("Rejected Decisions — 반려된 대안",
                                       "이 대안이 섬길 진 취지를 보유(record)."),
    ("context", "trial_error"): ("Trial & Error — 시행착오",
                                 "교훈·피해야 할 것·현재 유효성(record)."),
    ("context", "observation"): ("Observations — 관찰",
                                 "발견·관찰. 분류 전 임시 record. 후속 TRI/DEC/SSOT 갱신으로 승격되며 supersede."),
    ("task",): ("Tasks — 작업",
                "결정·취지를 외부 이슈에 잇는 작업 브릿지(제3 범주). 활성은 여기, 완료는 done/."),
}


def cmd_init(args) -> int:
    vault = resolve_vault(args.vault)
    today = now().strftime("%Y-%m-%d")
    created: List[str] = []
    kept: List[str] = []

    def ensure_dir(p: Path):
        if args.dry_run:
            return
        p.mkdir(parents=True, exist_ok=True)

    def write_if_absent(p: Path, content: str):
        if p.exists():
            kept.append(str(p))
            return
        if args.dry_run:
            created.append(str(p))
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        created.append(str(p))

    ensure_dir(vault)
    for parts in INIT_INDEX_FOLDERS:
        folder = vault.joinpath(*parts)
        ensure_dir(folder)
        if parts[0] == "context":
            ensure_dir(folder / "retired")
        if parts == ("task",):
            ensure_dir(folder / "done")
            ensure_dir(folder / "retired")

    write_if_absent(vault / "README.md", ROOT_README_TEMPLATE.format(today=today))

    for parts in INIT_INDEX_FOLDERS:
        title, summary = INDEX_FILE_DESC[parts]
        content = (
            f"---\n"
            f"title: {title}\n"
            f"created_at: {today}\n"
            f"summary: {summary}\n"
            f"tags: [meta]\n"
            f"audience: [human, agent]\n"
            f"---\n"
            f"\n# {title}\n"
            f"\n{summary}\n"
            f"\n{INDEX_HEADER}\n"
        )
        write_if_absent(index_path(vault, parts), content)

    if not args.dry_run:
        refresh_all_indexes(vault)

    emit_ok(args,
            {"vault": str(vault), "created": created, "kept": kept},
            text_lines=[f"vault: {vault}",
                        f"생성: {len(created)}건",
                        f"유지: {len(kept)}건"])
    return EXIT_OK


def cmd_capture(args) -> int:
    vault = resolve_vault(args.vault)
    ensure_vault(vault)

    t = args.type
    if t not in TYPE_SPECS:
        raise CliError(EXIT_USAGE, "unknown_type", f"unknown type: {t}")
    spec = TYPE_SPECS[t]

    rel_inputs = {
        "intents": parse_csv(args.intents),
        "rejected_decisions": parse_csv(args.rejected),
        "ssot": parse_csv(args.ssot),
        "runbook": parse_csv(args.runbook),
        "decisions": parse_csv(args.decisions),
        "tasks": parse_csv(args.tasks),
    }
    supersedes_arg = args.supersedes

    # §11.3 invariants
    if t in HUB_TYPES:
        for k, v in rel_inputs.items():
            if v:
                raise CliError(EXIT_USAGE, "hub_relations",
                               f"hub type '{t}' must not declare relations (--{k})")
    if t in LIVING_TYPES and supersedes_arg:
        raise CliError(EXIT_USAGE, "living_no_supersede",
                       f"living type '{t}' cannot --supersedes")
    if t in TASK_TYPES and supersedes_arg:
        raise CliError(EXIT_USAGE, "task_no_supersede",
                       f"task type '{t}' cannot --supersedes (use complete/reopen)")
    if t not in HUB_TYPES:
        allowed = set(spec.allowed_relations)
        for k, v in rel_inputs.items():
            if v and k not in allowed:
                raise CliError(EXIT_USAGE, "relation_not_allowed",
                               f"type '{t}' does not write relations.{k}")

    # §7 verified_at scope + strict date validation (same rules as refresh schema)
    if args.verified_at:
        if t not in VERIFIED_AT_TYPES:
            raise CliError(EXIT_USAGE, "verified_at_not_allowed",
                           f"--verified-at not allowed for type '{t}' "
                           f"(only {','.join(VERIFIED_AT_TYPES)})")
        if not _is_valid_iso_date(args.verified_at):
            raise CliError(EXIT_USAGE, "bad_verified_at",
                           f"--verified-at must be strict YYYY-MM-DD; "
                           f"got {args.verified_at!r}")
    # §7 affects_paths scope
    affects_paths = parse_csv(args.affects_paths)
    if affects_paths and t not in AFFECTS_PATHS_TYPES:
        raise CliError(EXIT_USAGE, "affects_paths_not_allowed",
                       f"--affects-paths not allowed for type '{t}' "
                       f"(only {','.join(AFFECTS_PATHS_TYPES)})")

    # Required field placeholder check — refuse template placeholder values
    # at the capture boundary so `refresh --check schema` never has to flag a
    # document the same CLI just produced.
    if _is_placeholder_value(args.title):
        raise CliError(EXIT_USAGE, "placeholder_title",
                       f"--title looks like an unfilled template placeholder "
                       f"({args.title!r}); replace with the real title")
    if _is_placeholder_value(args.summary):
        raise CliError(EXIT_USAGE, "placeholder_summary",
                       f"--summary looks like an unfilled template placeholder "
                       f"({args.summary!r}); replace with the real summary")

    if not parse_csv(args.tags):
        raise CliError(EXIT_USAGE, "empty_tags", "--tags must be non-empty")
    for _t in parse_csv(args.tags):
        if _is_placeholder_value(_t):
            raise CliError(EXIT_USAGE, "placeholder_tag",
                           f"--tags contains placeholder item ({_t!r}); "
                           f"replace with real vocabulary tags")

    search_terms = parse_csv(args.search_terms)

    if args.slug:
        slug = sanitize_slug(args.slug)
    else:
        slug = slugify(args.title)
    if not slug:
        raise CliError(EXIT_USAGE, "empty_slug",
                       "could not derive slug from title (try --slug explicitly)")
    folder = folder_dir(vault, t)
    if spec.prefix:  # record or task — timestamped id, collision-suffixed
        initial = record_basename(t, now(), slug)
        bn = unique_basename(folder, initial)
    else:
        bn = slug
        # vault-wide uniqueness for living slugs (§5).
        # include_indexes=True so a slug like 'ssot' or 'auth' (matching a folder
        # index file) is rejected — never silently overwrite derived indexes.
        target = folder / f"{bn}.md"
        if target.exists():
            raise CliError(EXIT_CONFLICT, "living_exists",
                           f"path already exists: {target} — "
                           f"인덱스 파일이거나 동명 노트입니다. 갱신하거나 다른 slug 사용.")
        existing = find_doc_anywhere(vault, bn, include_indexes=True)
        if existing is not None:
            raise CliError(EXIT_CONFLICT, "living_exists",
                           f"basename '{bn}' already in use at {existing}; "
                           f"갱신하거나 다른 slug 사용.")

    # resolve relations + verify each target's actual type matches the field
    resolved: dict = {}
    for k, vals in rel_inputs.items():
        if not vals:
            continue
        if k == "tasks":
            for v in vals:
                validate_task_ref(v)
            resolved[k] = list(vals)
            continue
        resolved[k] = []
        expected = RELATION_TARGET_TYPES.get(k)
        for v in vals:
            full = resolve_friendly(vault, v)
            if expected is not None:
                target_path = find_doc_anywhere(vault, full)
                if target_path is None:
                    # resolve_friendly said "found" (NFC stem matched) but
                    # find_doc_anywhere can't open it — refuse rather than
                    # silently store a ref that broken-rel will flag later.
                    raise CliError(EXIT_VALIDATION, "ref_unresolvable",
                                   f"--{k} {v}: resolved to {full!r} but path lookup "
                                   f"failed (possible Unicode/filesystem mismatch)")
                target_doc = read_doc(vault, target_path)
                if target_doc.doc_type != expected:
                    raise CliError(EXIT_VALIDATION, "relation_type_mismatch",
                                   f"--{k} {v}: 타입 불일치 (예상={expected}, "
                                   f"실제={target_doc.doc_type})")
            resolved[k].append(full)

    supersedes_id = None
    if supersedes_arg:
        supersedes_id = resolve_friendly(vault, supersedes_arg)
        # §13.3: --supersedes target must be an ACTIVE context/* record
        target_path = find_doc_anywhere(vault, supersedes_id)
        target_doc = read_doc(vault, target_path) if target_path else None
        if target_doc is None or target_doc.doc_type not in CONTEXT_RECORD_TYPES:
            raise CliError(EXIT_USAGE, "supersede_target_not_record",
                           f"--supersedes target must be a context record "
                           f"(got {target_doc.doc_type if target_doc else 'missing'})")
        if target_doc.retired:
            raise CliError(EXIT_VALIDATION, "supersede_target_retired",
                           f"--supersedes target must be active (got retired {supersedes_id}); "
                           f"the new record must supersede the latest active version")

    fm: dict = {}
    fm["title"] = args.title
    fm["created_at"] = now().strftime("%Y-%m-%d")
    fm["summary"] = args.summary
    fm["tags"] = parse_csv(args.tags)
    if args.verified_at:
        fm["verified_at"] = args.verified_at
    if args.audience:
        fm["audience"] = parse_csv(args.audience)
    if search_terms:
        fm["search_terms"] = search_terms
    if affects_paths:
        fm["affects_paths"] = affects_paths
    if supersedes_id:
        fm["supersedes"] = [supersedes_id]
    if resolved:
        fm["relations"] = resolved

    body_lines = [""]
    for sec in spec.sections:
        body_lines.append(f"## {sec}")
        body_lines.append("")
    body = "\n".join(body_lines) + "\n"

    target = folder / f"{bn}.md"
    write_doc(target, fm, body, dry_run=args.dry_run)

    if supersedes_id and not args.dry_run:
        _supersede_old(vault, supersedes_id, bn)

    if not args.dry_run:
        refresh_all_indexes(vault)

    emit_ok(args,
            {"id": bn, "path": str(target), "type": t, "supersedes": supersedes_id},
            text_lines=[f"생성: {target} (id={bn})"
                        + (f" supersedes={supersedes_id}" if supersedes_id else "")])
    return EXIT_OK


def _supersede_old(vault: Path, old_id: str, new_id: str) -> None:
    old_path = find_doc_anywhere(vault, old_id)
    if old_path is None:
        raise CliError(EXIT_VALIDATION, "supersede_missing",
                       f"supersedes target missing: {old_id}")
    old = read_doc(vault, old_path)
    today = now().strftime("%Y-%m-%d")
    old.frontmatter["retired_at"] = today
    old.frontmatter["retired_type"] = "superseded"
    old.frontmatter["superseded_by"] = new_id
    if old.retired:
        write_doc(old.path, old.frontmatter, old.body)
        return
    write_doc(old.path, old.frontmatter, old.body)
    spec = TYPE_SPECS[old.doc_type]
    rd = retired_subdir(vault.joinpath(*spec.folder))
    rd.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old.path), str(rd / old.path.name))


def cmd_retire(args) -> int:
    vault = resolve_vault(args.vault)
    ensure_vault(vault)

    if args.type not in ("deprecated", "superseded"):
        raise CliError(EXIT_USAGE, "bad_retire_type",
                       f"--type must be deprecated|superseded, got {args.type}")
    if args.type == "deprecated" and args.superseded_by:
        raise CliError(EXIT_USAGE, "deprecated_with_superseded_by",
                       "--type deprecated cannot have --superseded-by")
    if args.type == "superseded" and not args.superseded_by:
        raise CliError(EXIT_USAGE, "superseded_missing_ref",
                       "--type superseded requires --superseded-by")

    bn = args.basename
    tp = find_doc_anywhere(vault, bn)
    if tp is None:
        raise CliError(EXIT_VALIDATION, "retire_missing", f"target not found: {bn}")
    td = read_doc(vault, tp)
    _spec_td = TYPE_SPECS.get(td.doc_type)
    if _spec_td is None or not (_spec_td.is_record or _spec_td.is_task):
        raise CliError(EXIT_USAGE, "retire_not_record",
                       f"only records or task can be retired (got {td.doc_type})")
    if _spec_td.is_task and args.type == "superseded":
        raise CliError(EXIT_USAGE, "task_no_supersede",
                       "task cannot be superseded; use complete to finish it, "
                       "or retire --type deprecated for an invalid task")
    if td.retired:
        raise CliError(EXIT_VALIDATION, "already_retired", f"{bn} is already retired")

    today = now().strftime("%Y-%m-%d")
    td.frontmatter["retired_at"] = today
    td.frontmatter["retired_type"] = args.type
    new_id = None
    if args.type == "superseded":
        new_id = resolve_friendly(vault, args.superseded_by)
        if new_id == bn:
            raise CliError(EXIT_VALIDATION, "self_supersede", "cannot supersede self")
        # §13.3: successor must be an active context/* record (not ssot/runbook)
        new_path = find_doc_anywhere(vault, new_id)
        new_doc = read_doc(vault, new_path) if new_path else None
        if new_doc is None or new_doc.doc_type not in CONTEXT_RECORD_TYPES:
            raise CliError(EXIT_USAGE, "successor_not_record",
                           f"--superseded-by must point to a context record "
                           f"(got {new_doc.doc_type if new_doc else 'missing'})")
        if new_doc.retired:
            raise CliError(EXIT_USAGE, "successor_retired",
                           f"--superseded-by must point to an active record (got retired {new_id})")
        td.frontmatter["superseded_by"] = new_id

    write_doc(td.path, td.frontmatter, td.body, dry_run=args.dry_run)

    spec = TYPE_SPECS[td.doc_type]
    rd = retired_subdir(vault.joinpath(*spec.folder))
    if not args.dry_run:
        rd.mkdir(parents=True, exist_ok=True)
        shutil.move(str(td.path), str(rd / td.path.name))

    if new_id and not args.dry_run:
        np = find_doc_anywhere(vault, new_id)
        if np is None:
            raise CliError(EXIT_VALIDATION, "supersede_new_missing",
                           f"--superseded-by {new_id} not found")
        nd = read_doc(vault, np)
        existing = nd.frontmatter.get("supersedes", [])
        if not isinstance(existing, list):
            existing = []
        if bn not in existing:
            existing.append(bn)
        nd.frontmatter["supersedes"] = existing
        write_doc(nd.path, nd.frontmatter, nd.body)

    if not args.dry_run:
        refresh_all_indexes(vault)

    emit_ok(args,
            {"id": bn, "retired_type": args.type, "superseded_by": new_id},
            text_lines=[f"retired: {bn} → retired_type={args.type}"
                        + (f" superseded_by={new_id}" if new_id else "")])
    return EXIT_OK


def _move_task(vault: Path, args, *, to_done: bool) -> int:
    """Shared mechanism for complete (active→done/) and reopen (done/→active).

    task is the only type with a binary active/done state expressed by path —
    mirrors the active/retired path convention ("path is the canonical
    state"). The body is edited in place; this flips only the lifecycle
    location. In connected mode, task-github keeps the GitHub issue as the
    source of truth and projects state here; the wiki CLI never reads GitHub."""
    ensure_vault(vault)
    bn = args.basename
    p = find_doc_anywhere(vault, bn)
    if p is None:
        raise CliError(EXIT_VALIDATION, "task_missing", f"target not found: {bn}")
    d = read_doc(vault, p)
    verb = "complete" if to_done else "reopen"
    if d.doc_type != "task":
        raise CliError(EXIT_USAGE, f"{verb}_not_task",
                       f"only task can be {verb}d (got {d.doc_type or 'unknown'})")
    if d.retired:
        raise CliError(EXIT_VALIDATION, f"{verb}_retired",
                       f"{bn} is retired, not active/done; {verb} does not apply")
    if to_done and d.done:
        raise CliError(EXIT_VALIDATION, "already_done", f"{bn} is already done")
    if (not to_done) and (not d.done):
        raise CliError(EXIT_VALIDATION, "not_done",
                       f"{bn} is already active (not done)")
    task_root = vault.joinpath(*TYPE_SPECS["task"].folder)
    dest_dir = (task_root / "done") if to_done else task_root
    dest = dest_dir / d.path.name
    # Never clobber a same-named file at the destination (defends the
    # basename-uniqueness invariant even if a vault was hand-edited into a
    # colliding state).
    if dest.exists():
        raise CliError(EXIT_CONFLICT, f"{verb}_dest_exists",
                       f"destination already exists: {dest} — "
                       f"refusing to overwrite (basename collision)")
    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d.path), str(dest))
        refresh_all_indexes(vault)
    state = "done" if to_done else "active"
    emit_ok(args,
            {"id": bn, "state": state, "path": str(dest)},
            text_lines=[f"{'완료' if to_done else '재개'}: {bn} → "
                        f"task/{'done/' if to_done else ''}"])
    return EXIT_OK


def cmd_complete(args) -> int:
    return _move_task(resolve_vault(args.vault), args, to_done=True)


def cmd_reopen(args) -> int:
    return _move_task(resolve_vault(args.vault), args, to_done=False)


def cmd_recall(args) -> int:
    vault = resolve_vault(args.vault)
    ensure_vault(vault)

    if args.backlinks_of:
        docs = find_backlinks(vault, args.backlinks_of, include_retired=args.include_retired)
        results = [{
            "id": d.doc_id, "type": d.doc_type, "path": str(d.path),
            "summary": d.frontmatter.get("summary", ""), "retired": d.retired,
        } for d in docs]
        emit_ok(args,
                {"mode": "backlinks", "target": args.backlinks_of, "results": results},
                text_lines=[f"백링크 ({args.backlinks_of}): {len(results)}건"] +
                           [f"  - {r['id']} — {r['summary']}" for r in results])
        return EXIT_OK

    if args.read:
        refs = parse_csv(args.read)
        if not refs:
            raise CliError(EXIT_USAGE, "read_empty", "--read requires at least one basename")
        results: List[dict] = []
        for ref in refs:
            if args.fuzzy:
                # resolve_friendly raises ref_missing/ref_ambiguous itself —
                # downgrade to read_missing only if it returns a basename we
                # then fail to open (shouldn't happen, but mirrors strict path).
                resolved = resolve_friendly(vault, ref, allow_fuzzy=True)
                p = find_doc_anywhere(vault, resolved)
            else:
                p = find_doc_anywhere(vault, ref)
            if p is None:
                raise CliError(EXIT_VALIDATION, "read_missing", f"not found: {ref}")
            is_retired = "retired" in p.relative_to(vault).parts
            if is_retired and not args.include_retired:
                raise CliError(EXIT_VALIDATION, "read_retired",
                               f"'{ref}' is retired; pass --include-retired to read it")
            text = p.read_text(encoding="utf-8")
            results.append({
                "id": ref, "path": str(p), "text": text, "retired": is_retired,
            })
        if len(results) == 1:
            emit_ok(args,
                    {"mode": "read", "id": results[0]["id"], "path": results[0]["path"],
                     "text": results[0]["text"], "results": results},
                    text_lines=[results[0]["text"]])
        else:
            emit_ok(args,
                    {"mode": "read", "results": results},
                    text_lines=[f"--- {r['id']} ---\n{r['text']}" for r in results])
        return EXIT_OK

    docs: List[WikiDoc] = []
    for parts in discover_index_folders(vault):
        for p in iter_active_docs(vault, parts):
            docs.append(read_doc(vault, p))
        if args.include_retired:
            for p in iter_retired_docs(vault, parts):
                docs.append(read_doc(vault, p))
            for p in iter_done_docs(vault, parts):
                docs.append(read_doc(vault, p))

    type_filter = args.type
    tag_filter = args.tag or []
    query = (args.query or "").lower()

    matched: List[WikiDoc] = []
    for d in docs:
        if type_filter and d.doc_type != type_filter:
            continue
        tags = d.frontmatter.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        if tag_filter and not all(t in tags for t in tag_filter):
            continue
        if query:
            search_terms_val = d.frontmatter.get("search_terms", [])
            if not isinstance(search_terms_val, list):
                search_terms_val = []
            blob = " ".join([
                str(d.frontmatter.get("title", "")),
                str(d.frontmatter.get("summary", "")),
                " ".join(str(x) for x in tags),
                " ".join(str(x) for x in search_terms_val),
            ]).lower()
            if query not in blob:
                continue
        matched.append(d)
    matched.sort(key=lambda d: d.doc_id)

    limit = args.limit if args.limit and args.limit > 0 else 10

    if args.stage == 2 and args.section:
        results = []
        for d in matched[:limit]:
            m = re.search(rf"(?ms)^## {re.escape(args.section)}\n(.*?)(?=^## |\Z)", d.body)
            sb = m.group(1).strip() if m else ""
            truncated = False
            if len(sb.encode("utf-8")) > 500:
                sb = sb.encode("utf-8")[:500].decode("utf-8", errors="ignore") + "…"
                truncated = True
            results.append({"id": d.doc_id, "type": d.doc_type,
                            "section": args.section, "content": sb,
                            "truncated": truncated})
        emit_ok(args,
                {"mode": "stage2", "section": args.section, "results": results},
                text_lines=[f"Stage 2 ({args.section}): {len(results)}건"] +
                           [f"--- {r['id']} ---\n{r['content']}" for r in results])
        return EXIT_OK

    if args.stage == 3:
        results = [{
            "id": d.doc_id, "type": d.doc_type, "path": str(d.path),
            "text": d.path.read_text(encoding="utf-8"),
        } for d in matched[:limit]]
        emit_ok(args, {"mode": "stage3", "results": results},
                text_lines=[r["text"] for r in results])
        return EXIT_OK

    # Stage 1 (default)
    stage1: List[dict] = []
    total = 0
    truncated_at: Optional[int] = None
    for d in matched:
        item = {
            "id": d.doc_id, "type": d.doc_type,
            "summary": d.frontmatter.get("summary", ""),
            "tags": d.frontmatter.get("tags", []),
            "verified_at": d.frontmatter.get("verified_at"),
            "retired": d.retired,
        }
        st = d.frontmatter.get("search_terms")
        if st:
            item["search_terms"] = st
        chunk = json.dumps(item, ensure_ascii=False)
        if total + len(chunk) > 2048 and stage1:
            truncated_at = len(stage1)
            break
        total += len(chunk)
        stage1.append(item)
        if len(stage1) >= limit:
            break

    payload = {"mode": "stage1", "results": stage1}
    if truncated_at is not None:
        payload["truncated"] = True
        payload["hint"] = "결과가 2KB를 넘어 절단됨. --type/--tag/--limit로 좁히세요."
    emit_ok(args, payload,
            text_lines=[f"Recall ({len(stage1)}건):"] +
                       [f"  - {r['id']} [{r['type']}] {r['summary']}" for r in stage1])
    return EXIT_OK


# ──────────────────────────────────────────────────────────────────────────
# (g.1) refresh — integrity checks (§13.5, §14.5)
# ──────────────────────────────────────────────────────────────────────────
ALL_REFRESH_CHECKS = [
    "stale", "supersede", "broken-rel", "task-ref", "orphan",
    "index", "retired-in-index", "active-ref-retired", "tags",
    "changed-path-stale", "duplicate-basename", "empty-lesson",
    "schema",
]


def _git_changed_paths(vault: Path) -> Optional[List[str]]:
    """Return a list of git-tracked changed paths, or None if unavailable.

    Uses `git diff --name-only HEAD` from the vault's parent (typical repo
    root). On any failure (no git, no repo, error) → None.
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(vault.parent if vault.parent.exists() else vault),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if out.returncode != 0:
        return None
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _parse_tag_vocabulary(path: Path) -> Optional[set]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^## 어휘\n(.*?)(?=^## |\Z)", text)
    if not m:
        return None
    out = set()
    for line in m.group(1).splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.add(s[2:].strip())
    return out


def _section_body(body: str, header: str) -> str:
    m = re.search(rf"(?ms)^## {re.escape(header)}\n(.*?)(?=^## |\Z)", body)
    return (m.group(1) if m else "").strip()


def _validate_fix_arg(raw: Optional[str]) -> List[str]:
    """Parse --fix value. None → no fix. Empty/bare → error.
    Unknown values → error. Returns the list of fix names.
    """
    if raw is None:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise CliError(EXIT_USAGE, "fix_bare",
                       "--fix requires an argument (allowed: " + ",".join(FIX_WHITELIST) + ")")
    for p in parts:
        if p not in FIX_WHITELIST:
            raise CliError(EXIT_USAGE, "fix_not_allowed",
                           f"--fix '{p}' not allowed (whitelist: " + ",".join(FIX_WHITELIST) + ")")
    return parts


def cmd_refresh(args) -> int:
    vault = resolve_vault(args.vault)
    ensure_vault(vault)

    if args.check is None or args.check == "all":
        checks = list(ALL_REFRESH_CHECKS)
    else:
        raw_parts = [c.strip() for c in args.check.split(",")]
        checks = [c for c in raw_parts if c]
        if not checks:
            raise CliError(EXIT_USAGE, "check_empty",
                           "--check requires a check name or 'all'")
        unknown = [c for c in checks if c not in ALL_REFRESH_CHECKS]
        if unknown:
            raise CliError(EXIT_USAGE, "check_unknown",
                           f"unknown check(s): {','.join(unknown)} "
                           f"(allowed: {','.join(ALL_REFRESH_CHECKS)},all)")

    fixes = _validate_fix_arg(args.fix)

    folders = discover_index_folders(vault)
    all_active: List[WikiDoc] = []
    all_retired: List[WikiDoc] = []
    for parts in folders:
        for p in iter_active_docs(vault, parts):
            all_active.append(read_doc(vault, p))
        for p in iter_retired_docs(vault, parts):
            all_retired.append(read_doc(vault, p))
        # done tasks are terminal: part of the graph (all_docs) for schema /
        # broken-rel / supersede / duplicate checks, but excluded from
        # active-only checks (stale / orphan / empty-lesson use all_active).
        for p in iter_done_docs(vault, parts):
            all_retired.append(read_doc(vault, p))
    all_docs = all_active + all_retired
    by_id = {d.doc_id: d for d in all_docs}

    scope_prefix = (vault / args.path).resolve() if args.path else None

    def in_scope(d: WikiDoc) -> bool:
        if scope_prefix is None:
            return True
        try:
            d.path.resolve().relative_to(scope_prefix)
            return True
        except ValueError:
            return False

    issues: List[dict] = []
    today = now().date()
    days = args.days if args.days else 90

    if "stale" in checks:
        for d in all_active:
            if not in_scope(d):
                continue
            if d.doc_type not in TIME_STALE_TYPES:
                continue
            va = d.frontmatter.get("verified_at")
            if not va:
                continue
            # Reject loose forms (`2026-1-1`) using the same strict helper
            # the schema check uses — otherwise schema and stale disagree on
            # what a valid date looks like. Invalid dates are silently
            # skipped here so the `schema` check is the single reporter.
            if not _is_valid_iso_date(va):
                continue
            vd = datetime.strptime(va, "%Y-%m-%d").date()
            age = (today - vd).days
            if age > days:
                issues.append({"check": "stale", "path": str(d.path),
                               "field": "verified_at",
                               "message": f"{d.doc_id}: verified_at {va} ({age}일, 기준 {days}일)"})

    if "supersede" in checks:
        for d in all_docs:
            if not in_scope(d):
                continue
            sup = d.frontmatter.get("supersedes", [])
            if isinstance(sup, list):
                for oid in sup:
                    old = by_id.get(oid)
                    if old is None:
                        issues.append({"check": "supersede", "path": str(d.path),
                                       "field": "supersedes", "target": oid,
                                       "message": f"{d.doc_id}.supersedes → {oid} (없음)"})
                        continue
                    if old.frontmatter.get("superseded_by") != d.doc_id:
                        issues.append({"check": "supersede", "path": str(old.path),
                                       "field": "superseded_by", "target": d.doc_id,
                                       "message": f"{old.doc_id}.superseded_by ≠ {d.doc_id}"})
            sb = d.frontmatter.get("superseded_by")
            if sb:
                new = by_id.get(sb)
                if new is None:
                    issues.append({"check": "supersede", "path": str(d.path),
                                   "field": "superseded_by", "target": sb,
                                   "message": f"{d.doc_id}.superseded_by → {sb} (없음)"})
                else:
                    new_sup = new.frontmatter.get("supersedes", [])
                    if not isinstance(new_sup, list) or d.doc_id not in new_sup:
                        issues.append({"check": "supersede", "path": str(new.path),
                                       "field": "supersedes", "target": d.doc_id,
                                       "message": f"{new.doc_id}.supersedes ∌ {d.doc_id}"})

    for d in all_docs:
        if not in_scope(d):
            continue
        rel = d.frontmatter.get("relations")
        if not isinstance(rel, dict):
            continue
        for field, values in rel.items():
            if not isinstance(values, list):
                continue
            if field == "tasks":
                if "task-ref" in checks:
                    for t in values:
                        if not TASK_REF_RE.match(t):
                            issues.append({"check": "task-ref", "path": str(d.path),
                                           "field": "tasks", "target": t,
                                           "message": f"{d.doc_id}.relations.tasks: '{t}' (owner/repo#N 형식 아님)"})
                continue
            for v in values:
                tp = find_doc_anywhere(vault, v)
                if tp is None:
                    if "broken-rel" in checks:
                        issues.append({"check": "broken-rel", "path": str(d.path),
                                       "field": field, "target": v,
                                       "message": f"{d.doc_id}.relations.{field} → {v} (위키 문서 부재)"})
                else:
                    tp_retired = "retired" in tp.relative_to(vault).parts
                    if (not d.retired) and (not d.done) and tp_retired and "active-ref-retired" in checks:
                        issues.append({"check": "active-ref-retired", "path": str(d.path),
                                       "field": field, "target": v,
                                       "message": f"active {d.doc_id} → retired {v}"})

    if "orphan" in checks:
        incoming: dict = {}
        for d in all_active:
            rel = d.frontmatter.get("relations")
            if not isinstance(rel, dict):
                continue
            for k, vs in rel.items():
                if k == "tasks" or not isinstance(vs, list):
                    continue
                for v in vs:
                    incoming.setdefault(v, []).append(d.doc_id)
        for d in all_active:
            if not in_scope(d) or d.doc_type not in RECORD_TYPES:
                continue
            rel = d.frontmatter.get("relations")
            has_out = isinstance(rel, dict) and any(
                (k != "tasks" and isinstance(v, list) and v) for k, v in rel.items()
            )
            has_in = d.doc_id in incoming
            if not has_out and not has_in:
                issues.append({"check": "orphan", "path": str(d.path),
                               "message": f"{d.doc_id}: 백링크·관계 모두 없음"})

    # Folders to inspect for index issues: discovered folders (notes present)
    # PLUS the seed set (init's standard folders), so a deleted standard
    # index file in an empty folder is still detected. We dedupe while
    # preserving the discovery order — discovered first, then any init
    # folders that aren't yet listed.
    check_folders: List[Tuple[str, ...]] = list(folders)
    seen_folders = set(folders)
    for parts in INIT_INDEX_FOLDERS:
        if parts not in seen_folders and vault.joinpath(*parts).is_dir():
            check_folders.append(parts)
            seen_folders.add(parts)

    derived_by_folder = {p: derive_index_lines(vault, p) for p in check_folders}
    fixed: List[dict] = []

    def _should_have_index(parts: Tuple[str, ...]) -> bool:
        # Standard init folders always need an index (it's part of the vault
        # contract from §6/§10). Nested folders only when they actually
        # contain notes — avoids creating stubs for ad-hoc empty subfolders.
        return parts in INIT_INDEX_FOLDERS or bool(derived_by_folder.get(parts))

    for parts in check_folders:
        idx = find_index_file(vault, parts)
        if idx is None or not idx.is_file():
            if "index" in checks and _should_have_index(parts):
                if scope_prefix is not None:
                    try:
                        vault.joinpath(*parts).resolve().relative_to(scope_prefix)
                    except ValueError:
                        continue
                canonical = index_path(vault, parts)
                note_count = len(derived_by_folder.get(parts, []))
                issues.append({"check": "index",
                               "path": str(canonical),
                               "field": "index",
                               "message": (f"index 누락: {canonical.relative_to(vault)} "
                                           f"(노트 {note_count}건)")})
            continue
        if scope_prefix is not None:
            try:
                idx.resolve().relative_to(scope_prefix)
            except ValueError:
                continue
        text = idx.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^## 노트\n(.*?)(?=^## |\Z)", text)
        body = m.group(1) if m else ""
        actual = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("- [[")]
        derived = derived_by_folder[parts]
        if "index" in checks:
            for ln in derived:
                if ln not in actual:
                    issues.append({"check": "index", "path": str(idx),
                                   "message": f"index 누락: {ln}"})
            for ln in actual:
                if ln not in derived:
                    issues.append({"check": "index", "path": str(idx),
                                   "message": f"index 잔존: {ln}"})
        if "retired-in-index" in checks:
            for ln in actual:
                m2 = re.search(r"\[\[([^\]]+)\]\]", ln)
                if not m2:
                    continue
                bn = m2.group(1)
                tp = find_doc_anywhere(vault, bn)
                if tp is not None and "retired" in tp.relative_to(vault).parts:
                    issues.append({"check": "retired-in-index", "path": str(idx),
                                   "target": bn,
                                   "message": f"index에 retired 문서 노출: {bn}"})

    if "tags" in checks:
        vocab_path = vault / "ssot" / "tag-vocabulary.md"
        if vocab_path.is_file():
            vocab = _parse_tag_vocabulary(vocab_path)
            if vocab is not None:
                for d in all_docs:
                    if not in_scope(d):
                        continue
                    tags = d.frontmatter.get("tags", []) or []
                    if not isinstance(tags, list):
                        continue
                    for t in tags:
                        if t not in vocab:
                            issues.append({"check": "tags", "path": str(d.path),
                                           "field": "tags", "target": t,
                                           "message": f"{d.doc_id}.tags: '{t}' (어휘 밖)"})

    if "schema" in checks:
        for d in all_docs:
            if not in_scope(d):
                continue
            fm = d.frontmatter

            # Required common fields (v1 §7)
            if not fm:
                issues.append({"check": "schema", "path": str(d.path),
                               "field": "frontmatter",
                               "message": f"{d.doc_id}: frontmatter 누락 (문서는 '---'로 시작해야 함)"})
                continue
            for req in ("title", "summary"):
                v = fm.get(req)
                if not isinstance(v, str) or not v.strip():
                    issues.append({"check": "schema", "path": str(d.path),
                                   "field": req,
                                   "message": f"{d.doc_id}: '{req}' 필수 (non-empty scalar)"})
                elif _is_placeholder_value(v):
                    issues.append({"check": "schema", "path": str(d.path),
                                   "field": req,
                                   "message": (f"{d.doc_id}: '{req}' placeholder({v!r}) "
                                               f"— 템플릿 값 그대로. 실제 값으로 채우세요")})
            # created_at: required + valid calendar date
            ca = fm.get("created_at")
            if not _is_valid_iso_date(ca):
                issues.append({"check": "schema", "path": str(d.path),
                               "field": "created_at",
                               "message": (f"{d.doc_id}: 'created_at' 필수 + 유효한 ISO 날짜 "
                                           f"(YYYY-MM-DD); got {ca!r}")})
            # verified_at / retired_at: optional but valid date when present
            for opt_date in ("verified_at", "retired_at"):
                if opt_date in fm and not _is_valid_iso_date(fm[opt_date]):
                    issues.append({"check": "schema", "path": str(d.path),
                                   "field": opt_date,
                                   "message": (f"{d.doc_id}: '{opt_date}' 유효한 ISO 날짜여야 함; "
                                               f"got {fm[opt_date]!r}")})
            tags = fm.get("tags")
            if not isinstance(tags, list) or not tags:
                issues.append({"check": "schema", "path": str(d.path),
                               "field": "tags",
                               "message": f"{d.doc_id}: 'tags' 필수 (non-empty list)"})
            elif isinstance(tags, list):
                for t in tags:
                    if isinstance(t, str) and _is_placeholder_value(t):
                        issues.append({"check": "schema", "path": str(d.path),
                                       "field": "tags",
                                       "target": t,
                                       "message": (f"{d.doc_id}: tags placeholder 항목({t!r}) "
                                                   f"— 템플릿 값 그대로")})

            # Type-scoped optional fields (v1 §7)
            if "verified_at" in fm and d.doc_type and d.doc_type not in VERIFIED_AT_TYPES:
                issues.append({"check": "schema", "path": str(d.path),
                               "field": "verified_at",
                               "message": (f"{d.doc_id}: 'verified_at'은 {d.doc_type} 타입에 허용 안 됨 "
                                           f"(허용: {','.join(VERIFIED_AT_TYPES)})")})
            if "affects_paths" in fm and d.doc_type and d.doc_type not in AFFECTS_PATHS_TYPES:
                issues.append({"check": "schema", "path": str(d.path),
                               "field": "affects_paths",
                               "message": (f"{d.doc_id}: 'affects_paths'는 {d.doc_type} 타입에 허용 안 됨 "
                                           f"(허용: {','.join(AFFECTS_PATHS_TYPES)})")})

            # forbidden top-level fields (id, status, classified_as)
            for forbidden in FORBIDDEN_FIELDS:
                if forbidden in fm:
                    issues.append({"check": "schema", "path": str(d.path),
                                   "field": forbidden,
                                   "message": f"{d.doc_id}: '{forbidden}' 필드 금지 (v1 §7)"})
            # living: relations 키 자체 금지
            if d.doc_type in LIVING_TYPES and "relations" in fm:
                issues.append({"check": "schema", "path": str(d.path),
                               "field": "relations",
                               "message": f"{d.doc_id}: living({d.doc_type})은 relations 키를 두지 않는다"})
            rel = fm.get("relations")
            if isinstance(rel, dict):
                # lifecycle fields must be top-level, not nested under relations
                for life in LIFECYCLE_FIELDS:
                    if life in rel:
                        issues.append({"check": "schema", "path": str(d.path),
                                       "field": f"relations.{life}",
                                       "message": (f"{d.doc_id}: lifecycle '{life}'는 "
                                                   f"top-level이어야 함 (relations 안 금지)")})
                # relation sub-keys must be in the type's allowed list
                spec = TYPE_SPECS.get(d.doc_type)
                if spec is not None:
                    allowed = set(spec.allowed_relations)
                    for k, vs in rel.items():
                        if k in LIFECYCLE_FIELDS:
                            continue
                        if k == "tasks":
                            # type-allowance still applies; tasks is in allowed lists where supported
                            if "tasks" not in allowed:
                                issues.append({"check": "schema", "path": str(d.path),
                                               "field": f"relations.{k}",
                                               "message": f"{d.doc_id}: relations.{k}은 "
                                                          f"{d.doc_type} 타입에 허용되지 않음"})
                            continue
                        if k not in allowed:
                            issues.append({"check": "schema", "path": str(d.path),
                                           "field": f"relations.{k}",
                                           "message": f"{d.doc_id}: relations.{k}은 "
                                                      f"{d.doc_type} 타입에 허용되지 않음 "
                                                      f"(허용: {sorted(allowed) or '없음'})"})
                            continue
                        # relation target type cross-check (intents → intent, etc.)
                        # Reuse the by_id map built above; O(1) lookup instead of
                        # per-target find_doc_anywhere/read_doc.
                        expected = RELATION_TARGET_TYPES.get(k)
                        if expected is None or not isinstance(vs, list):
                            continue
                        for v in vs:
                            td = by_id.get(v)
                            if td is None:
                                continue  # broken-rel will flag separately
                            if td.doc_type != expected:
                                issues.append({"check": "schema", "path": str(d.path),
                                               "field": f"relations.{k}",
                                               "target": v,
                                               "message": (f"{d.doc_id}.relations.{k} → {v} "
                                                           f"타입 불일치 (예상={expected}, "
                                                           f"실제={td.doc_type})")})

    if "duplicate-basename" in checks:
        # Key by NFC-normalized stem so NFC/NFD pairs (visually identical
        # filenames produced by different OS / tools) collapse into the
        # same bucket and get flagged.
        seen: dict = {}
        for p in iter_every_md(vault):
            seen.setdefault(_nfc(p.stem), []).append(p)
        for bn, paths in seen.items():
            if len(paths) > 1:
                # Filter by scope if requested (any path in scope triggers).
                if scope_prefix is not None and not any(
                    _is_in(p, scope_prefix) for p in paths
                ):
                    continue
                issues.append({"check": "duplicate-basename", "basename": bn,
                               "paths": [str(p) for p in paths],
                               "message": f"basename '{bn}' 중복: " +
                                          ", ".join(str(p) for p in paths)})

    if "empty-lesson" in checks:
        for d in all_active:
            if not in_scope(d) or d.doc_type != "trial_error":
                continue
            sb = _section_body(d.body, "교훈")
            if not sb or PLACEHOLDER_RE.match(sb):
                issues.append({"check": "empty-lesson", "path": str(d.path),
                               "field": "## 교훈",
                               "message": f"{d.doc_id}: ## 교훈 비어있거나 placeholder"})

    if "changed-path-stale" in checks:
        changed: Optional[List[str]]
        if args.changed_path:
            changed = parse_csv(args.changed_path)
        else:
            changed = _git_changed_paths(vault)
        if changed:
            for d in all_active:
                if not in_scope(d):
                    continue
                if d.doc_type not in PATH_STALE_TYPES:
                    continue
                ap = d.frontmatter.get("affects_paths", []) or []
                if not isinstance(ap, list) or not ap:
                    continue
                va = d.frontmatter.get("verified_at")
                # Policy (matches `stale` and frontmatter-schema.md): an
                # invalid verified_at is silently skipped here so the
                # `schema` check is the single reporter. Otherwise a
                # malformed date would be double-flagged: once by schema
                # and once here as a drift warning the operator can't act
                # on. `va is None` (no verified_at) still falls through
                # and reports drift — that's a legitimate "never verified
                # against this code path" signal.
                if va is not None:
                    if not _is_valid_iso_date(va):
                        continue
                    vd = datetime.strptime(va, "%Y-%m-%d").date()
                    if vd == today:
                        continue
                # Match any glob in affects_paths against any changed path
                hits = [cp for cp in changed
                        if any(fnmatch.fnmatch(cp, glob) for glob in ap)]
                if hits:
                    issues.append({
                        "check": "changed-path-stale", "path": str(d.path),
                        "field": "affects_paths",
                        "matched": hits[:5],
                        "message": (f"{d.doc_id}: affects_paths {ap} 매칭 변경({len(hits)}건) "
                                    f"+ verified_at={va or '없음'}"),
                    })

    # --fix application (whitelist) — run AFTER all checks recorded
    if fixes:
        if "index" in fixes:
            today = now().strftime("%Y-%m-%d")
            # Use the same expanded folder set as the check so deleting a
            # standard index from an empty vault is recoverable.
            for parts in check_folders:
                idx = find_index_file(vault, parts)
                # Missing index — create canonical NFC skeleton and then sync.
                # Standard init folders are always restored (they're part of
                # the vault contract). Nested folders only when they actually
                # have notes — avoids stubbing ad-hoc empty subfolders.
                if (idx is None or not idx.is_file()) and _should_have_index(parts):
                    canonical = index_path(vault, parts)
                    if scope_prefix is not None:
                        try:
                            canonical.resolve().relative_to(scope_prefix)
                        except ValueError:
                            continue
                    if parts in INDEX_FILE_DESC:
                        title, summary = INDEX_FILE_DESC[parts]
                    else:
                        folder_name = _nfc(parts[-1])
                        title = folder_name
                        summary = f"{folder_name} 영역 인덱스 (nested)"
                    canonical.parent.mkdir(parents=True, exist_ok=True)
                    canonical.write_text(
                        f"---\n"
                        f"title: {title}\n"
                        f"created_at: {today}\n"
                        f"summary: {summary}\n"
                        f"tags: [meta]\n"
                        f"audience: [human, agent]\n"
                        f"---\n"
                        f"\n# {title}\n"
                        f"\n{summary}\n"
                        f"\n{INDEX_HEADER}\n",
                        encoding="utf-8",
                    )
                    fixed.append({"fix": "index", "path": str(canonical),
                                  "message": (f"index 생성: "
                                              f"{canonical.relative_to(vault)}")})
                    rewrite_index(vault, parts)
                    continue
                if idx is None or not idx.is_file():
                    continue
                if scope_prefix is not None:
                    try:
                        idx.resolve().relative_to(scope_prefix)
                    except ValueError:
                        continue
                changed_flag = rewrite_index(vault, parts)
                if changed_flag:
                    fixed.append({"fix": "index", "path": str(idx),
                                  "message": f"index 동기화: {idx.relative_to(vault)}"})
        if "retired-in-index" in fixes:
            for parts in check_folders:
                idx = find_index_file(vault, parts)
                if idx is None or not idx.is_file():
                    continue
                if scope_prefix is not None:
                    try:
                        idx.resolve().relative_to(scope_prefix)
                    except ValueError:
                        continue
                text = idx.read_text(encoding="utf-8")
                m = re.search(r"(?ms)^## 노트\n(.*?)(?=^## |\Z)", text)
                if not m:
                    continue
                body = m.group(1)
                kept_lines: List[str] = []
                removed: List[str] = []
                for raw in body.splitlines():
                    s = raw.strip()
                    if not s.startswith("- [["):
                        kept_lines.append(raw)
                        continue
                    m2 = re.search(r"\[\[([^\]]+)\]\]", s)
                    if not m2:
                        kept_lines.append(raw)
                        continue
                    bn = m2.group(1)
                    tp = find_doc_anywhere(vault, bn)
                    if tp is not None and "retired" in tp.relative_to(vault).parts:
                        removed.append(bn)
                    else:
                        kept_lines.append(raw)
                if removed:
                    new_body = "\n".join(ln for ln in kept_lines if ln.strip())
                    new_text = (text[: m.start(1)] + ("\n" + new_body + "\n" if new_body else "\n")
                                + text[m.end(1):])
                    idx.write_text(new_text, encoding="utf-8")
                    for bn in removed:
                        fixed.append({"fix": "retired-in-index", "path": str(idx),
                                      "target": bn,
                                      "message": f"index에서 retired 제거: {bn}"})

        # After fix, drop the issues that the fix addressed.
        fixed_checks = {"index": "index", "retired-in-index": "retired-in-index"}
        addressed = {fixed_checks[f] for f in fixes if f in fixed_checks}
        if addressed:
            issues = [it for it in issues if it["check"] not in addressed]

    # Output (always emit {issues:[...]})
    payload = {"issues": issues}
    if fixes:
        payload["fixed"] = fixed
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        if not issues:
            print("✅ 무결성 OK — 이슈 0건.")
        else:
            print(f"무결성 이슈 {len(issues)}건:")
            for it in issues:
                print(f"  [{it['check']}] {it['message']}")
        if fixed:
            print(f"적용된 수정 {len(fixed)}건:")
            for fx in fixed:
                print(f"  [{fx['fix']}] {fx['message']}")
    if args.strict and issues:
        return EXIT_STRICT
    return EXIT_OK


def _is_in(p: Path, prefix: Path) -> bool:
    try:
        p.resolve().relative_to(prefix)
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────────────────────────────────
# (h) Argument parsing / dispatch
# ──────────────────────────────────────────────────────────────────────────
def _common_parent() -> argparse.ArgumentParser:
    """Shared options accepted in any position on each subcommand."""
    pp = argparse.ArgumentParser(add_help=False)
    pp.add_argument("--vault", default=None, help="vault root (default: ./wiki)")
    pp.add_argument("--json", action="store_true", help="machine-readable output")
    return pp


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wiki_cli", description="AI-native wiki CLI")
    # Top-level mirrors `--vault`/`--json` so both positions work:
    #   wiki_cli --vault X capture ...    (legacy)
    #   wiki_cli capture --vault X ...    (definition contract §13)
    # Subparser values use SUPPRESS so omitting them doesn't clobber top-level.
    p.add_argument("--vault", default=None, help="vault root (default: ./wiki)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _sub_common(sp):
        sp.add_argument("--vault", default=argparse.SUPPRESS,
                        help="vault root (default: ./wiki)")
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    pi = sub.add_parser("init", help="initialize a wiki vault (idempotent)")
    _sub_common(pi)
    pi.add_argument("--dry-run", action="store_true")
    pi.set_defaults(func=cmd_init)

    pc = sub.add_parser("capture", help="create a wiki document")
    _sub_common(pc)
    pc.add_argument("type", choices=list(TYPE_SPECS.keys()))
    pc.add_argument("--title", required=True)
    pc.add_argument("--summary", required=True)
    pc.add_argument("--tags", required=True, help="comma-separated tags")
    pc.add_argument("--slug", default=None)
    pc.add_argument("--intents", default=None, help="comma-separated refs")
    pc.add_argument("--ssot", default=None, help="comma-separated ssot refs")
    pc.add_argument("--runbook", default=None, help="comma-separated runbook refs")
    pc.add_argument("--rejected", default=None, help="rejected_decisions refs")
    pc.add_argument("--decisions", default=None)
    pc.add_argument("--tasks", default=None, help="owner/repo#N comma list")
    pc.add_argument("--supersedes", default=None)
    pc.add_argument("--verified-at", default=None, dest="verified_at")
    pc.add_argument("--audience", default=None)
    pc.add_argument("--affects-paths", default=None, dest="affects_paths",
                    help="comma-separated globs (ssot/runbook/trial_error/observation only)")
    pc.add_argument("--search-terms", default=None, dest="search_terms",
                    help="comma-separated optional search keywords")
    pc.add_argument("--dry-run", action="store_true")
    pc.set_defaults(func=cmd_capture)

    pr = sub.add_parser("retire", help="retire a context record")
    _sub_common(pr)
    pr.add_argument("basename")
    pr.add_argument("--type", required=True)
    pr.add_argument("--superseded-by", default=None, dest="superseded_by")
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=cmd_retire)

    pco = sub.add_parser("complete", help="mark a task done (move to task/done/)")
    _sub_common(pco)
    pco.add_argument("basename")
    pco.add_argument("--dry-run", action="store_true")
    pco.set_defaults(func=cmd_complete)

    pre = sub.add_parser("reopen", help="reopen a done task (move back to task/)")
    _sub_common(pre)
    pre.add_argument("basename")
    pre.add_argument("--dry-run", action="store_true")
    pre.set_defaults(func=cmd_reopen)

    pq = sub.add_parser("recall", help="hierarchical query (read-only)")
    _sub_common(pq)
    pq.add_argument("query", nargs="?", default=None)
    pq.add_argument("--type", default=None)
    pq.add_argument("--tag", action="append", default=None)
    pq.add_argument("--section", default=None)
    pq.add_argument("--stage", type=int, default=1)
    pq.add_argument("--limit", type=int, default=10)
    pq.add_argument("--backlinks-of", default=None, dest="backlinks_of")
    pq.add_argument("--read", default=None,
                    help="comma-separated basenames; batch reads preserve order")
    pq.add_argument("--include-retired", action="store_true", dest="include_retired")
    pq.add_argument("--fuzzy", action="store_true",
                    help="allow slug-fragment fallback when --read can't find an exact match")
    pq.set_defaults(func=cmd_recall)

    pf = sub.add_parser("refresh", help="integrity report (read-only by default)")
    _sub_common(pf)
    pf.add_argument("--check", default="all")
    pf.add_argument("--days", type=int, default=90)
    pf.add_argument("--path", default=None)
    pf.add_argument("--changed-path", default=None, dest="changed_path",
                    help="comma-separated changed paths; overrides git diff")
    pf.add_argument("--fix", default=None,
                    help="whitelist: index,retired-in-index. bare --fix is rejected.")
    pf.add_argument("--strict", action="store_true")
    pf.set_defaults(func=cmd_refresh)

    return p


# ──────────────────────────────────────────────────────────────────────────
# (i) Output formatting
# ──────────────────────────────────────────────────────────────────────────
def emit_ok(args, payload: dict, text_lines: Optional[List[str]] = None) -> None:
    if args.json:
        out = {"ok": True}
        out.update(payload)
        print(json.dumps(out, ensure_ascii=False))
    elif text_lines:
        print("\n".join(text_lines))


def emit_fail(args, error_code: str, message: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "error_code": error_code, "message": message},
                         ensure_ascii=False))
    else:
        print(message, file=sys.stderr)


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    try:
        return args.func(args)
    except CliError as e:
        emit_fail(args, e.error_code, e.message)
        return e.exit_code
    except Exception as e:  # pragma: no cover
        emit_fail(args, "internal_error", repr(e))
        return EXIT_GENERAL


if __name__ == "__main__":
    sys.exit(main())
