#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


context_cli = load("context_cli_cross", ROOT / "plugins/context-core/skills/context/scripts/context_cli.py")
decision_cli = load("decision_cli_cross", ROOT / "plugins/context-decision/skills/decision/scripts/decision_cli.py")
CORE_CLI = ROOT / "plugins/context-core/skills/context/scripts/context_cli.py"
DECISION_CLI = ROOT / "plugins/context-decision/skills/decision/scripts/decision_cli.py"


def run_cli(repo: Path, cli: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(cli), *arguments],
        cwd=repo,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
    )


def initialize(repo: Path) -> None:
    core = context_cli.build_init_bundle(repo)
    context_cli.apply_bundle(repo, core["bundle"], core["approval_digest"])
    addon = decision_cli.build_init_plan()
    area = context_cli.build_area_register_bundle(repo, addon["owner_descriptor"], addon["index_seed"])
    context_cli.apply_bundle(repo, area["bundle"], area["approval_digest"])


def choice(candidate_id: str = "cand_550e8400e29b41d4a716446655440000", claim_key: str = "choice", *, informed_by: list[str] | None = None) -> dict:
    value = {
        "schema": "context-capture-candidate/v1",
        "candidate_id": candidate_id,
        "claim_key": claim_key,
        "title": "인증 세션 소유권",
        "claim": "인증 세션은 BFF가 소유한다.",
        "summary": "OAuth callback과 cookie 경계를 BFF로 통합한다.",
        "captured_from": "conversation",
        "requested_kind": None,
        "specialized_kinds": ["decision"],
        "fallback_kind": "observation",
        "scope_hint": "project/auth",
        "source_refs": ["conversation:test"],
        "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
        "owner_inputs": {
            "decision": {
                "decision": "인증 세션은 BFF가 소유한다.",
                "rationale": "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
                "rejected_alternatives": ["SPA token 소유: XSS 노출이 커져 반려"],
                "decision_key": "session-owner",
            },
            "observation": {
                "observation": "대화에서 인증 세션을 BFF가 소유하기로 합의했다는 진술이 있었다.",
                "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
            },
        },
    }
    if informed_by:
        value["informed_by"] = informed_by
    return value


def decision_attestation(value: dict) -> dict:
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": value["schema"],
        "input_digest": decision_cli.canonical_digest(value),
        "assertions": [
            {"name": "explicit_choice", "value": True, "evidence_pointers": ["/owner_inputs/decision/decision"]},
            {"name": "scope_identified", "value": True, "evidence_pointers": ["/scope_hint"]},
            {"name": "commitment_present", "value": True, "evidence_pointers": ["/evidence/0"]},
        ],
    }


def obs_attestation(value: dict) -> dict:
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": value["schema"],
        "input_digest": context_cli.canonical_digest(value),
        "assertions": [
            {"name": "reusable_observation", "value": True, "evidence_pointers": ["/owner_inputs/observation/observation"]},
            {"name": "evidence_present", "value": True, "evidence_pointers": ["/owner_inputs/observation/evidence/0"]},
        ],
    }


