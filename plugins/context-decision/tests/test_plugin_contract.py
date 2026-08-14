#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PHASE0 = ROOT / "tests/context-v1/phase0/phase0_contract.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phase0 = load("phase0_distribution_contract", PHASE0)
CLI_PATH = ROOT / "plugins/context-decision/skills/decision/scripts/decision_cli.py"


def digest_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def write_preflight_inputs(root: Path, case: dict) -> tuple[Path, Path]:
    inventory = root / f"{case['id']}-inventory.json"
    doctor = root / f"{case['id']}-doctor.json"
    inventory.write_text(json.dumps(case["inventory"], ensure_ascii=False), encoding="utf-8")
    doctor.write_text(json.dumps(case["doctor"], ensure_ascii=False), encoding="utf-8")
    return inventory, doctor


def preflight_args(case: dict, inventory: Path, doctor: Path) -> list[str]:
    return [
        "--host",
        case["host"],
        "--core-inventory",
        f"@{inventory}",
        "--core-doctor",
        f"@{doctor}",
    ]


def run_cli(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        cwd=repo,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
    )


class PluginContractTests(unittest.TestCase):
    def test_acceptance_02_core_missing(self) -> None:
        fixtures = ROOT / "tests/context-v1/fixtures/host-inventory"
        required = json.loads((fixtures / "required-plugin.json").read_text(encoding="utf-8"))
        cases = json.loads((fixtures / "preflight-cases.json").read_text(encoding="utf-8"))["cases"]
        missing = next(case for case in cases if case["expected_code"] == "core_missing")

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repository"
            host = Path(temp) / "host-config"
            repo.mkdir()
            host.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "keep.txt").write_text("repository bytes\n", encoding="utf-8")
            (host / "settings.json").write_text('{"keep":true}\n', encoding="utf-8")
            before = (digest_tree(repo), digest_tree(host))

            result = phase0.classify_preflight(missing["inventory"], missing["doctor"], required)
            rendered = phase0.render_preflight(result, missing["host"], required)

            self.assertEqual("core_missing", rendered["code"])
            self.assertEqual("context-core@jeis-ai-plugins", rendered["required_plugin"]["selector"])
            self.assertEqual("Jeis-Jw/ai-plugins", rendered["required_plugin"]["source"])
            self.assertIn("사용자가 직접 설치", " ".join(rendered["manual_actions"]))
            self.assertEqual({"repository": "none", "host_configuration": "none"}, rendered["write_policy"])
            self.assertEqual(before, (digest_tree(repo), digest_tree(host)))

    def test_schema_and_capabilities_are_the_only_core_free_surfaces(self) -> None:
        protocol = (ROOT / "plugins/context-decision/skills/decision/references/decision-protocol.md").read_text(encoding="utf-8")
        init = (ROOT / "plugins/context-decision/skills/init/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`schema`와 `capabilities`만 core 없이", protocol)
        for token in ("identity", "enabled", "protocol", "repository_state=absent"):
            self.assertIn(token, protocol)
        for forbidden in ("install", "enable", "update", "marketplace add", "cache probing", "embedded core"):
            self.assertIn(forbidden, protocol)
        self.assertIn("먼저 context-core 설치", init)
        self.assertIn("context_cli.py bootstrap", init)

    def test_public_cli_runs_exact_six_state_preflight_before_init(self) -> None:
        fixtures = ROOT / "tests/context-v1/fixtures/host-inventory"
        required = json.loads((fixtures / "required-plugin.json").read_text(encoding="utf-8"))
        cases = json.loads((fixtures / "preflight-cases.json").read_text(encoding="utf-8"))["cases"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repository"
            host = root / "host-config"
            repo.mkdir()
            host.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "keep.txt").write_text("repository bytes\n", encoding="utf-8")
            (host / "settings.json").write_text('{"keep":true}\n', encoding="utf-8")
            for case in cases:
                with self.subTest(case=case["id"]):
                    inventory, doctor = write_preflight_inputs(root, case)
                    before = (digest_tree(repo), digest_tree(host))
                    completed = run_cli(
                        repo,
                        "init",
                        *preflight_args(case, inventory, doctor),
                        "--json",
                    )
                    payload = json.loads(completed.stdout)
                    self.assertEqual(before, (digest_tree(repo), digest_tree(host)))
                    if case["expected_code"] in {"ready", "core_uninitialized"}:
                        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                        self.assertTrue(payload["ok"])
                        self.assertEqual("context-decision-init-plan/v1", payload["result"]["schema"])
                        self.assertEqual(case["doctor"]["repository_state"], payload["result"]["core_repository_state"])
                        self.assertEqual("bootstrap", payload["result"]["bootstrap"]["operation"])
                    else:
                        self.assertEqual(5, completed.returncode, completed.stdout + completed.stderr)
                        self.assertFalse(payload["ok"])
                        self.assertEqual(case["expected_code"], payload["error"]["code"])
                        self.assertEqual(case["expected_rendered"]["message"], payload["error"]["message"])
                        details = payload["error"]["details"]
                        self.assertEqual(case["host"], details["host"])
                        self.assertEqual(required, details["required_plugin"])
                        self.assertEqual(case["expected_observed"], details["observed"])
                        self.assertEqual(case["expected_rendered"]["manual_actions"], details["manual_actions"])
                        self.assertEqual({"repository": "none", "host_configuration": "none"}, details["write_policy"])

    def test_non_static_cli_fails_closed_without_host_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "keep.txt").write_text("repository bytes\n", encoding="utf-8")
            before = digest_tree(repo)
            completed = run_cli(repo, "init", "--json")
            self.assertEqual(5, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("core_preflight_required", json.loads(completed.stdout)["error"]["code"])
            self.assertEqual(before, digest_tree(repo))
            for command in (("schema", "--json"), ("capabilities", "--json")):
                static = run_cli(repo, *command)
                self.assertEqual(0, static.returncode, static.stdout + static.stderr)

    def test_public_direct_capture_is_two_phase_and_semantic_owner_controlled(self) -> None:
        fixtures = ROOT / "tests/context-v1/fixtures/host-inventory"
        cases = json.loads((fixtures / "preflight-cases.json").read_text(encoding="utf-8"))["cases"]
        ready = next(case for case in cases if case["expected_code"] == "ready")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repository"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "keep.txt").write_text("repository bytes\n", encoding="utf-8")
            inventory, doctor = write_preflight_inputs(root, ready)
            preflight = preflight_args(ready, inventory, doctor)
            common = [
                "--candidate-id",
                "cand_550e8400e29b41d4a716446655440000",
                "--title",
                "인증 세션 소유권",
                "--summary",
                "OAuth callback과 cookie 경계를 BFF로 통합한다.",
                "--scope",
                "project/auth",
                "--decision-key",
                "session-owner",
                "--captured-from",
                "conversation",
                "--commitment-evidence",
                "결정 권한자가 현재 따를 선택으로 확정했다.",
                "--sec-decision",
                "인증 세션은 BFF가 소유한다.",
                "--sec-rationale",
                "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
                "--sec-alternatives",
                "SPA token 소유: XSS 노출이 커져 반려",
            ]
            before = digest_tree(repo)
            prepared = run_cli(repo, "candidate", "prepare", *common, *preflight, "--json")
            self.assertEqual(0, prepared.returncode, prepared.stdout + prepared.stderr)
            candidate = json.loads(prepared.stdout)["result"]
            self.assertEqual(["결정 권한자가 현재 따를 선택으로 확정했다."], candidate["evidence"])
            self.assertNotIn("explicit direct decision request", json.dumps(candidate, ensure_ascii=False))
            candidate_path = root / "candidate.json"
            candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
            attestation = {
                "schema": "context-semantic-attestation/v1",
                "operation": "claim",
                "input_schema": candidate["schema"],
                "input_digest": canonical_digest(candidate),
                "assertions": [
                    {"name": "explicit_choice", "value": True, "evidence_pointers": ["/owner_inputs/decision/decision"]},
                    {"name": "scope_identified", "value": True, "evidence_pointers": ["/scope_hint"]},
                    {"name": "commitment_present", "value": True, "evidence_pointers": ["/evidence/0"]},
                ],
            }
            attestation_path = root / "attestation.json"
            attestation_path.write_text(json.dumps(attestation, ensure_ascii=False), encoding="utf-8")
            accepted = run_cli(
                repo,
                "capture",
                "--candidate",
                f"@{candidate_path}",
                "--attestation",
                f"@{attestation_path}",
                *preflight,
                "--json",
            )
            self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
            accepted_result = json.loads(accepted.stdout)["result"]
            self.assertEqual("claim", accepted_result["decision"])
            self.assertEqual(candidate, accepted_result["semantic_inputs"][0]["value"])
            self.assertEqual(before, digest_tree(repo))

            decline_cases = (
                (
                    "fact",
                    "cand_123e4567e89b42d3a456426614174000",
                    "Safari에서 third-party cookie가 차단된다.",
                    "재현 로그에서 확인한 사실이다.",
                    "사실 발견은 현재 따를 선택이 아니다.",
                ),
                (
                    "idea",
                    "cand_987e6543e21b42d3a456426614174002",
                    "인증 세션을 edge에 두면 좋을 것 같다.",
                    "브레인스토밍에서 나온 아이디어다.",
                    "아이디어는 현재 따르기로 확정된 선택이 아니다.",
                ),
            )
            for label, candidate_id, claim, evidence, reason in decline_cases:
                with self.subTest(decision=label):
                    declined_candidate = dict(candidate)
                    declined_candidate["candidate_id"] = candidate_id
                    declined_candidate["claim"] = claim
                    declined_candidate["evidence"] = [evidence]
                    declined_candidate["owner_inputs"] = {
                        "decision": {
                            **candidate["owner_inputs"]["decision"],
                            "decision": claim,
                        }
                    }
                    declined_path = root / f"{label}.json"
                    declined_path.write_text(json.dumps(declined_candidate, ensure_ascii=False), encoding="utf-8")
                    declined = run_cli(
                        repo,
                        "capture",
                        "--candidate",
                        f"@{declined_path}",
                        "--decline-reason",
                        reason,
                        *preflight,
                        "--json",
                    )
                    self.assertEqual(0, declined.returncode, declined.stdout + declined.stderr)
                    declined_result = json.loads(declined.stdout)["result"]
                    self.assertEqual("decline", declined_result["decision"])
                    self.assertEqual([], declined_result["artifact_drafts"])
                    self.assertEqual([], declined_result["semantic_attestations"])
                    self.assertEqual(before, digest_tree(repo))

    def test_public_skill_documents_preflight_and_two_phase_capture(self) -> None:
        decision = (ROOT / "plugins/context-decision/skills/decision/SKILL.md").read_text(encoding="utf-8")
        init = (ROOT / "plugins/context-decision/skills/init/SKILL.md").read_text(encoding="utf-8")
        protocol = (ROOT / "plugins/context-decision/skills/decision/references/decision-protocol.md").read_text(encoding="utf-8")
        combined = "\n".join((decision, init, protocol))
        for token in ("--host", "--core-inventory", "--core-doctor", "candidate prepare", "capture --candidate", "decline"):
            self.assertIn(token, combined)


if __name__ == "__main__":
    unittest.main()
