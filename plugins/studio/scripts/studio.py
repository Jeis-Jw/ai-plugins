#!/usr/bin/env python3
"""studio — deterministic state helper for the living-agent-team workspace.

The producer (main thread) and the ritual brokers own all *behavior*; this CLI
owns the *state* that must not be model-improvised: the mission budget ledger,
the KPI-link rule on the backlog, and the delta-evidence recorded from each run.

Machine state lives in fenced ```json blocks (stdlib json — no hand-rolled YAML
parser, which nested contracts make fragile). Human prose sits outside the fence.

Workspace layout (created by `init`):

    <workspace>/                 default: studio/
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
import datetime
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any


JSON_FENCE_RE = re.compile(r"```json[ \t]*\n(.*?)\n```", re.DOTALL)
# backlog item: "- [ ] text ... (kpi: <token>)"  — the (kpi: ...) tag is mandatory.
BACKLOG_ITEM_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
# require a non-space first char so "(kpi: )" does not satisfy the link rule
KPI_TAG_RE = re.compile(r"\(kpi:\s*([^)\s][^)]*)\)")

MISSION_REQUIRED = ("mission", "kpi", "done_when", "budget", "gates", "autonomy")
VALID_ANCHORS = (
    "artifact",
    "acceptance-criteria",
    "risk",
    "rejected-alternative",
    "repro-test",
)

# agent policy config (.studio.yml)
CONFIG_PATH_DEFAULT = ".studio.yml"
KNOWN_MODELS = ("sonnet", "opus", "haiku", "fable")   # blank/omitted = inherit session
KNOWN_EFFORTS = ("low", "medium", "high", "xhigh", "max")

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
    return Path(getattr(args, "workspace", None) or "studio")


def require_workspace(ws: Path) -> None:
    if not ws.is_dir() or not (ws / "board.md").is_file():
        fail(3, "no_workspace", f"no studio workspace at {ws} (run: studio.py init)")


def extract_json_block(text: str) -> Any:
    m = JSON_FENCE_RE.search(text)
    if not m:
        raise ValueError("no ```json block found")
    return json.loads(m.group(1))


def read_json_block(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return extract_json_block(path.read_text(encoding="utf-8"))


def write_board(ws: Path, board: dict) -> None:
    body = (
        "# board — studio operating board\n\n"
        "> Machine state is the fenced json block below (the producer's source "
        "of truth for budget, tracks, and recorded runs). Edit via `studio.py`, "
        "not by hand.\n\n"
        "```json\n" + json.dumps(board, ensure_ascii=False, indent=2) + "\n```\n"
    )
    (ws / "board.md").write_text(body, encoding="utf-8")


def load_board(ws: Path) -> dict:
    return read_json_block(ws / "board.md")


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
        "# .studio.yml — crew agent model/effort policy.\n"
        "# Resolution (most→least specific): run-override > rituals.<ritual>.<step>\n"
        "#   > roles.<role> > defaults > (omit ⇒ inherit the producer session).\n"
        "# model: sonnet|opus|haiku|fable  (blank = inherit)   effort: low|medium|high|xhigh|max\n"
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
        "# ritual layer = override a role FOR ONE STEP. Only meaningful where the\n"
        "# step differs from the role (brainstorm has distinct steps); pairing steps\n"
        "# are the roles themselves, so set those under roles: instead.\n"
        "rituals:\n"
        "  brainstorm:\n"
        "    diverge:\n"
        "      effort: low       # blind opening proposals are cheap; debate/critic inherit roles\n"
    )


def cmd_config(args: argparse.Namespace) -> None:
    path = Path(args.path or CONFIG_PATH_DEFAULT)
    if args.ccmd == "scaffold":
        if path.exists() and not args.force:
            fail(2, "exists", f"{path} already exists (use --force)")
        path.write_text(render_default_config(), encoding="utf-8")
        ok(path=str(path), created=True)
    # get / validate both need to parse
    if not path.is_file():
        if args.ccmd == "get":
            ok(path=str(path), present=False, config={})  # absent ⇒ all inherit
        fail(3, "no_config", f"no config at {path} (run: studio.py config scaffold)")
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
    ok(path=str(path), present=True, config=cfg, problems=problems)


def _validate_config(cfg: dict) -> list[dict]:
    problems: list[dict] = []

    def check_mefr(block: dict, where: str) -> None:
        if not isinstance(block, dict):
            problems.append({"severity": "error", "where": where, "msg": "must be a mapping"})
            return
        m = block.get("model")
        if m not in (None, "") and m not in KNOWN_MODELS:
            problems.append({"severity": "warning", "where": where, "msg": f"unknown model {m!r} (known: {', '.join(KNOWN_MODELS)})"})
        e = block.get("effort")
        if e not in (None, "") and e not in KNOWN_EFFORTS:
            problems.append({"severity": "error", "where": where, "msg": f"bad effort {e!r} (must be {', '.join(KNOWN_EFFORTS)})"})

    if "defaults" in cfg:
        check_mefr(cfg["defaults"], "defaults")
    for role, blk in (cfg.get("roles") or {}).items():
        check_mefr(blk, f"roles.{role}")
    for ritual, steps in (cfg.get("rituals") or {}).items():
        if not isinstance(steps, dict):
            problems.append({"severity": "error", "where": f"rituals.{ritual}", "msg": "must be a mapping of steps"})
            continue
        for step, blk in steps.items():
            check_mefr(blk, f"rituals.{ritual}.{step}")
    return problems


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> None:
    ws = workspace(args)
    if (ws / "board.md").is_file() and not args.force:
        fail(2, "exists", f"workspace already at {ws} (use --force to re-scaffold)")

    for sub in ("missions", "minutes", "raw", "crew"):
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
            "schema": 1,
            "studio_mode": {"active": False, "started_at": None, "ended_at": None},
            "budget": {"total_tokens": None, "per_run_default": None, "spent_tokens": 0},
            "tracks": [],
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
    board = load_board(ws)
    bud = board.setdefault("budget", {"spent_tokens": 0})
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
    write_board(ws, board)
    ok(budget=bud, changed=changed)


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

    missing = [k for k in MISSION_REQUIRED if k not in contract]
    problems = list(missing and [f"missing key: {k}" for k in missing] or [])
    kpi = contract.get("kpi")
    if kpi is not None and (not isinstance(kpi, list) or not kpi):
        problems.append("kpi must be a non-empty list")
    budget = contract.get("budget")
    if budget is not None and not (
        isinstance(budget, dict) and "total_tokens" in budget
    ):
        problems.append("budget must include total_tokens")
    if problems:
        fail(6, "invalid_mission", "; ".join(problems), problems=problems)
    ok(
        path=str(path),
        kpi_ids=[k.get("id") if isinstance(k, dict) else k for k in kpi],
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


def cmd_run_record(args: argparse.Namespace) -> None:
    ws = workspace(args)
    require_workspace(ws)
    out = _load_run_output(args)

    ritual = out.get("ritual", "unknown")
    # id precedence: explicit output field > --id > clock+random (random suffix
    # guards against two runs in the same second with the same ritual colliding).
    run_id = (
        out.get("run_id")
        or args.id
        or f"RUN-{now_stamp()}-{slugify(ritual)}-{os.urandom(3).hex()}"
    )
    cost = out.get("cost") or {}
    try:
        cost_tokens = int(cost.get("tokens") or 0)
    except (TypeError, ValueError):
        fail(4, "bad_cost", f"cost.tokens must be a number, got {cost.get('tokens')!r}")
    if cost_tokens < 0:
        fail(4, "bad_cost", "cost.tokens must be >= 0")
    verdict = out.get("verdict") or {}
    delta_log = out.get("delta_log") or []
    aborted = bool(out.get("aborted"))

    # count real (non-dry) deltas with a valid anchor — the evidence tally.
    valid_deltas = [
        d
        for d in delta_log
        if isinstance(d, dict)
        and not d.get("dry")
        and d.get("anchor") in VALID_ANCHORS
    ]

    # ---- write minutes (synthesis + delta_log only; raw transcript stays in raw/)
    minutes_path = ws / "minutes" / f"{run_id}.md"
    body = _render_minutes(run_id, out, valid_deltas, aborted)
    minutes_path.write_text(body, encoding="utf-8")

    # ---- update board ledger (idempotent on run_id: re-recording the same run
    # replaces its entry and its cost, never double-counts the budget)
    board = load_board(ws)
    entry = {
        "run_id": run_id,
        "ritual": ritual,
        "track": out.get("track") or getattr(args, "track", None),
        "verdict": verdict,
        "cost_tokens": cost_tokens,
        "valid_deltas": len(valid_deltas),
        "aborted": aborted,
        "minutes": str(minutes_path),
    }
    bud = board["budget"]
    spent = int(bud.get("spent_tokens") or 0)
    prior = next((r for r in board["runs"] if r.get("run_id") == run_id), None)
    if prior is not None:
        spent -= int(prior.get("cost_tokens") or 0)   # undo the old cost
        board["runs"] = [r for r in board["runs"] if r.get("run_id") != run_id]
    board["runs"].append(entry)
    bud["spent_tokens"] = spent + cost_tokens
    total = bud.get("total_tokens")
    exceeded = total is not None and bud["spent_tokens"] > total
    if exceeded:
        board["mission_state"] = "paused"  # budget exhausted → owner gate to resume
    write_board(ws, board)

    ok(
        run_id=run_id,
        minutes=str(minutes_path),
        valid_deltas=len(valid_deltas),
        aborted=aborted,
        spent_tokens=bud["spent_tokens"],
        budget_total=total,
        budget_exceeded=exceeded,
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
    board = load_board(ws)
    mode = mode_state(board)
    if args.mcmd == "start":
        if not mode.get("active"):
            mode["active"] = True
            mode["started_at"] = now_stamp()
            mode["ended_at"] = None
            write_board(ws, board)
        ok(mode=mode)
    if args.mcmd == "end":
        if mode.get("active"):
            mode["active"] = False
            mode["ended_at"] = now_stamp()
            write_board(ws, board)
        ok(mode=mode)
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
    p.add_argument("--workspace", help="workspace dir (default: studio)")
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

    sp = sub.add_parser("run", help="run ops")
    rsub = sp.add_subparsers(dest="rcmd", required=True)
    rr = rsub.add_parser("record", help="record a run output → minutes + board ledger")
    rr.add_argument("--json", help="run output JSON (inline, @file, or - for stdin)")
    rr.add_argument("--id", help="override run id (else derived from output/clock)")
    rr.add_argument("--track", help="track slug this run belongs to (producer-owned)")
    rr.set_defaults(func=cmd_run_record)

    sp = sub.add_parser("config", help="agent model/effort policy (.studio.yml)")
    csub = sp.add_subparsers(dest="ccmd", required=True)
    for name, helptext in (("scaffold", "write a default .studio.yml"),
                           ("validate", "check the config"),
                           ("get", "parse the config → JSON (for the producer to pass to brokers)")):
        cp = csub.add_parser(name, help=helptext)
        cp.add_argument("--path", help=f"config path (default {CONFIG_PATH_DEFAULT})")
        if name == "scaffold":
            cp.add_argument("--force", action="store_true")
        cp.set_defaults(func=cmd_config)

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
