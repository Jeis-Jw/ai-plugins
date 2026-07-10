#!/usr/bin/env python3
"""Runnable checks for studio.py — exercises the exit-code contract that the
gates depend on (init idempotency, mission validation, the KPI-link rule, run
recording + budget ledger, and the delta/theatre tally).

Run: python3 plugins/studio/tests/test_studio.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
CLI = PLUGIN / "scripts" / "studio.py"
JSON_BLOCK = re.compile(r"```json[ \t]*\n(.*?)\n```", re.DOTALL)


def plugin_text(name: str) -> str:
    return (PLUGIN / name).read_text(encoding="utf-8")


def board_state(ws: Path) -> dict:
    return json.loads(JSON_BLOCK.search((ws / "board.md").read_text()).group(1))


def run(args, cwd, expect=0, stdin=None):
    env = {**os.environ, "STUDIO_ROOT": str(PLUGIN), "SOURCE_DATE_EPOCH": "1700000000"}
    p = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd, env=env, input=stdin, capture_output=True, text=True,
    )
    assert p.returncode == expect, (
        f"args={args} expected exit {expect} got {p.returncode}\n{p.stdout}\n{p.stderr}"
    )
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"_raw": p.stdout}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 0) default workspace errors point to the hidden repo-local directory
        r = run(["--help"], tmp)
        assert "workspace dir (default: .studio/)" in r["_raw"], r
        r = run(["mode", "status"], tmp, expect=3)
        assert r["error_code"] == "no_workspace" and ".studio/" in r["message"], r

        # 1) init scaffolds workspace + copies crew personas
        r = run(["init"], tmp)
        assert r["ok"] and r["created"], r
        ws = tmp / ".studio"
        assert not (tmp / "studio").exists()
        assert (ws / "board.md").is_file()
        assert (ws / "backlog.md").is_file()
        assert (ws / "missions" / "TEMPLATE.md").is_file()
        assert board_state(ws)["schema"] == 2
        for sub in ("items", "bundles", "deltas", "outbox"):
            assert (ws / "context" / sub).is_dir(), sub
        crew = sorted(p.name for p in (ws / "crew").glob("*.md"))
        assert crew == [
            "architect.md",
            "creator.md",
            "curator.md",
            "dev.md",
            "planner-a.md",
            "planner-b.md",
            "product-designer.md",
            "qa.md",
            "researcher.md",
            "reviewer.md",
            "strategist.md",
            "visual-designer.md",
        ], crew

        # 2) init is not idempotent without --force (guards accidental clobber)
        run(["init"], tmp, expect=2)
        run(["init", "--force"], tmp, expect=0)

        # 3) mission validate — the shipped TEMPLATE is a valid contract
        r = run(["mission", "validate", ".studio/missions/TEMPLATE.md"], tmp)
        assert r["ok"] and r["kpi_ids"] == ["k1", "k2"], r

        # 4) mission validate — missing kpi → gate violation exit 6
        bad = ws / "missions" / "bad.md"
        bad.write_text('```json\n{"mission":"m","done_when":"d","budget":{"total_tokens":1},"gates":[],"autonomy":"a"}\n```\n', encoding="utf-8")
        r = run(["mission", "validate", ".studio/missions/bad.md"], tmp, expect=6)
        assert not r["ok"] and any("kpi" in p for p in r["problems"]), r
        strict_bad = ws / "missions" / "strict-bad.md"
        strict_bad.write_text(
            '```json\n{"mission":"m","kpi":[{"id":"k1","goal":""}],'
            '"done_when":"d","budget":{"total_tokens":1,"per_run_default":1},'
            '"gates":[],"autonomy":"a","surprise":true}\n```\n',
            encoding="utf-8",
        )
        r = run(["mission", "validate", str(strict_bad)], tmp, expect=6)
        assert any("unknown key" in p for p in r["problems"]), r
        assert any("goal" in p for p in r["problems"]), r

        # 5) backlog check — default item has (kpi: k1) → ok
        r = run(["backlog", "check"], tmp)
        assert r["ok"] and r["items"] == 1, r
        #    add an item with no KPI link → exit 6
        (ws / "backlog.md").write_text(
            "# backlog\n\n- [ ] linked (kpi: k1)\n- [ ] orphan with no kpi tag\n",
            encoding="utf-8",
        )
        r = run(["backlog", "check"], tmp, expect=6)
        assert len(r["violations"]) == 1 and r["violations"][0]["line"] == 4, r

        #    KPI tag must be non-empty — "(kpi: )" does not satisfy the rule
        (ws / "backlog.md").write_text("# backlog\n\n- [ ] whitespace only (kpi: )\n", encoding="utf-8")
        run(["backlog", "check"], tmp, expect=6)
        (ws / "backlog.md").write_text("# backlog\n\n- [ ] ok (kpi: k1)\n", encoding="utf-8")
        run(["backlog", "check"], tmp)

        # 6) budget — total is settable via the CLI (enables the exhausted→paused gate)
        r = run(["budget", "--set-total", "100"], tmp)
        assert r["budget"]["total_tokens"] == 100, r

        # 6a) mode — studio stays "on shift" until explicitly ended
        r = run(["mode", "status"], tmp)
        assert r["ok"] and r["mode"]["active"] is False, r
        r = run(["mode", "start"], tmp)
        assert r["ok"] and r["mode"]["active"] is True, r
        assert board_state(ws)["studio_mode"]["active"] is True, board_state(ws)
        r = run(["mode", "status"], tmp)
        assert r["mode"]["active"] is True and r["mode"]["started_at"] == "20231114-221320", r
        r = run(["mode", "end"], tmp)
        assert r["ok"] and r["mode"]["active"] is False, r
        assert board_state(ws)["studio_mode"]["active"] is False, board_state(ws)

        #    run record — one valid delta, one dry; budget ledger updates
        run_out = {
            "run_id": "RUN-test-brainstorm-1",
            "ritual": "brainstorm",
            "participants": ["planner-a", "planner-b"],
            "synthesis": "scope = parser + stdout only",
            "minority": "planner-a wants tag stats (v2)",
            "delta_log": [
                {"round": 1, "changed_what": "dropped config file", "anchor": "rejected-alternative", "evidence": "no config in v1"},
                {"round": 2, "changed_what": "everyone agrees it's good", "dry": True},
            ],
            "verdict": {"alive": True, "reason": "one anchored delta"},
            "cost": {"tokens": 150, "rounds": 2},
            "proposals": ["tag stats as a v2 backlog item"],
        }
        r = run(["run", "record", "--json", "-", "--track", "t1"], tmp, stdin=json.dumps(run_out))
        assert r["ok"] and r["valid_deltas"] == 1, r          # dry delta excluded
        assert r["spent_tokens"] == 150 and r["budget_exceeded"], r
        minutes = tmp / r["minutes"]        # CLI returns a workspace-relative path
        assert minutes.is_file()
        text = minutes.read_text(encoding="utf-8")
        assert "rejected-alternative" in text and "DRY" in text, text
        #    budget exceeded → board mission paused; --track recorded
        assert board_state(ws).get("mission_state") == "paused", board_state(ws)
        assert board_state(ws)["runs"][0]["track"] == "t1", board_state(ws)

        # 6b) run record is idempotent on run_id — re-recording does not double-count
        r = run(["run", "record", "--json", "-"], tmp, stdin=json.dumps(run_out))
        assert r["spent_tokens"] == 150, r                     # not 300
        assert len(board_state(ws)["runs"]) == 1, board_state(ws)

        # 6c) schema-v1 receipt is compact-appended; unknown tokens never alter spend
        receipt_out = {
            "run_id": "RUN-receipt",
            "ritual": "brainstorm",
            "delta_log": [],
            "verdict": {"alive": False, "reason": "dry"},
            "cost": {"tokens": 5, "token_coverage": "exact", "elapsed_ms": 1000, "rounds": 1},
            "receipt": {
                "schema": "workflow-receipt/v1", "emitter": "studio", "workflow": "studio-brainstorm",
                "run_id": "RUN-receipt", "started_at": "2026-07-10T00:00:00.000Z",
                "finished_at": "2026-07-10T00:00:01.000Z", "elapsed_ms": 1000,
                "tokens": 5, "token_coverage": "exact", "counters": {"rounds": 1},
                "quality": {"alive": False},
            },
        }
        receipt_log = tmp / "receipts.jsonl"
        r = run(["run", "record", "--json", "-", "--receipt-log", str(receipt_log)], tmp,
                stdin=json.dumps(receipt_out))
        assert r["spent_tokens"] == 155 and not r["warnings"], r
        receipt_line = receipt_log.read_text(encoding="utf-8").strip()
        assert receipt_line == json.dumps(receipt_out["receipt"], ensure_ascii=False,
                                          separators=(",", ":")), receipt_line

        null_receipt_out = {**receipt_out, "run_id": "RUN-null-receipt"}
        null_receipt_out["cost"] = {
            "tokens": None, "token_coverage": "unavailable", "elapsed_ms": 1000, "rounds": 1,
        }
        null_receipt_out["receipt"] = {
            **receipt_out["receipt"], "run_id": "RUN-null-receipt",
            "tokens": None, "token_coverage": "unavailable",
        }
        r = run(["run", "record", "--json", "-", "--receipt-log", str(tmp)], tmp,
                stdin=json.dumps(null_receipt_out))
        assert r["spent_tokens"] == 155, r
        assert len(r["warnings"]) == 1 and "append failed" in r["warnings"][0], r
        stored = next(item for item in board_state(ws)["runs"] if item["run_id"] == "RUN-null-receipt")
        assert stored["cost_tokens"] is None, stored

        # 6d) raising the budget above spend clears the paused state
        r = run(["budget", "--set-total", "1000"], tmp)
        assert "mission_state" not in board_state(ws), board_state(ws)

        # 6e) budget reserve/dispatch/settle is fenced and idempotent
        r = run(["budget", "reserve", "res-1", "--lease-id", "lease-1", "--tokens", "40"], tmp)
        assert r["changed"] and r["reservation"]["status"] == "reserved", r
        r = run(["budget", "reserve", "res-1", "--lease-id", "lease-1", "--tokens", "40"], tmp)
        assert not r["changed"], r
        run(["budget", "dispatch", "res-1", "--lease-id", "stale"], tmp, expect=6)
        r = run(["budget", "dispatch", "res-1", "--lease-id", "lease-1"], tmp)
        assert r["reservation"]["status"] == "dispatched", r
        r = run(["budget", "dispatch", "res-1", "--lease-id", "lease-1"], tmp)
        assert not r["changed"], r
        r = run(["budget", "settle", "res-1", "--lease-id", "lease-1", "--tokens", "30"], tmp)
        assert r["changed"] and r["spent_tokens"] == 185, r
        r = run(["budget", "settle", "res-1", "--lease-id", "lease-1", "--tokens", "30"], tmp)
        assert not r["changed"] and r["reservation"]["settled_tokens"] == 30, r

        # 6f) malformed run outputs hit the exit-code contract, not a crash
        run(["run", "record", "--json", "-"], tmp, expect=4,
            stdin=json.dumps({"run_id": "z", "cost": {"tokens": "lots"}}))       # non-numeric cost
        run(["run", "record", "--json", "@/no/such/file.json"], tmp, expect=4)    # missing @file
        run(["run", "record", "--json", "-"], tmp, expect=4,
            stdin=json.dumps({"error": "brainstorm needs >=2 personas"}))         # broker error, not a run
        r = run(["run", "record", "--json", "-"], tmp, expect=4,
                stdin=json.dumps({"run_id": "../escape", "ritual": "brainstorm", "delta_log": []}))
        assert r["error_code"] == "unsafe_id" and not (tmp / "escape.md").exists(), r
        r = run(["run", "record", "--json", "-"], tmp, expect=6, stdin=json.dumps({
            "run_id": "strict-delta", "ritual": "brainstorm", "cost": {"tokens": 0},
            "delta_log": [{"round": 1, "changed_what": "claimed", "anchor": "artifact"}],
        }))
        assert r["error_code"] == "invalid_run_output" and any("evidence" in p for p in r["problems"]), r
        r = run(["run", "record", "--json", "-"], tmp, expect=6, stdin=json.dumps({
            "run_id": "false-ready", "ritual": "pairing", "cost": {"tokens": 0},
            "delta_log": [{"round": 1, "changed_what": "implemented", "anchor": "artifact", "evidence": "diff"}],
            "verdict": {"alive": True, "open_count": 0}, "changedFiles": [],
            "verification": [], "blockedChecks": [], "readyForIntegration": True,
        }))
        assert any("changedFiles" in p for p in r["problems"]), r

        # 7) aborted run — deltas quarantined, not counted as evidence
        aborted_out = {"run_id": "RUN-test-brainstorm-2", "ritual": "brainstorm", "aborted": True,
                       "cost": {"tokens": 10},
                       "delta_log": [{"round": 1, "changed_what": "x", "anchor": "risk", "evidence": "repro"}]}
        r = run(["run", "record", "--json", "-"], tmp, stdin=json.dumps(aborted_out))
        assert r["ok"] and r["aborted"] and r["valid_deltas"] == 1, r

        # 7a) concurrent run records serialize their board read-modify-write
        concurrent = [
            {"run_id": "RUN-concurrent-a", "ritual": "brainstorm", "cost": {"tokens": 7}, "delta_log": []},
            {"run_id": "RUN-concurrent-b", "ritual": "brainstorm", "cost": {"tokens": 11}, "delta_log": []},
        ]
        env = {**os.environ, "STUDIO_ROOT": str(PLUGIN), "SOURCE_DATE_EPOCH": "1700000000"}
        procs = [
            subprocess.Popen(
                [sys.executable, str(CLI), "run", "record", "--json", "-"],
                cwd=tmp, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            for _ in concurrent
        ]
        results = [proc.communicate(json.dumps(payload)) for proc, payload in zip(procs, concurrent)]
        assert all(proc.returncode == 0 for proc in procs), results
        concurrent_ids = {r["run_id"] for r in board_state(ws)["runs"] if r["run_id"].startswith("RUN-concurrent")}
        assert concurrent_ids == {"RUN-concurrent-a", "RUN-concurrent-b"}, board_state(ws)

        # 8) evidence tally — 1 valid delta from the non-aborted run
        r = run(["evidence"], tmp)
        assert r["ok"] and r["total_valid_deltas"] == 1, r
        assert r["aborted_runs"] == 1 and r["runs"] == 6, r
        assert r["theatre"] is False, r

        # 8a) schema 1 is projected lazily and persisted on the next mutation
        legacy = tmp / "legacy"
        legacy.mkdir()
        legacy_board = {
            "schema": 1, "budget": {"total_tokens": 50, "spent_tokens": 0},
            "tracks": [], "runs": [],
        }
        (legacy / "board.md").write_text(
            "# board\n\n```json\n" + json.dumps(legacy_board) + "\n```\n",
            encoding="utf-8",
        )
        r = run(["--workspace", str(legacy), "board"], tmp)
        assert r["board"]["schema"] == 2 and r["board"]["tracks"] == {}, r
        assert board_state(legacy)["schema"] == 1  # read-only projection does not rewrite
        run(["--workspace", str(legacy), "budget", "--set-total", "60"], tmp)
        assert board_state(legacy)["schema"] == 2

        # 8b) QualityPlan: evidence/floors gate before utility; unknown telemetry stays incomplete
        quality_plan = {
            "schema": 1,
            "id": "quality-v1",
            "criteria": [
                {"id": "artifact-correct", "kind": "artifact", "weight": 0.6, "floor": 0.8, "measure": "tests"},
                {"id": "context-usable", "kind": "context", "weight": 0.4, "floor": 0.7, "measure": "handoff rubric"},
            ],
            "utility_weights": {"quality": 1.0, "tokens": 0.000001, "elapsed": 0.0000001, "avoidable_owner_question": 0.1},
        }
        evidence = [
            {"criterion_id": "artifact-correct", "ref": "test:studio", "score": 0.9},
            {"criterion_id": "context-usable", "ref": "review:context", "score": 0.8},
        ]
        telemetry = {"tokens": 100, "elapsed_ms": 200, "avoidable_owner_questions": 0}
        r = run(["quality", "evaluate", "--plan", json.dumps(quality_plan),
                 "--evidence", json.dumps(evidence[:1]), "--telemetry", json.dumps(telemetry)], tmp)
        assert not r["evaluation"]["floors_passed"] and r["evaluation"]["utility"] is None, r
        low = [evidence[0], {**evidence[1], "score": 0.5}]
        r = run(["quality", "evaluate", "--plan", json.dumps(quality_plan),
                 "--evidence", json.dumps(low), "--telemetry", json.dumps(telemetry)], tmp)
        assert not r["evaluation"]["complete"] and r["evaluation"]["utility"] is None, r
        unknown_tokens = {**telemetry, "tokens": None}
        r = run(["quality", "evaluate", "--plan", json.dumps(quality_plan),
                 "--evidence", json.dumps(evidence), "--telemetry", json.dumps(unknown_tokens)], tmp)
        assert r["evaluation"]["floors_passed"] and not r["evaluation"]["telemetry_complete"], r
        assert r["evaluation"]["utility"] is None, r
        r = run(["quality", "evaluate", "--plan", json.dumps(quality_plan),
                 "--evidence", json.dumps(evidence), "--telemetry", json.dumps(telemetry)], tmp)
        assert r["evaluation"]["complete"] and isinstance(r["evaluation"]["utility"], float), r

        # 8c) Context Kernel projection is immutable/idempotent; compact and prune are local
        item1 = {"id": "item-1", "kind": "fact", "content": "bounded", "source_ref": "issue:54"}
        r = run(["context", "put", "item", "--json", json.dumps(item1)], tmp)
        assert r["changed"] and r["context"]["digest"].startswith("sha256:"), r
        item1_digest = r["context"]["digest"]
        r = run(["context", "put", "item", "--json", json.dumps(item1)], tmp)
        assert not r["changed"], r
        run(["context", "put", "item", "--json", json.dumps({
            "id": "item-2", "kind": "decision", "content": {"boundary": "reference-only"}, "source_ref": "dec:executor",
        })], tmp)
        r = run(["context", "compact", "--bundle-id", "bundle-1", "--item-id", "item-1", "--item-id", "item-2"], tmp)
        assert r["context"]["item_refs"][0] == {"id": "item-1", "digest": item1_digest}, r
        bundle_digest = r["context"]["digest"]
        for delta_id in ("delta-1", "delta-2"):
            run(["context", "put", "delta", "--json", json.dumps({
                "id": delta_id, "base_ref": "bundle-1", "changes": {"add": [delta_id]},
            })], tmp)
        r = run(["context", "prune", "--keep-deltas", "1"], tmp)
        assert len(r["removed"]) == 1 and (ws / "context" / "deltas" / "delta-2.json").is_file(), r
        bad_digest = {**item1, "id": "item-bad", "digest": "sha256:deadbeef"}
        run(["context", "put", "item", "--json", json.dumps(bad_digest)], tmp, expect=6)
        candidate = {
            "id": "promotion-1", "promotion_type": "decision",
            "summary": "keep task-github reference-only", "source_refs": ["item-2"],
            "owner_gate": True,
        }
        r = run(["context", "outbox", "--json", json.dumps(candidate)], tmp)
        assert r["changed"] and r["candidate"]["status"] == "pending", r
        r = run(["context", "outbox", "--json", json.dumps(candidate)], tmp)
        assert not r["changed"] and (ws / "context" / "outbox" / "promotion-1.json").is_file(), r
        run(["context", "outbox", "--json", json.dumps({**candidate, "id": "promotion-no-gate", "owner_gate": False})], tmp, expect=6)

        # 8d) one active executor lease per track, fenced by lease_id and reservation
        run(["budget", "reserve", "res-lease-1", "--lease-id", "lease-a", "--tokens", "20"], tmp)
        r = run(["lease", "claim", "track-a", "--lease-id", "lease-a", "--executor", "external",
                 "--reservation-id", "res-lease-1"], tmp)
        assert r["lease"]["state"] == "claimed", r
        r = run(["lease", "claim", "track-a", "--lease-id", "lease-a", "--executor", "external",
                 "--reservation-id", "res-lease-1"], tmp)
        assert not r["changed"], r
        run(["budget", "reserve", "res-lease-2", "--lease-id", "lease-b", "--tokens", "20"], tmp)
        run(["lease", "claim", "track-a", "--lease-id", "lease-b", "--executor", "native",
             "--reservation-id", "res-lease-2"], tmp, expect=6)
        run(["lease", "transition", "track-a", "--lease-id", "stale", "--state", "running"], tmp, expect=6)
        r = run(["lease", "transition", "track-a", "--lease-id", "lease-a", "--state", "running",
                 "--external-ref", "issue:54"], tmp)
        assert r["lease"]["state"] == "running" and r["lease"]["external_ref"] == "issue:54", r
        r = run(["lease", "transition", "track-a", "--lease-id", "lease-a", "--state", "running"], tmp)
        assert not r["changed"], r
        r = run(["lease", "transition", "track-a", "--lease-id", "lease-a", "--state", "succeeded"], tmp)
        assert r["lease"]["state"] == "succeeded", r

        # 8e) WorkPacket/ResultEnvelope + task-github reference adapter boundary
        packet = {
            "schema": 1, "track_id": "track-external", "objective": "ship guarded parser",
            "acceptance_criteria": ["tests pass", "context handoff is usable"],
            "context_ref": "bundle-1", "digest": bundle_digest,
            "quality_plan_ref": "quality-v1", "constraints": {"state_copy": "references-only"},
            "budget_reservation_id": "res-wf-ext", "gates": ["integration"],
            "executor": "task-github",
        }
        capabilities = {
            "schema": 1, "source": "agent-visible-skill-catalog",
            "catalog": ["task-github:start", "task-github:run", "task-github:done", "task-github:doctor"],
            "doctor": {"mode": "read-only", "status": "pass"},
            "preflight": {"mode": "read-only", "status": "pass"},
        }
        run(["workflow", "validate-packet", "--json", json.dumps(packet)], tmp)
        unsafe_context = {**packet, "track_id": "track-unsafe-context", "context_ref": "../escape"}
        r = run(["workflow", "validate-packet", "--json", json.dumps(unsafe_context)], tmp, expect=6)
        assert any("context_ref" in problem for problem in r["problems"]), r
        missing_context = {**packet, "track_id": "track-missing-context", "context_ref": "bundle-missing"}
        r = run(["workflow", "dispatch", "--packet", json.dumps(missing_context),
                 "--plan", json.dumps(quality_plan), "--capabilities", json.dumps(capabilities),
                 "--lease-id", "lease-missing-context"], tmp, expect=6)
        assert r["error_code"] == "context_pack_required", r
        mismatched_context = {**packet, "track_id": "track-mismatch-context", "digest": "sha256:" + "0" * 64}
        r = run(["workflow", "dispatch", "--packet", json.dumps(mismatched_context),
                 "--plan", json.dumps(quality_plan), "--capabilities", json.dumps(capabilities),
                 "--lease-id", "lease-mismatch-context"], tmp, expect=6)
        assert r["error_code"] == "context_digest_mismatch", r
        r = run(["context", "compact", "--bundle-id", "bundle-tampered",
                 "--item-id", "item-1", "--item-id", "item-2"], tmp)
        tampered_digest = r["context"]["digest"]
        tampered_path = ws / "context" / "bundles" / "bundle-tampered.json"
        tampered_pack = json.loads(tampered_path.read_text(encoding="utf-8"))
        tampered_pack["item_refs"][0]["digest"] = "sha256:" + "1" * 64
        tampered_path.write_text(json.dumps(tampered_pack), encoding="utf-8")
        tampered_packet = {
            **packet, "track_id": "track-tampered-context",
            "context_ref": "bundle-tampered", "digest": tampered_digest,
        }
        r = run(["workflow", "dispatch", "--packet", json.dumps(tampered_packet),
                 "--plan", json.dumps(quality_plan), "--capabilities", json.dumps(capabilities),
                 "--lease-id", "lease-tampered-context"], tmp, expect=6)
        assert r["error_code"] == "digest_mismatch", r
        run(["budget", "reserve", "res-wf-ext", "--lease-id", "lease-wf-ext", "--tokens", "120"], tmp)
        r = run(["workflow", "dispatch", "--packet", json.dumps(packet),
                 "--plan", json.dumps(quality_plan),
                 "--capabilities", json.dumps(capabilities), "--lease-id", "lease-wf-ext"], tmp)
        assert r["selected_executor"] == "external" and not r["fallback"], r
        assert r["worker_handoff"]["kind"] == "separate-worker-handoff", r
        assert r["worker_handoff"]["state_contract"].startswith("return external_ref"), r
        success = {
            "status": "succeeded", "external_ref": "issue:54", "artifact_refs": ["git:abc123"],
            "evidence_refs": evidence, "context_delta_refs": ["delta-2"], "telemetry": telemetry,
            "gates": [{"id": "integration", "status": "passed", "evidence_ref": "test:full"}],
            "failure_class": None,
        }
        run(["workflow", "validate-result", "--json", json.dumps(success)], tmp)
        weakened_plan = {
            **quality_plan,
            "criteria": [
                {**quality_plan["criteria"][0], "floor": 0.1},
                {**quality_plan["criteria"][1], "floor": 0.1},
            ],
        }
        r = run(["workflow", "result", "--packet", json.dumps(packet), "--plan", json.dumps(weakened_plan),
                 "--json", json.dumps(success), "--lease-id", "lease-wf-ext"], tmp, expect=6)
        assert r["error_code"] == "quality_plan_binding_mismatch", r
        r = run(["workflow", "result", "--packet", json.dumps(packet), "--plan", json.dumps(quality_plan),
                 "--json", json.dumps(success), "--lease-id", "lease-wf-ext"], tmp)
        assert r["readyForIntegration"] and r["lease"]["state"] == "succeeded", r
        assert r["lease"]["external_ref"] == "issue:54" and r["lease"]["coarse_status"] == "succeeded", r
        assert not ({"issue", "branch", "pr", "raw_transcript"} & set(r["lease"])), r
        r = run(["workflow", "result", "--packet", json.dumps(packet), "--plan", json.dumps(quality_plan),
                 "--json", json.dumps(success), "--lease-id", "lease-wf-ext"], tmp)
        assert not r["changed"], r

        # succeeded artifacts/evidence/gates still wait when token telemetry is unknown
        unknown_packet = {
            **packet,
            "track_id": "track-unknown-tokens",
            "budget_reservation_id": "res-unknown-tokens",
        }
        run(["budget", "reserve", "res-unknown-tokens", "--lease-id", "lease-unknown-tokens",
             "--tokens", "80"], tmp)
        run(["workflow", "dispatch", "--packet", json.dumps(unknown_packet),
             "--plan", json.dumps(quality_plan), "--capabilities", json.dumps(capabilities),
             "--lease-id", "lease-unknown-tokens"], tmp)
        unknown_success = {
            **success,
            "external_ref": "issue:unknown-tokens",
            "telemetry": {**telemetry, "tokens": None},
        }
        spent_before_unknown = board_state(ws)["budget"]["spent_tokens"]
        r = run(["workflow", "result", "--packet", json.dumps(unknown_packet),
                 "--plan", json.dumps(quality_plan), "--json", json.dumps(unknown_success),
                 "--lease-id", "lease-unknown-tokens"], tmp)
        assert not r["readyForIntegration"] and not r["evaluation"]["telemetry_complete"], r
        assert r["lease"]["state"] == "waiting_gate" and r["lease"]["coarse_status"] == "incomplete", r
        board_after_unknown = board_state(ws)
        assert board_after_unknown["budget"]["spent_tokens"] == spent_before_unknown, board_after_unknown
        unknown_reservation = board_after_unknown["budget"]["reservations"]["res-unknown-tokens"]
        assert unknown_reservation["status"] == "dispatched", unknown_reservation
        assert "settled_tokens" not in unknown_reservation, unknown_reservation

        # pre-dispatch unavailable/unknown falls back to native before any external start
        fallback_packet = {**packet, "track_id": "track-fallback", "budget_reservation_id": "res-fallback"}
        run(["budget", "reserve", "res-fallback", "--lease-id", "lease-fallback", "--tokens", "30"], tmp)
        r = run(["workflow", "dispatch", "--packet", json.dumps(fallback_packet),
                 "--plan", json.dumps(quality_plan),
                 "--lease-id", "lease-fallback"], tmp)
        assert r["selected_executor"] == "native" and r["fallback"] and r["worker_handoff"] is None, r

        # after external dispatch, failure requires resume or cancel-confirm+release before fallback
        failed_packet = {**packet, "track_id": "track-failed", "budget_reservation_id": "res-failed"}
        run(["budget", "reserve", "res-failed", "--lease-id", "lease-failed", "--tokens", "40"], tmp)
        run(["workflow", "dispatch", "--packet", json.dumps(failed_packet),
             "--plan", json.dumps(quality_plan),
             "--capabilities", json.dumps(capabilities), "--lease-id", "lease-failed"], tmp)
        failure = {
            "status": "failed", "external_ref": "issue:failed", "artifact_refs": [],
            "evidence_refs": [], "context_delta_refs": [],
            "telemetry": {"tokens": None, "elapsed_ms": 5, "avoidable_owner_questions": 0},
            "gates": [{"id": "integration", "status": "failed", "evidence_ref": "log:failure"}],
            "failure_class": "retriable",
        }
        r = run(["workflow", "result", "--packet", json.dumps(failed_packet), "--plan", json.dumps(quality_plan),
                 "--json", json.dumps(failure), "--lease-id", "lease-failed"], tmp)
        assert not r["readyForIntegration"] and r["lease"]["recovery_required"], r
        assert r["lease"]["state"] == "failed", r
        r = run(["workflow", "dispatch", "--packet", json.dumps(failed_packet),
                 "--plan", json.dumps(quality_plan), "--capabilities", json.dumps(capabilities),
                 "--lease-id", "lease-failed"], tmp, expect=6)
        assert r["error_code"] == "recovery_required", r
        premature = {**failed_packet, "budget_reservation_id": "res-premature", "executor": "native"}
        run(["budget", "reserve", "res-premature", "--lease-id", "lease-premature", "--tokens", "10"], tmp)
        r = run(["workflow", "dispatch", "--packet", json.dumps(premature),
                 "--plan", json.dumps(quality_plan), "--lease-id", "lease-premature"], tmp, expect=6)
        assert r["error_code"] == "active_lease_exists", r
        r = run(["workflow", "recover", "track-failed", "--lease-id", "lease-failed", "--action", "resume"], tmp)
        assert not r["native_fallback_allowed"] and r["lease"]["coarse_status"] == "running", r
        run(["workflow", "result", "--packet", json.dumps(failed_packet), "--plan", json.dumps(quality_plan),
             "--json", json.dumps(failure), "--lease-id", "lease-failed"], tmp)
        r = run(["workflow", "recover", "track-failed", "--lease-id", "lease-failed", "--action", "cancel-release"], tmp)
        assert r["native_fallback_allowed"] and r["lease"]["cancel_confirmed"], r
        native_packet = {**failed_packet, "budget_reservation_id": "res-native", "executor": "native"}
        run(["budget", "reserve", "res-native", "--lease-id", "lease-native", "--tokens", "10"], tmp)
        r = run(["workflow", "dispatch", "--packet", json.dumps(native_packet),
                 "--plan", json.dumps(quality_plan), "--lease-id", "lease-native"], tmp)
        assert r["selected_executor"] == "native" and not r["fallback"], r

        # wiki provider is optional; absent preserves outbox, available still needs owner gate
        r = run(["workflow", "promote", "promotion-1", "--provider-status", "unavailable"], tmp)
        assert r["provider"] == "local-outbox" and r["handoff"] is None, r
        run(["workflow", "promote", "promotion-1", "--provider-status", "available"], tmp, expect=6)
        r = run(["workflow", "promote", "promotion-1", "--provider-status", "available", "--owner-approved"], tmp)
        assert r["provider"] == "wiki-markdown" and r["handoff"]["skill"] == "wiki-markdown:wiki", r

        # 9) config (.studio.yml) — scaffold, validate, parse, guards
        cfg = tmp / ".studio.yml"
        r = run(["config", "scaffold", "--path", str(cfg)], tmp)
        assert r["ok"] and r["created"], r
        run(["config", "scaffold", "--path", str(cfg)], tmp, expect=2)     # no clobber
        r = run(["config", "validate", "--path", str(cfg)], tmp)
        assert r["ok"] and not [p for p in r["problems"] if p["severity"] == "error"], r
        r = run(["config", "get", "--path", str(cfg)], tmp)
        assert r["config"]["roles"]["critic"]["effort"] == "high", r
        assert r["config"]["roles"]["architect"]["effort"] == "high", r
        assert r["config"]["roles"]["creator"]["effort"] == "medium", r
        assert r["config"]["defaults"]["model"] is None, r                  # blank → null → inherit
        assert r["config"]["rituals"]["brainstorm"]["diverge"]["effort"] == "low", r
        #    bad effort value → hard error on BOTH validate and get (exit 6),
        #    so a bad config can never reach the brokers via the producer's `get`
        (tmp / "bad.yml").write_text("defaults:\n  effort: turbo\n", encoding="utf-8")
        r = run(["config", "validate", "--path", str(tmp / "bad.yml")], tmp, expect=6)
        assert any("effort" in p["msg"] for p in r["problems"]), r
        run(["config", "get", "--path", str(tmp / "bad.yml")], tmp, expect=6)
        #    tab indentation is rejected (silently mis-parses otherwise) → exit 4
        (tmp / "tabs.yml").write_text("roles:\n\tdev:\n\t\teffort: high\n", encoding="utf-8")
        run(["config", "get", "--path", str(tmp / "tabs.yml")], tmp, expect=4)
        #    unknown model is a warning, not an error (still exit 0)
        (tmp / "warn.yml").write_text("defaults:\n  model: gpt\n", encoding="utf-8")
        r = run(["config", "validate", "--path", str(tmp / "warn.yml")], tmp)
        assert r["ok"] and any(p["severity"] == "warning" for p in r["problems"]), r
        #    absent config → present False, everything inherits the session
        r = run(["config", "get", "--path", str(tmp / "none.yml")], tmp)
        assert r["present"] is False and r["config"] == {}, r

        # 10) cast suggest — producer can turn a work kind into concrete crew
        r = run(["cast", "suggest", "idea"], tmp)
        assert r["ok"] and r["kind"] == "idea", r
        assert r["ritual"] == "brainstorm", r
        assert r["crew"] == ["planner-a", "planner-b", "researcher", "critic"], r
        assert r["participants"] == ["planner-a", "planner-b", "researcher"], r
        assert r["critic"] is True, r
        assert [p["name"] for p in r["personas"]] == r["participants"], r
        assert r["personas"][2]["role"] == "자료수집", r
        assert "근거 우선" in r["personas"][2]["prior"], r
        assert r["missing"] == [], r

        r = run(["cast", "suggest", "implementation"], tmp)
        assert r["ritual"] == "pairing", r
        assert r["crew"] == ["dev", "qa"], r
        assert r["participants"] == ["dev", "qa"], r
        assert r["critic"] is True, r

        r = run(["cast", "suggest", "unknown-kind"], tmp, expect=6)
        assert r["error_code"] == "unknown_cast", r

        # 10a) an explicit workspace remains supported for init and state commands
        custom_ws = tmp / "custom-studio-workspace"
        r = run(["--workspace", str(custom_ws), "init"], tmp)
        assert r["ok"] and Path(r["workspace"]) == custom_ws, r
        assert (custom_ws / "board.md").is_file()
        r = run(["--workspace", str(custom_ws), "mode", "status"], tmp)
        assert r["ok"] and r["mode"]["active"] is False, r

        # 11) producer contract — main thread may coordinate, not edit/integrate
        producer = plugin_text("skills/producer/SKILL.md")
        for phrase in (
            "studio 규약은 Codex/Claude의 일반",
            "`apply_patch`, `git apply`, 직접 파일 수정",
            "track 변경을 main에 직접 반영",
            "Workflow가 callable tool로 없으면 `multi_agent_v1`",
            "producer의 역할은 **spawn / wait / record / report**뿐",
            "QA pass. track 변경을 main에 반영할까요?",
            "integrator worker",
            "`readyForIntegration:false`이면",
            "task-github Python/JS callable API를 만들거나 import하지 않는다",
            "agent-visible `task-github:*` skill catalog",
            "`separate-worker-handoff`",
            "`workflow recover --action resume`",
            "`--action cancel-release`",
            "ResultEnvelope 필수 필드",
            "provider가 absent/unknown이면 `context outbox`",
        ):
            assert phrase in producer, phrase

        # 12) pairing output carries the integration handoff contract
        pairing = plugin_text("broker/pairing.workflow.js")
        for phrase in (
            "worktreePath: WT",
            "branch: BRANCH",
            "changedFiles: [...changedFiles]",
            "verification,",
            "blockedChecks,",
            "readyForIntegration,",
        ):
            assert phrase in pairing, phrase

    print("all studio.py checks passed")


if __name__ == "__main__":
    main()
