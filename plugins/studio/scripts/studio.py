#!/usr/bin/env python3
"""studio — deterministic state helper for the living-agent-team workspace.

The producer (main thread) and the ritual brokers own all *behavior*; this CLI
owns the *state* that must not be model-improvised: the mission budget ledger,
the KPI-link rule on the backlog, and the delta-evidence recorded from each run.

Machine state lives in fenced ```json blocks (stdlib json — no hand-rolled YAML
parser, which nested contracts make fragile). Human prose sits outside the fence.

Workspace layout (created by `init`):

    <workspace>/                 default: .studio/
      missions/                  one file per mission contract (+ TEMPLATE.md)
      minutes/                   one file per recorded run (synthesis + delta_log)
      raw/                       raw transcripts (git-ignored, TTL-pruned)
      crew/                      persona files (copied from the plugin on init)
      board.md                   operating board — budget ledger + tracks + runs
      backlog.md                 KPI-linked backlog (every item cites a KPI)

Every subcommand prints one JSON object and uses these exit codes:
    0 ok · 2 usage · 3 no workspace · 4 not found/parse · 6 gate violation
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from execution_control import (
    CONTRACT_DIGEST as EXECUTION_CONTRACT_DIGEST,
    ControlError as ExecutionControlError,
    dispatch as execution_dispatch,
    efficiency_summary as execution_efficiency_summary,
    ensure_execution_state,
    evaluate_golden_case,
    invalidate_evidence as execution_invalidate_evidence,
    load_contract as load_execution_contract,
    record_capability_snapshot,
    record_closeout as execution_record_closeout,
    record_evidence as execution_record_evidence,
    record_result as execution_record_result,
    validate_instance as validate_execution_instance,
)


JSON_FENCE_RE = re.compile(r"```json[ \t]*\n(.*?)\n```", re.DOTALL)
# backlog item: "- [ ] text ... (kpi: <token>)"  — the (kpi: ...) tag is mandatory.
BACKLOG_ITEM_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
# require a non-space first char so "(kpi: )" does not satisfy the link rule
KPI_TAG_RE = re.compile(r"\(kpi:\s*([^)\s][^)]*)\)")

MISSION_REQUIRED = ("mission", "kpi", "done_when", "budget", "gates", "autonomy")
MISSION_ALLOWED = frozenset(MISSION_REQUIRED)
MISSION_BUDGET_REQUIRED = frozenset(("total_tokens", "per_run_default"))
MISSION_KPI_REQUIRED = frozenset(("id", "goal"))
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VALID_ANCHORS = (
    "artifact",
    "acceptance-criteria",
    "risk",
    "rejected-alternative",
    "repro-test",
)
DELTA_ALLOWED = frozenset(
    ("round", "changed_what", "anchor", "evidence", "rejected_alternative", "dry")
)
WORKFLOW_RECEIPT_SCHEMA = "workflow-receipt/v1"
WORKFLOW_RECEIPT_FIELDS = frozenset((
    "schema", "emitter", "workflow", "run_id", "started_at", "finished_at",
    "elapsed_ms", "tokens", "token_coverage", "counters", "quality",
))
REVIEW_CYCLE_SCHEMA = "studio-review-cycle/v1"
REVIEW_EVENT_SCHEMA = "studio-review-event/v1"
ISSUE_EVENT_SCHEMA = "studio-issue-event/v1"
QA_MODES = frozenset(("development", "delta", "full", "final", "integration"))
FULL_QA_REASONS = frozenset((
    "impact-unknown", "shared-contract-changed", "cross-track-change",
    "dependency-surface-changed", "independence-required", "integration-gate",
))
RETRY_CLASSIFICATIONS = frozenset((
    "product-defect", "environment-transient", "tool-unavailable",
    "configuration-error", "criteria-gap",
))
FRESH_CONTEXT_REASONS = frozenset((
    "context-unavailable", "domain-shift", "complexity-boundary",
    "independence-required", "cycle-ledger-invalid",
))
REVIEW_EVENT_TYPES = frozenset((
    "finding-opened", "fix-submitted", "qa-completed", "retry-recorded",
    "handoff-recorded", "evidence-recorded",
))
REVIEW_EVENT_FIELDS = {
    "finding-opened": {"head", "finding"},
    "fix-submitted": {"finding_ids", "change"},
    "qa-completed": {
        "qa_mode", "head", "passed", "checks", "blocked_checks", "evidence_refs",
        "finding_results", "full_qa_reason",
    },
    "retry-recorded": {"classification", "failure", "attempt", "finding_ids"},
    "handoff-recorded": {"fresh_context", "continuation_ref", "reason"},
    "evidence-recorded": {"evidence"},
}

# agent policy config (.studio.yml)
CONFIG_PATH_DEFAULT = ".studio.yml"
WORKSPACE_PATH_DEFAULT = ".studio"
# These are Studio's portable scaffold suggestions, not a claim that every
# runtime supports them. A verified runtime advertisement is authoritative.
ABSTRACT_EFFORTS = ("low", "medium", "high", "xhigh", "max")
AGENT_RUNTIMES = ("claude", "codex")
TOOL_ACTIVATIONS = ("auto", "always", "never")
TOOL_FALLBACKS = ("native", "stop")
WORKER_PROVIDERS = ("native", "task-worker", "task-github")
REVIEWER_PROVIDERS = ("native", "session-review")
ROUTING_PLAN_SCHEMA = "studio-routing-plan/v1"
CAPABILITY_SNAPSHOT_SCHEMA = "studio-capability-snapshot/v1"
RUNTIME_CAPABILITY_SCHEMA = "studio-runtime-capability/v1"
REVIEW_LEASE_SCHEMA = "workflow-review-lease/v1"
REVIEW_EDGE_RESERVATION_SCHEMA = "studio-review-edge-reservation/v1"

CASTS = {
    "idea": {
        "ritual": "brainstorm",
        "crew": ["planner-a", "planner-b", "researcher", "critic"],
        "tool_hints": ["wiki-markdown recall"],
    },
    "product-direction": {
        "ritual": "brainstorm",
        "crew": ["strategist", "planner-a", "planner-b", "product-designer", "critic"],
        "tool_hints": ["wiki-markdown recall"],
    },
    "technical-design": {
        "ritual": "brainstorm",
        "crew": ["architect", "dev", "qa", "critic"],
        "tool_hints": ["wiki-markdown recall"],
    },
    "ui-build": {
        "ritual": "brainstorm",
        "crew": ["product-designer", "visual-designer", "dev", "qa"],
        "tool_hints": [],
    },
    "content": {
        "ritual": "brainstorm",
        "crew": ["strategist", "creator", "visual-designer", "reviewer"],
        "tool_hints": [],
    },
    "implementation": {
        "ritual": "pairing",
        "crew": ["dev", "qa"],
        "tool_hints": [],
    },
    "launch": {
        "ritual": "brainstorm",
        "crew": ["qa", "reviewer", "curator"],
        "tool_hints": ["session-review when independent approval is needed"],
    },
}
CAST_ALIASES = {
    "direction": "product-direction",
    "design": "technical-design",
    "ui": "ui-build",
    "build": "implementation",
    "release": "launch",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def ok(**kw: Any) -> None:
    print(json.dumps({"ok": True, **kw}, ensure_ascii=False))
    sys.exit(0)


def fail(code: int, error_code: str, message: str, **kw: Any) -> None:
    print(
        json.dumps(
            {"ok": False, "error_code": error_code, "message": message, **kw},
            ensure_ascii=False,
        )
    )
    sys.exit(code)


def now_stamp() -> str:
    # SOURCE_DATE_EPOCH lets tests pin the clock; else wall clock.
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        dt = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    else:
        dt = datetime.datetime.now()
    return dt.strftime("%Y%m%d-%H%M%S")


def slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"\s+", "-", (text or "").strip().lower())
    s = re.sub(r"[^0-9a-z가-힣_-]", "", s)
    return s[:limit].strip("-") or "untitled"


def plugin_root() -> Path:
    # STUDIO_ROOT (explicit) wins; else this script's plugin root (scripts/..).
    env = os.environ.get("STUDIO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def workspace(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "workspace", None) or WORKSPACE_PATH_DEFAULT)


def validate_safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value) or value in (".", ".."):
        fail(4, "unsafe_id", f"{field} must be a path-safe identifier, got {value!r}")
    return value


def require_workspace(ws: Path) -> None:
    if not ws.is_dir() or not (ws / "board.md").is_file():
        fail(
            3,
            "no_workspace",
            f"no studio workspace at {ws}/ (run: studio.py init)",
        )


def extract_json_block(text: str) -> Any:
    m = JSON_FENCE_RE.search(text)
    if not m:
        raise ValueError("no ```json block found")
    return json.loads(m.group(1))


def read_json_block(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return extract_json_block(path.read_text(encoding="utf-8"))


def load_json_arg(raw_arg: str | None, label: str) -> Any:
    if raw_arg in (None, "-"):
        raw = sys.stdin.read()
    elif raw_arg.startswith("@"):
        try:
            raw = Path(raw_arg[1:]).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            fail(4, "not_found", f"{label} file not found: {raw_arg[1:]} ({exc})")
    else:
        raw = raw_arg
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(4, "parse", f"{label} is not valid JSON: {exc}")


def atomic_write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(body)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def render_board(board: dict) -> str:
    return (
        "# board — studio operating board\n\n"
        "> Machine state is the fenced json block below (the producer's source "
        "of truth for budget, tracks, and recorded runs). Edit via `studio.py`, "
        "not by hand.\n\n"
        "```json\n" + json.dumps(board, ensure_ascii=False, indent=2) + "\n```\n"
    )


def write_board(ws: Path, board: dict) -> None:
    atomic_write_text(ws / "board.md", render_board(board))


def load_board(ws: Path) -> dict:
    board = read_json_block(ws / "board.md")
    if not isinstance(board, dict):
        fail(4, "bad_board", "board state must be an object")
    return migrate_board(board)


def migrate_board(board: dict) -> dict:
    """Project schema 1 into schema 2 in memory; mutating commands persist it."""
    schema = board.get("schema", 1)
    if schema not in (1, 2):
        fail(4, "unsupported_schema", f"unsupported board schema: {schema}")
    if schema == 1:
        old_tracks = board.get("tracks") or []
        if isinstance(old_tracks, list):
            board["tracks"] = {
                str(track.get("track_id") or track.get("id")): track
                for track in old_tracks
                if isinstance(track, dict) and (track.get("track_id") or track.get("id"))
            }
        elif not isinstance(old_tracks, dict):
            board["tracks"] = {}
        board["schema"] = 2
    board.setdefault("tracks", {})
    board.setdefault("runs", [])
    board.setdefault("review_cycles", {})
    board.setdefault("capability_cache", {})
    board.setdefault("routing_plans", {})
    board.setdefault("review_lease_edges", {})
    board.setdefault("workflow_counters", {"duplicate_prevented": 0})
    budget = board.setdefault("budget", {})
    budget.setdefault("total_tokens", None)
    budget.setdefault("per_run_default", None)
    budget.setdefault("spent_tokens", 0)
    budget.setdefault("reservations", {})
    return board


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@contextlib.contextmanager
def board_transaction(ws: Path):
    """Serialize read-modify-write and replace board.md atomically."""
    lock_path = ws / ".board.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        board = load_board(ws)
        try:
            yield board
        except BaseException:
            raise
        else:
            write_board(ws, board)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def mode_state(board: dict) -> dict:
    return board.setdefault(
        "studio_mode",
        {"active": False, "started_at": None, "ended_at": None},
    )


def read_persona(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(4, "bad_persona", f"persona missing frontmatter: {path}")
    try:
        _, frontmatter, body = text.split("---\n", 2)
    except ValueError:
        fail(4, "bad_persona", f"persona has malformed frontmatter: {path}")
    meta = parse_yaml_subset(frontmatter)
    return {
        "name": meta.get("name") or path.stem,
        "role": meta.get("role"),
        "prior": meta.get("prior"),
        "requested_tools": meta.get("requested_tools") or [],
        "activation": meta.get("activation") or "always",
        "body": body.strip(),
        "path": str(path),
    }


# --------------------------------------------------------------------------- #
# .studio.yml — minimal indented-YAML-subset parser (stdlib only)
#
# Supports arbitrary-key nested mappings and scalar leaves — enough for the
# agent model/effort policy. An empty value opens a nested mapping only when the
# next line is more-indented; otherwise it is a null leaf (e.g. `model:` = inherit).
# No lists, no flow syntax — the config never needs them.
# --------------------------------------------------------------------------- #
def _strip_comment(line: str) -> str:
    out, quote = [], None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(v: str) -> Any:
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
    if (len(v) >= 2) and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        return v


def parse_yaml_subset(text: str) -> dict:
    # collect (indent, key, rawvalue) for non-blank lines
    rows = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        # tabs in the indent would count as 0 (lstrip only strips spaces) and
        # silently collapse nesting — YAML bans tab indentation, so do we.
        if "\t" in line[:len(line) - len(line.lstrip(" \t"))]:
            raise ValueError(f"tab indentation not allowed (use spaces): {raw!r}")
        if ":" not in line:
            raise ValueError(f"invalid config line: {raw!r}")
        key, val = line.strip().split(":", 1)
        rows.append((indent, key.strip(), val.strip()))

    root: dict = {}
    stack = [(-1, root)]

    def next_indent(i: int) -> int | None:
        return rows[i + 1][0] if i + 1 < len(rows) else None

    for i, (indent, key, val) in enumerate(rows):
        while indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError("config indentation underflow")
        parent = stack[-1][1]
        ni = next_indent(i)
        if val == "" and ni is not None and ni > indent:
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(val)
    return root


def render_default_config() -> str:
    return (
        "# .studio.yml — Studio-owned agent policy and optional tool routing.\n"
        "# Native Studio is the default. External tools are considered only when an\n"
        "# uncommented tools.worker/reviewer block explicitly configures one.\n"
        "# Agent resolution (most→least specific): run override > provider ritual\n"
        "#   > common ritual > provider agent > common agent > provider role\n"
        "#   > common role > provider defaults > common defaults > session inherit.\n"
        "# model/effort: runtime-owned ids (blank = inherit). Scaffold effort names\n"
        "# are portable policy hints only; a verified runtime advertisement wins.\n"
        f"# portable effort examples: {','.join(ABSTRACT_EFFORTS)}\n"
        "\n"
        "defaults:\n"
        "  model:            # blank = inherit the session model (recommended default)\n"
        "  effort: medium\n"
        "\n"
        "roles:\n"
        "  strategist:\n"
        "    effort: medium\n"
        "  researcher:\n"
        "    effort: medium\n"
        "  planner-a:\n"
        "    effort: medium\n"
        "  planner-b:\n"
        "    effort: medium\n"
        "  architect:\n"
        "    effort: high\n"
        "  product-designer:\n"
        "    effort: medium\n"
        "  visual-designer:\n"
        "    effort: medium\n"
        "  dev:\n"
        "    effort: high\n"
        "  creator:\n"
        "    effort: medium\n"
        "  qa:\n"
        "    effort: high\n"
        "  reviewer:\n"
        "    effort: high\n"
        "  curator:\n"
        "    effort: medium\n"
        "  critic:\n"
        "    effort: high        # the anti-theatre judge — keep it sharp\n"
        "  summarizer:\n"
        "    effort: low         # neutral compression; cheap is fine\n"
        "\n"
        "agents:\n"
        "  producer:\n"
        "    effort: high\n"
        "\n"
        "# ritual layer = override a role FOR ONE STEP. Only meaningful where the\n"
        "# step differs from the role (brainstorm has distinct steps); pairing steps\n"
        "# are the roles themselves, so set those under roles: instead.\n"
        "rituals:\n"
        "  brainstorm:\n"
        "    diverge:\n"
        "      effort: low       # blind opening proposals are cheap; debate/critic inherit roles\n"
        "\n"
        "# Provider overlays are optional. Only claude and codex are supported initially.\n"
        "# providers:\n"
        "#   claude:\n"
        "#     roles:\n"
        "#       architect:\n"
        "#         model: claude-opus-4-1\n"
        "#   codex:\n"
        "#     agents:\n"
        "#       producer:\n"
        "#         model: gpt-5\n"
        "#\n"
        "# Optional external adapters (examples only; keep commented for native):\n"
        "# tools:\n"
        "#   worker:\n"
        "#     provider: task-worker    # native|task-worker|task-github\n"
        "#     activation: auto         # auto|always|never\n"
        "#     fallback: native         # native|stop\n"
        "#   reviewer:\n"
        "#     provider: session-review # native|session-review\n"
        "#     activation: auto\n"
        "#     fallback: native\n"
    )


def cmd_config(args: argparse.Namespace) -> None:
    path = Path(args.path or CONFIG_PATH_DEFAULT)
    if args.ccmd == "scaffold":
        if path.exists() and not args.force:
            fail(2, "exists", f"{path} already exists (use --force)")
        path.write_text(render_default_config(), encoding="utf-8")
        ok(path=str(path), created=True)
    # get / validate / resolve all need to parse
    if not path.is_file():
        if args.ccmd == "get":
            ok(path=str(path), present=False, config={})  # absent ⇒ all inherit
        if args.ccmd == "resolve":
            cfg = {}
        else:
            fail(3, "no_config", f"no config at {path} (run: studio.py config scaffold)")
    else:
        try:
            cfg = parse_yaml_subset(path.read_text(encoding="utf-8"))
        except ValueError as e:
            fail(4, "parse", f"{path}: {e}")

    problems = _validate_config(cfg)
    # both validate AND get hard-fail on error-severity problems, so a bad
    # effort can never reach the brokers through the producer's `get` step.
    if any(p["severity"] == "error" for p in problems):
        fail(6, "invalid_config", "config has errors", problems=problems)
    if args.ccmd == "validate":
        ok(path=str(path), problems=problems)
    if args.ccmd == "resolve":
        raw_runtime_capability = (
            load_json_arg(args.runtime_capability, "runtime capability")
            if args.runtime_capability else None
        )
        runtime = args.agent_runtime or (
            raw_runtime_capability.get("runtime")
            if isinstance(raw_runtime_capability, dict) else None
        )
        runtime_capability = _canonical_runtime_capability(
            raw_runtime_capability, runtime, raw_runtime_capability.get("runtime")
            if isinstance(raw_runtime_capability, dict) else None,
        )
        run_override = {"model": args.model, "effort": args.effort}
        profile = resolve_agent_profile(
            cfg, runtime, args.role, args.agent, args.ritual, args.step,
            run_override, runtime_capability,
        )
        unsupported = _unsupported_profile_fields(profile)
        if unsupported:
            fail(6, "unsupported_runtime_profile", "resolved agent profile is not advertised by the verified runtime", problems=unsupported)
        ok(path=str(path), present=path.is_file(), profile=profile, problems=problems)
    ok(path=str(path), present=True, config=cfg, problems=problems)


def _validate_config(cfg: dict) -> list[dict]:
    problems: list[dict] = []

    if not isinstance(cfg, dict):
        return [{"severity": "error", "where": "config", "msg": "must be a mapping"}]

    allowed_top = {"defaults", "roles", "agents", "rituals", "providers", "tools"}
    for key in sorted(set(cfg) - allowed_top):
        problems.append({"severity": "error", "where": key, "msg": "unknown top-level key"})

    def check_mefr(block: dict, where: str) -> None:
        if not isinstance(block, dict):
            problems.append({"severity": "error", "where": where, "msg": "must be a mapping"})
            return
        for key in sorted(set(block) - {"model", "effort"}):
            problems.append({"severity": "error", "where": f"{where}.{key}", "msg": "unknown agent policy key"})
        m = block.get("model")
        if m not in (None, "") and (not isinstance(m, str) or not m.strip()):
            problems.append({"severity": "error", "where": where, "msg": "model must be a provider model id string or null"})
        e = block.get("effort")
        if e not in (None, "") and (not isinstance(e, str) or not e.strip()):
            problems.append({"severity": "error", "where": where, "msg": "effort must be a runtime effort id string or null"})

    def check_policy(policy: Any, where: str) -> None:
        if not isinstance(policy, dict):
            problems.append({"severity": "error", "where": where, "msg": "must be a mapping"})
            return
        allowed = {"defaults", "roles", "agents", "rituals"}
        for key in sorted(set(policy) - allowed):
            problems.append({"severity": "error", "where": f"{where}.{key}", "msg": "unknown provider policy key"})
        if "defaults" in policy:
            check_mefr(policy["defaults"], f"{where}.defaults" if where else "defaults")
        for collection in ("roles", "agents"):
            blocks = policy[collection] if collection in policy else {}
            if not isinstance(blocks, dict):
                problems.append({"severity": "error", "where": f"{where}.{collection}".strip("."), "msg": "must be a mapping"})
                continue
            for name, blk in blocks.items():
                check_mefr(blk, f"{where}.{collection}.{name}".strip("."))
        rituals = policy["rituals"] if "rituals" in policy else {}
        if not isinstance(rituals, dict):
            problems.append({"severity": "error", "where": f"{where}.rituals".strip("."), "msg": "must be a mapping"})
        else:
            for ritual, steps in rituals.items():
                if not isinstance(steps, dict):
                    problems.append({"severity": "error", "where": f"{where}.rituals.{ritual}".strip("."), "msg": "must be a mapping of steps"})
                    continue
                for step, blk in steps.items():
                    check_mefr(blk, f"{where}.rituals.{ritual}.{step}".strip("."))

    check_policy({key: cfg[key] for key in ("defaults", "roles", "agents", "rituals") if key in cfg}, "")
    providers = cfg["providers"] if "providers" in cfg else {}
    if not isinstance(providers, dict):
        problems.append({"severity": "error", "where": "providers", "msg": "must be a mapping"})
    else:
        for provider in sorted(set(providers) - set(AGENT_RUNTIMES)):
            problems.append({"severity": "error", "where": f"providers.{provider}", "msg": "unsupported provider profile"})
        for provider in AGENT_RUNTIMES:
            if provider in providers:
                check_policy(providers[provider], f"providers.{provider}")

    tools = cfg["tools"] if "tools" in cfg else {}
    if not isinstance(tools, dict):
        problems.append({"severity": "error", "where": "tools", "msg": "must be a mapping"})
    else:
        for key in sorted(set(tools) - {"worker", "reviewer"}):
            problems.append({"severity": "error", "where": f"tools.{key}", "msg": "unknown tool kind"})
        for kind, providers_allowed in (("worker", WORKER_PROVIDERS), ("reviewer", REVIEWER_PROVIDERS)):
            if kind not in tools:
                continue
            block = tools[kind]
            where = f"tools.{kind}"
            if not isinstance(block, dict):
                problems.append({"severity": "error", "where": where, "msg": "must be a mapping"})
                continue
            if set(block) != {"provider", "activation", "fallback"}:
                problems.append({"severity": "error", "where": where, "msg": "must contain exactly provider, activation, fallback"})
            if block.get("provider") not in providers_allowed:
                problems.append({"severity": "error", "where": f"{where}.provider", "msg": f"must be one of {', '.join(providers_allowed)}"})
            if block.get("activation") not in TOOL_ACTIVATIONS:
                problems.append({"severity": "error", "where": f"{where}.activation", "msg": f"must be one of {', '.join(TOOL_ACTIVATIONS)}"})
            if block.get("fallback") not in TOOL_FALLBACKS:
                problems.append({"severity": "error", "where": f"{where}.fallback", "msg": f"must be one of {', '.join(TOOL_FALLBACKS)}"})
    return problems


def _policy_value(block: Any, field: str) -> Any:
    if not isinstance(block, dict):
        return None
    value = block.get(field)
    return value if value not in (None, "") else None


def resolve_agent_profile(
    cfg: dict, runtime: str | None, role: str | None, agent: str | None,
    ritual: str | None, step: str | None, run_override: dict | None = None,
    runtime_capability: dict | None = None,
) -> dict:
    """Resolve model/effort independently using the documented ten layers."""
    provider = (cfg.get("providers") or {}).get(runtime, {}) if runtime else {}
    common_ritual = ((cfg.get("rituals") or {}).get(ritual, {}) or {}).get(step, {}) if ritual and step else {}
    provider_ritual = ((provider.get("rituals") or {}).get(ritual, {}) or {}).get(step, {}) if ritual and step else {}
    layers = [
        ("run-override", run_override or {}),
        ("provider-ritual", provider_ritual),
        ("common-ritual", common_ritual),
        ("provider-agent", (provider.get("agents") or {}).get(agent, {}) if agent else {}),
        ("common-agent", (cfg.get("agents") or {}).get(agent, {}) if agent else {}),
        ("provider-role", (provider.get("roles") or {}).get(role, {}) if role else {}),
        ("common-role", (cfg.get("roles") or {}).get(role, {}) if role else {}),
        ("provider-defaults", provider.get("defaults") or {}),
        ("common-defaults", cfg.get("defaults") or {}),
    ]
    resolved, sources = {}, {}
    for field in ("model", "effort"):
        for source, block in layers:
            value = _policy_value(block, field)
            if value is not None:
                resolved[field] = value
                sources[field] = source
                break
        else:
            resolved[field] = None
            sources[field] = "session-inherit"
    profile = {
        "runtime": runtime,
        "role": role,
        "agent": agent,
        "ritual": ritual,
        "step": step,
        **resolved,
        "sources": sources,
    }
    profile["validation"] = _profile_validation(profile, runtime_capability)
    return profile


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> None:
    ws = workspace(args)
    if (ws / "board.md").is_file() and not args.force:
        fail(2, "exists", f"workspace already at {ws} (use --force to re-scaffold)")

    for sub in (
        "missions",
        "minutes",
        "raw",
        "crew",
        "context/items",
        "context/bundles",
        "context/deltas",
        "context/outbox",
    ):
        (ws / sub).mkdir(parents=True, exist_ok=True)

    # copy shipped persona templates into the live crew roster
    src_crew = plugin_root() / "crew"
    copied = []
    if src_crew.is_dir():
        for f in sorted(src_crew.glob("*.md")):
            dst = ws / "crew" / f.name
            if not dst.exists() or args.force:
                shutil.copyfile(f, dst)
                copied.append(f.name)

    # mission template
    tpl = plugin_root() / "templates" / "mission.md"
    if tpl.is_file():
        shutil.copyfile(tpl, ws / "missions" / "TEMPLATE.md")

    # backlog
    (ws / "backlog.md").write_text(
        "# backlog\n\n"
        "> Every item MUST cite a mission KPI as `(kpi: <id>)` — enforced by "
        "`studio.py backlog check`. No KPI link, no work.\n\n"
        "- [ ] example item (kpi: k1)\n",
        encoding="utf-8",
    )

    # raw transcripts are TTL-pruned scratch, never committed
    (ws / "raw" / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")

    # board ledger (budget filled from the active mission later)
    write_board(
        ws,
        {
            "schema": 2,
            "studio_mode": {"active": False, "started_at": None, "ended_at": None},
            "budget": {
                "total_tokens": None,
                "per_run_default": None,
                "spent_tokens": 0,
                "reservations": {},
            },
            "tracks": {},
            "runs": [],
        },
    )
    ok(workspace=str(ws), crew_copied=copied, created=True)


# --------------------------------------------------------------------------- #
# budget — set the ledger caps (so the exhausted → paused gate is reachable
# without hand-editing board.md; the producer calls this after the owner gates
# the mission contract, copying the contract's budget into the live ledger).
# --------------------------------------------------------------------------- #
def cmd_budget(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    with board_transaction(ws) as board:
        bud = board.setdefault("budget", {"spent_tokens": 0, "reservations": {}})
        bud.setdefault("reservations", {})
        changed = {}
        if args.set_total is not None:
            if args.set_total < 0:
                fail(2, "bad_budget", "total must be >= 0")
            bud["total_tokens"] = args.set_total
            changed["total_tokens"] = args.set_total
        if args.set_per_run is not None:
            if args.set_per_run < 0:
                fail(2, "bad_budget", "per_run must be >= 0")
            bud["per_run_default"] = args.set_per_run
            changed["per_run_default"] = args.set_per_run
        # clearing paused if we just raised the cap above spend
        total = bud.get("total_tokens")
        if total is not None and int(bud.get("spent_tokens") or 0) <= total:
            board.pop("mission_state", None)
    ok(budget=bud, changed=changed)


def _budget_reservations(budget: dict) -> dict:
    reservations = budget.setdefault("reservations", {})
    if not isinstance(reservations, dict):
        fail(4, "bad_budget", "budget.reservations must be an object")
    return reservations


def _active_reserved_tokens(reservations: dict) -> int:
    return sum(
        int(item.get("tokens") or 0)
        for item in reservations.values()
        if item.get("status") in ("reserved", "dispatched")
    )


def cmd_budget_lifecycle(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    reservation_id = validate_safe_id(args.reservation_id, "reservation_id")
    lease_id = validate_safe_id(args.lease_id, "lease_id")

    with board_transaction(ws) as board:
        budget = board.setdefault("budget", {"spent_tokens": 0, "reservations": {}})
        reservations = _budget_reservations(budget)
        current = reservations.get(reservation_id)
        changed = False

        if args.lifecycle == "reserve":
            if args.tokens is None or args.tokens < 0:
                fail(2, "bad_budget", "reserve tokens must be >= 0")
            desired = {
                "reservation_id": reservation_id,
                "lease_id": lease_id,
                "tokens": args.tokens,
                "status": "reserved",
            }
            if current is not None:
                if (
                    current.get("lease_id") == lease_id
                    and current.get("tokens") == args.tokens
                ):
                    ok(reservation=current, changed=False)
                fail(6, "reservation_conflict", f"reservation {reservation_id} already exists with different data")
            total = budget.get("total_tokens")
            committed = int(budget.get("spent_tokens") or 0) + _active_reserved_tokens(reservations)
            if total is not None and committed + args.tokens > total:
                fail(6, "budget_exceeded", "reservation would exceed total token budget")
            reservations[reservation_id] = desired
            current = desired
            changed = True

        else:
            if current is None:
                fail(4, "reservation_not_found", f"unknown reservation: {reservation_id}")
            if current.get("lease_id") != lease_id:
                fail(6, "stale_lease", f"reservation {reservation_id} is fenced by another lease")

            if args.lifecycle == "dispatch":
                if current.get("status") == "dispatched":
                    ok(reservation=current, changed=False)
                if current.get("status") != "reserved":
                    fail(6, "invalid_budget_transition", f"cannot dispatch from {current.get('status')}")
                current["status"] = "dispatched"
                changed = True
            elif args.lifecycle == "settle":
                if args.tokens is None or args.tokens < 0:
                    fail(2, "bad_budget", "settle tokens must be >= 0")
                if current.get("status") == "settled":
                    if current.get("settled_tokens") == args.tokens:
                        ok(reservation=current, changed=False)
                    fail(6, "reservation_conflict", "settled token count cannot change")
                if current.get("status") != "dispatched":
                    fail(6, "invalid_budget_transition", f"cannot settle from {current.get('status')}")
                current["status"] = "settled"
                current["settled_tokens"] = args.tokens
                budget["spent_tokens"] = int(budget.get("spent_tokens") or 0) + args.tokens
                changed = True
            elif args.lifecycle == "release":
                if current.get("status") == "released":
                    ok(reservation=current, changed=False)
                if current.get("status") not in ("reserved", "dispatched"):
                    fail(6, "invalid_budget_transition", f"cannot release from {current.get('status')}")
                current["status"] = "released"
                changed = True
            else:  # argparse guarantees this; keep the state machine explicit.
                fail(2, "bad_budget_action", f"unknown lifecycle action: {args.lifecycle}")

    ok(reservation=current, changed=changed, spent_tokens=budget.get("spent_tokens", 0))


# --------------------------------------------------------------------------- #
# mission validate
# --------------------------------------------------------------------------- #
def cmd_mission_validate(args: argparse.Namespace) -> None:
    path = Path(args.path)
    try:
        contract = read_json_block(path)
    except FileNotFoundError:
        fail(4, "not_found", f"mission file not found: {path}")
    except ValueError as e:
        fail(4, "parse", f"{path}: {e}")

    if not isinstance(contract, dict):
        fail(6, "invalid_mission", "mission contract must be an object", problems=["contract must be an object"])
    problems = [f"missing key: {key}" for key in MISSION_REQUIRED if key not in contract]
    problems += [f"unknown key: {key}" for key in sorted(set(contract) - MISSION_ALLOWED)]

    for key in ("mission", "done_when", "autonomy"):
        if key in contract and (not isinstance(contract[key], str) or not contract[key].strip()):
            problems.append(f"{key} must be a non-empty string")

    kpi = contract.get("kpi")
    kpi_ids = []
    if kpi is not None:
        if not isinstance(kpi, list) or not kpi:
            problems.append("kpi must be a non-empty list")
        else:
            for index, item in enumerate(kpi):
                if not isinstance(item, dict):
                    problems.append(f"kpi[{index}] must be an object")
                    continue
                if set(item) != MISSION_KPI_REQUIRED:
                    problems.append(f"kpi[{index}] must contain exactly id and goal")
                kid = item.get("id")
                if not isinstance(kid, str) or not SAFE_ID_RE.fullmatch(kid):
                    problems.append(f"kpi[{index}].id must be a path-safe non-empty string")
                else:
                    kpi_ids.append(kid)
                if not isinstance(item.get("goal"), str) or not item.get("goal", "").strip():
                    problems.append(f"kpi[{index}].goal must be a non-empty string")
            if len(kpi_ids) != len(set(kpi_ids)):
                problems.append("kpi ids must be unique")

    budget = contract.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or set(budget) != MISSION_BUDGET_REQUIRED:
            problems.append("budget must contain exactly total_tokens and per_run_default")
        else:
            for key in MISSION_BUDGET_REQUIRED:
                value = budget.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    problems.append(f"budget.{key} must be a non-negative integer")
            if not problems and budget["per_run_default"] > budget["total_tokens"]:
                problems.append("budget.per_run_default must not exceed total_tokens")

    gates = contract.get("gates")
    if gates is not None and (
        not isinstance(gates, list)
        or any(not isinstance(gate, str) or not gate.strip() for gate in gates)
        or len(gates) != len(set(gates))
    ):
        problems.append("gates must be a list of unique non-empty strings")
    if problems:
        fail(6, "invalid_mission", "; ".join(problems), problems=problems)
    ok(
        path=str(path),
        kpi_ids=kpi_ids,
        budget=budget,
    )


# --------------------------------------------------------------------------- #
# backlog check — the KPI-link rule
# --------------------------------------------------------------------------- #
def cmd_backlog_check(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    path = ws / "backlog.md"
    if not path.is_file():
        fail(4, "not_found", f"no backlog at {path}")

    violations = []
    items = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = BACKLOG_ITEM_RE.match(line)
        if not m:
            continue
        items += 1
        text = m.group(1)
        if not KPI_TAG_RE.search(text):
            violations.append({"line": lineno, "text": text.strip()})

    if violations:
        fail(
            6,
            "kpi_link_missing",
            f"{len(violations)} backlog item(s) missing a (kpi: <id>) tag",
            violations=violations,
            items=items,
        )
    ok(items=items, violations=[])


# --------------------------------------------------------------------------- #
# run record — write minutes + update the budget ledger
# --------------------------------------------------------------------------- #
def _load_run_output(args: argparse.Namespace) -> dict:
    if args.json == "-" or args.json is None:
        raw = sys.stdin.read()
    elif args.json.startswith("@"):
        try:
            raw = Path(args.json[1:]).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as e:
            fail(4, "not_found", f"run output file not found: {args.json[1:]} ({e})")
    else:
        raw = args.json
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(4, "parse", f"run output is not valid JSON: {e}")
    if not isinstance(obj, dict):
        fail(2, "bad_output", "run output must be a JSON object")
    # a broker precondition failure returns {error: ...} — refuse to record it as
    # a run (else it would count as a zero-delta run and poison the theatre tally)
    if obj.get("error"):
        fail(4, "broker_error", f"run output is a broker error, not a run: {obj['error']}")
    return obj


def _validate_delta_log(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["delta_log must be a list"]
    problems = []
    for index, delta in enumerate(value):
        if not isinstance(delta, dict):
            problems.append(f"delta_log[{index}] must be an object")
            continue
        unknown = sorted(set(delta) - DELTA_ALLOWED)
        if unknown:
            problems.append(f"delta_log[{index}] has unknown keys: {', '.join(unknown)}")
        round_value = delta.get("round")
        if isinstance(round_value, bool) or not isinstance(round_value, int) or round_value < 1:
            problems.append(f"delta_log[{index}].round must be a positive integer")
        if not isinstance(delta.get("changed_what"), str) or not delta.get("changed_what", "").strip():
            problems.append(f"delta_log[{index}].changed_what must be a non-empty string")
        if "dry" in delta and not isinstance(delta["dry"], bool):
            problems.append(f"delta_log[{index}].dry must be boolean")
        if not delta.get("dry"):
            if delta.get("anchor") not in VALID_ANCHORS:
                problems.append(f"delta_log[{index}].anchor must be a valid anchor")
            if not isinstance(delta.get("evidence"), str) or not delta.get("evidence", "").strip():
                problems.append(f"delta_log[{index}].evidence is required for non-dry deltas")
        for key in ("anchor", "evidence", "rejected_alternative"):
            if key in delta and delta[key] is not None and not isinstance(delta[key], str):
                problems.append(f"delta_log[{index}].{key} must be a string when present")
    return problems


def _pairing_readiness_problems(out: dict) -> list[str]:
    problems = []
    ready = out.get("readyForIntegration")
    if not isinstance(ready, bool):
        return ["pairing readyForIntegration must be boolean"]
    changed = out.get("changedFiles")
    verification = out.get("verification")
    blocked = out.get("blockedChecks")
    verdict = out.get("verdict")
    if not isinstance(changed, list) or not changed or any(not isinstance(p, str) or not p.strip() for p in changed):
        problems.append("pairing changedFiles must contain at least one repo-relative path")
    if not isinstance(verification, list) or not verification:
        problems.append("pairing verification must contain at least one executed check")
    else:
        malformed = any(
            not isinstance(item, dict)
            or not isinstance(item.get("command"), str)
            or not item.get("command", "").strip()
            or not isinstance(item.get("result"), str)
            for item in verification
        )
        passed = any(
            isinstance(item, dict)
            and re.match(r"^pass(?:\b|:)", item.get("result", ""), re.IGNORECASE)
            for item in verification
        )
        if malformed or not passed:
            problems.append("pairing verification entries need commands and at least one pass result")
    if not isinstance(blocked, list):
        problems.append("pairing blockedChecks must be a list")
    elif blocked:
        problems.append("pairing blockedChecks must be empty")
    if not isinstance(verdict, dict) or verdict.get("alive") is not True:
        problems.append("pairing verdict.alive must be true")
    if isinstance(verdict, dict) and int(verdict.get("open_count") or 0) != 0:
        problems.append("pairing verdict.open_count must be zero")
    return problems if ready else []


def _receipt_time(value: Any, field: str) -> datetime.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(datetime.timezone.utc)


def workflow_receipt_problems(receipt: Any) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    problems = []
    if set(receipt) != WORKFLOW_RECEIPT_FIELDS:
        problems.append("receipt fields do not match workflow-receipt/v1")
    if receipt.get("schema") != WORKFLOW_RECEIPT_SCHEMA:
        problems.append("receipt.schema must be workflow-receipt/v1")
    if receipt.get("emitter") != "studio":
        problems.append("receipt.emitter must be studio")
    if not isinstance(receipt.get("workflow"), str) or not receipt.get("workflow", "").strip():
        problems.append("receipt.workflow must be a non-empty string")
    receipt_run_id = receipt.get("run_id")
    if not isinstance(receipt_run_id, str) or not SAFE_ID_RE.fullmatch(receipt_run_id):
        problems.append("receipt.run_id must be path-safe")
    try:
        started = _receipt_time(receipt.get("started_at"), "receipt.started_at")
        finished = _receipt_time(receipt.get("finished_at"), "receipt.finished_at")
        expected_elapsed = int((finished - started).total_seconds() * 1000)
        if expected_elapsed < 0 or receipt.get("elapsed_ms") != expected_elapsed:
            problems.append("receipt.elapsed_ms must match its timestamps")
    except ValueError as exc:
        problems.append(str(exc))
    tokens = receipt.get("tokens")
    coverage = receipt.get("token_coverage")
    if tokens is None:
        if coverage != "unavailable":
            problems.append("receipt tokens:null requires token_coverage unavailable")
    elif isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        problems.append("receipt.tokens must be a non-negative integer or null")
    elif coverage != "exact":
        problems.append("Studio measured tokens require token_coverage exact")
    counters = receipt.get("counters")
    if not isinstance(counters, dict) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counters.values()
    ):
        problems.append("receipt.counters must contain non-negative integers")
    if not isinstance(receipt.get("quality"), dict):
        problems.append("receipt.quality must be an object")
    return problems


def _append_receipt(path: str, receipt: dict) -> str | None:
    try:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        return f"receipt append failed: {exc}"
    return None


def cmd_run_record(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    out = _load_run_output(args)

    ritual = out.get("ritual", "unknown")
    # id precedence: explicit output field > --id > clock+random (random suffix
    # guards against two runs in the same second with the same ritual colliding).
    run_id = validate_safe_id((
        out.get("run_id")
        or args.id
        or f"RUN-{now_stamp()}-{slugify(ritual)}-{os.urandom(3).hex()}"
    ), "run_id")
    if not isinstance(ritual, str) or not ritual.strip():
        fail(6, "invalid_run_output", "ritual must be a non-empty string")
    cost = out.get("cost") or {}
    if not isinstance(cost, dict):
        fail(6, "invalid_run_output", "cost must be an object")
    cost_tokens = cost.get("tokens")
    if cost_tokens is not None and (
        isinstance(cost_tokens, bool) or not isinstance(cost_tokens, int) or cost_tokens < 0
    ):
        fail(4, "bad_cost", f"cost.tokens must be a non-negative integer or null, got {cost_tokens!r}")
    expected_coverage = "unavailable" if cost_tokens is None else "exact"
    if cost.get("token_coverage") not in (None, expected_coverage):
        fail(4, "bad_cost", f"cost.token_coverage must be {expected_coverage}")
    cost_elapsed = cost.get("elapsed_ms")
    if cost_elapsed is not None and (
        isinstance(cost_elapsed, bool) or not isinstance(cost_elapsed, int) or cost_elapsed < 0
    ):
        fail(4, "bad_cost", "cost.elapsed_ms must be a non-negative integer")
    receipt = out.get("receipt")
    if receipt is not None:
        receipt_problems = workflow_receipt_problems(receipt)
        if receipt.get("run_id") != run_id:
            receipt_problems.append("receipt.run_id must match the recorded run_id")
        if receipt.get("tokens") != cost_tokens:
            receipt_problems.append("receipt.tokens must match cost.tokens")
        if cost_elapsed is not None and receipt.get("elapsed_ms") != cost_elapsed:
            receipt_problems.append("receipt.elapsed_ms must match cost.elapsed_ms")
        if receipt_problems:
            fail(6, "invalid_run_output", "; ".join(receipt_problems), problems=receipt_problems)
    verdict = out.get("verdict") or {}
    if not isinstance(verdict, dict):
        fail(6, "invalid_run_output", "verdict must be an object")
    delta_log = out.get("delta_log", [])
    problems = _validate_delta_log(delta_log)
    if ritual == "pairing":
        problems += _pairing_readiness_problems(out)
    if problems:
        fail(6, "invalid_run_output", "; ".join(problems), problems=problems)
    aborted = bool(out.get("aborted"))
    review_cycle_delta = out.get("review_cycle_delta")
    if review_cycle_delta is not None:
        review_cycle_delta = _review_cycle_delta(review_cycle_delta)

    # count real (non-dry) deltas with a valid anchor — the evidence tally.
    valid_deltas = [
        d
        for d in delta_log
        if isinstance(d, dict)
        and not d.get("dry")
        and d.get("anchor") in VALID_ANCHORS
    ]

    # ---- write minutes (synthesis + delta_log only; raw transcript stays in raw/)
    minutes_dir = (ws / "minutes").resolve()
    minutes_path = ws / "minutes" / f"{run_id}.md"
    if minutes_path.resolve().parent != minutes_dir:
        fail(4, "unsafe_id", "run_id escapes the minutes directory")
    body = _render_minutes(run_id, out, valid_deltas, aborted)

    # ---- update board ledger (idempotent on run_id: re-recording the same run
    # replaces its entry and its cost, never double-counts the budget)
    entry = {
        "run_id": run_id,
        "ritual": ritual,
        "track": out.get("track") or getattr(args, "track", None),
        "verdict": verdict,
        "cost_tokens": cost_tokens,
        "cost_elapsed_ms": cost_elapsed if cost_elapsed is not None else (
            receipt.get("elapsed_ms") if receipt is not None else None
        ),
        "valid_deltas": len(valid_deltas),
        "aborted": aborted,
        "minutes": str(minutes_path),
    }
    if review_cycle_delta is not None:
        entry["review_cycle_id"] = review_cycle_delta["cycle_id"]
    if receipt is not None:
        entry["receipt"] = receipt
    issue_events = []
    with board_transaction(ws) as board:
        if review_cycle_delta is not None:
            cycle = _review_cycle_from_board(board, review_cycle_delta["cycle_id"])
            for review_event in review_cycle_delta["events"]:
                cycle, _, issue_event = _apply_review_event(cycle, review_event)
                if issue_event is not None:
                    issue_events.append(issue_event)
        bud = board.setdefault("budget", {"spent_tokens": 0, "reservations": {}})
        runs = board.setdefault("runs", [])
        if not isinstance(runs, list):
            fail(4, "bad_board", "board.runs must be a list")
        spent = int(bud.get("spent_tokens") or 0)
        prior = next((r for r in runs if r.get("run_id") == run_id), None)
        if prior is not None:
            prior_tokens = prior.get("cost_tokens")
            if cost_tokens is not None and prior_tokens is not None:
                spent -= int(prior_tokens)   # undo the old known cost
            board["runs"] = [r for r in runs if r.get("run_id") != run_id]
        board["runs"].append(entry)
        bud["spent_tokens"] = spent + (cost_tokens if cost_tokens is not None else 0)
        total = bud.get("total_tokens")
        exceeded = total is not None and bud["spent_tokens"] > total
        if exceeded:
            board["mission_state"] = "paused"  # budget exhausted → owner gate to resume
        atomic_write_text(minutes_path, body)

    warnings = []
    if getattr(args, "receipt_log", None):
        if receipt is None:
            warnings.append("receipt append skipped: run output has no receipt")
        else:
            append_warning = _append_receipt(args.receipt_log, receipt)
            if append_warning:
                warnings.append(append_warning)
    ok(
        run_id=run_id,
        minutes=str(minutes_path),
        valid_deltas=len(valid_deltas),
        aborted=aborted,
        spent_tokens=bud["spent_tokens"],
        budget_total=total,
        budget_exceeded=exceeded,
        receipt=receipt,
        review_cycle_id=review_cycle_delta["cycle_id"] if review_cycle_delta else None,
        issue_events=issue_events,
        warnings=warnings,
    )


def _render_minutes(run_id: str, out: dict, valid_deltas: list, aborted: bool) -> str:
    v = out.get("verdict") or {}
    lines = [
        f"# minutes — {run_id}",
        "",
        f"- ritual: {out.get('ritual', 'unknown')}",
        f"- participants: {', '.join(out.get('participants') or []) or 'n/a'}",
        f"- verdict: alive={v.get('alive')} — {v.get('reason', '')}",
        f"- cost: {json.dumps(out.get('cost') or {}, ensure_ascii=False)}",
        f"- valid_deltas: {len(valid_deltas)}"
        + ("  (ABORTED — evidence marked aborted, do not merge into synthesis)" if aborted else ""),
        "",
        "## synthesis",
        "",
        str(out.get("synthesis") or "_none_"),
        "",
        "## minority",
        "",
        str(out.get("minority") or "none"),
        "",
        "## delta_log",
        "",
    ]
    for d in out.get("delta_log") or []:
        if not isinstance(d, dict):
            continue
        tag = "DRY" if d.get("dry") else (d.get("anchor") or "?")
        if aborted:
            tag = f"ABORTED/{tag}"
        lines.append(
            f"- [round {d.get('round', '?')}] ({tag}) {d.get('changed_what', '')}"
            + (f" — evidence: {d['evidence']}" if d.get("evidence") else "")
            + (
                f" — rejected: {d['rejected_alternative']}"
                if d.get("rejected_alternative")
                else ""
            )
        )
    props = out.get("proposals") or []
    if props:
        lines += ["", "## proposals (→ backlog, KPI-link before adding)", ""]
        lines += [f"- {p}" for p in props]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# quality — hard floors first, weighted utility only for complete candidates
# --------------------------------------------------------------------------- #
QUALITY_PLAN_REQUIRED = frozenset(("schema", "id", "criteria", "utility_weights"))
QUALITY_CRITERION_REQUIRED = frozenset(("id", "kind", "weight", "floor", "measure"))
UTILITY_KEYS = frozenset(("quality", "tokens", "elapsed", "avoidable_owner_question"))
TELEMETRY_KEYS = frozenset(("tokens", "elapsed_ms", "avoidable_owner_questions"))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_quality_plan(plan: Any) -> list[str]:
    if not isinstance(plan, dict):
        return ["QualityPlan must be an object"]
    problems = []
    if set(plan) != QUALITY_PLAN_REQUIRED:
        problems.append("QualityPlan must contain exactly schema, id, criteria, utility_weights")
    if plan.get("schema") != 1:
        problems.append("QualityPlan.schema must be 1")
    if not isinstance(plan.get("id"), str) or not SAFE_ID_RE.fullmatch(plan.get("id", "")):
        problems.append("QualityPlan.id must be a path-safe identifier")
    criteria = plan.get("criteria")
    criterion_ids = []
    kinds = set()
    if not isinstance(criteria, list) or not criteria:
        problems.append("QualityPlan.criteria must be a non-empty list")
    else:
        for index, criterion in enumerate(criteria):
            if not isinstance(criterion, dict) or set(criterion) != QUALITY_CRITERION_REQUIRED:
                problems.append(f"criteria[{index}] must contain exactly id, kind, weight, floor, measure")
                continue
            criterion_id = criterion.get("id")
            if not isinstance(criterion_id, str) or not SAFE_ID_RE.fullmatch(criterion_id):
                problems.append(f"criteria[{index}].id must be path-safe")
            else:
                criterion_ids.append(criterion_id)
            if criterion.get("kind") not in ("artifact", "context"):
                problems.append(f"criteria[{index}].kind must be artifact or context")
            else:
                kinds.add(criterion["kind"])
            for key in ("weight", "floor"):
                value = criterion.get(key)
                if not _number(value) or not 0 <= value <= 1:
                    problems.append(f"criteria[{index}].{key} must be between 0 and 1")
            if not isinstance(criterion.get("measure"), str) or not criterion.get("measure", "").strip():
                problems.append(f"criteria[{index}].measure must be a non-empty string")
        if len(criterion_ids) != len(set(criterion_ids)):
            problems.append("criterion ids must be unique")
        if kinds != {"artifact", "context"}:
            problems.append("QualityPlan requires both artifact and context criteria")

    weights = plan.get("utility_weights")
    if not isinstance(weights, dict) or set(weights) != UTILITY_KEYS:
        problems.append("utility_weights must contain quality, tokens, elapsed, avoidable_owner_question")
    else:
        if any(not _number(value) or value < 0 for value in weights.values()):
            problems.append("utility weights must be non-negative numbers")
        elif not all(weights["quality"] > weights[key] for key in UTILITY_KEYS - {"quality"}):
            problems.append("quality must have the highest utility weight")
    return problems


def evaluate_quality(plan: dict, evidence_refs: Any, telemetry: Any) -> dict:
    problems = validate_quality_plan(plan)
    if problems:
        fail(6, "invalid_quality_plan", "; ".join(problems), problems=problems)
    if not isinstance(evidence_refs, list):
        fail(6, "invalid_evidence", "evidence_refs must be a list")
    evidence_problems = []
    evidence_by_criterion: dict[str, list[dict]] = {}
    for index, evidence in enumerate(evidence_refs):
        if not isinstance(evidence, dict) or set(evidence) != {"criterion_id", "ref", "score"}:
            evidence_problems.append(f"evidence_refs[{index}] must contain criterion_id, ref, score")
            continue
        if not isinstance(evidence.get("criterion_id"), str):
            evidence_problems.append(f"evidence_refs[{index}].criterion_id must be a string")
        if not isinstance(evidence.get("ref"), str) or not evidence.get("ref", "").strip():
            evidence_problems.append(f"evidence_refs[{index}].ref must be non-empty")
        if not _number(evidence.get("score")) or not 0 <= evidence.get("score", -1) <= 1:
            evidence_problems.append(f"evidence_refs[{index}].score must be between 0 and 1")
        if not evidence_problems or all(not item.startswith(f"evidence_refs[{index}]") for item in evidence_problems):
            evidence_by_criterion.setdefault(evidence["criterion_id"], []).append(evidence)
    if evidence_problems:
        fail(6, "invalid_evidence", "; ".join(evidence_problems), problems=evidence_problems)

    results = []
    weighted_score = 0.0
    total_weight = 0.0
    for criterion in plan["criteria"]:
        refs = evidence_by_criterion.get(criterion["id"], [])
        score = max((item["score"] for item in refs), default=None)
        passed = score is not None and score >= criterion["floor"]
        results.append({
            "criterion_id": criterion["id"],
            "kind": criterion["kind"],
            "floor": criterion["floor"],
            "score": score,
            "evidence_refs": [item["ref"] for item in refs],
            "passed": passed,
        })
        if score is not None:
            weighted_score += score * criterion["weight"]
            total_weight += criterion["weight"]
    floors_passed = all(result["passed"] for result in results)
    quality_score = weighted_score / total_weight if total_weight else None

    telemetry_complete = (
        isinstance(telemetry, dict)
        and set(telemetry) == TELEMETRY_KEYS
        and _number(telemetry.get("tokens"))
        and telemetry.get("tokens", -1) >= 0
        and _number(telemetry.get("elapsed_ms"))
        and telemetry.get("elapsed_ms", -1) >= 0
        and isinstance(telemetry.get("avoidable_owner_questions"), int)
        and not isinstance(telemetry.get("avoidable_owner_questions"), bool)
        and telemetry.get("avoidable_owner_questions", -1) >= 0
    )
    utility = None
    if floors_passed and telemetry_complete and quality_score is not None:
        weights = plan["utility_weights"]
        utility = (
            quality_score * weights["quality"]
            - telemetry["tokens"] * weights["tokens"]
            - telemetry["elapsed_ms"] * weights["elapsed"]
            - telemetry["avoidable_owner_questions"] * weights["avoidable_owner_question"]
        )
    return {
        "quality_plan_ref": plan["id"],
        "criteria": results,
        "floors_passed": floors_passed,
        "quality_score": quality_score,
        "telemetry_complete": telemetry_complete,
        "utility": utility,
        "complete": floors_passed and telemetry_complete,
    }


def cmd_quality_evaluate(args: argparse.Namespace) -> None:
    plan = load_json_arg(args.plan, "QualityPlan")
    evidence = load_json_arg(args.evidence, "evidence_refs")
    telemetry = load_json_arg(args.telemetry, "telemetry")
    ok(evaluation=evaluate_quality(plan, evidence, telemetry))


# --------------------------------------------------------------------------- #
# context kernel — local projection only; optional providers consume outbox
# --------------------------------------------------------------------------- #
CONTEXT_FIELDS = {
    "item": frozenset(("schema", "id", "kind", "content", "source_ref", "created_at", "digest")),
    "pack": frozenset(("schema", "id", "item_refs", "created_at", "digest")),
    "delta": frozenset(("schema", "id", "base_ref", "changes", "created_at", "digest")),
}
CONTEXT_DIRS = {"item": "items", "pack": "bundles", "delta": "deltas"}
OUTBOX_FIELDS = frozenset(
    ("schema", "id", "promotion_type", "summary", "source_refs", "owner_gate", "status", "digest")
)


def _prepare_context_object(kind: str, value: Any) -> dict:
    if not isinstance(value, dict):
        fail(6, "invalid_context", f"Context{kind.title()} must be an object")
    obj = dict(value)
    obj.setdefault("schema", 1)
    obj.setdefault("created_at", now_stamp())
    obj.setdefault("digest", "auto")
    expected_fields = CONTEXT_FIELDS[kind]
    if set(obj) != expected_fields:
        fail(6, "invalid_context", f"Context{kind.title()} fields must be exactly {', '.join(sorted(expected_fields))}")
    obj["id"] = validate_safe_id(obj.get("id"), f"Context{kind.title()}.id")
    if obj.get("schema") != 1:
        fail(6, "invalid_context", "context schema must be 1")
    if not isinstance(obj.get("created_at"), str) or not obj.get("created_at", "").strip():
        fail(6, "invalid_context", "created_at must be a non-empty string")
    if kind == "item":
        if not isinstance(obj.get("kind"), str) or not obj.get("kind", "").strip():
            fail(6, "invalid_context", "ContextItem.kind must be non-empty")
        if not isinstance(obj.get("content"), (str, dict, list)):
            fail(6, "invalid_context", "ContextItem.content must be string, object, or list")
        if not isinstance(obj.get("source_ref"), str) or not obj.get("source_ref", "").strip():
            fail(6, "invalid_context", "ContextItem.source_ref must be non-empty")
    elif kind == "pack":
        refs = obj.get("item_refs")
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, dict) or set(ref) != {"id", "digest"}
            or not isinstance(ref.get("id"), str) or not isinstance(ref.get("digest"), str)
            for ref in refs
        ):
            fail(6, "invalid_context", "ContextPack.item_refs must contain {id,digest} entries")
    elif kind == "delta":
        if not isinstance(obj.get("base_ref"), str) or not obj.get("base_ref", "").strip():
            fail(6, "invalid_context", "ContextDelta.base_ref must be non-empty")
        if not isinstance(obj.get("changes"), (dict, list)) or not obj.get("changes"):
            fail(6, "invalid_context", "ContextDelta.changes must be a non-empty object or list")
    digest_payload = {key: value for key, value in obj.items() if key != "digest"}
    expected_digest = canonical_digest(digest_payload)
    if obj["digest"] == "auto":
        obj["digest"] = expected_digest
    elif obj["digest"] != expected_digest:
        fail(6, "digest_mismatch", f"context digest mismatch: expected {expected_digest}")
    return obj


def _context_path(ws: Path, kind: str, object_id: str) -> Path:
    return ws / "context" / CONTEXT_DIRS[kind] / f"{object_id}.json"


def _store_context(ws: Path, kind: str, value: Any) -> tuple[dict, Path, bool]:
    obj = _prepare_context_object(kind, value)
    path = _context_path(ws, kind, obj["id"])
    body = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") == body:
            return obj, path, False
        fail(6, "context_conflict", f"context object already exists with different content: {obj['id']}")
    atomic_write_text(path, body)
    return obj, path, True


def cmd_context_put(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    obj, path, changed = _store_context(ws, args.kind, load_json_arg(args.json, f"Context{args.kind.title()}"))
    ok(context=obj, path=str(path), changed=changed)


def cmd_context_compact(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    refs = []
    for item_id in args.item_id:
        item_id = validate_safe_id(item_id, "item_id")
        path = _context_path(ws, "item", item_id)
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            fail(4, "context_not_found", f"cannot load ContextItem {item_id}: {exc}")
        refs.append({"id": item_id, "digest": item.get("digest")})
    pack, path, changed = _store_context(ws, "pack", {
        "id": args.bundle_id,
        "item_refs": refs,
        "created_at": now_stamp(),
        "digest": "auto",
    })
    ok(context=pack, path=str(path), changed=changed)


def cmd_context_prune(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    if args.keep_deltas < 0:
        fail(2, "bad_prune", "keep-deltas must be >= 0")
    delta_dir = ws / "context" / "deltas"
    ranked = []
    for path in delta_dir.glob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fail(4, "invalid_context", f"cannot parse context delta: {path}")
        ranked.append((str(obj.get("created_at") or ""), str(obj.get("id") or path.stem), path))
    ranked.sort(reverse=True)
    removed = [path for _, _, path in ranked[args.keep_deltas:]]
    for path in removed:
        path.unlink()
    ok(kept=min(args.keep_deltas, len(ranked)), removed=[str(path) for path in removed])


def cmd_context_outbox(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    value = load_json_arg(args.json, "promotion candidate")
    if not isinstance(value, dict):
        fail(6, "invalid_promotion", "promotion candidate must be an object")
    candidate = dict(value)
    candidate.setdefault("schema", 1)
    candidate.setdefault("status", "pending")
    candidate.setdefault("digest", "auto")
    if set(candidate) != OUTBOX_FIELDS:
        fail(6, "invalid_promotion", f"promotion candidate fields must be exactly {', '.join(sorted(OUTBOX_FIELDS))}")
    candidate["id"] = validate_safe_id(candidate.get("id"), "promotion candidate id")
    if candidate.get("schema") != 1 or candidate.get("status") != "pending":
        fail(6, "invalid_promotion", "new promotion candidates require schema=1 and status=pending")
    if candidate.get("promotion_type") not in ("decision", "rejected_decision", "trial_error", "ssot"):
        fail(6, "invalid_promotion", "unsupported promotion_type")
    if not isinstance(candidate.get("summary"), str) or not candidate.get("summary", "").strip():
        fail(6, "invalid_promotion", "promotion summary must be non-empty")
    if not isinstance(candidate.get("source_refs"), list) or not candidate.get("source_refs") or any(
        not isinstance(ref, str) or not ref.strip() for ref in candidate.get("source_refs", [])
    ):
        fail(6, "invalid_promotion", "source_refs must be a non-empty string list")
    if candidate.get("owner_gate") is not True:
        fail(6, "owner_gate_required", "promotion requires owner_gate=true")
    expected = canonical_digest({key: value for key, value in candidate.items() if key != "digest"})
    if candidate["digest"] == "auto":
        candidate["digest"] = expected
    elif candidate["digest"] != expected:
        fail(6, "digest_mismatch", f"promotion digest mismatch: expected {expected}")
    path = ws / "context" / "outbox" / f"{candidate['id']}.json"
    body = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") == body:
            ok(candidate=candidate, path=str(path), changed=False)
        fail(6, "promotion_conflict", f"promotion candidate already exists: {candidate['id']}")
    atomic_write_text(path, body)
    ok(candidate=candidate, path=str(path), changed=True)


# --------------------------------------------------------------------------- #
# executor lease — one active lease per track with fencing
# --------------------------------------------------------------------------- #
ACTIVE_LEASE_STATES = frozenset(("claimed", "running", "waiting_gate"))
TERMINAL_LEASE_STATES = frozenset(("succeeded", "failed", "cancelled"))
LEASE_TRANSITIONS = {
    "claimed": frozenset(("running", "cancelled")),
    "running": frozenset(("waiting_gate", "succeeded", "failed", "cancelled")),
    "waiting_gate": frozenset(("running", "succeeded", "failed", "cancelled")),
}


def _claim_lease(board: dict, track_id: str, lease_id: str, executor: str, reservation_id: str) -> tuple[dict, bool]:
    tracks = board.setdefault("tracks", {})
    if not isinstance(tracks, dict):
        fail(4, "bad_board", "board.tracks must be an object in schema 2")
    track = tracks.setdefault(track_id, {"track_id": track_id, "lease_history": []})
    current = track.get("executor_lease")
    if current and current.get("lease_id") == lease_id:
        if current.get("executor") == executor and current.get("budget_reservation_id") == reservation_id:
            return current, False
        fail(6, "lease_conflict", "lease id already exists with different claim data")
    current_reservation = None
    if current:
        current_reservation = _budget_reservations(board["budget"]).get(current.get("budget_reservation_id"))
    replacement_fenced = current and (
        current.get("state") in ACTIVE_LEASE_STATES
        or (current_reservation and current_reservation.get("status") in ("reserved", "dispatched"))
    )
    if replacement_fenced:
        fail(6, "active_lease_exists", f"track {track_id} already has fenced lease {current.get('lease_id')}")
    reservations = _budget_reservations(board["budget"])
    reservation = reservations.get(reservation_id)
    if not reservation or reservation.get("lease_id") != lease_id or reservation.get("status") != "reserved":
        fail(6, "reservation_required", "claim requires a reserved budget reservation fenced by the same lease")
    if current:
        track.setdefault("lease_history", []).append(current)
    current = {
        "lease_id": lease_id,
        "executor": executor,
        "state": "claimed",
        "budget_reservation_id": reservation_id,
        "external_ref": None,
        "coarse_status": "claimed",
    }
    track["executor_lease"] = current
    return current, True


def cmd_lease_claim(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    track_id = validate_safe_id(args.track_id, "track_id")
    lease_id = validate_safe_id(args.lease_id, "lease_id")
    reservation_id = validate_safe_id(args.reservation_id, "reservation_id")
    with board_transaction(ws) as board:
        current, changed = _claim_lease(board, track_id, lease_id, args.executor, reservation_id)
    ok(lease=current, changed=changed)


def _transition_lease(board: dict, track_id: str, lease_id: str, state: str, external_ref: str | None = None) -> tuple[dict, bool]:
    track = board.setdefault("tracks", {}).get(track_id)
    lease = track and track.get("executor_lease")
    if not lease:
        fail(4, "lease_not_found", f"no lease for track {track_id}")
    if lease.get("lease_id") != lease_id:
        fail(6, "stale_lease", f"track {track_id} is fenced by another lease")
    old_state = lease.get("state")
    if old_state == state:
        return lease, False
    if state not in LEASE_TRANSITIONS.get(old_state, frozenset()):
        fail(6, "invalid_lease_transition", f"cannot transition {old_state} to {state}")
    reservation = _budget_reservations(board["budget"])[lease["budget_reservation_id"]]
    if state == "running":
        if reservation.get("lease_id") != lease_id:
            fail(6, "stale_lease", "budget reservation is fenced by another lease")
        if reservation.get("status") == "reserved":
            reservation["status"] = "dispatched"
        elif reservation.get("status") != "dispatched":
            fail(6, "invalid_budget_transition", "running requires a reserved or dispatched budget")
    lease["state"] = state
    lease["coarse_status"] = state
    if external_ref is not None:
        lease["external_ref"] = external_ref
    if state == "cancelled":
        lease["cancel_confirmed"] = True
        lease["recovery_required"] = False
    elif state == "failed":
        lease["recovery_required"] = True
    return lease, True


def cmd_lease_transition(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    track_id = validate_safe_id(args.track_id, "track_id")
    lease_id = validate_safe_id(args.lease_id, "lease_id")
    with board_transaction(ws) as board:
        lease, changed = _transition_lease(board, track_id, lease_id, args.state, args.external_ref)
    ok(lease=lease, changed=changed)


# --------------------------------------------------------------------------- #
# review cycle — stable findings, delta QA, evidence reuse, compact handoff
# --------------------------------------------------------------------------- #
def _review_cycles(board: dict) -> dict:
    cycles = board.setdefault("review_cycles", {})
    if not isinstance(cycles, dict):
        fail(4, "bad_board", "board.review_cycles must be an object")
    return cycles


def _review_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(6, "invalid_review_contract", f"{field} must be a non-empty string")
    return value.strip()


def _review_string_list(value: Any, field: str, *, non_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        fail(6, "invalid_review_contract", f"{field} must be a string list")
    result = [item.strip() for item in value]
    if non_empty and not result:
        fail(6, "invalid_review_contract", f"{field} must not be empty")
    if len(result) != len(set(result)):
        fail(6, "invalid_review_contract", f"{field} must not contain duplicates")
    return result


def _review_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        fail(6, "invalid_review_contract", f"{field} must be a sha256 digest")
    return value


def _review_cycle_digest(cycle: dict) -> str:
    return canonical_digest({key: value for key, value in cycle.items() if key != "digest"})


def _seal_review_cycle(cycle: dict) -> dict:
    cycle["digest"] = _review_cycle_digest(cycle)
    return cycle


def _review_binding(payload: dict) -> dict:
    required = {
        "cycle_id", "track_id", "criteria_digest", "base_head", "quality_plan_ref",
    }
    allowed = required | {
        "definition_ref", "issue_ref", "requires_final_qa", "requires_integration_gate",
    }
    unknown = sorted(set(payload) - allowed)
    missing = sorted(required - set(payload))
    if unknown or missing:
        fail(
            6, "invalid_review_contract", "review cycle binding fields are invalid",
            unknown=unknown, missing=missing,
        )
    cycle_id = validate_safe_id(payload["cycle_id"], "cycle_id")
    track_id = validate_safe_id(payload["track_id"], "track_id")
    quality_plan_ref = validate_safe_id(payload["quality_plan_ref"], "quality_plan_ref")
    criteria_digest = _review_digest(payload["criteria_digest"], "criteria_digest")
    base_head = _review_text(payload["base_head"], "base_head")
    definition_ref = payload.get("definition_ref")
    if definition_ref is not None and not isinstance(definition_ref, dict):
        fail(6, "invalid_review_contract", "definition_ref must be an object or null")
    issue_ref = payload.get("issue_ref")
    if issue_ref is not None and (not isinstance(issue_ref, str) or not issue_ref.strip()):
        fail(6, "invalid_review_contract", "issue_ref must be null or a non-empty string")
    for key in ("requires_final_qa", "requires_integration_gate"):
        if key in payload and not isinstance(payload[key], bool):
            fail(6, "invalid_review_contract", f"{key} must be boolean")
    return {
        "cycle_id": cycle_id,
        "track_id": track_id,
        "criteria_digest": criteria_digest,
        "base_head": base_head,
        "quality_plan_ref": quality_plan_ref,
        "definition_ref": definition_ref,
        "issue_ref": issue_ref.strip() if isinstance(issue_ref, str) else None,
        "requires_final_qa": payload.get("requires_final_qa", True),
        "requires_integration_gate": payload.get("requires_integration_gate", True),
    }


def _new_review_cycle(binding: dict) -> dict:
    timestamp = now_stamp()
    cycle = {
        "schema": REVIEW_CYCLE_SCHEMA,
        **binding,
        "state": "review-cycle",
        "findings": {},
        "evidence": {},
        "events": [],
        "next_finding_seq": 1,
        "required_full_qa_reason": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "counters": {
            "qa_rounds": 0,
            "development_qa": 0,
            "delta_qa": 0,
            "full_qa": 0,
            "final_qa": 0,
            "integration_gate": 0,
            "transient_retries": 0,
            "tool_unavailable_retries": 0,
            "configuration_retries": 0,
            "handoffs": 0,
            "fresh_contexts": 0,
            "evidence_reused": 0,
            "evidence_invalidated": 0,
        },
        "full_qa_reason_counts": {},
    }
    return _seal_review_cycle(cycle)


def cmd_review_open(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    payload = load_json_arg(args.json, "review cycle binding")
    if not isinstance(payload, dict):
        fail(6, "invalid_review_contract", "review cycle binding must be an object")
    binding = _review_binding(payload)
    with board_transaction(ws) as board:
        cycles = _review_cycles(board)
        existing = cycles.get(binding["cycle_id"])
        if existing is not None:
            existing = _review_cycle_from_board(board, binding["cycle_id"])
            expected = {key: existing.get(key) for key in binding}
            if expected != binding:
                fail(6, "review_cycle_binding_mismatch", "cycle id is already bound to another contract")
            cycle = existing
            changed = False
        else:
            cycle = _new_review_cycle(binding)
            cycles[binding["cycle_id"]] = cycle
            changed = True
    ok(cycle=cycle, changed=changed)


def _review_evidence(value: Any) -> dict:
    required = {
        "ref", "head", "criteria_digest", "covered_paths", "surface_digest",
        "tool_version", "environment_digest", "command_digest",
    }
    if not isinstance(value, dict) or set(value) != required:
        fail(6, "invalid_review_contract", "evidence pin fields do not match the contract")
    return {
        "ref": _review_text(value["ref"], "evidence.ref"),
        "head": _review_text(value["head"], "evidence.head"),
        "criteria_digest": _review_digest(value["criteria_digest"], "evidence.criteria_digest"),
        "covered_paths": _review_string_list(value["covered_paths"], "evidence.covered_paths", non_empty=True),
        "surface_digest": _review_digest(value["surface_digest"], "evidence.surface_digest"),
        "tool_version": _review_text(value["tool_version"], "evidence.tool_version"),
        "environment_digest": _review_digest(value["environment_digest"], "evidence.environment_digest"),
        "command_digest": _review_digest(value["command_digest"], "evidence.command_digest"),
    }


def _review_change(value: Any) -> dict:
    required = {
        "head", "criteria_digest", "changed_paths", "surface_digest", "tool_version",
        "environment_digest", "impact_known", "shared_contract_changed",
    }
    if not isinstance(value, dict) or set(value) != required:
        fail(6, "invalid_review_contract", "change impact fields do not match the contract")
    if not isinstance(value["impact_known"], bool) or not isinstance(value["shared_contract_changed"], bool):
        fail(6, "invalid_review_contract", "impact_known and shared_contract_changed must be boolean")
    return {
        "head": _review_text(value["head"], "change.head"),
        "criteria_digest": _review_digest(value["criteria_digest"], "change.criteria_digest"),
        "changed_paths": _review_string_list(value["changed_paths"], "change.changed_paths", non_empty=True),
        "surface_digest": _review_digest(value["surface_digest"], "change.surface_digest"),
        "tool_version": _review_text(value["tool_version"], "change.tool_version"),
        "environment_digest": _review_digest(value["environment_digest"], "change.environment_digest"),
        "impact_known": value["impact_known"],
        "shared_contract_changed": value["shared_contract_changed"],
    }


def _paths_overlap(left: list[str], right: list[str]) -> bool:
    def overlaps(a: str, b: str) -> bool:
        a = a.rstrip("/")
        b = b.rstrip("/")
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")
    return any(overlaps(a, b) for a in left for b in right)


def review_evidence_decision(evidence: dict, change: dict) -> dict:
    reasons = []
    if not change["impact_known"]:
        reasons.append("impact-unknown")
    if evidence["criteria_digest"] != change["criteria_digest"]:
        reasons.append("criteria-changed")
    if evidence["tool_version"] != change["tool_version"]:
        reasons.append("tool-version-changed")
    if evidence["environment_digest"] != change["environment_digest"]:
        reasons.append("environment-changed")
    if evidence["surface_digest"] != change["surface_digest"]:
        reasons.append("dependency-surface-changed")
    if change["shared_contract_changed"]:
        reasons.append("shared-contract-changed")
    if _paths_overlap(evidence["covered_paths"], change["changed_paths"]):
        reasons.append("covered-path-overlap")
    return {"ref": evidence["ref"], "reusable": not reasons, "reasons": reasons}


def cmd_review_evidence_check(args: argparse.Namespace) -> None:
    evidence = _review_evidence(load_json_arg(args.evidence, "evidence pin"))
    change = _review_change(load_json_arg(args.change, "change impact"))
    ok(decision=review_evidence_decision(evidence, change))


def cmd_review_plan_next(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    cycle_id = validate_safe_id(args.cycle_id, "cycle_id")
    head = _review_text(args.head, "head")
    command_digest = _review_digest(args.command_digest, "command_digest")
    environment_digest = _review_digest(args.environment_digest, "environment_digest")
    tool_version = _review_text(args.tool_version, "tool_version")
    changed_paths = _review_string_list(args.changed_path or [], "changed_paths")
    allowed_commands = _review_string_list(args.allowed_command or [], "allowed_commands")
    requested_reason = args.full_qa_reason
    if requested_reason is not None and requested_reason not in FULL_QA_REASONS:
        fail(6, "invalid_full_qa_reason", f"full QA reason must be one of {sorted(FULL_QA_REASONS)}")

    with board_transaction(ws) as board:
        cycle = _review_cycle_from_board(board, cycle_id)
        valid = [item for item in cycle["evidence"].values() if item.get("status") == "valid"]
        invalidated = sorted(
            item["ref"] for item in cycle["evidence"].values()
            if item.get("status") == "invalidated"
        )
        exact = next((
            item for item in valid
            if item["head"] == head
            and item["command_digest"] == command_digest
            and item["environment_digest"] == environment_digest
            and item["tool_version"] == tool_version
        ), None)
        physical_key = canonical_digest({
            "cycle_id": cycle_id, "head": head, "command_digest": command_digest,
            "environment_digest": environment_digest, "tool_version": tool_version,
        })
        reason = "integration-gate" if args.integration_gate else (
            requested_reason or cycle.get("required_full_qa_reason")
        )
        if exact is not None:
            action, qa_mode, physical_runs = "reuse-evidence", "delta", 0
            reused = [exact["ref"]]
            cycle["counters"]["duplicate_prevented"] = int(
                cycle["counters"].get("duplicate_prevented") or 0
            ) + 1
            board.setdefault("workflow_counters", {}).setdefault("duplicate_prevented", 0)
            board["workflow_counters"]["duplicate_prevented"] += 1
            _seal_review_cycle(cycle)
        else:
            telemetry_paused = False
            if args.telemetry_policy == "fail-closed":
                cycle_runs = [run for run in board.get("runs", []) if run.get("review_cycle_id") == cycle_id]
                telemetry_paused = any(run.get("cost_tokens") is None for run in cycle_runs)
            if telemetry_paused:
                action, qa_mode, physical_runs = "pause", None, 0
            elif reason:
                action, qa_mode, physical_runs = "full-qa", "full", 1
            else:
                action, qa_mode, physical_runs = "delta-qa", "delta", 1
            reused = sorted(item["ref"] for item in valid)

        open_findings = sorted(
            item["id"] for item in cycle["findings"].values()
            if item["status"] != "closed"
        )
        plan = {
            "schema": "studio-review-next-action/v1",
            "cycle_id": cycle_id,
            "episode_id": cycle_id,
            "head": head,
            "physical_key": physical_key,
            "action": action,
            "qa_mode": qa_mode,
            "impact_set": changed_paths,
            "allowed_commands": allowed_commands,
            "full_qa_reason": reason if qa_mode == "full" else None,
            "open_findings": open_findings,
            "reused_evidence": reused,
            "invalidated_evidence": invalidated,
            "physical_runs": physical_runs,
            "duplicate_prevented": board.setdefault("workflow_counters", {}).get("duplicate_prevented", 0),
            "telemetry_gate": "paused" if action == "pause" else "open",
        }
        plan["digest"] = canonical_digest(plan)
    ok(plan=plan)


def _review_finding_ids(event: dict) -> list[str]:
    if event.get("type") == "finding-opened":
        return [event["finding"]["id"]]
    if event.get("type") == "qa-completed":
        return [item["id"] for item in event.get("finding_results", [])]
    return list(event.get("finding_ids") or [])


def _review_evidence_refs(event: dict) -> list[str]:
    refs = list(event.get("evidence_refs") or [])
    for item in event.get("finding_results", []):
        refs.extend(item.get("evidence_refs") or [])
    if event.get("type") == "evidence-recorded":
        refs.append(event["evidence"]["ref"])
    return sorted(set(refs))


def _review_cycle_delta(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"cycle_id", "events"}:
        fail(6, "invalid_review_contract", "review_cycle_delta must contain cycle_id and events")
    cycle_id = validate_safe_id(value["cycle_id"], "cycle_id")
    events = value["events"]
    if not isinstance(events, list) or not events:
        fail(6, "invalid_review_contract", "review_cycle_delta.events must be a non-empty list")
    if any(not isinstance(event, dict) for event in events):
        fail(6, "invalid_review_contract", "review_cycle_delta.events must contain objects")
    event_ids = [event.get("event_id") for event in events]
    if any(not isinstance(event_id, str) or not SAFE_ID_RE.fullmatch(event_id) for event_id in event_ids):
        fail(6, "invalid_review_contract", "review_cycle_delta event ids must be path-safe strings")
    if len(event_ids) != len(set(event_ids)):
        fail(6, "invalid_review_contract", "review_cycle_delta event ids must be unique")
    return {"cycle_id": cycle_id, "events": events}


def _review_issue_event(cycle: dict, event: dict) -> dict | None:
    issue_ref = cycle.get("issue_ref")
    if not issue_ref or event["type"] in {"handoff-recorded", "evidence-recorded"}:
        return None
    if event["type"] == "retry-recorded" and event.get("classification") in {
        "environment-transient", "tool-unavailable", "configuration-error",
    }:
        return None
    finding_ids = _review_finding_ids(event)
    evidence_refs = _review_evidence_refs(event)
    marker = f"studio-review-event:{event['event_id']}"
    title = event["type"].replace("-", " ")
    details = [
        f"- Cycle: `{cycle['cycle_id']}`",
        f"- State: `{cycle['state']}`",
        f"- Head: `{event.get('head') or cycle.get('base_head')}`",
    ]
    if finding_ids:
        details.append(f"- Findings: `{', '.join(finding_ids)}`")
    if event.get("qa_mode"):
        details.append(f"- QA mode: `{event['qa_mode']}`")
    if evidence_refs:
        details.append(f"- Evidence: `{', '.join(evidence_refs)}`")
    if event.get("full_qa_reason"):
        details.append(f"- Full QA reason: `{event['full_qa_reason']}`")
    return {
        "schema": ISSUE_EVENT_SCHEMA,
        "event_id": event["event_id"],
        "issue_ref": issue_ref,
        "cycle_id": cycle["cycle_id"],
        "track_id": cycle["track_id"],
        "type": event["type"],
        "state": cycle["state"],
        "finding_ids": finding_ids,
        "evidence_refs": evidence_refs,
        "marker": marker,
        "comment_markdown": f"<!-- {marker} -->\n## Studio {title}\n\n" + "\n".join(details),
    }


def _normalise_review_event(cycle: dict, raw: Any) -> dict:
    if not isinstance(raw, dict):
        fail(6, "invalid_review_event", "review event must be an object")
    event = json.loads(json.dumps(raw))
    if event.get("schema") != REVIEW_EVENT_SCHEMA:
        fail(6, "invalid_review_event", f"review event schema must be {REVIEW_EVENT_SCHEMA}")
    event["event_id"] = validate_safe_id(event.get("event_id"), "event_id")
    if event.get("type") not in REVIEW_EVENT_TYPES:
        fail(6, "invalid_review_event", f"event type must be one of {sorted(REVIEW_EVENT_TYPES)}")
    common = {"schema", "cycle_id", "event_id", "type", "at"}
    unknown = sorted(set(event) - common - REVIEW_EVENT_FIELDS[event["type"]])
    if unknown:
        fail(6, "invalid_review_event", "review event contains unknown fields", unknown=unknown)
    if event.get("cycle_id") != cycle["cycle_id"]:
        fail(6, "review_cycle_binding_mismatch", "event cycle_id does not match the target cycle")
    if "at" in event:
        _review_text(event["at"], "event.at")
    return event


def _apply_review_event(cycle: dict, raw: Any) -> tuple[dict, bool, dict | None]:
    event = _normalise_review_event(cycle, raw)
    request_digest = canonical_digest({key: value for key, value in event.items() if key != "at"})
    prior = next((item for item in cycle["events"] if item.get("event_id") == event["event_id"]), None)
    if prior is not None:
        if prior.get("request_digest") != request_digest:
            fail(6, "review_event_conflict", "event_id is already bound to different content")
        return cycle, False, _review_issue_event(cycle, prior)

    event.setdefault("at", now_stamp())
    event["request_digest"] = request_digest

    findings = cycle["findings"]
    counters = cycle["counters"]
    event_type = event["type"]
    if event_type == "finding-opened":
        finding = event.get("finding")
        if not isinstance(finding, dict):
            fail(6, "invalid_review_event", "finding-opened requires finding")
        allowed = {"id", "title", "severity", "repro", "affected_criteria", "evidence_refs"}
        if set(finding) - allowed:
            fail(6, "invalid_review_event", "finding contains unknown fields")
        finding_id = finding.get("id")
        if finding_id is None:
            finding_id = f"F-{cycle['next_finding_seq']:04d}"
        if not isinstance(finding_id, str) or not re.fullmatch(r"F-[0-9]{4,}", finding_id):
            fail(6, "invalid_review_event", "finding.id must look like F-0001")
        if finding_id in findings:
            fail(6, "finding_conflict", f"finding already exists: {finding_id}")
        numeric = int(finding_id.split("-", 1)[1])
        cycle["next_finding_seq"] = max(cycle["next_finding_seq"], numeric + 1)
        normalised_finding = {
            "id": finding_id,
            "status": "open",
            "title": _review_text(finding.get("title"), "finding.title"),
            "severity": _review_text(finding.get("severity"), "finding.severity"),
            "repro": _review_text(finding.get("repro"), "finding.repro"),
            "affected_criteria": _review_string_list(
                finding.get("affected_criteria", []), "finding.affected_criteria", non_empty=True,
            ),
            "evidence_refs": _review_string_list(finding.get("evidence_refs", []), "finding.evidence_refs"),
            "opened_at_head": _review_text(event.get("head"), "event.head"),
            "closed_by_evidence": [],
        }
        findings[finding_id] = normalised_finding
        event["finding"] = normalised_finding
        cycle["state"] = "review-cycle"
    elif event_type == "evidence-recorded":
        evidence = _review_evidence(event.get("evidence"))
        if evidence["criteria_digest"] != cycle["criteria_digest"]:
            fail(6, "new_cycle_required", "evidence criteria differ from the cycle binding")
        existing = cycle["evidence"].get(evidence["ref"])
        if existing and {k: v for k, v in existing.items() if k not in {"status", "invalidated_by"}} != evidence:
            fail(6, "evidence_conflict", "evidence ref is already bound to another pin")
        if existing and existing.get("status") != "valid":
            fail(6, "evidence_invalidated", "invalidated evidence ref cannot be resurrected; record a new pin")
        cycle["evidence"][evidence["ref"]] = {**evidence, "status": "valid", "invalidated_by": None}
        event["evidence"] = evidence
    elif event_type == "fix-submitted":
        finding_ids = _review_string_list(event.get("finding_ids"), "finding_ids", non_empty=True)
        for finding_id in finding_ids:
            finding = findings.get(finding_id)
            if not finding or finding["status"] not in {"open", "blocked"}:
                fail(6, "invalid_finding_transition", f"cannot submit fix for {finding_id}")
            finding["status"] = "fixed-pending-verification"
        change = _review_change(event.get("change"))
        if change["criteria_digest"] != cycle["criteria_digest"]:
            fail(6, "new_cycle_required", "criteria changed; start a new review cycle")
        decisions = []
        for evidence in cycle["evidence"].values():
            if evidence.get("status") != "valid":
                continue
            decision = review_evidence_decision(evidence, change)
            decisions.append(decision)
            if decision["reusable"]:
                evidence["status"] = "valid"
                evidence["invalidated_by"] = None
                counters["evidence_reused"] += 1
            else:
                evidence["status"] = "invalidated"
                evidence["invalidated_by"] = event["event_id"]
                counters["evidence_invalidated"] += 1
        event["finding_ids"] = finding_ids
        event["change"] = change
        event["evidence_decisions"] = decisions
        cycle["base_head"] = change["head"]
        if not change["impact_known"]:
            cycle["required_full_qa_reason"] = "impact-unknown"
        elif change["shared_contract_changed"]:
            cycle["required_full_qa_reason"] = "shared-contract-changed"
        elif any("dependency-surface-changed" in item["reasons"] for item in decisions):
            cycle["required_full_qa_reason"] = "dependency-surface-changed"
        cycle["state"] = "review-cycle"
    elif event_type == "qa-completed":
        qa_mode = event.get("qa_mode")
        if qa_mode not in QA_MODES:
            fail(6, "invalid_review_event", f"qa_mode must be one of {sorted(QA_MODES)}")
        if not isinstance(event.get("passed"), bool):
            fail(6, "invalid_review_event", "qa-completed requires boolean passed")
        event["checks"] = _review_string_list(event.get("checks", []), "checks")
        event["blocked_checks"] = _review_string_list(event.get("blocked_checks", []), "blocked_checks")
        event["evidence_refs"] = _review_string_list(event.get("evidence_refs", []), "evidence_refs")
        invalid_qa_refs = [
            ref for ref in event["evidence_refs"]
            if cycle["evidence"].get(ref, {}).get("status") != "valid"
        ]
        if invalid_qa_refs:
            fail(
                6, "invalid_review_event", "QA may reference only valid cycle evidence",
                invalid_evidence_refs=invalid_qa_refs,
            )
        if event["passed"] and not event["evidence_refs"]:
            fail(6, "invalid_review_event", "passed QA requires pinned evidence")
        results = event.get("finding_results", [])
        if not isinstance(results, list):
            fail(6, "invalid_review_event", "finding_results must be a list")
        normalised_results = []
        for result in results:
            if not isinstance(result, dict) or set(result) != {"id", "status", "evidence_refs"}:
                fail(6, "invalid_review_event", "finding result fields are invalid")
            finding = findings.get(result["id"])
            if not finding:
                fail(6, "finding_not_found", f"unknown finding: {result['id']}")
            if result["status"] not in {"open", "closed", "blocked"}:
                fail(6, "invalid_review_event", "finding result status must be open, closed, or blocked")
            evidence_refs = _review_string_list(result["evidence_refs"], "finding_result.evidence_refs")
            if result["status"] == "closed" and not evidence_refs:
                fail(6, "invalid_finding_transition", "closed finding requires defense evidence")
            if result["status"] == "closed" and event["passed"] is not True:
                fail(6, "invalid_finding_transition", "failed QA cannot close a finding")
            invalid_refs = [
                ref for ref in evidence_refs
                if cycle["evidence"].get(ref, {}).get("status") != "valid"
            ]
            if invalid_refs:
                fail(
                    6, "invalid_finding_transition",
                    "finding results may reference only valid cycle evidence",
                    invalid_evidence_refs=invalid_refs,
                )
            finding["status"] = result["status"]
            if result["status"] == "closed":
                finding["closed_by_evidence"] = evidence_refs
                finding["closed_at_head"] = _review_text(event.get("head"), "event.head")
            normalised_results.append({**result, "evidence_refs": evidence_refs})
        event["finding_results"] = normalised_results
        if qa_mode == "full":
            reason = event.get("full_qa_reason")
            if reason not in FULL_QA_REASONS:
                fail(6, "full_qa_reason_required", "full QA requires a machine-readable reason")
            required_reason = cycle.get("required_full_qa_reason")
            if required_reason and reason != required_reason:
                fail(6, "full_qa_reason_mismatch", "full QA reason must match the pending boundary change")
            reasons = cycle["full_qa_reason_counts"]
            reasons[reason] = int(reasons.get(reason) or 0) + 1
        elif event.get("full_qa_reason") is not None:
            fail(6, "invalid_review_event", "full_qa_reason is only valid for full QA")
        counters["qa_rounds"] += 1
        counter_key = {
            "development": "development_qa",
            "delta": "delta_qa",
            "full": "full_qa",
            "final": "final_qa",
            "integration": "integration_gate",
        }[qa_mode]
        counters[counter_key] += 1
        unresolved = [item for item in findings.values() if item["status"] != "closed"]
        clean = event["passed"] and not event["blocked_checks"] and not unresolved and bool(event["checks"])
        if qa_mode == "full" and clean:
            cycle["required_full_qa_reason"] = None
        if qa_mode == "final":
            if cycle.get("required_full_qa_reason"):
                fail(6, "full_qa_required", "final QA cannot bypass a required full QA")
            if not clean:
                fail(6, "final_qa_incomplete", "final QA requires passed checks and zero open findings")
            cycle["state"] = (
                "final-qa-passed" if cycle["requires_integration_gate"] else "integration-ready"
            )
        elif qa_mode == "integration":
            if cycle.get("required_full_qa_reason"):
                fail(6, "full_qa_required", "integration cannot bypass a required full QA")
            if cycle["requires_final_qa"] and cycle["state"] != "final-qa-passed":
                fail(6, "final_qa_required", "integration requires final QA first")
            if not clean:
                fail(6, "integration_gate_incomplete", "integration gate requires passed checks and zero open findings")
            cycle["state"] = "integration-ready"
        elif clean:
            cycle["state"] = (
                "integration-ready"
                if not cycle["requires_final_qa"] and not cycle["requires_integration_gate"]
                else "stabilized"
            )
        else:
            cycle["state"] = "review-cycle"
        cycle["base_head"] = _review_text(event.get("head"), "event.head")
    elif event_type == "retry-recorded":
        classification = event.get("classification")
        if classification not in RETRY_CLASSIFICATIONS:
            fail(6, "invalid_review_event", f"classification must be one of {sorted(RETRY_CLASSIFICATIONS)}")
        event["failure"] = _review_text(event.get("failure"), "failure")
        if not isinstance(event.get("attempt"), int) or isinstance(event.get("attempt"), bool) or event["attempt"] < 1:
            fail(6, "invalid_review_event", "retry attempt must be a positive integer")
        if classification == "environment-transient":
            counters["transient_retries"] += 1
        elif classification == "tool-unavailable":
            counters["tool_unavailable_retries"] += 1
        elif classification == "configuration-error":
            counters["configuration_retries"] += 1
        elif classification == "criteria-gap":
            cycle["state"] = "blocked"
            event["new_cycle_required"] = True
        elif classification == "product-defect":
            finding_ids = _review_string_list(event.get("finding_ids", []), "finding_ids", non_empty=True)
            if any(finding_id not in findings for finding_id in finding_ids):
                fail(6, "finding_not_found", "product-defect retry must reference an existing finding")
            event["finding_ids"] = finding_ids
    elif event_type == "handoff-recorded":
        if not isinstance(event.get("fresh_context"), bool):
            fail(6, "invalid_review_event", "handoff fresh_context must be boolean")
        continuation = event.get("continuation_ref")
        if continuation is not None and (not isinstance(continuation, str) or not continuation.strip()):
            fail(6, "invalid_review_event", "continuation_ref must be null or non-empty")
        reason = event.get("reason")
        if event["fresh_context"] and reason not in FRESH_CONTEXT_REASONS:
            fail(6, "fresh_context_reason_required", "fresh context requires a machine-readable reason")
        if not event["fresh_context"] and reason is not None:
            fail(6, "invalid_review_event", "continuation handoff does not take a fresh-context reason")
        counters["handoffs"] += 1
        counters["fresh_contexts"] += int(event["fresh_context"])

    event["digest"] = canonical_digest(event)
    cycle["events"].append(event)
    cycle["updated_at"] = now_stamp()
    _seal_review_cycle(cycle)
    return cycle, True, _review_issue_event(cycle, event)


def _review_cycle_from_board(board: dict, cycle_id: str) -> dict:
    cycle = _review_cycles(board).get(cycle_id)
    if not isinstance(cycle, dict):
        fail(4, "review_cycle_not_found", f"review cycle not found: {cycle_id}")
    if cycle.get("schema") != REVIEW_CYCLE_SCHEMA or cycle.get("digest") != _review_cycle_digest(cycle):
        fail(6, "review_cycle_invalid", "review cycle schema or digest is invalid")
    return cycle


def cmd_review_event(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    cycle_id = validate_safe_id(args.cycle_id, "cycle_id")
    raw = load_json_arg(args.json, "review event")
    with board_transaction(ws) as board:
        cycle = _review_cycle_from_board(board, cycle_id)
        cycle, changed, issue_event = _apply_review_event(cycle, raw)
    ok(cycle=cycle, changed=changed, issue_event=issue_event)


def _review_handoff(cycle: dict) -> dict:
    findings = [
        {
            "id": item["id"], "status": item["status"], "severity": item["severity"],
            "title": item["title"], "repro": item["repro"],
            "affected_criteria": item["affected_criteria"],
        }
        for item in cycle["findings"].values()
        if item["status"] != "closed"
    ]
    evidence = [
        {key: item[key] for key in ("ref", "head", "criteria_digest", "surface_digest", "tool_version", "environment_digest")}
        for item in cycle["evidence"].values() if item.get("status") == "valid"
    ]
    pack = {
        "schema": "studio-review-handoff/v1",
        "cycle_id": cycle["cycle_id"],
        "track_id": cycle["track_id"],
        "state": cycle["state"],
        "definition_ref": cycle.get("definition_ref"),
        "issue_ref": cycle.get("issue_ref"),
        "quality_plan_ref": cycle["quality_plan_ref"],
        "criteria_digest": cycle["criteria_digest"],
        "base_head": cycle["base_head"],
        "next_finding_seq": cycle["next_finding_seq"],
        "open_findings": findings,
        "valid_evidence": evidence,
        "required_full_qa_reason": cycle.get("required_full_qa_reason"),
        "last_event_id": cycle["events"][-1]["event_id"] if cycle["events"] else None,
    }
    pack["digest"] = canonical_digest(pack)
    return pack


def _review_summary(cycle: dict, board: dict) -> dict:
    total_decisions = cycle["counters"]["evidence_reused"] + cycle["counters"]["evidence_invalidated"]
    runs = [run for run in board.get("runs", []) if run.get("review_cycle_id") == cycle["cycle_id"]]
    token_values = [run.get("cost_tokens") for run in runs]
    elapsed_values = [run.get("cost_elapsed_ms") for run in runs]
    known_tokens = [value for value in token_values if isinstance(value, int) and not isinstance(value, bool)]
    known_elapsed = [value for value in elapsed_values if isinstance(value, int) and not isinstance(value, bool)]

    def coverage(known: list[int], total: int) -> str:
        if not total or not known:
            return "unavailable"
        return "exact" if len(known) == total else "partial"

    return {
        "cycle_id": cycle["cycle_id"],
        "track_id": cycle["track_id"],
        "state": cycle["state"],
        "open_findings": sum(
            item["status"] != "closed"
            for item in cycle["findings"].values()
        ),
        "counters": cycle["counters"],
        "full_qa_reason_counts": cycle["full_qa_reason_counts"],
        "cost": {
            "physical_runs": len(runs),
            "tokens": sum(known_tokens) if known_tokens else None,
            "token_coverage": coverage(known_tokens, len(runs)),
            "elapsed_ms": sum(known_elapsed) if known_elapsed else None,
            "elapsed_coverage": coverage(known_elapsed, len(runs)),
        },
        "evidence_reuse_ratio": (
            cycle["counters"]["evidence_reused"] / total_decisions if total_decisions else None
        ),
        "integration_ready": cycle["state"] == "integration-ready",
    }


def cmd_review_read(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    cycle_id = validate_safe_id(args.cycle_id, "cycle_id")
    board = load_board(ws)
    cycle = _review_cycle_from_board(board, cycle_id)
    if args.review_command == "status":
        ok(cycle=cycle)
    if args.review_command == "handoff":
        ok(handoff=_review_handoff(cycle))
    ok(summary=_review_summary(cycle, board))


def validate_review_lease(value: Any) -> list[str]:
    fields = {
        "schema", "lease_id", "owner", "provider", "episode_id", "edge_id",
        "requirement", "criteria_digest", "evidence_refs", "digest",
    }
    if not isinstance(value, dict):
        return ["review_lease must be an object"]
    problems = []
    if set(value) != fields:
        problems.append("review_lease fields do not match workflow-review-lease/v1")
    if value.get("schema") != REVIEW_LEASE_SCHEMA:
        problems.append(f"review_lease.schema must be {REVIEW_LEASE_SCHEMA}")
    for key in ("lease_id", "episode_id", "edge_id"):
        if not isinstance(value.get(key), str) or not SAFE_ID_RE.fullmatch(value.get(key, "")):
            problems.append(f"review_lease.{key} must be a path-safe identifier")
    if value.get("owner") not in ("studio", "task-worker"):
        problems.append("review_lease.owner must be studio or task-worker")
    if value.get("provider") not in REVIEWER_PROVIDERS:
        problems.append("review_lease.provider must be native or session-review")
    if value.get("requirement") not in ("self", "independent"):
        problems.append("review_lease.requirement must be self or independent")
    if not isinstance(value.get("criteria_digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("criteria_digest", "")):
        problems.append("review_lease.criteria_digest must be a sha256 digest")
    refs = value.get("evidence_refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in (refs or [])):
        problems.append("review_lease.evidence_refs must be a string list")
    elif len(refs) != len(set(refs)):
        problems.append("review_lease.evidence_refs must be unique")
    expected = canonical_digest({key: item for key, item in value.items() if key != "digest"})
    if value.get("digest") != expected:
        problems.append("review_lease.digest does not match its canonical payload")
    return problems


def _native_review_fallback_lease(source: dict) -> dict:
    target = {**source, "provider": "native"}
    target["digest"] = canonical_digest({
        key: value for key, value in target.items() if key != "digest"
    })
    return target


def _review_fallback_authorization(mission_id: str, source: dict) -> dict:
    payload = {
        "schema": "studio-review-fallback-authorization/v1",
        "mission_id": mission_id,
        "edge_id": source["edge_id"],
        "source_lease_digest": source["digest"],
        "target_lease": _native_review_fallback_lease(source),
    }
    return {**payload, "digest": canonical_digest(payload)}


def _validate_review_edge_reservation(value: Any) -> dict:
    fields = {
        "schema", "state", "mission_id", "edge_id", "original_lease",
        "accepted_lease", "fallback_authorization",
    }
    if not isinstance(value, dict) or set(value) != fields:
        fail(4, "bad_board", "review edge reservation fields are invalid")
    if value.get("schema") != REVIEW_EDGE_RESERVATION_SCHEMA:
        fail(4, "bad_board", "review edge reservation schema is invalid")
    if value.get("state") not in ("pending", "accepted"):
        fail(4, "bad_board", "review edge reservation state is invalid")
    if any(
        not isinstance(value.get(key), str)
        or not SAFE_ID_RE.fullmatch(value.get(key, ""))
        for key in ("mission_id", "edge_id")
    ):
        fail(4, "bad_board", "review edge reservation identity is invalid")
    original = value.get("original_lease")
    problems = validate_review_lease(original)
    if problems or original.get("edge_id") != value["edge_id"]:
        fail(4, "bad_board", "review edge original lease is invalid", problems=problems)
    accepted = value.get("accepted_lease")
    if value["state"] == "accepted":
        accepted_problems = validate_review_lease(accepted)
        if accepted_problems or accepted.get("edge_id") != value["edge_id"]:
            fail(4, "bad_board", "review edge accepted lease is invalid", problems=accepted_problems)
    elif accepted is not None:
        fail(4, "bad_board", "pending review edge cannot have an accepted lease")
    authorization = value.get("fallback_authorization")
    if authorization is not None:
        auth_fields = {
            "schema", "mission_id", "edge_id", "source_lease_digest",
            "target_lease", "digest",
        }
        if not isinstance(authorization, dict) or set(authorization) != auth_fields:
            fail(4, "bad_board", "review fallback authorization fields are invalid")
        auth_payload = {key: item for key, item in authorization.items() if key != "digest"}
        target = authorization.get("target_lease")
        target_problems = validate_review_lease(target)
        if (
            authorization.get("schema") != "studio-review-fallback-authorization/v1"
            or authorization.get("mission_id") != value["mission_id"]
            or authorization.get("edge_id") != value["edge_id"]
            or authorization.get("source_lease_digest") != original["digest"]
            or target_problems
            or target.get("provider") != "native"
            or target.get("edge_id") != value["edge_id"]
            or authorization.get("digest") != canonical_digest(auth_payload)
        ):
            fail(4, "bad_board", "review fallback authorization is invalid", problems=target_problems)
    return value


def _review_edge_lease_ids(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    reservation = _validate_review_edge_reservation(value)
    leases = [reservation["original_lease"], reservation.get("accepted_lease")]
    authorization = reservation.get("fallback_authorization")
    if authorization:
        leases.append(authorization["target_lease"])
    return {lease["lease_id"] for lease in leases if isinstance(lease, dict)}


def _reserve_review_edge(
    board: dict, *, mission_id: str, review_lease: dict, action: str,
) -> tuple[bool, dict | None]:
    """Fence one review edge while allowing one exact authorized native replan."""
    if action not in {
        "capability-required", "runtime-capability-required",
        "review-lease-replan-required", "dispatch",
    }:
        return False, None
    edges = board.setdefault("review_lease_edges", {})
    edge_id = review_lease["edge_id"]
    for other_edge, binding in edges.items():
        if other_edge != edge_id and review_lease["lease_id"] in _review_edge_lease_ids(binding):
            fail(6, "review_edge_rebind", "review lease id is already reserved for another edge")
    prior = edges.get(edge_id)
    if isinstance(prior, str):
        # Schema-2 boards stored accepted digests directly. Preserve their
        # immutable meaning; they cannot be retroactively treated as pending.
        if prior != review_lease["digest"] or action == "review-lease-replan-required":
            fail(6, "review_edge_rebind", "legacy accepted review edge is immutable")
        return False, None
    if prior is None:
        reservation = {
            "schema": REVIEW_EDGE_RESERVATION_SCHEMA,
            "state": "accepted" if action == "dispatch" else "pending",
            "mission_id": mission_id,
            "edge_id": edge_id,
            "original_lease": review_lease,
            "accepted_lease": review_lease if action == "dispatch" else None,
            "fallback_authorization": None,
        }
    else:
        reservation = _validate_review_edge_reservation(prior)
        if reservation["mission_id"] != mission_id:
            fail(6, "review_edge_rebind", "review edge reservation belongs to another mission")
        if reservation["state"] == "accepted":
            if reservation["accepted_lease"] != review_lease:
                fail(6, "review_edge_rebind", "accepted review edge is immutable")
            if action == "review-lease-replan-required":
                fail(6, "review_edge_rebind", "accepted review edge cannot authorize a fallback replan")
            return False, None
        authorization = reservation.get("fallback_authorization")
        if action == "dispatch":
            expected = authorization["target_lease"] if authorization else reservation["original_lease"]
            if review_lease != expected:
                fail(6, "review_edge_rebind", "dispatch lease differs from the pending reservation")
            reservation = {**reservation, "state": "accepted", "accepted_lease": review_lease}
        elif review_lease != reservation["original_lease"]:
            fail(6, "review_edge_rebind", "pending review edge cannot be rebound")
    authorization = reservation.get("fallback_authorization")
    if action == "review-lease-replan-required":
        if (
            reservation["original_lease"]["owner"] != "studio"
            or reservation["original_lease"]["provider"] != "session-review"
        ):
            fail(6, "review_edge_rebind", "native fallback requires a pending Studio session-review lease")
        expected_authorization = _review_fallback_authorization(
            mission_id, reservation["original_lease"],
        )
        if authorization is not None and authorization != expected_authorization:
            fail(6, "review_edge_rebind", "review fallback authorization conflicts with the reservation")
        reservation = {**reservation, "fallback_authorization": expected_authorization}
        authorization = expected_authorization
    changed = prior != reservation
    if changed:
        edges[edge_id] = reservation
    return changed, authorization


def _load_optional_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        cfg = parse_yaml_subset(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        fail(4, "parse", f"{path}: {exc}")
    problems = _validate_config(cfg)
    if any(problem["severity"] == "error" for problem in problems):
        fail(6, "invalid_config", "config has errors", problems=problems)
    return cfg


def _host_runtime() -> str | None:
    explicit = os.environ.get("STUDIO_HOST_RUNTIME")
    if explicit in AGENT_RUNTIMES:
        return explicit
    if os.environ.get("CLAUDE_CODE") or os.environ.get("CLAUDECODE"):
        return "claude"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    return None


def _validate_runtime_capability_input(value: Any, *, allow_unknown_runtime: bool = False) -> list[str]:
    fields = {
        "schema", "runtime", "version", "advertised_models", "advertised_efforts",
    }
    if not isinstance(value, dict):
        return ["runtime capability must be an object"]
    problems = []
    if set(value) != fields:
        problems.append("runtime capability fields do not match studio-runtime-capability/v1")
    if value.get("schema") != RUNTIME_CAPABILITY_SCHEMA:
        problems.append(f"runtime capability schema must be {RUNTIME_CAPABILITY_SCHEMA}")
    if value.get("runtime") not in AGENT_RUNTIMES and not (
        allow_unknown_runtime and value.get("runtime") is None
    ):
        problems.append("runtime capability runtime must be claude or codex")
    version = value.get("version")
    if version is not None and (not isinstance(version, str) or not version.strip()):
        problems.append("runtime capability version must be null or a non-empty string")
    for field in ("advertised_models", "advertised_efforts"):
        advertised = value.get(field)
        if advertised is not None and (
            not isinstance(advertised, list)
            or any(not isinstance(item, str) or not item.strip() for item in advertised)
        ):
            problems.append(f"runtime capability {field} must be null or a string list")
        elif isinstance(advertised, list) and len(advertised) != len(set(advertised)):
            problems.append(f"runtime capability {field} must be unique")
    return problems


def _canonical_runtime_capability(
    raw: Any, selected_runtime: str | None, verified_host_runtime: str | None,
) -> dict:
    if raw is not None:
        problems = _validate_runtime_capability_input(raw)
        if problems:
            fail(6, "invalid_runtime_capability", "; ".join(problems), problems=problems)
        observed_runtime = raw["runtime"]
        if verified_host_runtime and observed_runtime != verified_host_runtime:
            fail(6, "runtime_capability_conflict", "runtime capability does not match the verified host runtime")
        base = {
            "schema": RUNTIME_CAPABILITY_SCHEMA,
            "runtime": observed_runtime,
            "version": raw["version"],
            "advertised_models": (
                sorted(raw["advertised_models"])
                if raw["advertised_models"] is not None else None
            ),
            "advertised_efforts": (
                sorted(raw["advertised_efforts"])
                if raw["advertised_efforts"] is not None else None
            ),
        }
        verified = True
    else:
        observed_runtime = verified_host_runtime
        base = {
            "schema": RUNTIME_CAPABILITY_SCHEMA,
            "runtime": observed_runtime,
            "version": None,
            "advertised_models": None,
            "advertised_efforts": None,
        }
        verified = observed_runtime in AGENT_RUNTIMES
    return {
        **base,
        "verified": verified,
        "dispatch_allowed": bool(
            selected_runtime is None
            or (verified and observed_runtime == selected_runtime)
        ),
        "digest": canonical_digest(base),
    }


def _profile_validation(profile: dict, runtime_capability: dict | None) -> dict:
    validation = {}
    for field, advertised_field, advertised_source in (
        ("model", "advertised_models", "runtime-advertised-models"),
        ("effort", "advertised_efforts", "runtime-advertised-efforts"),
    ):
        value = profile.get(field)
        if value is None:
            validation[field] = {"status": "not-configured", "source": "session-inherit"}
            continue
        advertised = (
            runtime_capability.get(advertised_field)
            if isinstance(runtime_capability, dict) and runtime_capability.get("verified")
            else None
        )
        if advertised is None:
            validation[field] = {
                "status": "unknown", "source": "runtime-advertisement-unavailable",
            }
        elif value in advertised:
            validation[field] = {"status": "supported", "source": advertised_source}
        else:
            validation[field] = {"status": "unsupported", "source": advertised_source}
    return validation


def _unsupported_profile_fields(profile: dict) -> list[dict]:
    return [
        {
            "field": field,
            "value": profile.get(field),
            "runtime": profile.get("runtime"),
            "source": verdict.get("source"),
        }
        for field, verdict in profile.get("validation", {}).items()
        if verdict.get("status") == "unsupported"
    ]


def _tool_request(cfg: dict, kind: str, override: str | None, need: bool) -> dict:
    providers = WORKER_PROVIDERS if kind == "worker" else REVIEWER_PROVIDERS
    if override is not None:
        if override not in providers:
            fail(6, "invalid_routing_override", f"{kind} override must be one of {', '.join(providers)}")
        return {
            "source": "run-override", "provider": override, "activation": "always",
            "fallback": "stop", "need": need, "explicit": True,
        }
    configured = (cfg.get("tools") or {}).get(kind)
    if not configured:
        return {
            "source": "native", "provider": "native", "activation": "never",
            "fallback": "native", "need": need, "explicit": False,
        }
    provider = configured["provider"]
    active = configured["activation"] == "always" or (
        configured["activation"] == "auto" and need
    )
    if configured["activation"] == "never" or not active:
        provider = "native"
    return {
        "source": "config", "provider": provider,
        "configured_provider": configured["provider"],
        "activation": configured["activation"], "fallback": configured["fallback"],
        "need": need, "explicit": False,
    }


CAPABILITY_REQUIRED_CONTRACTS = {
    "task-worker": {"work-packet/v1", REVIEW_LEASE_SCHEMA, "task-worker.review-permit/v1"},
    "task-github": {"work-packet/v1", REVIEW_LEASE_SCHEMA, "task-worker.review-permit/v1"},
    "session-review": {REVIEW_LEASE_SCHEMA},
}


def validate_routing_capability(value: Any, provider: str, mission_id: str, environment_digest: str) -> list[str]:
    fields = {"schema", "provider", "mission_id", "environment_digest", "status", "contracts"}
    if not isinstance(value, dict):
        return [f"{provider} capability snapshot must be an object"]
    problems = []
    if set(value) != fields:
        problems.append(f"{provider} capability fields do not match the contract")
    if value.get("schema") != CAPABILITY_SNAPSHOT_SCHEMA:
        problems.append(f"{provider} capability schema must be {CAPABILITY_SNAPSHOT_SCHEMA}")
    if value.get("provider") != provider:
        problems.append(f"capability provider must be {provider}")
    if value.get("mission_id") != mission_id:
        problems.append("capability mission_id mismatch")
    if value.get("environment_digest") != environment_digest:
        problems.append("capability environment_digest mismatch")
    if value.get("status") not in ("available", "unavailable"):
        problems.append("capability status must be available or unavailable")
    contracts = value.get("contracts")
    if not isinstance(contracts, list) or any(not isinstance(item, str) or not item.strip() for item in (contracts or [])):
        problems.append("capability contracts must be a string list")
    elif len(contracts) != len(set(contracts)):
        problems.append("capability contracts must be unique")
    elif value.get("status") == "available":
        missing = sorted(CAPABILITY_REQUIRED_CONTRACTS[provider] - set(contracts))
        if missing:
            problems.append(f"available {provider} lacks required contracts: {', '.join(missing)}")
    return problems


def _capability_inputs(raw: Any) -> dict[str, dict]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail(6, "invalid_capability_snapshot", "capabilities must be a snapshot or provider mapping")
    if raw.get("schema") == CAPABILITY_SNAPSHOT_SCHEMA:
        return {raw.get("provider"): raw}
    if any(key not in CAPABILITY_REQUIRED_CONTRACTS for key in raw):
        fail(6, "invalid_capability_snapshot", "capability mapping contains an unsupported provider")
    return raw


def _routing_plan_digest(plan: dict) -> str:
    return canonical_digest({key: value for key, value in plan.items() if key not in {"digest", "plan_id"}})


def validate_routing_plan(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["RoutingPlan must be an object"]
    required = {
        "schema", "plan_id", "mission_id", "environment_digest", "runtime_profile",
        "runtime_capability", "agent_profile", "worker", "reviewer", "review_lease",
        "capability_refs", "probe_targets", "action", "digest",
    }
    problems = []
    if set(value) != required:
        problems.append("RoutingPlan fields do not match studio-routing-plan/v1")
    if value.get("schema") != ROUTING_PLAN_SCHEMA:
        problems.append(f"RoutingPlan.schema must be {ROUTING_PLAN_SCHEMA}")
    for key in ("plan_id", "mission_id"):
        if not isinstance(value.get(key), str) or not SAFE_ID_RE.fullmatch(value.get(key, "")):
            problems.append(f"RoutingPlan.{key} must be a path-safe identifier")
    if not isinstance(value.get("environment_digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("environment_digest", "")):
        problems.append("RoutingPlan.environment_digest must be a sha256 digest")
    if value.get("runtime_profile") not in (*AGENT_RUNTIMES, None):
        problems.append("RoutingPlan.runtime_profile is invalid")
    runtime_capability = value.get("runtime_capability")
    sealed_runtime_fields = {
        "schema", "runtime", "version", "advertised_models", "advertised_efforts",
        "verified", "dispatch_allowed", "digest",
    }
    if not isinstance(runtime_capability, dict) or set(runtime_capability) != sealed_runtime_fields:
        problems.append("RoutingPlan.runtime_capability fields do not match studio-runtime-capability/v1")
    else:
        raw_runtime_capability = {
            key: runtime_capability[key]
            for key in ("schema", "runtime", "version", "advertised_models", "advertised_efforts")
        }
        problems.extend(_validate_runtime_capability_input(
            raw_runtime_capability, allow_unknown_runtime=True,
        ))
        if not isinstance(runtime_capability.get("verified"), bool):
            problems.append("RoutingPlan.runtime_capability.verified must be boolean")
        if not isinstance(runtime_capability.get("dispatch_allowed"), bool):
            problems.append("RoutingPlan.runtime_capability.dispatch_allowed must be boolean")
        if runtime_capability.get("digest") != canonical_digest(raw_runtime_capability):
            problems.append("RoutingPlan.runtime_capability.digest does not match its canonical payload")
    if value.get("review_lease") is not None:
        problems.extend(validate_review_lease(value["review_lease"]))
    expected_digest = _routing_plan_digest(value)
    expected_plan_id = "routing-" + expected_digest.split(":", 1)[1][:16]
    if value.get("plan_id") != expected_plan_id:
        problems.append("RoutingPlan.plan_id does not match its canonical payload")
    if value.get("digest") != expected_digest:
        problems.append("RoutingPlan.digest does not match its canonical payload")
    return problems


def cmd_routing_plan(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    mission_id = validate_safe_id(args.mission_id, "mission_id")
    environment_digest = _review_digest(args.environment_digest, "environment_digest")
    cfg = _load_optional_config(Path(args.config or CONFIG_PATH_DEFAULT))
    raw_runtime_capability = (
        load_json_arg(args.runtime_capability, "runtime capability")
        if args.runtime_capability else None
    )
    host_runtime = args.host_runtime or _host_runtime()
    runtime = args.agent_runtime or (
        raw_runtime_capability.get("runtime")
        if isinstance(raw_runtime_capability, dict) else host_runtime
    )
    runtime_capability = _canonical_runtime_capability(
        raw_runtime_capability, runtime, host_runtime,
    )
    work_need = bool(args.work_need)
    review_lease = load_json_arg(args.review_lease, "review lease") if args.review_lease else None
    if review_lease is not None:
        lease_problems = validate_review_lease(review_lease)
        if lease_problems:
            fail(6, "invalid_review_lease", "; ".join(lease_problems), problems=lease_problems)
    review_need = bool(args.review_need or review_lease is not None)
    if review_need and review_lease is None:
        fail(6, "review_lease_required", "review need requires a canonical review lease")

    worker = _tool_request(cfg, "worker", args.worker, work_need)
    reviewer = _tool_request(cfg, "reviewer", args.reviewer, review_need)
    if not review_need:
        reviewer["provider"] = "native"
    if review_lease and review_lease["owner"] == "task-worker":
        if args.reviewer is not None:
            fail(6, "review_owner_conflict", "worker-owned review forbids a Studio reviewer override")
        if worker["provider"] not in ("task-worker", "task-github"):
            fail(6, "review_owner_conflict", "task-worker review ownership requires an external worker lease")
        reviewer = {
            **reviewer, "provider": review_lease["provider"], "owner": "task-worker",
            "dispatch": False, "source": "review-lease",
        }
    elif review_lease:
        reviewer["owner"] = "studio"
        reviewer["dispatch"] = True
        if reviewer["provider"] != review_lease["provider"]:
            fail(6, "review_provider_mismatch", "Studio reviewer route must match review_lease.provider")
    else:
        reviewer["owner"] = None
        reviewer["dispatch"] = False

    external_targets = []
    if worker["provider"] != "native":
        external_targets.append(worker["provider"])
    if reviewer.get("dispatch") and reviewer["provider"] != "native":
        external_targets.append(reviewer["provider"])
    if len(external_targets) != len(set(external_targets)):
        fail(6, "duplicate_external_lease", "one provider may have only one Studio lease")

    raw_capabilities = load_json_arg(args.capabilities, "capabilities") if args.capabilities else None
    inputs = _capability_inputs(raw_capabilities)
    if set(inputs) - set(external_targets):
        fail(6, "unselected_capability_snapshot", "capabilities may be supplied only for selected external providers")

    capability_refs, probe_targets, statuses = {}, [], {}
    with board_transaction(ws) as board:
        cache = board.setdefault("capability_cache", {})
        for provider in external_targets:
            key = canonical_digest({
                "mission_id": mission_id, "provider": provider,
                "environment_digest": environment_digest,
            })
            cached = cache.get(key)
            supplied = inputs.get(provider)
            if supplied is not None:
                cap_problems = validate_routing_capability(supplied, provider, mission_id, environment_digest)
                if cap_problems:
                    fail(6, "invalid_capability_snapshot", "; ".join(cap_problems), problems=cap_problems)
                sealed = {**supplied, "digest": canonical_digest(supplied)}
                if cached is not None and cached != sealed:
                    fail(6, "capability_snapshot_conflict", "capability result is already pinned for this mission/provider/environment")
                if cached is None:
                    cache[key] = sealed
                    cached = sealed
                    probe_targets.append(provider)
            elif cached is None:
                probe_targets.append(provider)
            if cached is not None:
                capability_refs[provider] = {"key": key, "digest": cached["digest"]}
                statuses[provider] = cached["status"]
            else:
                statuses[provider] = "unknown"

        action = "dispatch"
        review_replan_required = False
        for route in (worker, reviewer):
            provider = route.get("provider")
            if provider == "native" or (route is reviewer and not route.get("dispatch")):
                route["selected"] = "native" if provider == "native" else provider
                route["fallback_used"] = False
                continue
            status = statuses[provider]
            route["capability_status"] = status
            if status == "available":
                route["selected"] = provider
                route["fallback_used"] = False
            elif status == "unknown":
                route["selected"] = None
                route["fallback_used"] = False
                action = "capability-required"
            elif route["explicit"] or route["fallback"] == "stop":
                route["selected"] = None
                route["fallback_used"] = False
                action = "stop"
            elif (
                route is reviewer
                and review_lease
                and review_lease["owner"] == "studio"
                and review_lease["provider"] == "session-review"
            ):
                # A signed session-review lease cannot silently turn into a
                # native review. Require a new canonical native lease instead.
                route["selected"] = None
                route["fallback_used"] = False
                review_replan_required = True
            else:
                route["selected"] = "native"
                route["fallback_used"] = True

        if review_replan_required:
            action = "review-lease-replan-required"

        if (
            review_lease and review_lease["owner"] == "task-worker"
            and action == "dispatch" and worker.get("selected") != worker.get("provider")
        ):
            action = "stop"
        if runtime is not None and not runtime_capability["dispatch_allowed"]:
            action = "runtime-capability-required"
        agent_profile = resolve_agent_profile(
            cfg, runtime, args.role, args.agent, args.ritual, args.step,
            {"model": args.model, "effort": args.effort}, runtime_capability,
        )
        unsupported = _unsupported_profile_fields(agent_profile)
        if unsupported:
            fail(6, "unsupported_runtime_profile", "resolved agent profile is not advertised by the verified runtime", problems=unsupported)
        edge_changed, fallback_authorization = (False, None)
        if review_lease:
            edge_changed, fallback_authorization = _reserve_review_edge(
                board,
                mission_id=mission_id,
                review_lease=review_lease,
                action=action,
            )
        if fallback_authorization:
            reviewer = {**reviewer, "replan": fallback_authorization}
        plan = {
            "schema": ROUTING_PLAN_SCHEMA,
            "plan_id": "pending",
            "mission_id": mission_id,
            "environment_digest": environment_digest,
            "runtime_profile": runtime,
            "runtime_capability": runtime_capability,
            "agent_profile": agent_profile,
            "worker": worker,
            "reviewer": reviewer,
            "review_lease": review_lease,
            "capability_refs": capability_refs,
            "probe_targets": sorted(probe_targets),
            "action": action,
        }
        digest = _routing_plan_digest(plan)
        plan["plan_id"] = "routing-" + digest.split(":", 1)[1][:16]
        plan["digest"] = _routing_plan_digest(plan)
        plans = board.setdefault("routing_plans", {})
        changed = plan["digest"] not in plans
        plans.setdefault(plan["digest"], plan)
    ok(routing_plan=plan, changed=changed or edge_changed)


# --------------------------------------------------------------------------- #
# workflow adapter — validate and hand off; never import external workflow APIs
# --------------------------------------------------------------------------- #
WORK_PACKET_FIELDS = frozenset((
    "schema", "track_id", "objective", "acceptance_criteria", "context_ref",
    "digest", "quality_plan_ref", "constraints", "budget_reservation_id", "gates", "executor",
))
RESULT_ENVELOPE_FIELDS = frozenset((
    "status", "external_ref", "artifact_refs", "evidence_refs", "context_delta_refs",
    "telemetry", "gates", "failure_class",
))
CAPABILITY_FIELDS = frozenset(("schema", "source", "catalog", "doctor", "preflight"))
TASK_GITHUB_REQUIRED_SKILLS = frozenset((
    "task-github:start", "task-github:run", "task-github:done", "task-github:doctor",
))


def validate_work_packet(packet: Any) -> list[str]:
    if not isinstance(packet, dict):
        return ["WorkPacket must be an object"]
    problems = []
    if set(packet) != WORK_PACKET_FIELDS:
        problems.append("WorkPacket fields do not match the binding contract")
    if packet.get("schema") != 1:
        problems.append("WorkPacket.schema must be 1")
    for key in ("track_id", "quality_plan_ref", "budget_reservation_id"):
        if not isinstance(packet.get(key), str) or not SAFE_ID_RE.fullmatch(packet.get(key, "")):
            problems.append(f"WorkPacket.{key} must be a path-safe identifier")
    if not isinstance(packet.get("objective"), str) or not packet.get("objective", "").strip():
        problems.append("WorkPacket.objective must be a non-empty string")
    if not isinstance(packet.get("context_ref"), str) or not SAFE_ID_RE.fullmatch(packet.get("context_ref", "")):
        problems.append("WorkPacket.context_ref must be a path-safe identifier")
    if not isinstance(packet.get("digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", packet.get("digest", "")):
        problems.append("WorkPacket.digest must be a sha256 digest")
    criteria = packet.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or any(not isinstance(item, str) or not item.strip() for item in criteria):
        problems.append("WorkPacket.acceptance_criteria must be a non-empty string list")
    if not isinstance(packet.get("constraints"), dict):
        problems.append("WorkPacket.constraints must be an object")
    else:
        review_lease = packet["constraints"].get("review_lease")
        if review_lease is not None:
            problems.extend(validate_review_lease(review_lease))
    gates = packet.get("gates")
    if not isinstance(gates, list) or any(not isinstance(gate, str) or not gate.strip() for gate in gates) or len(gates) != len(set(gates or [])):
        problems.append("WorkPacket.gates must be a unique string list")
    if packet.get("executor") not in WORKER_PROVIDERS:
        problems.append("WorkPacket.executor must be native, task-worker, or task-github")
    return problems


def validate_result_envelope(envelope: Any) -> list[str]:
    if not isinstance(envelope, dict):
        return ["ResultEnvelope must be an object"]
    problems = []
    if set(envelope) != RESULT_ENVELOPE_FIELDS:
        problems.append("ResultEnvelope fields do not match the binding contract")
    if envelope.get("status") not in ("succeeded", "failed", "waiting_gate", "cancelled"):
        problems.append("ResultEnvelope.status is invalid")
    if envelope.get("external_ref") is not None and (
        not isinstance(envelope.get("external_ref"), str) or not envelope.get("external_ref", "").strip()
    ):
        problems.append("ResultEnvelope.external_ref must be null or non-empty")
    for key in ("artifact_refs", "context_delta_refs"):
        value = envelope.get(key)
        if not isinstance(value, list) or any(not isinstance(ref, str) or not ref.strip() for ref in (value or [])):
            problems.append(f"ResultEnvelope.{key} must be a string list")
    if not isinstance(envelope.get("evidence_refs"), list):
        problems.append("ResultEnvelope.evidence_refs must be a list")
    telemetry = envelope.get("telemetry")
    if not isinstance(telemetry, dict) or set(telemetry) != TELEMETRY_KEYS:
        problems.append("ResultEnvelope.telemetry must contain tokens, elapsed_ms, avoidable_owner_questions")
    else:
        tokens = telemetry.get("tokens")
        if tokens is not None and (not _number(tokens) or tokens < 0):
            problems.append("telemetry.tokens must be a non-negative number or null")
        if not _number(telemetry.get("elapsed_ms")) or telemetry.get("elapsed_ms", -1) < 0:
            problems.append("telemetry.elapsed_ms must be non-negative")
        questions = telemetry.get("avoidable_owner_questions")
        if not isinstance(questions, int) or isinstance(questions, bool) or questions < 0:
            problems.append("telemetry.avoidable_owner_questions must be a non-negative integer")
    gates = envelope.get("gates")
    if not isinstance(gates, list):
        problems.append("ResultEnvelope.gates must be a list")
    else:
        ids = []
        for index, gate in enumerate(gates):
            if not isinstance(gate, dict) or set(gate) != {"id", "status", "evidence_ref"}:
                problems.append(f"ResultEnvelope.gates[{index}] must contain id, status, evidence_ref")
                continue
            ids.append(gate.get("id"))
            if not isinstance(gate.get("id"), str) or not gate.get("id", "").strip():
                problems.append(f"ResultEnvelope.gates[{index}].id must be non-empty")
            if gate.get("status") not in ("passed", "waiting", "failed"):
                problems.append(f"ResultEnvelope.gates[{index}].status is invalid")
            if gate.get("evidence_ref") is not None and not isinstance(gate.get("evidence_ref"), str):
                problems.append(f"ResultEnvelope.gates[{index}].evidence_ref must be string or null")
        if len(ids) != len(set(ids)):
            problems.append("ResultEnvelope gate ids must be unique")
    failure = envelope.get("failure_class")
    if failure is not None and (not isinstance(failure, str) or not failure.strip()):
        problems.append("ResultEnvelope.failure_class must be null or non-empty")
    if envelope.get("status") == "failed" and failure is None:
        problems.append("failed ResultEnvelope requires failure_class")
    if envelope.get("status") == "succeeded" and failure is not None:
        problems.append("succeeded ResultEnvelope requires failure_class=null")
    return problems


def validate_capability_snapshot(snapshot: Any) -> list[str]:
    if not isinstance(snapshot, dict):
        return ["capability snapshot must be an object"]
    problems = []
    if set(snapshot) != CAPABILITY_FIELDS:
        problems.append("capability snapshot fields must be schema, source, catalog, doctor, preflight")
    if snapshot.get("schema") != 1 or snapshot.get("source") != "agent-visible-skill-catalog":
        problems.append("capability snapshot requires schema=1 and agent-visible-skill-catalog source")
    if not isinstance(snapshot.get("catalog"), list) or any(not isinstance(item, str) for item in snapshot.get("catalog", [])):
        problems.append("capability catalog must be a string list")
    for key in ("doctor", "preflight"):
        check = snapshot.get(key)
        if not isinstance(check, dict) or set(check) != {"mode", "status"}:
            problems.append(f"{key} must contain mode and status")
        elif check.get("mode") != "read-only" or check.get("status") not in ("pass", "fail", "unavailable", "unknown"):
            problems.append(f"{key} requires mode=read-only and a valid status")
    return problems


def task_github_available(snapshot: dict) -> bool:
    return (
        TASK_GITHUB_REQUIRED_SKILLS.issubset(set(snapshot.get("catalog") or []))
        and snapshot.get("doctor", {}).get("status") == "pass"
        and snapshot.get("preflight", {}).get("status") == "pass"
    )


def cmd_workflow_validate_packet(args: argparse.Namespace) -> None:
    packet = load_json_arg(args.json, "WorkPacket")
    problems = validate_work_packet(packet)
    if problems:
        fail(6, "invalid_work_packet", "; ".join(problems), problems=problems)
    ok(work_packet=packet)


def cmd_workflow_validate_result(args: argparse.Namespace) -> None:
    envelope = load_json_arg(args.json, "ResultEnvelope")
    problems = validate_result_envelope(envelope)
    if problems:
        fail(6, "invalid_result_envelope", "; ".join(problems), problems=problems)
    ok(result_envelope=envelope)


def cmd_workflow_dispatch(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    packet = load_json_arg(args.packet, "WorkPacket")
    plan = load_json_arg(args.plan, "QualityPlan")
    problems = validate_work_packet(packet)
    if problems:
        fail(6, "invalid_work_packet", "; ".join(problems), problems=problems)
    plan_problems = validate_quality_plan(plan)
    if plan_problems:
        fail(6, "invalid_quality_plan", "; ".join(plan_problems), problems=plan_problems)
    if plan["id"] != packet["quality_plan_ref"]:
        fail(6, "quality_plan_mismatch", "WorkPacket quality_plan_ref does not match QualityPlan.id")
    lease_id = validate_safe_id(args.lease_id, "lease_id")
    routing_plan = load_json_arg(args.routing_plan, "RoutingPlan") if args.routing_plan else None
    if routing_plan is not None:
        routing_problems = validate_routing_plan(routing_plan)
        if routing_problems:
            fail(6, "invalid_routing_plan", "; ".join(routing_problems), problems=routing_problems)
    review_lease = packet["constraints"].get("review_lease")
    if (packet["executor"] == "task-worker" or review_lease is not None) and routing_plan is None:
        fail(6, "routing_plan_required", "task-worker and canonical review leases require a RoutingPlan")

    context_path = _context_path(ws, "pack", packet["context_ref"])
    try:
        stored_pack = json.loads(context_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(6, "context_pack_required", f"cannot load ContextPack {packet['context_ref']}: {exc}")
    canonical_pack = _prepare_context_object("pack", stored_pack)
    if canonical_pack["id"] != packet["context_ref"]:
        fail(6, "context_ref_mismatch", "stored ContextPack id does not match WorkPacket.context_ref")
    if canonical_pack["digest"] != packet["digest"]:
        fail(6, "context_digest_mismatch", "WorkPacket.digest does not match the stored canonical ContextPack")

    dispatch_binding = {
        "quality_plan": {
            "id": plan["id"],
            "digest": canonical_digest(plan),
            "canonical": json.loads(json.dumps(plan, ensure_ascii=False, sort_keys=True)),
        },
        "context_pack": {
            "ref": canonical_pack["id"],
            "digest": canonical_pack["digest"],
        },
        "routing_plan": (
            {"plan_id": routing_plan["plan_id"], "digest": routing_plan["digest"]}
            if routing_plan else None
        ),
        "review_lease": (
            {"lease_id": review_lease["lease_id"], "digest": review_lease["digest"]}
            if review_lease else None
        ),
    }

    snapshot = None
    external_ready = False
    selected_provider = "native"
    if routing_plan is not None:
        if args.capabilities is not None:
            fail(6, "capability_snapshot_already_pinned", "RoutingPlan dispatch cannot accept a second capability snapshot")
        runtime_capability = routing_plan["runtime_capability"]
        if routing_plan["runtime_profile"] is not None and not (
            runtime_capability.get("verified")
            and runtime_capability.get("dispatch_allowed")
            and runtime_capability.get("runtime") == routing_plan["runtime_profile"]
        ):
            fail(6, "runtime_not_dispatchable", "RoutingPlan runtime is not verified for the current host harness")
        if routing_plan["action"] != "dispatch":
            fail(6, "routing_not_dispatchable", f"RoutingPlan action is {routing_plan['action']}")
        route_worker = routing_plan["worker"]
        selected_provider = route_worker.get("selected")
        if selected_provider != packet["executor"]:
            fail(6, "routing_executor_mismatch", "WorkPacket.executor differs from RoutingPlan worker selection")
        if routing_plan.get("review_lease") != review_lease:
            fail(6, "review_lease_mismatch", "WorkPacket review lease differs from RoutingPlan")
        external_ready = selected_provider in ("task-worker", "task-github")
    elif packet["executor"] == "task-github":
        if args.capabilities is None:
            snapshot = {
                "schema": 1, "source": "agent-visible-skill-catalog", "catalog": [],
                "doctor": {"mode": "read-only", "status": "unknown"},
                "preflight": {"mode": "read-only", "status": "unknown"},
            }
        else:
            snapshot = load_json_arg(args.capabilities, "capability snapshot")
        capability_problems = validate_capability_snapshot(snapshot)
        if capability_problems:
            fail(6, "invalid_capability_snapshot", "; ".join(capability_problems), problems=capability_problems)
        external_ready = task_github_available(snapshot)
        selected_provider = "task-github" if external_ready else "native"

    selected = "external" if external_ready else "native"
    fallback = routing_plan is None and packet["executor"] == "task-github" and selected == "native"
    with board_transaction(ws) as board:
        if routing_plan is not None:
            pinned = board.setdefault("routing_plans", {}).get(routing_plan["digest"])
            if pinned != routing_plan:
                fail(6, "routing_plan_unpinned", "dispatch requires the canonical RoutingPlan pinned on this board")
        lease, _ = _claim_lease(
            board, packet["track_id"], lease_id, selected, packet["budget_reservation_id"]
        )
        existing_binding = lease.get("dispatch_binding")
        if existing_binding is not None and existing_binding != dispatch_binding:
            fail(6, "dispatch_binding_mismatch", "an existing lease cannot be rebound to another QualityPlan or ContextPack")
        if lease.get("recovery_required"):
            fail(6, "recovery_required", "failed dispatch must resume or cancel-release before dispatching again")
        lease["dispatch_binding"] = dispatch_binding
        lease["capability_snapshot"] = snapshot
        lease["requested_executor"] = packet["executor"]
        lease["selected_provider"] = selected_provider
        lease["review_ownership"] = review_lease["owner"] if review_lease else None
        lease, _ = _transition_lease(board, packet["track_id"], lease_id, "running")

    handoff = None
    if selected == "external":
        handoff = {
            "kind": "separate-worker-handoff",
            "executor": selected_provider,
            "work_packet": packet,
            "skill_catalog": sorted(TASK_GITHUB_REQUIRED_SKILLS) if selected_provider == "task-github" else [],
            "preflight": "read-only-complete",
            "state_contract": "return external_ref, coarse status, and ResultEnvelope only",
            "review_ownership": (
                "externally-owned" if review_lease and review_lease["owner"] == "studio"
                else "worker-owned" if review_lease else "none"
            ),
            "review_permit": review_lease,
        }
    ok(
        selected_executor=selected,
        selected_provider=selected_provider,
        fallback=fallback,
        fallback_reason="pre-dispatch capability unavailable or unknown" if fallback else None,
        lease=lease,
        worker_handoff=handoff,
    )


def _result_gates_pass(packet: dict, envelope: dict) -> bool:
    by_id = {gate["id"]: gate for gate in envelope.get("gates", []) if isinstance(gate, dict) and "id" in gate}
    return all(
        gate_id in by_id
        and by_id[gate_id].get("status") == "passed"
        and isinstance(by_id[gate_id].get("evidence_ref"), str)
        and bool(by_id[gate_id]["evidence_ref"].strip())
        for gate_id in packet["gates"]
    )


def cmd_workflow_result(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    packet = load_json_arg(args.packet, "WorkPacket")
    plan = load_json_arg(args.plan, "QualityPlan")
    envelope = load_json_arg(args.json, "ResultEnvelope")
    routing_plan = load_json_arg(args.routing_plan, "RoutingPlan") if args.routing_plan else None
    packet_problems = validate_work_packet(packet)
    result_problems = validate_result_envelope(envelope)
    if packet_problems:
        fail(6, "invalid_work_packet", "; ".join(packet_problems), problems=packet_problems)
    if result_problems:
        fail(6, "invalid_result_envelope", "; ".join(result_problems), problems=result_problems)
    if routing_plan is not None:
        routing_problems = validate_routing_plan(routing_plan)
        if routing_problems:
            fail(6, "invalid_routing_plan", "; ".join(routing_problems), problems=routing_problems)
    plan_problems = validate_quality_plan(plan)
    if plan_problems:
        fail(6, "invalid_quality_plan", "; ".join(plan_problems), problems=plan_problems)
    if plan.get("id") != packet["quality_plan_ref"]:
        fail(6, "quality_plan_mismatch", "WorkPacket quality_plan_ref does not match QualityPlan.id")
    evaluation = evaluate_quality(plan, envelope["evidence_refs"], envelope["telemetry"])
    provided_plan_digest = canonical_digest(plan)
    lease_id = validate_safe_id(args.lease_id, "lease_id")
    gates_passed = _result_gates_pass(packet, envelope)
    ready = bool(
        envelope["status"] == "succeeded"
        and envelope["artifact_refs"]
        and evaluation["complete"]
        and gates_passed
    )

    with board_transaction(ws) as board:
        track = board.setdefault("tracks", {}).get(packet["track_id"])
        lease = track and track.get("executor_lease")
        if not lease:
            fail(4, "lease_not_found", f"no lease for track {packet['track_id']}")
        if lease.get("lease_id") != lease_id:
            fail(6, "stale_lease", "ResultEnvelope lease_id is stale")
        if lease.get("budget_reservation_id") != packet["budget_reservation_id"]:
            fail(6, "reservation_mismatch", "ResultEnvelope packet uses another reservation")
        binding = lease.get("dispatch_binding")
        if not isinstance(binding, dict):
            fail(6, "dispatch_binding_required", "workflow result requires the canonical dispatch binding")
        quality_binding = binding.get("quality_plan") or {}
        if (
            quality_binding.get("id") != packet["quality_plan_ref"]
            or quality_binding.get("digest") != provided_plan_digest
            or quality_binding.get("canonical") != json.loads(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        ):
            fail(6, "quality_plan_binding_mismatch", "ResultEnvelope QualityPlan differs from the canonical dispatch binding")
        context_binding = binding.get("context_pack") or {}
        if context_binding != {"ref": packet["context_ref"], "digest": packet["digest"]}:
            fail(6, "context_binding_mismatch", "ResultEnvelope WorkPacket context differs from the dispatch binding")
        routing_binding = binding.get("routing_plan")
        if routing_binding is not None:
            if routing_plan is None:
                fail(6, "routing_plan_required", "result requires the canonical RoutingPlan used at dispatch")
            if routing_binding != {"plan_id": routing_plan["plan_id"], "digest": routing_plan["digest"]}:
                fail(6, "routing_plan_binding_mismatch", "ResultEnvelope RoutingPlan differs from dispatch")
        elif routing_plan is not None:
            fail(6, "routing_plan_binding_mismatch", "legacy dispatch cannot accept a later RoutingPlan")
        review_lease = packet["constraints"].get("review_lease")
        expected_review_binding = (
            {"lease_id": review_lease["lease_id"], "digest": review_lease["digest"]}
            if review_lease else None
        )
        if binding.get("review_lease") != expected_review_binding:
            fail(6, "review_lease_binding_mismatch", "ResultEnvelope review lease differs from dispatch")
        if lease.get("executor") == "external" and not envelope.get("external_ref"):
            fail(6, "external_ref_required", "external executor ResultEnvelope requires external_ref")
        if lease.get("executor") == "native" and envelope.get("external_ref") is not None:
            fail(6, "external_ref_forbidden", "native executor ResultEnvelope requires external_ref=null")
        if lease.get("result_envelope") == envelope:
            ok(readyForIntegration=ready, evaluation=evaluation, gates_passed=gates_passed, lease=lease, changed=False)
        if lease.get("recovery_required"):
            fail(6, "recovery_required", "resume or cancel-release the prior failed result before ingesting another")

        lease["result_envelope"] = envelope
        lease["external_ref"] = envelope.get("external_ref")
        lease["coarse_status"] = envelope["status"]
        if envelope["status"] == "failed":
            if lease.get("state") in ("running", "waiting_gate"):
                lease, _ = _transition_lease(board, packet["track_id"], lease_id, "failed")
            elif lease.get("state") != "failed":
                fail(6, "invalid_lease_transition", "failed result requires a running or waiting lease")
            # Failed remains replacement-fenced. Fallback is forbidden until
            # explicit resume or cancel-confirm+release.
            lease["coarse_status"] = "failed"
            lease["recovery_required"] = True
        elif envelope["status"] == "waiting_gate" or (envelope["status"] == "succeeded" and not ready):
            if lease.get("state") == "running":
                lease, _ = _transition_lease(board, packet["track_id"], lease_id, "waiting_gate")
            lease["coarse_status"] = "waiting_gate" if envelope["status"] == "waiting_gate" else "incomplete"
        elif envelope["status"] == "cancelled":
            if lease.get("state") in ACTIVE_LEASE_STATES:
                lease, _ = _transition_lease(board, packet["track_id"], lease_id, "cancelled")
            reservation = _budget_reservations(board["budget"])[packet["budget_reservation_id"]]
            if reservation.get("status") in ("reserved", "dispatched"):
                reservation["status"] = "released"
            lease["coarse_status"] = "cancelled"
        elif ready:
            reservation = _budget_reservations(board["budget"])[packet["budget_reservation_id"]]
            tokens = envelope["telemetry"]["tokens"]
            if reservation.get("status") == "dispatched":
                reservation["status"] = "settled"
                reservation["settled_tokens"] = tokens
                board["budget"]["spent_tokens"] = int(board["budget"].get("spent_tokens") or 0) + tokens
            elif reservation.get("status") != "settled" or reservation.get("settled_tokens") != tokens:
                fail(6, "invalid_budget_transition", "successful result cannot settle reservation")
            lease, _ = _transition_lease(board, packet["track_id"], lease_id, "succeeded")
            lease["coarse_status"] = "succeeded"
    ok(readyForIntegration=ready, evaluation=evaluation, gates_passed=gates_passed, lease=lease, changed=True)


def cmd_workflow_recover(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    track_id = validate_safe_id(args.track_id, "track_id")
    lease_id = validate_safe_id(args.lease_id, "lease_id")
    with board_transaction(ws) as board:
        track = board.setdefault("tracks", {}).get(track_id)
        lease = track and track.get("executor_lease")
        if not lease:
            fail(4, "lease_not_found", f"no lease for track {track_id}")
        if lease.get("lease_id") != lease_id:
            fail(6, "stale_lease", "recovery lease_id is stale")
        if not lease.get("recovery_required"):
            fail(6, "recovery_not_required", "lease has no failed result awaiting recovery")
        if args.action == "resume":
            prior_result = lease.pop("result_envelope", None)
            if prior_result is not None:
                lease.setdefault("result_history", []).append(prior_result)
            if lease.get("state") == "failed":
                reservation = _budget_reservations(board["budget"])[lease["budget_reservation_id"]]
                if reservation.get("status") != "dispatched":
                    fail(6, "invalid_budget_transition", "failed lease resume requires dispatched budget")
                lease["state"] = "running"
            lease["coarse_status"] = "running"
            lease["recovery_required"] = False
            lease["resume_count"] = int(lease.get("resume_count") or 0) + 1
            fallback_allowed = False
        else:
            if lease.get("state") in ACTIVE_LEASE_STATES:
                lease, _ = _transition_lease(board, track_id, lease_id, "cancelled")
            elif lease.get("state") == "failed":
                lease["state"] = "cancelled"
                lease["cancel_confirmed"] = True
                lease["recovery_required"] = False
            reservation = _budget_reservations(board["budget"])[lease["budget_reservation_id"]]
            if reservation.get("status") in ("reserved", "dispatched"):
                reservation["status"] = "released"
            lease["recovery_required"] = False
            lease["coarse_status"] = "cancelled"
            fallback_allowed = True
    ok(lease=lease, action=args.action, native_fallback_allowed=fallback_allowed)


def cmd_workflow_promote(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    candidate_id = validate_safe_id(args.candidate_id, "candidate_id")
    path = ws / "context" / "outbox" / f"{candidate_id}.json"
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(4, "promotion_not_found", f"cannot load promotion candidate: {exc}")
    if args.provider_status in ("unavailable", "unknown"):
        ok(provider="local-outbox", candidate=candidate, handoff=None, changed=False)
    if not args.owner_approved:
        fail(6, "owner_gate_required", "wiki promotion requires explicit owner approval")
    candidate["status"] = "ready_for_provider"
    candidate["digest"] = canonical_digest({key: value for key, value in candidate.items() if key != "digest"})
    atomic_write_text(path, json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
    ok(
        provider="wiki-markdown",
        candidate=candidate,
        handoff={
            "kind": "agent-visible-provider-handoff",
            "skill": "wiki-markdown:wiki",
            "action": "capture",
            "candidate_ref": str(path),
        },
        changed=True,
    )


# --------------------------------------------------------------------------- #
# native execution control — permit/profile/claim/receipt/evidence/closeout
# --------------------------------------------------------------------------- #
def _execution_contract() -> tuple[dict, Path]:
    try:
        return load_execution_contract(plugin_root())
    except ExecutionControlError as exc:
        fail(6, exc.code, exc.message, **exc.details)


def _execution_failure(exc: ExecutionControlError) -> None:
    fail(6, exc.code, exc.message, **exc.details)


def cmd_execution_contract(args: argparse.Namespace) -> None:
    contract, path = _execution_contract()
    results = []
    try:
        for case in contract["golden_cases"]:
            actual = evaluate_golden_case(contract, case)
            if actual != case["expected"]:
                raise ExecutionControlError(
                    "golden_case_failed",
                    f"canonical golden case failed: {case['id']}",
                    expected=case["expected"],
                    actual=actual,
                )
            results.append(case["id"])
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(
        schema=contract["schema"],
        digest=contract["digest"],
        expected_digest=EXECUTION_CONTRACT_DIGEST,
        path=str(path),
        golden_cases=results,
    )


def cmd_execution_golden(args: argparse.Namespace) -> None:
    contract, _ = _execution_contract()
    selected = [
        case for case in contract["golden_cases"]
        if args.case == "all" or case["id"] == args.case
    ]
    if not selected:
        fail(4, "golden_case_not_found", f"golden case not found: {args.case}")
    results = {}
    try:
        for case in selected:
            actual = evaluate_golden_case(contract, case)
            if actual != case["expected"]:
                raise ExecutionControlError(
                    "golden_case_failed",
                    f"canonical golden case failed: {case['id']}",
                    expected=case["expected"],
                    actual=actual,
                )
            results[case["id"]] = actual
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], results=results)


def cmd_execution_dispatch(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    request = load_json_arg(args.json, "native execution dispatch")
    try:
        with board_transaction(ws) as board:
            state = ensure_execution_state(board)
            decision = execution_dispatch(state, contract, request)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], decision=decision)


def cmd_execution_capability(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    snapshot = load_json_arg(args.json, "capability snapshot")
    try:
        with board_transaction(ws) as board:
            state = ensure_execution_state(board)
            snapshot, changed = record_capability_snapshot(state, contract, snapshot)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], snapshot=snapshot, changed=changed)


def cmd_execution_result(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    request = load_json_arg(args.json, "native execution result")
    try:
        with board_transaction(ws) as board:
            state = ensure_execution_state(board)
            decision = execution_record_result(state, contract, request)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], decision=decision)


def cmd_execution_evidence(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    evidence = load_json_arg(args.json, "verification evidence")
    try:
        with board_transaction(ws) as board:
            state = ensure_execution_state(board)
            decision = execution_record_evidence(state, contract, evidence)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], decision=decision)


def cmd_execution_invalidate(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    evidence_id = validate_safe_id(args.evidence_id, "evidence_id")
    change = load_json_arg(args.change, "evidence change")
    try:
        with board_transaction(ws) as board:
            state = ensure_execution_state(board)
            decision = execution_invalidate_evidence(state, contract, evidence_id, change)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], decision=decision)


def cmd_execution_closeout(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    receipt = load_json_arg(args.receipt, "closeout receipt")
    applicability = load_json_arg(args.applicability, "closeout applicability")
    try:
        with board_transaction(ws) as board:
            state = ensure_execution_state(board)
            decision = execution_record_closeout(state, contract, receipt, applicability)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], decision=decision)


def cmd_execution_summary(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    contract, _ = _execution_contract()
    mission_id = validate_safe_id(args.mission_id, "mission_id")
    try:
        board = load_board(ws)
        state = ensure_execution_state(board)
        summary = execution_efficiency_summary(state, mission_id)
        validate_execution_instance(contract, "efficiency-summary", summary)
    except ExecutionControlError as exc:
        _execution_failure(exc)
    ok(contract_digest=contract["digest"], summary=summary, read_only=True)


# --------------------------------------------------------------------------- #
# board / evidence (read-only)
# --------------------------------------------------------------------------- #
def cmd_board(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    ok(board=load_board(ws))


# --------------------------------------------------------------------------- #
# mode — producer "on shift" state
# --------------------------------------------------------------------------- #
def cmd_mode(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    if args.mcmd == "status":
        ok(mode=mode_state(load_board(ws)))
    with board_transaction(ws) as board:
        mode = mode_state(board)
        if args.mcmd == "start" and not mode.get("active"):
            mode["active"] = True
            mode["started_at"] = now_stamp()
            mode["ended_at"] = None
        elif args.mcmd == "end" and mode.get("active"):
            mode["active"] = False
            mode["ended_at"] = now_stamp()
    ok(mode=mode)


def cmd_evidence(args: argparse.Namespace) -> None:
    """Aggregate the delta evidence across recorded runs — the baseline tally.

    delta==0 across a team run is the design's 'theatre' verdict signal.
    """
    ws = workspace(args)
    require_workspace(ws)
    board = load_board(ws)
    total_valid = 0
    aborted_runs = 0
    for r in board.get("runs", []):
        if r.get("aborted"):
            aborted_runs += 1
            continue
        total_valid += int(r.get("valid_deltas") or 0)
    ok(
        total_valid_deltas=total_valid,
        runs=len(board.get("runs", [])),
        aborted_runs=aborted_runs,
        theatre=(total_valid == 0 and len(board.get("runs", [])) > aborted_runs),
    )


# --------------------------------------------------------------------------- #
# cast — deterministic default crew selection for the producer
# --------------------------------------------------------------------------- #
def _crew_dir_for_cast(ws: Path) -> Path:
    live = ws / "crew"
    return live if live.is_dir() else plugin_root() / "crew"


def cmd_cast_list(args: argparse.Namespace) -> None:
    ok(kinds=sorted(CASTS), aliases=CAST_ALIASES)


def cmd_cast_suggest(args: argparse.Namespace) -> None:
    kind = CAST_ALIASES.get(args.kind, args.kind)
    spec = CASTS.get(kind)
    if spec is None:
        fail(
            6,
            "unknown_cast",
            f"unknown cast kind: {args.kind}",
            kinds=sorted(CASTS),
            aliases=CAST_ALIASES,
        )

    crew_dir = _crew_dir_for_cast(workspace(args))
    crew = list(spec["crew"])
    participants = [name for name in crew if name != "critic"]
    personas = []
    missing = []
    for name in participants:
        path = crew_dir / f"{name}.md"
        if not path.is_file():
            missing.append(name)
            continue
        persona = read_persona(path)
        if persona.get("activation") != "always":
            continue
        personas.append(persona)
    if missing:
        fail(6, "missing_crew", "cast references missing crew persona(s)", missing=missing)

    ok(
        kind=kind,
        ritual=spec["ritual"],
        crew=crew,
        participants=[p["name"] for p in personas],
        critic=("critic" in crew or spec["ritual"] in ("brainstorm", "pairing")),
        personas=personas,
        missing=[],
        tool_hints=spec.get("tool_hints") or [],
    )


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="studio")
    p.add_argument("--workspace", help="workspace dir (default: .studio/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="scaffold a studio workspace")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("mission", help="mission-contract ops")
    msub = sp.add_subparsers(dest="mcmd", required=True)
    mv = msub.add_parser("validate", help="check a mission contract has required fields")
    mv.add_argument("path")
    mv.set_defaults(func=cmd_mission_validate)

    sp = sub.add_parser("backlog", help="backlog ops")
    bsub = sp.add_subparsers(dest="bcmd", required=True)
    bc = bsub.add_parser("check", help="enforce the KPI-link rule on every item")
    bc.set_defaults(func=cmd_backlog_check)

    sp = sub.add_parser("budget", help="set the mission budget ledger caps")
    sp.add_argument("--set-total", type=int, help="total token cap (enables the exhausted→paused gate)")
    sp.add_argument("--set-per-run", type=int, help="advisory per-run token cap the producer applies at convene")
    sp.set_defaults(func=cmd_budget)
    blife = sp.add_subparsers(dest="lifecycle")
    for action in ("reserve", "dispatch", "settle", "release"):
        bp = blife.add_parser(action, help=f"{action} an idempotent budget reservation")
        bp.add_argument("reservation_id")
        bp.add_argument("--lease-id", required=True)
        if action in ("reserve", "settle"):
            bp.add_argument("--tokens", type=int, required=True)
        bp.set_defaults(func=cmd_budget_lifecycle)

    sp = sub.add_parser("run", help="run ops")
    rsub = sp.add_subparsers(dest="rcmd", required=True)
    rr = rsub.add_parser("record", help="record a run output → minutes + board ledger")
    rr.add_argument("--json", help="run output JSON (inline, @file, or - for stdin)")
    rr.add_argument("--id", help="override run id (else derived from output/clock)")
    rr.add_argument("--track", help="track slug this run belongs to (producer-owned)")
    rr.add_argument("--receipt-log", help="optional JSONL receipt sink; append failure is warning-only")
    rr.set_defaults(func=cmd_run_record)

    sp = sub.add_parser("review", help="stable review-cycle state and evidence reuse")
    rvsub = sp.add_subparsers(dest="review_command", required=True)
    ro = rvsub.add_parser("open", help="open an idempotent review cycle bound to one track")
    ro.add_argument("--json", required=True, help="review-cycle binding JSON")
    ro.set_defaults(func=cmd_review_open)
    revent = rvsub.add_parser("event", help="apply one idempotent review-cycle event")
    revent.add_argument("cycle_id")
    revent.add_argument("--json", required=True, help="review event JSON")
    revent.set_defaults(func=cmd_review_event)
    for action, helptext in (
        ("status", "read the full cycle ledger"),
        ("handoff", "emit only active findings and valid evidence pins"),
        ("summary", "emit cycle cost and QA counters"),
    ):
        rp = rvsub.add_parser(action, help=helptext)
        rp.add_argument("cycle_id")
        rp.set_defaults(func=cmd_review_read)
    rec = rvsub.add_parser("evidence-check", help="decide whether pinned evidence survives a change")
    rec.add_argument("--evidence", required=True, help="evidence pin JSON")
    rec.add_argument("--change", required=True, help="change impact JSON")
    rec.set_defaults(func=cmd_review_evidence_check)
    rnext = rvsub.add_parser("plan-next", help="plan the next allowed physical QA action")
    rnext.add_argument("cycle_id")
    rnext.add_argument("--head", required=True)
    rnext.add_argument("--command-digest", required=True)
    rnext.add_argument("--environment-digest", required=True)
    rnext.add_argument("--tool-version", required=True)
    rnext.add_argument("--changed-path", action="append")
    rnext.add_argument("--allowed-command", action="append")
    rnext.add_argument("--full-qa-reason", choices=sorted(FULL_QA_REASONS))
    rnext.add_argument("--integration-gate", action="store_true")
    rnext.add_argument("--telemetry-policy", choices=("legacy", "fail-closed"), default="legacy")
    rnext.set_defaults(func=cmd_review_plan_next)

    sp = sub.add_parser("config", help="agent model/effort policy (.studio.yml)")
    csub = sp.add_subparsers(dest="ccmd", required=True)
    for name, helptext in (("scaffold", "write a default .studio.yml"),
                           ("validate", "check the config"),
                           ("get", "parse the config → JSON (for the producer to pass to brokers)"),
                           ("resolve", "resolve one agent profile with provider overlays")):
        cp = csub.add_parser(name, help=helptext)
        cp.add_argument("--path", help=f"config path (default {CONFIG_PATH_DEFAULT})")
        if name == "scaffold":
            cp.add_argument("--force", action="store_true")
        if name == "resolve":
            cp.add_argument("--agent-runtime", choices=AGENT_RUNTIMES)
            cp.add_argument("--runtime-capability", help="verified studio-runtime-capability/v1 JSON")
            cp.add_argument("--role")
            cp.add_argument("--agent")
            cp.add_argument("--ritual")
            cp.add_argument("--step")
            cp.add_argument("--model")
            cp.add_argument("--effort")
        cp.set_defaults(func=cmd_config)

    sp = sub.add_parser("routing", help="deterministic optional-tool routing")
    rtsub = sp.add_subparsers(dest="routing_command", required=True)
    rtp = rtsub.add_parser("plan", help="resolve worker, reviewer, runtime profile, and capability probes")
    rtp.add_argument("--mission-id", required=True)
    rtp.add_argument("--environment-digest", required=True)
    rtp.add_argument("--config", help=f"config path (default {CONFIG_PATH_DEFAULT})")
    rtp.add_argument("--worker", choices=WORKER_PROVIDERS)
    rtp.add_argument("--reviewer", choices=REVIEWER_PROVIDERS)
    rtp.add_argument("--work-need", action="store_true")
    rtp.add_argument("--review-need", action="store_true")
    rtp.add_argument("--review-lease", help="canonical workflow-review-lease/v1 JSON")
    rtp.add_argument("--capabilities", help="selected provider capability snapshot mapping")
    rtp.add_argument("--agent-runtime", choices=AGENT_RUNTIMES)
    rtp.add_argument("--host-runtime", choices=AGENT_RUNTIMES)
    rtp.add_argument("--runtime-capability", help="verified studio-runtime-capability/v1 JSON")
    rtp.add_argument("--role")
    rtp.add_argument("--agent")
    rtp.add_argument("--ritual")
    rtp.add_argument("--step")
    rtp.add_argument("--model")
    rtp.add_argument("--effort")
    rtp.set_defaults(func=cmd_routing_plan)

    sp = sub.add_parser("board", help="read the operating board")
    sp.set_defaults(func=cmd_board)

    sp = sub.add_parser("mode", help="studio on-shift mode")
    mosub = sp.add_subparsers(dest="mcmd", required=True)
    for name, helptext in (
        ("start", "turn studio mode on"),
        ("end", "turn studio mode off"),
        ("status", "read studio mode"),
    ):
        mp = mosub.add_parser(name, help=helptext)
        mp.set_defaults(func=cmd_mode)

    sp = sub.add_parser("evidence", help="tally delta evidence (baseline/theatre check)")
    sp.set_defaults(func=cmd_evidence)

    sp = sub.add_parser("quality", help="QualityPlan hard-floor evaluation")
    qsub = sp.add_subparsers(dest="qcmd", required=True)
    qe = qsub.add_parser("evaluate", help="evaluate criterion evidence and telemetry")
    qe.add_argument("--plan", required=True, help="QualityPlan JSON (inline or @file)")
    qe.add_argument("--evidence", required=True, help="criterion-bound evidence_refs JSON")
    qe.add_argument("--telemetry", required=True, help="telemetry JSON")
    qe.set_defaults(func=cmd_quality_evaluate)

    sp = sub.add_parser("context", help="Context Kernel local projection")
    cxsub = sp.add_subparsers(dest="cxcmd", required=True)
    cp = cxsub.add_parser("put", help="store a ContextItem, ContextPack, or ContextDelta")
    cp.add_argument("kind", choices=sorted(CONTEXT_FIELDS))
    cp.add_argument("--json", required=True, help="context JSON (inline, @file, or -)")
    cp.set_defaults(func=cmd_context_put)
    cc = cxsub.add_parser("compact", help="compact ContextItems into a ContextPack")
    cc.add_argument("--bundle-id", required=True)
    cc.add_argument("--item-id", action="append", required=True)
    cc.set_defaults(func=cmd_context_compact)
    cr = cxsub.add_parser("prune", help="prune old local ContextDelta projections")
    cr.add_argument("--keep-deltas", type=int, required=True)
    cr.set_defaults(func=cmd_context_prune)
    co = cxsub.add_parser("outbox", help="preserve an owner-gated promotion candidate locally")
    co.add_argument("--json", required=True, help="promotion candidate JSON")
    co.set_defaults(func=cmd_context_outbox)

    sp = sub.add_parser("lease", help="track executor lease with fencing")
    lsub = sp.add_subparsers(dest="lcmd", required=True)
    lc = lsub.add_parser("claim", help="claim one executor lease for a track")
    lc.add_argument("track_id")
    lc.add_argument("--lease-id", required=True)
    lc.add_argument("--executor", required=True, choices=("native", "external"))
    lc.add_argument("--reservation-id", required=True)
    lc.set_defaults(func=cmd_lease_claim)
    lt = lsub.add_parser("transition", help="transition a fenced executor lease")
    lt.add_argument("track_id")
    lt.add_argument("--lease-id", required=True)
    lt.add_argument("--state", required=True, choices=sorted(set().union(*LEASE_TRANSITIONS.values())))
    lt.add_argument("--external-ref")
    lt.set_defaults(func=cmd_lease_transition)

    sp = sub.add_parser("workflow", help="optional executor contract and handoff")
    wfsub = sp.add_subparsers(dest="wcmd", required=True)
    wvp = wfsub.add_parser("validate-packet", help="validate a WorkPacket")
    wvp.add_argument("--json", required=True)
    wvp.set_defaults(func=cmd_workflow_validate_packet)
    wvr = wfsub.add_parser("validate-result", help="validate a ResultEnvelope")
    wvr.add_argument("--json", required=True)
    wvr.set_defaults(func=cmd_workflow_validate_result)
    wd = wfsub.add_parser("dispatch", help="select native/external before dispatch and claim a lease")
    wd.add_argument("--packet", required=True)
    wd.add_argument("--plan", required=True, help="canonical QualityPlan bound for this lease")
    wd.add_argument("--capabilities", help="agent-visible task-github capability snapshot")
    wd.add_argument("--routing-plan", help="canonical RoutingPlan pinned by routing plan")
    wd.add_argument("--lease-id", required=True)
    wd.set_defaults(func=cmd_workflow_dispatch)
    wr = wfsub.add_parser("result", help="ingest a coarse ResultEnvelope and evaluate integration readiness")
    wr.add_argument("--packet", required=True)
    wr.add_argument("--plan", required=True)
    wr.add_argument("--json", required=True)
    wr.add_argument("--lease-id", required=True)
    wr.add_argument("--routing-plan", help="canonical RoutingPlan used at dispatch")
    wr.set_defaults(func=cmd_workflow_result)
    wrec = wfsub.add_parser("recover", help="resume or cancel-confirm+release a failed external run")
    wrec.add_argument("track_id")
    wrec.add_argument("--lease-id", required=True)
    wrec.add_argument("--action", required=True, choices=("resume", "cancel-release"))
    wrec.set_defaults(func=cmd_workflow_recover)
    wp = wfsub.add_parser("promote", help="gate optional wiki provider handoff")
    wp.add_argument("candidate_id")
    wp.add_argument("--provider-status", required=True, choices=("available", "unavailable", "unknown"))
    wp.add_argument("--owner-approved", action="store_true")
    wp.set_defaults(func=cmd_workflow_promote)

    sp = sub.add_parser("execution", help="provider-neutral native execution control")
    exsub = sp.add_subparsers(dest="execution_command", required=True)
    exc = exsub.add_parser("contract", help="validate the exact canonical contract and all golden cases")
    exc.set_defaults(func=cmd_execution_contract)
    exg = exsub.add_parser("golden", help="evaluate canonical executable golden cases")
    exg.add_argument("--case", default="all")
    exg.set_defaults(func=cmd_execution_golden)
    exd = exsub.add_parser("dispatch", help="validate command policy and atomically claim a physical run")
    exd.add_argument("--json", required=True, help="dispatch request JSON (inline, @file, or -)")
    exd.set_defaults(func=cmd_execution_dispatch)
    excap = exsub.add_parser("capability", help="pin one mission/capability/environment probe result")
    excap.add_argument("--json", required=True, help="capability-snapshot/v1 JSON")
    excap.set_defaults(func=cmd_execution_capability)
    exr = exsub.add_parser("result", help="ingest a permit-bound command and mutation receipt")
    exr.add_argument("--json", required=True, help="result request JSON")
    exr.set_defaults(func=cmd_execution_result)
    exe = exsub.add_parser("evidence", help="ingest receipt-bound verification evidence")
    exe.add_argument("--json", required=True, help="verification-evidence/v1 JSON")
    exe.set_defaults(func=cmd_execution_evidence)
    exi = exsub.add_parser("invalidate", help="immutably invalidate evidence after an applicability change")
    exi.add_argument("evidence_id")
    exi.add_argument("--change", required=True, help="criteria/path/surface change JSON")
    exi.set_defaults(func=cmd_execution_invalidate)
    exclose = exsub.add_parser("closeout", help="reconcile integration-head closeout receipts")
    exclose.add_argument("--receipt", required=True, help="closeout-receipt/v1 JSON")
    exclose.add_argument("--applicability", required=True, help="ref to integration-head JSON mapping")
    exclose.set_defaults(func=cmd_execution_closeout)
    exs = exsub.add_parser("summary", help="read-only mission efficiency summary")
    exs.add_argument("--mission-id", required=True)
    exs.set_defaults(func=cmd_execution_summary)

    sp = sub.add_parser("cast", help="producer crew casting policy")
    casub = sp.add_subparsers(dest="castcmd", required=True)
    cl = casub.add_parser("list", help="list supported cast kinds")
    cl.set_defaults(func=cmd_cast_list)
    cs = casub.add_parser("suggest", help="choose default crew for a work kind")
    cs.add_argument("kind", help="one of: idea, product-direction, technical-design, ui-build, content, implementation, launch")
    cs.set_defaults(func=cmd_cast_suggest)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
