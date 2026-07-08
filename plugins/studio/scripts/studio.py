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

    sp = sub.add_parser("board", help="read the operating board")
    sp.set_defaults(func=cmd_board)

    sp = sub.add_parser("evidence", help="tally delta evidence (baseline/theatre check)")
    sp.set_defaults(func=cmd_evidence)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
