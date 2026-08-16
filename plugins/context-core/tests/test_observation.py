#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli_observation", CLI_PATH)
assert SPEC and SPEC.loader
context_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_cli
SPEC.loader.exec_module(context_cli)


def git_repo() -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", temp.name], check=True)
    return temp


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize(repo: Path) -> None:
    preview = context_cli.build_init_bundle(repo)
    context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])


def claim_attestation(candidate: dict) -> dict:
    digest = context_cli.canonical_digest(candidate)
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": candidate["schema"],
        "input_digest": digest,
        "assertions": [
            {"name": "reusable_observation", "value": True, "evidence_pointers": ["/owner_inputs/observation/observation"]},
            {"name": "evidence_present", "value": True, "evidence_pointers": ["/owner_inputs/observation/evidence/0"]},
        ],
    }


def observation_candidate(title: str, claim: str | None = None, *, kind_hint: str | None = None) -> dict:
    claim = claim or f"{title} claim"
    return context_cli.direct_candidate(
        "observation",
        title=title,
        summary=f"{title} summary",
        captured_from="workspace",
        owner_inputs={"observation": claim, "evidence": [f"{title} evidence"]},
        kind_hint=kind_hint,
    )


def observation_owner_result(title: str, claim: str | None = None, *, kind_hint: str | None = None, now: str = "2026-08-13T18:20:00+09:00") -> dict:
    candidate = observation_candidate(title, claim, kind_hint=kind_hint)
    return context_cli.draft_owner_result(candidate, claim_attestation(candidate), now=now)


def capture(repo: Path, title: str, claim: str | None = None, *, kind_hint: str | None = None, now: str = "2026-08-13T18:20:00+09:00") -> tuple[dict, str]:
    owner_result = observation_owner_result(title, claim, kind_hint=kind_hint, now=now)
    preview = context_cli.finalize_owner_result(repo, owner_result)
    context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
    return owner_result, preview["approval_preview"]["effects"][0]["id"]


def same_claim_attestation(lifecycle_input: dict) -> dict:
    digest = context_cli.canonical_digest(lifecycle_input)
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "same_claim",
        "input_schema": lifecycle_input["schema"],
        "input_digest": digest,
        "assertions": [{
            "name": "same_semantic_claim",
            "value": True,
            "evidence_pointers": ["/predecessor/primary_claim", "/successor/primary_claim"],
        }],
    }


