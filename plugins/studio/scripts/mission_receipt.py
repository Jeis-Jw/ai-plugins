#!/usr/bin/env python3
"""Studio mission receipt — 세션 간 재개 인덱스 (studio.mission-receipt/v1).

consumer 워크스페이스의 `.studio/receipt/<mission_id>.json` 파일 1개에 미션 재개
앵커만 영속화한다. crew 중간 추론·산출물 본문·메시지 로그는 스키마에 없다
(유계면 영속화, 무계면 재유도 — DEC-2026-07-30-235418).

쓰기 이벤트는 5종뿐이다: init(미션 착수) / lane(상태 전이) / gate(설정·해제) /
pause / close(완료). show는 read-only다. 고정 필드 집합 밖의 필드·state는
fail-closed로 거부하고 파일을 변경하지 않는다.

pause는 wiki `snapshot save`(SNAP)를 재사용해 고정 필드(완료/잔여/blocker/다음 한
걸음)를 남긴다. wiki CLI가 해소되지 않으면 snapshot_ref:null로 생략한다(soft dep).

exit: 0 성공 / 2 usage·스키마 위반 / 3 receipt 없음 / 4 JSON 손상
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "studio.mission-receipt/v1"
RECEIPT_DIR = Path(".studio") / "receipt"
STATUSES = frozenset(("active", "paused", "closed"))
LANE_STATES = frozenset(("pending", "dispatched", "returned", "reviewed", "done", "failed"))
TOP_FIELDS = frozenset((
    "schema", "mission_id", "objective", "done_when", "status", "lanes",
    "ready_next", "owner_gate", "snapshot_ref", "started_at", "updated_at",
))
LANE_FIELDS = frozenset(("lane_id", "role", "work_ref", "agent_id", "state", "updated_at"))
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
WORK_REF_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}:.{1,512}")

EXIT_BY_CODE = {
    "usage": 2,
    "schema_violation": 2,
    "receipt_exists": 2,
    "unknown_lane": 2,
    "mission_closed": 2,
    "receipt_not_found": 3,
    "receipt_corrupt": 4,
}


class ReceiptError(ValueError):
    """A usage or schema failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def emit(value: dict[str, Any], *, exit_code: int = 0) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    raise SystemExit(exit_code)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def receipt_path(mission_id: str) -> Path:
    return RECEIPT_DIR / f"{mission_id}.json"


