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
    "blocking_count",
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
INT_FIELDS = ("round", "blocking_count")

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
    if key in INT_FIELDS:
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


# ──────────────────────────────────────────────────────────────────────────
# Status consistency (#2, #6)
# ──────────────────────────────────────────────────────────────────────────
def validate_status(status: dict[str, Any]) -> None:
    """Check the written verdict is internally consistent: next_actor matches
    the phase owner, and an `approved` phase carries no blocking findings."""
    normalized = normalize_status(status)
    phase = str(normalized.get("phase"))
    expected = PHASE_OWNER.get(phase)
    next_actor = normalized.get("next_actor") or expected
    if expected is not None and next_actor not in {expected, "none"}:
        raise StatusError(
            f"phase '{phase}' requires next_actor '{expected}', got '{next_actor}'")
    blocking = normalized.get("blocking_count")
    if phase == "approved" and blocking is not None and int(blocking) != 0:
        raise StatusError(
            f"phase 'approved' requires blocking_count == 0, got {blocking}")


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
    raise StatusError("provide --slug or --file")


def cmd_status(args: argparse.Namespace) -> int:
    payload = {"ok": True, "status": extract_status(_status_text(args))}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_validate_turn(args: argparse.Namespace) -> int:
    validate_turn(extract_status(_status_text(args)), actor=args.actor,
                  allowed_phases=parse_phase_args(args.phase))
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def cmd_validate_complete(args: argparse.Namespace) -> int:
    validate_complete(extract_status(_status_text(args)), user_confirmed=args.user_confirmed)
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
    loaded = snapshot_load(_vault_arg(args), args.slug)
    validate_status(extract_status(loaded["text"]))
    print(json.dumps({"ok": True}, ensure_ascii=False))
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
    p_status.set_defaults(func=cmd_status)

    p_turn = sub.add_parser("validate-turn", help="validate actor ownership and lock")
    p_turn.add_argument("--file")
    p_turn.add_argument("--slug")
    p_turn.add_argument("--vault")
    p_turn.add_argument("--actor", required=True, choices=("worker", "reviewer"))
    p_turn.add_argument("--phase", action="append", help="allowed phase; repeat or comma-separate")
    p_turn.set_defaults(func=cmd_validate_turn)

    p_complete = sub.add_parser("validate-complete", help="validate complete gate")
    p_complete.add_argument("--file")
    p_complete.add_argument("--slug")
    p_complete.add_argument("--vault")
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
    p_vstatus.add_argument("--slug", required=True)
    p_vstatus.set_defaults(func=cmd_validate_status)
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
