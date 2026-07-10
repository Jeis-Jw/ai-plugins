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
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


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

# agent policy config (.studio.yml)
CONFIG_PATH_DEFAULT = ".studio.yml"
WORKSPACE_PATH_DEFAULT = ".studio"
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
    return read_json_block(ws / "board.md")


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
            "budget": {
                "total_tokens": None,
                "per_run_default": None,
                "spent_tokens": 0,
                "reservations": {},
            },
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
    try:
        cost_tokens = int(cost.get("tokens") or 0)
    except (TypeError, ValueError):
        fail(4, "bad_cost", f"cost.tokens must be a number, got {cost.get('tokens')!r}")
    if cost_tokens < 0:
        fail(4, "bad_cost", "cost.tokens must be >= 0")
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
        "valid_deltas": len(valid_deltas),
        "aborted": aborted,
        "minutes": str(minutes_path),
    }
    with board_transaction(ws) as board:
        bud = board.setdefault("budget", {"spent_tokens": 0, "reservations": {}})
        runs = board.setdefault("runs", [])
        if not isinstance(runs, list):
            fail(4, "bad_board", "board.runs must be a list")
        spent = int(bud.get("spent_tokens") or 0)
        prior = next((r for r in runs if r.get("run_id") == run_id), None)
        if prior is not None:
            spent -= int(prior.get("cost_tokens") or 0)   # undo the old cost
            board["runs"] = [r for r in runs if r.get("run_id") != run_id]
        board["runs"].append(entry)
        bud["spent_tokens"] = spent + cost_tokens
        total = bud.get("total_tokens")
        exceeded = total is not None and bud["spent_tokens"] > total
        if exceeded:
            board["mission_state"] = "paused"  # budget exhausted → owner gate to resume
        atomic_write_text(minutes_path, body)

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