def require_id(value: str, *, field: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ReceiptError("usage", f"{field} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}: {value!r}")
    return value


# ── schema (fail-closed) ─────────────────────────────────────────────────────

def _fail(message: str) -> None:
    raise ReceiptError("schema_violation", message)


def _require_str_list(value: Any, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        _fail(f"{field} must be a list of non-empty strings")


def _validate_lane(lane: Any) -> None:
    if not isinstance(lane, dict):
        _fail("each lane must be an object")
    extra, missing = set(lane) - LANE_FIELDS, LANE_FIELDS - set(lane)
    if extra or missing:
        _fail(f"lane field set mismatch: extra={sorted(extra)} missing={sorted(missing)}")
    for field in ("lane_id", "role", "updated_at"):
        if not isinstance(lane[field], str) or not lane[field]:
            _fail(f"lane.{field} must be a non-empty string")
    if lane["work_ref"] is not None and (
            not isinstance(lane["work_ref"], str) or not WORK_REF_RE.fullmatch(lane["work_ref"])):
        _fail("lane.work_ref must be null or '<skill-or-provider>:<opaque-ref>'")
    if lane["agent_id"] is not None and (not isinstance(lane["agent_id"], str) or not lane["agent_id"]):
        _fail("lane.agent_id must be null or a non-empty string")
    if lane["state"] not in LANE_STATES:
        _fail(f"lane.state must be one of {sorted(LANE_STATES)}: {lane['state']!r}")


def validate_receipt(data: Any, *, mission_id: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        _fail("receipt must be a JSON object")
    extra, missing = set(data) - TOP_FIELDS, TOP_FIELDS - set(data)
    if extra or missing:
        _fail(f"field set mismatch: extra={sorted(extra)} missing={sorted(missing)}")
    if data["schema"] != SCHEMA:
        _fail(f"schema must be {SCHEMA!r}: {data['schema']!r}")
    if data["mission_id"] != mission_id:
        _fail(f"mission_id mismatch: file has {data['mission_id']!r}, expected {mission_id!r}")
    if not isinstance(data["objective"], str) or not data["objective"]:
        _fail("objective must be a non-empty string")
    _require_str_list(data["done_when"], "done_when")
    if data["status"] not in STATUSES:
        _fail(f"status must be one of {sorted(STATUSES)}: {data['status']!r}")
    if not isinstance(data["lanes"], list):
        _fail("lanes must be a list")
    seen: set[str] = set()
    for lane in data["lanes"]:
        _validate_lane(lane)
        if lane["lane_id"] in seen:
            _fail(f"duplicate lane_id: {lane['lane_id']!r}")
        seen.add(lane["lane_id"])
    _require_str_list(data["ready_next"], "ready_next")
    gate = data["owner_gate"]
    if gate is not None and (
            not isinstance(gate, dict) or set(gate) != {"reason"}
            or not isinstance(gate["reason"], str) or not gate["reason"]):
        _fail("owner_gate must be null or {\"reason\": <non-empty string>}")
    if data["snapshot_ref"] is not None and not isinstance(data["snapshot_ref"], str):
        _fail("snapshot_ref must be null or a string")
    for field in ("started_at", "updated_at"):
        if not isinstance(data[field], str) or not data[field]:
            _fail(f"{field} must be a non-empty string")
    return data


def load_receipt(mission_id: str) -> dict[str, Any]:
    require_id(mission_id, field="mission_id")
    path = receipt_path(mission_id)
    if not path.is_file():
        raise ReceiptError("receipt_not_found", f"no receipt: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ReceiptError("receipt_corrupt", f"invalid JSON in {path}: {err}") from err
    return validate_receipt(data, mission_id=mission_id)


def save_receipt(receipt: dict[str, Any]) -> Path:
    # 쓰기 직전 재검증 — 위반이면 파일에 손대지 않는다 (fail-closed).
    validate_receipt(receipt, mission_id=receipt.get("mission_id", ""))
    path = receipt_path(receipt["mission_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    os.replace(tmp, path)
    return path


def require_open(receipt: dict[str, Any]) -> None:
    if receipt["status"] == "closed":
        raise ReceiptError("mission_closed", "closed mission receipt is immutable")


def resume_if_paused(receipt: dict[str, Any]) -> None:
    """lane 전이가 곧 재개다 — SNAP은 transient이므로 폐기한다."""
    if receipt["status"] == "paused":
        discard_snapshot(receipt)
        receipt["status"] = "active"
        receipt["snapshot_ref"] = None


# ── wiki SNAP bridge (soft dependency) ───────────────────────────────────────

def resolve_wiki_cli() -> Optional[Path]:
    """Locate wiki-markdown's wiki_cli.py. Order: STUDIO_WIKI_CLI override
    ("", "none", "off", "0" disable) → sibling-plugin search → PATH → None."""
    env = os.environ.get("STUDIO_WIKI_CLI")
    if env is not None:
        if env.strip().lower() in {"", "none", "off", "0"}:
            return None
        candidate = Path(env).expanduser()
        return candidate if candidate.exists() else None
    here = Path(__file__).resolve()
    parents = here.parents
    rel = ("wiki-markdown", "skills", "wiki", "scripts", "wiki_cli.py")
    candidates: list[Path] = []
    # monorepo: plugins/studio/scripts → plugins/wiki-markdown/.../wiki_cli.py
    if len(parents) > 2:
        candidates.append(parents[2].joinpath(*rel))
    # installed (versioned dirs): <marketplace>/wiki-markdown/<ver>/skills/.../wiki_cli.py
    for depth in (2, 3):
        if len(parents) > depth:
            candidates.extend(sorted(parents[depth].glob(
                "wiki-markdown/*/skills/wiki/scripts/wiki_cli.py")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = shutil.which("wiki_cli") or shutil.which("wiki_cli.py")
    return Path(found) if found else None


def resolve_vault() -> Path:
    env = os.environ.get("WIKI_VAULT")
    if env:
        return Path(env).expanduser()
    return Path.cwd() / "wiki"


def snap_slug(mission_id: str) -> str:
    return f"studio-mission-{mission_id}"


def _run_wiki(cli: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(cli), *args],
                          text=True, capture_output=True)


def save_snapshot(receipt: dict[str, Any],
                  sections: tuple[tuple[str, Optional[str]], ...]) -> tuple[Optional[str], str]:
    """SNAP 저장을 시도하고 (snapshot_ref, note)를 돌려준다. soft dep — 절대 raise하지 않는다."""
    cli = resolve_wiki_cli()
    if cli is None:
        return None, "skipped:wiki_cli_unresolved"
    vault = resolve_vault()
    if not vault.is_dir():
        return None, "skipped:vault_missing"
    slug = snap_slug(receipt["mission_id"])
    discussion = "\n".join(f"{label}: {value or '-'}" for label, value in sections)
    result = _run_wiki(
        cli, "snapshot", "save", "--vault", str(vault), "--slug", slug,
        "--title", f"studio mission pause — {receipt['mission_id']}",
        "--summary", receipt["objective"], "--tags", "studio,mission,pause",
        "--discussion", discussion)
    if result.returncode != 0:
        return None, "skipped:snapshot_save_failed"
    return f"SNAP-{slug}", "saved"


def discard_snapshot(receipt: dict[str, Any]) -> None:
    # ponytail: best-effort 폐기 — SNAP은 transient staging이라 실패해도 무해.
    if not receipt.get("snapshot_ref"):
        return
    cli = resolve_wiki_cli()
    if cli is None:
        return
    vault = resolve_vault()
    if not vault.is_dir():
        return
    _run_wiki(cli, "snapshot", "discard", snap_slug(receipt["mission_id"]),
              "--vault", str(vault))


# ── 쓰기 이벤트 5종 + show ───────────────────────────────────────────────────

def _replace_ready_next(receipt: dict[str, Any], values: Optional[list[str]]) -> None:
    if values is not None:
        receipt["ready_next"] = [item for item in values if item]


def cmd_init(args: argparse.Namespace) -> None:
    mission_id = require_id(args.mission_id, field="mission_id")
    path = receipt_path(mission_id)
    if path.exists():
        raise ReceiptError("receipt_exists", f"receipt already exists: {path}")
    now = now_utc()
    lanes: list[dict[str, Any]] = []
    for spec in args.lane or []:
        lane_id, sep, role = spec.partition("=")
        if not sep or not role:
            raise ReceiptError("usage", f"--lane expects LANE_ID=ROLE: {spec!r}")
        require_id(lane_id, field="lane_id")
        lanes.append({"lane_id": lane_id, "role": role, "work_ref": None,
                      "agent_id": None, "state": "pending", "updated_at": now})
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "mission_id": mission_id,
        "objective": args.objective,
        "done_when": [item for item in (args.done_when or []) if item],
        "status": "active",
        "lanes": lanes,
        "ready_next": [],
        "owner_gate": None,
        "snapshot_ref": None,
        "started_at": now,
        "updated_at": now,
    }
    _replace_ready_next(receipt, args.ready_next)
    saved = save_receipt(receipt)
    emit({"ok": True, "event": "init", "path": str(saved), "receipt": receipt})


def cmd_lane(args: argparse.Namespace) -> None:
    receipt = load_receipt(args.mission_id)
    require_open(receipt)
    if args.work_ref is not None and not WORK_REF_RE.fullmatch(args.work_ref):
        raise ReceiptError(
            "usage",
            f"--work-ref must look like <skill-or-provider>:<opaque-ref>: {args.work_ref!r}",
        )
    now = now_utc()
    lane = next((item for item in receipt["lanes"] if item["lane_id"] == args.lane_id), None)
    if lane is None:
        if args.role is None:
            raise ReceiptError(
                "unknown_lane",
                f"unknown lane_id {args.lane_id!r}; pass --role to add a new lane")
        require_id(args.lane_id, field="lane_id")
        lane = {"lane_id": args.lane_id, "role": args.role, "work_ref": None,
                "agent_id": None, "state": args.state, "updated_at": now}
        receipt["lanes"].append(lane)
    else:
        if args.role is not None:
            lane["role"] = args.role
        lane["state"] = args.state
        lane["updated_at"] = now
    if args.work_ref is not None:
        lane["work_ref"] = args.work_ref
    if args.agent_id is not None:
        lane["agent_id"] = args.agent_id
    _replace_ready_next(receipt, args.ready_next)
    resume_if_paused(receipt)
    receipt["updated_at"] = now
    saved = save_receipt(receipt)
    emit({"ok": True, "event": "lane", "path": str(saved), "receipt": receipt})


def cmd_gate(args: argparse.Namespace) -> None:
    receipt = load_receipt(args.mission_id)
    require_open(receipt)
    receipt["owner_gate"] = None if args.clear else {"reason": args.reason}
    receipt["updated_at"] = now_utc()
    saved = save_receipt(receipt)
    emit({"ok": True, "event": "gate", "path": str(saved), "receipt": receipt})


def cmd_pause(args: argparse.Namespace) -> None:
    receipt = load_receipt(args.mission_id)
    require_open(receipt)
    sections = (("완료", args.done), ("잔여", args.remaining),
                ("blocker", args.blocker), ("다음 한 걸음", args.next_step))
    ref, note = save_snapshot(receipt, sections)
    receipt["status"] = "paused"
    receipt["snapshot_ref"] = ref
    receipt["updated_at"] = now_utc()
    saved = save_receipt(receipt)
    emit({"ok": True, "event": "pause", "snapshot": note, "path": str(saved),
          "receipt": receipt})


def cmd_close(args: argparse.Namespace) -> None:
    receipt = load_receipt(args.mission_id)
    require_open(receipt)
    discard_snapshot(receipt)
    receipt["status"] = "closed"
    receipt["snapshot_ref"] = None
    receipt["updated_at"] = now_utc()
    saved = save_receipt(receipt)
    emit({"ok": True, "event": "close", "path": str(saved), "receipt": receipt})


def cmd_show(args: argparse.Namespace) -> None:
    receipt = load_receipt(args.mission_id)
    emit({"ok": True, "path": str(receipt_path(args.mission_id)), "receipt": receipt})


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mission_receipt.py",
        description="studio mission receipt — 세션 간 재개 인덱스 (studio.mission-receipt/v1)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("mission_id")
        p.add_argument("--json", action="store_true",
                       help="JSON 출력 (기본이자 유일한 출력 형식)")
        return p

    p_init = common(sub.add_parser("init", help="미션 착수 — receipt 생성"))
    p_init.add_argument("--objective", required=True)
    p_init.add_argument("--done-when", action="append", dest="done_when",
                        help="반복 지정 가능")
    p_init.add_argument("--lane", action="append",
                        help="LANE_ID=ROLE (state=pending), 반복 지정 가능")
    p_init.add_argument("--ready-next", action="append", dest="ready_next",
                        help="반복 지정 가능")
    p_init.set_defaults(handler=cmd_init)

    p_lane = common(sub.add_parser("lane", help="lane 상태 전이 (paused 미션은 재개된다)"))
    p_lane.add_argument("lane_id")
    p_lane.add_argument("--state", required=True, choices=sorted(LANE_STATES))
    p_lane.add_argument("--role", help="신규 lane을 추가할 때만 지정")
    p_lane.add_argument(
        "--work-ref", dest="work_ref", help="<skill-or-provider>:<opaque-ref>"
    )
    p_lane.add_argument("--agent-id", dest="agent_id", help="host agent id")
    p_lane.add_argument("--ready-next", action="append", dest="ready_next",
                        help="지정 시 목록 교체, 빈 문자열 1개면 비움")
    p_lane.set_defaults(handler=cmd_lane)

    p_gate = common(sub.add_parser("gate", help="owner gate 설정·해제"))
    gate_mode = p_gate.add_mutually_exclusive_group(required=True)
    gate_mode.add_argument("--reason")
    gate_mode.add_argument("--clear", action="store_true")
    p_gate.set_defaults(handler=cmd_gate)

    p_pause = common(sub.add_parser(
        "pause", help="일시중지 + SNAP handoff (wiki CLI 미해결이면 snapshot_ref:null)"))
    p_pause.add_argument("--done", help="SNAP 고정 필드: 완료")
    p_pause.add_argument("--remaining", help="SNAP 고정 필드: 잔여")
    p_pause.add_argument("--blocker", help="SNAP 고정 필드: blocker")
    p_pause.add_argument("--next-step", dest="next_step", help="SNAP 고정 필드: 다음 한 걸음")
    p_pause.set_defaults(handler=cmd_pause)

    p_close = common(sub.add_parser("close", help="미션 완료 — 이후 쓰기 금지"))
    p_close.set_defaults(handler=cmd_close)

    p_show = common(sub.add_parser("show", help="read-only 조회"))
    p_show.set_defaults(handler=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except ReceiptError as error:
        emit({"ok": False, "error_code": error.code, "message": str(error)},
             exit_code=EXIT_BY_CODE.get(error.code, 2))


if __name__ == "__main__":
    main()