class ObservationTests(unittest.TestCase):
    def test_observation_requires_substantive_claim_and_evidence(self) -> None:
        for inputs in (
            {"observation": "TODO", "evidence": ["evidence"]},
            {"observation": "claim", "evidence": []},
            {"observation": "claim", "evidence": ["..."]},
        ):
            with self.subTest(inputs=inputs), self.assertRaises(context_cli.ContextError):
                context_cli.direct_candidate(
                    "observation",
                    title="invalid",
                    summary="invalid observation",
                    captured_from="workspace",
                    owner_inputs=inputs,
                )

    def test_metadata_correction_does_not_change_claim(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            _, identifier = capture(repo, "원래 제목", "같은 claim")
            before = context_cli.observation_read(repo, identifier)
            preview = context_cli.build_observation_annotate_bundle(repo, identifier, title="교정 제목", tags=["corrected"])
            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            after = context_cli.observation_read(repo, identifier)
            self.assertEqual(before["sections"], after["sections"])
            self.assertNotIn("claim_fingerprint", before["artifact"])
            self.assertNotIn("claim_fingerprint", after["artifact"])
            self.assertEqual("교정 제목", after["artifact"]["title"])

    def test_acceptance_14_invalidate(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            _, identifier = capture(repo, "무효화할 관찰")
            preview = context_cli.build_observation_invalidate_bundle(
                repo, identifier, "재현 조건이 반증됨", now="2026-08-13T19:00:00+09:00"
            )
            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            index = context_cli.parse_area_index((repo / "context/observation/observation.index.md").read_text(encoding="utf-8"))
            self.assertEqual([], index.current)
            self.assertEqual("invalidated", index.history[0]["retired_reason"])
            self.assertEqual("2026-08-13T19:00:00+09:00", index.history[0]["retired_at"])
            retired = context_cli.observation_read(repo, identifier)
            self.assertEqual("재현 조건이 반증됨", retired["artifact"]["retirement_note"])
            self.assertEqual("evidence", retired["authority"])

    def test_acceptance_15_supersede(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            _, predecessor = capture(repo, "같은 제목", "Safari cookie claim")
            successor = observation_owner_result("같은 제목", "Safari cookie claim corrected", now="2026-08-13T19:00:00+09:00")
            lifecycle = context_cli.prepare_lifecycle_input(repo, "observation_supersede", predecessor, successor)
            attestation = same_claim_attestation(lifecycle)
            before = tree_digest(repo)
            preview = context_cli.build_observation_supersede_bundle(
                repo,
                predecessor,
                successor,
                lifecycle,
                attestation,
                now="2026-08-13T19:10:00+09:00",
            )
            self.assertEqual(before, tree_digest(repo), "supersede preview must not write")

            tampered = copy.deepcopy(lifecycle)
            tampered["predecessor"]["primary_claim"] += " tampered"
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.build_observation_supersede_bundle(repo, predecessor, successor, tampered, attestation)
            self.assertEqual("lifecycle_input_mismatch", caught.exception.code)
            self.assertEqual(before, tree_digest(repo))

            tampered_bundle = copy.deepcopy(preview["bundle"])
            plan = tampered_bundle["approval_material"]["plan"]
            owner_material = next(material for material in tampered_bundle["materials"] if material["path"] is None)
            owner_result = json.loads(owner_material["content"])
            lifecycle_semantic = next(item for item in owner_result["semantic_inputs"] if item["operation"] == "same_claim")
            lifecycle_semantic["value"]["successor"]["primary_claim"] += " tampered"
            lifecycle_semantic["input_digest"] = context_cli.canonical_digest(lifecycle_semantic["value"])
            next(item for item in owner_result["semantic_attestations"] if item["operation"] == "same_claim")["input_digest"] = lifecycle_semantic["input_digest"]
            owner_material["content"] = context_cli.canonical_json(owner_result)
            plan["owner_result_digest"] = context_cli.sha256_bytes(owner_material["content"].encode("utf-8"))
            tampered_bundle["approval_digest"] = context_cli.canonical_digest(tampered_bundle["approval_material"])
            with self.assertRaises(context_cli.ContextError) as apply_error:
                context_cli.apply_bundle(repo, tampered_bundle, tampered_bundle["approval_digest"])
            self.assertEqual("lifecycle_input_mismatch", apply_error.exception.code)
            self.assertEqual(before, tree_digest(repo))

            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            index = context_cli.parse_area_index((repo / "context/observation/observation.index.md").read_text(encoding="utf-8"))
            successor_id = index.current[0]["id"]
            self.assertEqual(predecessor, index.history[0]["id"])
            self.assertEqual(successor_id, index.history[0]["superseded_by"])
            old = context_cli.observation_read(repo, predecessor)["artifact"]
            new = context_cli.observation_read(repo, successor_id)["artifact"]
            self.assertEqual(successor_id, old["superseded_by"])
            self.assertIn(predecessor, new["supersedes"])

    def test_acceptance_16_repeated_supersede(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            _, first = capture(repo, "반복 제목", "claim v1")
            generations = [first]
            current = first
            for number, stamp in ((2, "2026-08-13T19:00:00+09:00"), (3, "2026-08-13T20:00:00+09:00")):
                successor = observation_owner_result("반복 제목", f"claim v{number}", now=stamp)
                lifecycle = context_cli.prepare_lifecycle_input(repo, "observation_supersede", current, successor)
                preview = context_cli.build_observation_supersede_bundle(
                    repo, current, successor, lifecycle, same_claim_attestation(lifecycle), now=stamp
                )
                context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
                current = next(effect["id"] for effect in preview["approval_preview"]["effects"] if effect["action"] == "create")
                generations.append(current)

            index = context_cli.parse_area_index((repo / "context/observation/observation.index.md").read_text(encoding="utf-8"))
            self.assertEqual(1, len(index.current))
            self.assertEqual(2, len(index.history))
            self.assertEqual(3, len({row["path"] for row in index.current + index.history}))
            for row in index.history:
                self.assertTrue(row["path"].endswith(f"--{row['id'][4:16]}.md"))

    def test_acceptance_17_decision_fallback(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            owner_result, identifier = capture(
                repo,
                "결정처럼 보인 발언",
                "대화에서 BFF가 세션을 소유하기로 합의했다는 진술이 있었다.",
                kind_hint="decision",
            )
            self.assertEqual("observation", owner_result["target_kind"])
            result = context_cli.observation_read(repo, identifier)
            self.assertEqual("decision", result["artifact"]["kind_hint"])
            self.assertEqual("evidence", result["authority"])
            self.assertNotIn("claim_fingerprint", result["artifact"])
            self.assertNotIn("source_claim_fingerprint", result["artifact"])
            self.assertFalse((repo / "context/decision").exists())


if __name__ == "__main__":
    unittest.main()
