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

        # 6c) raising the budget above spend clears the paused state
        r = run(["budget", "--set-total", "1000"], tmp)
        assert "mission_state" not in board_state(ws), board_state(ws)

        # 6d) budget reserve/dispatch/settle is fenced and idempotent
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
        assert r["changed"] and r["spent_tokens"] == 180, r
        r = run(["budget", "settle", "res-1", "--lease-id", "lease-1", "--tokens", "30"], tmp)
        assert not r["changed"] and r["reservation"]["settled_tokens"] == 30, r

        # 6e) malformed run outputs hit the exit-code contract, not a crash
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
        assert r["aborted_runs"] == 1 and r["runs"] == 4, r
        assert r["theatre"] is False, r

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
