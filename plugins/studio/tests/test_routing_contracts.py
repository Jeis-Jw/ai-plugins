#!/usr/bin/env python3
"""Targeted routing regressions for Studio's runtime and review contracts."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent
CLI = PLUGIN / "scripts" / "studio.py"


def digest(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha(char: str) -> str:
    return "sha256:" + char * 64


def run(args: list[str], cwd: Path, expect: int = 0) -> dict:
    env = {
        **os.environ,
        "STUDIO_ROOT": str(PLUGIN),
        "SOURCE_DATE_EPOCH": "1700000000",
    }
    proc = subprocess.run(
        [sys.executable, str(CLI), *args], cwd=cwd, env=env,
        capture_output=True, text=True,
    )
    assert proc.returncode == expect, (
        f"args={args} expected={expect} actual={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout)


def review_lease(lease_id: str, edge_id: str, provider: str) -> dict:
    value = {
        "schema": "workflow-review-lease/v1",
        "lease_id": lease_id,
        "owner": "studio",
        "provider": provider,
        "episode_id": "episode-routing",
        "edge_id": edge_id,
        "requirement": "independent",
        "criteria_digest": sha("a"),
        "evidence_refs": [],
    }
    return {**value, "digest": digest(value)}


def tool_capability(provider: str, mission: str, environment: str, status: str) -> dict:
    return {
        "schema": "studio-capability-snapshot/v1",
        "provider": provider,
        "mission_id": mission,
        "environment_digest": environment,
        "status": status,
        "contracts": ["workflow-review-lease/v1"],
    }


def runtime_capability(
    runtime: str,
    *,
    models: list[str] | None,
    efforts: list[str] | None,
) -> dict:
    return {
        "schema": "studio-runtime-capability/v1",
        "runtime": runtime,
        "version": "test-runtime-1",
        "advertised_models": models,
        "advertised_efforts": efforts,
    }


def canonical_plan(plan: dict) -> dict:
    body = {key: value for key, value in plan.items() if key not in {"digest", "plan_id"}}
    plan_digest = digest(body)
    sealed = {**body, "plan_id": "routing-" + plan_digest.split(":", 1)[1][:16]}
    return {**sealed, "digest": plan_digest}


def setup_dispatch_inputs(tmp: Path) -> tuple[dict, dict]:
    run(["init"], tmp)
    run(["context", "put", "item", "--json", json.dumps({
        "id": "item-routing", "kind": "fact", "content": "runtime guarded",
        "source_ref": "test:routing",
    })], tmp)
    compacted = run([
        "context", "compact", "--bundle-id", "bundle-routing",
        "--item-id", "item-routing",
    ], tmp)
    plan = {
        "schema": 1,
        "id": "quality-routing",
        "criteria": [
            {
                "id": "routing-correct", "kind": "artifact", "weight": 0.7,
                "floor": 1.0, "measure": "targeted test",
            },
            {
                "id": "handoff-usable", "kind": "context", "weight": 0.3,
                "floor": 1.0, "measure": "canonical binding",
            },
        ],
        "utility_weights": {
            "quality": 1.0, "tokens": 0.0, "elapsed": 0.0,
            "avoidable_owner_question": 0.0,
        },
    }
    packet = {
        "schema": 1,
        "track_id": "track-routing",
        "objective": "enforce runtime routing",
        "acceptance_criteria": ["runtime capability is verified"],
        "context_ref": "bundle-routing",
        "digest": compacted["context"]["digest"],
        "quality_plan_ref": "quality-routing",
        "constraints": {"state_copy": "references-only"},
        "budget_reservation_id": "res-routing",
        "gates": ["integration"],
        "executor": "native",
    }
    run(["budget", "reserve", "res-routing", "--lease-id", "lease-routing", "--tokens", "10"], tmp)
    return packet, plan


def main() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        packet, quality_plan = setup_dispatch_inputs(tmp)
        environment = sha("9")

        mismatch = run([
            "routing", "plan", "--mission-id", "mission-runtime-mismatch",
            "--environment-digest", environment,
            "--agent-runtime", "claude", "--host-runtime", "codex",
        ], tmp)["routing_plan"]
        assert mismatch["action"] == "runtime-capability-required", mismatch
        assert mismatch["runtime_profile"] == "claude", mismatch
        assert not mismatch["runtime_capability"]["dispatch_allowed"], mismatch

        verified = run([
            "routing", "plan", "--mission-id", "mission-runtime-verified",
            "--environment-digest", environment,
            "--agent-runtime", "codex", "--runtime-capability",
            json.dumps(runtime_capability("codex", models=None, efforts=None)),
        ], tmp)["routing_plan"]
        assert verified["action"] == "dispatch", verified
        tampered = canonical_plan({
            **verified,
            "runtime_capability": {
                **verified["runtime_capability"],
                "dispatch_allowed": False,
            },
        })
        rejected = run([
            "workflow", "dispatch", "--packet", json.dumps(packet),
            "--plan", json.dumps(quality_plan),
            "--routing-plan", json.dumps(tampered),
            "--lease-id", "lease-routing",
        ], tmp, expect=6)
        assert rejected["error_code"] == "runtime_not_dispatchable", rejected

        reviewer_cfg = tmp / "reviewer.yml"
        reviewer_cfg.write_text(
            "tools:\n  reviewer:\n    provider: session-review\n"
            "    activation: auto\n    fallback: native\n",
            encoding="utf-8",
        )
        session_lease = review_lease("lease-session", "edge-replan", "session-review")
        pending = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--review-need", "--review-lease", json.dumps(session_lease),
        ], tmp)["routing_plan"]
        assert pending["action"] == "capability-required", pending
        unavailable = tool_capability(
            "session-review", "mission-review-replan", environment, "unavailable",
        )
        first = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--review-need", "--review-lease", json.dumps(session_lease),
            "--capabilities", json.dumps({"session-review": unavailable}),
        ], tmp)["routing_plan"]
        assert first["action"] == "review-lease-replan-required", first
        assert first["reviewer"]["selected"] is None, first
        authorization = first["reviewer"]["replan"]
        native_lease = authorization["target_lease"]
        assert native_lease["lease_id"] == session_lease["lease_id"], authorization
        assert native_lease["edge_id"] == session_lease["edge_id"], authorization
        assert native_lease["provider"] == "native", authorization
        cached = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--review-need", "--review-lease", json.dumps(session_lease),
        ], tmp)["routing_plan"]
        assert cached["action"] == "review-lease-replan-required", cached
        assert cached["probe_targets"] == [], cached
        review_dispatch = run([
            "workflow", "dispatch", "--packet", json.dumps(packet),
            "--plan", json.dumps(quality_plan),
            "--routing-plan", json.dumps(cached),
            "--lease-id", "lease-routing",
        ], tmp, expect=6)
        assert review_dispatch["error_code"] == "routing_not_dispatchable", review_dispatch

        wrong_mission = run([
            "routing", "plan", "--mission-id", "mission-review-other",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--reviewer", "native", "--review-need",
            "--review-lease", json.dumps(native_lease),
        ], tmp, expect=6)
        assert wrong_mission["error_code"] == "review_edge_rebind", wrong_mission
        wrong_edge_lease = review_lease("lease-session", "edge-replan-other", "native")
        wrong_edge = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--reviewer", "native", "--review-need",
            "--review-lease", json.dumps(wrong_edge_lease),
        ], tmp, expect=6)
        assert wrong_edge["error_code"] == "review_edge_rebind", wrong_edge
        wrong_digest_lease = review_lease("lease-other", "edge-replan", "native")
        wrong_digest = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--reviewer", "native", "--review-need",
            "--review-lease", json.dumps(wrong_digest_lease),
        ], tmp, expect=6)
        assert wrong_digest["error_code"] == "review_edge_rebind", wrong_digest
        replanned = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--reviewer", "native", "--review-need",
            "--review-lease", json.dumps(native_lease),
        ], tmp)["routing_plan"]
        assert replanned["action"] == "dispatch", replanned
        assert replanned["reviewer"]["selected"] == "native", replanned
        assert replanned["probe_targets"] == [], replanned
        accepted_rebind = run([
            "routing", "plan", "--mission-id", "mission-review-replan",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--review-need", "--review-lease", json.dumps(session_lease),
        ], tmp, expect=6)
        assert accepted_rebind["error_code"] == "review_edge_rebind", accepted_rebind

        legacy_lease = review_lease("lease-legacy", "edge-legacy", "native")
        board_path = tmp / ".studio" / "board.md"
        board_text = board_path.read_text(encoding="utf-8")
        board_prefix, board_rest = board_text.split("```json\n", 1)
        board_json, board_suffix = board_rest.split("\n```\n", 1)
        board = json.loads(board_json)
        board["review_lease_edges"][legacy_lease["edge_id"]] = legacy_lease["digest"]
        board_path.write_text(
            board_prefix + "```json\n" + json.dumps(board, ensure_ascii=False, indent=2)
            + "\n```\n" + board_suffix,
            encoding="utf-8",
        )
        legacy_same = run([
            "routing", "plan", "--mission-id", "mission-legacy-edge",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--reviewer", "native", "--review-need",
            "--review-lease", json.dumps(legacy_lease),
        ], tmp)["routing_plan"]
        assert legacy_same["action"] == "dispatch", legacy_same
        legacy_rebind = run([
            "routing", "plan", "--mission-id", "mission-legacy-edge",
            "--environment-digest", environment, "--config", str(reviewer_cfg),
            "--reviewer", "native", "--review-need",
            "--review-lease", json.dumps(review_lease("lease-new", "edge-legacy", "native")),
        ], tmp, expect=6)
        assert legacy_rebind["error_code"] == "review_edge_rebind", legacy_rebind

        profile_cfg = tmp / "profiles.yml"
        profile_cfg.write_text(
            "roles:\n  architect:\n    model: common-architect\n    effort: deliberate\n"
            "providers:\n  codex:\n    roles:\n      architect:\n"
            "        model: codex-architect\n        effort: deep\n",
            encoding="utf-8",
        )
        structural = run(["config", "validate", "--path", str(profile_cfg)], tmp)
        assert not structural["problems"], structural
        supported = run([
            "routing", "plan", "--mission-id", "mission-advertised",
            "--environment-digest", environment, "--config", str(profile_cfg),
            "--agent-runtime", "codex", "--role", "architect",
            "--runtime-capability", json.dumps(runtime_capability(
                "codex", models=["codex-architect"], efforts=["deep"],
            )),
        ], tmp)["routing_plan"]
        validation = supported["agent_profile"]["validation"]
        assert validation["model"]["status"] == "supported", supported
        assert validation["model"]["source"] == "runtime-advertised-models", supported
        assert validation["effort"]["status"] == "supported", supported

        unsupported = run([
            "routing", "plan", "--mission-id", "mission-unsupported",
            "--environment-digest", environment, "--config", str(profile_cfg),
            "--agent-runtime", "codex", "--role", "architect",
            "--runtime-capability", json.dumps(runtime_capability(
                "codex", models=["other-model"], efforts=["low"],
            )),
        ], tmp, expect=6)
        assert unsupported["error_code"] == "unsupported_runtime_profile", unsupported
        assert {p["field"] for p in unsupported["problems"]} == {"model", "effort"}, unsupported

        unknown = run([
            "config", "resolve", "--path", str(profile_cfg),
            "--agent-runtime", "codex", "--role", "architect",
        ], tmp)["profile"]
        assert unknown["validation"]["model"] == {
            "status": "unknown", "source": "runtime-advertisement-unavailable",
        }, unknown
        assert unknown["validation"]["effort"] == {
            "status": "unknown", "source": "runtime-advertisement-unavailable",
        }, unknown

    print("all targeted Studio routing contract checks passed")


def test_routing_contracts() -> None:
    main()


if __name__ == "__main__":
    main()