class CrossPluginFlowTests(unittest.TestCase):
    def test_acceptance_18_owner_installed(self) -> None:
        value = choice()
        owner_result = decision_cli.build_claim_result(value, decision_attestation(value))
        capabilities = context_cli.capabilities_result()
        capabilities["owners"].append(decision_cli.decision_capability())
        routed = context_cli.route_candidates([value], capabilities, [owner_result])
        self.assertEqual(1, len(routed["routes"]))
        self.assertEqual("context-decision", routed["routes"][0]["owner"])
        self.assertEqual("decision", routed["routes"][0]["target_kind"])

    def test_acceptance_21_independent_claims(self) -> None:
        decision = choice()
        observation = {
            **choice("cand_123e4567e89b42d3a456426614174000", "fact"),
            "requested_kind": "observation",
            "specialized_kinds": ["observation"],
            "fallback_kind": None,
            "claim": "Safari에서 third-party cookie가 차단된다.",
        }
        observation["owner_inputs"] = {"observation": {"observation": observation["claim"], "evidence": ["재현 fixture"]}}
        dec_result = decision_cli.build_claim_result(decision, decision_attestation(decision))
        obs_result = context_cli.draft_owner_result(observation, obs_attestation(observation))
        capabilities = context_cli.capabilities_result()
        capabilities["owners"].append(decision_cli.decision_capability())
        routed = context_cli.route_candidates([observation, decision], capabilities, [obs_result, dec_result])
        self.assertEqual(["observation", "decision"], [item["target_kind"] for item in routed["routes"]])

    def test_acceptance_31_evidence_relation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            initialize(repo)
            obs_candidate = {
                **choice("cand_123e4567e89b42d3a456426614174000", "fact"),
                "requested_kind": "observation",
                "specialized_kinds": ["observation"],
                "fallback_kind": None,
                "title": "Safari cookie 관찰",
                "claim": "Safari에서 third-party cookie가 차단된다.",
                "summary": "Safari cookie 제한을 재현했다.",
            }
            obs_candidate["owner_inputs"] = {"observation": {"observation": obs_candidate["claim"], "evidence": ["재현 fixture"]}}
            obs_result = context_cli.draft_owner_result(obs_candidate, obs_attestation(obs_candidate), now="2026-08-14T09:00:00+09:00")
            obs_bundle = context_cli.finalize_owner_result(repo, obs_result)
            context_cli.apply_bundle(repo, obs_bundle["bundle"], obs_bundle["approval_digest"])
            obs_id = obs_result["effects"][0]["id"]

            value = choice(informed_by=[obs_id])
            dec_result = decision_cli.build_claim_result(value, decision_attestation(value), repo=repo)
            receipt = decision_cli.validate_batch(repo, dec_result)
            dec_bundle = context_cli.finalize_owner_result(repo, dec_result, receipt)
            context_cli.apply_bundle(repo, dec_bundle["bundle"], dec_bundle["approval_digest"])
            self.assertEqual("current", context_cli.observation_read(repo, obs_id)["state"])
            dec_id = dec_result["effects"][0]["id"]
            decision = decision_cli.read_decision(repo, dec_id)
            self.assertEqual([obs_id], decision_cli.find_current(repo, dec_id)["frontmatter"]["relations"]["informed_by"])

    def test_acceptance_32_fallback_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            initialize(repo)
            fallback = choice()
            fallback["requested_kind"] = "observation"
            fallback["specialized_kinds"] = ["observation"]
            fallback["fallback_kind"] = None
            fallback["kind_hint"] = "decision"
            fallback["owner_inputs"] = {"observation": fallback["owner_inputs"]["observation"]}
            obs_result = context_cli.draft_owner_result(fallback, obs_attestation(fallback), now="2026-08-14T09:00:00+09:00")
            obs_bundle = context_cli.finalize_owner_result(repo, obs_result)
            context_cli.apply_bundle(repo, obs_bundle["bundle"], obs_bundle["approval_digest"])
            obs_id = obs_result["effects"][0]["id"]

            dec_candidate = choice("cand_123e4567e89b42d3a456426614174000", "choice-import")
            dec_result = decision_cli.build_claim_result(
                dec_candidate, decision_attestation(dec_candidate), repo=repo,
                created_at="2026-08-14T09:00:00+09:00",
            )
            lifecycle = context_cli.prepare_lifecycle_input(repo, "decision_fallback_import", obs_id, dec_result)
            same_claim = {
                "schema": "context-semantic-attestation/v1",
                "operation": "same_claim",
                "input_schema": lifecycle["schema"],
                "input_digest": decision_cli.canonical_digest(lifecycle),
                "assertions": [{"name": "same_semantic_claim", "value": True, "evidence_pointers": ["/predecessor/primary_claim", "/successor/primary_claim"]}],
            }
            imported = decision_cli.build_fallback_import_result(repo, obs_id, dec_result, lifecycle, same_claim, retired_at="2026-08-14T10:00:00+09:00")
            receipt = decision_cli.validate_batch(repo, imported)
            bundle = context_cli.finalize_owner_result(repo, imported, receipt)
            self.assertEqual({"decision", "observation"}, {effect["area"] for effect in bundle["approval_preview"]["effects"]})
            context_cli.apply_bundle(repo, bundle["bundle"], bundle["approval_digest"])
            self.assertEqual("history", context_cli.observation_read(repo, obs_id)["state"])
            dec_id = next(effect["id"] for effect in imported["effects"] if effect["area"] == "decision")
            self.assertIn(obs_id, decision_cli.find_current(repo, dec_id)["frontmatter"]["supersedes"])

    def test_acceptance_37_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            core = context_cli.build_init_bundle(repo)
            context_cli.apply_bundle(repo, core["bundle"], core["approval_digest"])

            def make(number: int) -> dict:
                value = {
                    **choice(f"cand_550e8400e29b41d4a71644665544{number:04x}", f"fact-{number}"),
                    "requested_kind": "observation",
                    "specialized_kinds": ["observation"],
                    "fallback_kind": None,
                    "title": f"병렬 관찰 {number}",
                    "claim": f"병렬 claim {number}",
                    "summary": f"병렬 capture {number}",
                }
                value["owner_inputs"] = {"observation": {"observation": value["claim"], "evidence": [f"fixture {number}"]}}
                return context_cli.draft_owner_result(value, obs_attestation(value), now=f"2026-08-14T09:00:0{number}+09:00")

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(make, (1, 2)))
            bundles = []
            for result in results:
                bundle = context_cli.finalize_owner_result(repo, result, prior_bundles=bundles)
                context_cli.apply_bundle(repo, bundle["bundle"], bundle["approval_digest"])
                bundles.append(bundle["bundle"])
            index = context_cli.parse_area_index((repo / "context/observation/observation.index.md").read_text(encoding="utf-8"))
            self.assertEqual(2, len(index.current))
            self.assertEqual(2, len({row["id"] for row in index.current}))

    def test_acceptance_44_decision_init_bootstraps_absent_core(self) -> None:
        fixtures = ROOT / "tests/context-v1/fixtures/host-inventory"
        case = next(
            item
            for item in json.loads((fixtures / "preflight-cases.json").read_text(encoding="utf-8"))["cases"]
            if item["expected_code"] == "core_uninitialized"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repository"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "keep.txt").write_text("preserve\n", encoding="utf-8")
            inventory = root / "inventory.json"
            doctor = root / "doctor.json"
            inventory.write_text(json.dumps(case["inventory"], ensure_ascii=False), encoding="utf-8")
            doctor.write_text(json.dumps(case["doctor"], ensure_ascii=False), encoding="utf-8")
            planned = run_cli(
                repo,
                DECISION_CLI,
                "init",
                "--host",
                case["host"],
                "--core-inventory",
                f"@{inventory}",
                "--core-doctor",
                f"@{doctor}",
                "--json",
            )
            self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
            plan = json.loads(planned.stdout)["result"]
            self.assertEqual("absent", plan["core_repository_state"])
            self.assertEqual("pending", plan["phases"][0]["status"])
            descriptor = root / "descriptor.json"
            seed = root / "decision.index.md"
            descriptor.write_text(json.dumps(plan["owner_descriptor"], ensure_ascii=False), encoding="utf-8")
            seed.write_text(plan["index_seed"], encoding="utf-8")

            completed = run_cli(
                repo,
                CORE_CLI,
                "bootstrap",
                "--descriptor",
                f"@{descriptor}",
                "--index-seed",
                f"@{seed}",
                "--json",
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)["result"]
            self.assertEqual(["applied", "applied"], [phase["status"] for phase in result["phases"]])
            self.assertEqual("ready", result["doctor"]["repository_state"])
            self.assertTrue((repo / "context/decision/decision.index.md").is_file())
            self.assertEqual("preserve\n", (repo / "keep.txt").read_text(encoding="utf-8"))
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / "CLAUDE.md").exists())

            repeated = run_cli(
                repo,
                CORE_CLI,
                "bootstrap",
                "--descriptor",
                f"@{descriptor}",
                "--index-seed",
                f"@{seed}",
                "--json",
            )
            self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
            self.assertEqual(
                ["noop", "noop"],
                [phase["status"] for phase in json.loads(repeated.stdout)["result"]["phases"]],
            )

    def test_acceptance_45_bootstrap_phase_failure_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repository"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            plan = decision_cli.build_init_plan()
            descriptor = root / "descriptor.json"
            invalid_seed = root / "invalid.index.md"
            valid_seed = root / "decision.index.md"
            descriptor.write_text(json.dumps(plan["owner_descriptor"], ensure_ascii=False), encoding="utf-8")
            invalid_seed.write_text(plan["index_seed"].replace('owner: "context-decision"', 'owner: "other"'), encoding="utf-8")
            valid_seed.write_text(plan["index_seed"], encoding="utf-8")

            failed = run_cli(
                repo,
                CORE_CLI,
                "bootstrap",
                "--descriptor",
                f"@{descriptor}",
                "--index-seed",
                f"@{invalid_seed}",
                "--json",
            )
            self.assertEqual(5, failed.returncode, failed.stdout + failed.stderr)
            error = json.loads(failed.stdout)["error"]
            self.assertEqual("index_seed_invalid", error["code"])
            self.assertEqual(
                [("core_init", "applied"), ("area_register", "failed")],
                [(phase["phase"], phase["status"]) for phase in error["details"]["phases"]],
            )
            self.assertEqual("ready", context_cli.doctor_repository(repo)["repository_state"])
            self.assertFalse((repo / "context/decision/decision.index.md").exists())

            retried = run_cli(
                repo,
                CORE_CLI,
                "bootstrap",
                "--descriptor",
                f"@{descriptor}",
                "--index-seed",
                f"@{valid_seed}",
                "--json",
            )
            self.assertEqual(0, retried.returncode, retried.stdout + retried.stderr)
            self.assertEqual(
                [("core_init", "noop"), ("area_register", "applied")],
                [(phase["phase"], phase["status"]) for phase in json.loads(retried.stdout)["result"]["phases"]],
            )


if __name__ == "__main__":
    unittest.main()
