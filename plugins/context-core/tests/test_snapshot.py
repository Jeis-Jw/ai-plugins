#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli_snapshot", CLI_PATH)
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


def claim_attestation(candidate: dict, kind: str) -> dict:
    digest = context_cli.canonical_digest(candidate)
    pointers = {
        "snapshot": [
            ("handoff_requested", "/owner_inputs/snapshot/current_context"),
            ("unfinished_context_present", "/owner_inputs/snapshot/open_items/0"),
        ],
        "observation": [
            ("reusable_observation", "/owner_inputs/observation/observation"),
            ("evidence_present", "/owner_inputs/observation/evidence/0"),
        ],
    }
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": candidate["schema"],
        "input_digest": digest,
        "assertions": [
            {"name": name, "value": True, "evidence_pointers": [pointer]}
            for name, pointer in pointers[kind]
        ],
    }


def snapshot_preview(repo: Path, title: str, filename: str | None = None) -> dict:
    candidate = context_cli.direct_candidate(
        "snapshot",
        title=title,
        summary=f"{title} summary",
        captured_from="conversation",
        owner_inputs={
            "current_context": f"{title} context",
            "open_items": [f"{title} open"],
            "next_steps": [f"{title} next"],
        },
    )
    return context_cli.build_snapshot_save_bundle(
        repo,
        candidate,
        claim_attestation(candidate, "snapshot"),
        filename=filename,
        now="2026-08-13T18:20:00+09:00",
    )


class SnapshotTests(unittest.TestCase):
    def test_acceptance_11_named_snapshots(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            before = tree_digest(repo)
            first = snapshot_preview(repo, "인증 handoff")
            self.assertEqual(before, tree_digest(repo), "preview must not write")
            context_cli.apply_bundle(repo, first["bundle"], first["approval_digest"])
            second = snapshot_preview(repo, "결제 handoff")
            context_cli.apply_bundle(repo, second["bundle"], second["approval_digest"])

            listing = context_cli.snapshot_list(repo)
            self.assertEqual(2, listing["returned"])
            self.assertEqual(2, len({item["id"] for item in listing["items"]}))

            with self.assertRaises(context_cli.ContextError) as caught:
                snapshot_preview(repo, "인증 handoff")
            self.assertEqual("path_exists", caught.exception.code)

    def test_acceptance_12_update_merge(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            create = snapshot_preview(repo, "인증 handoff")
            context_cli.apply_bundle(repo, create["bundle"], create["approval_digest"])
            identifier = create["approval_preview"]["effects"][0]["id"]
            original = context_cli.snapshot_load(repo, identifier)

            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.build_snapshot_update_bundle(repo, identifier, sections={"현재 맥락": "only"})
            self.assertEqual("snapshot_full_update_required", caught.exception.code)

            merge = context_cli.build_snapshot_update_bundle(
                repo,
                identifier,
                merge=True,
                sections={"열린 항목": "- 새 열린 항목"},
                now="2026-08-13T19:00:00+09:00",
            )
            context_cli.apply_bundle(repo, merge["bundle"], merge["approval_digest"])
            merged = context_cli.snapshot_load(repo, identifier)
            self.assertEqual(original["artifact"]["created_at"], merged["artifact"]["created_at"])
            self.assertEqual("2026-08-13T19:00:00+09:00", merged["artifact"]["updated_at"])
            self.assertEqual(original["sections"]["현재 맥락"], merged["sections"]["현재 맥락"])
            self.assertEqual("- 새 열린 항목", merged["sections"]["열린 항목"])

            before = tree_digest(repo)
            noop = context_cli.build_snapshot_update_bundle(
                repo,
                identifier,
                merge=True,
                sections={"열린 항목": "- 새 열린 항목"},
                now="2026-08-13T20:00:00+09:00",
            )
            self.assertTrue(noop["noop"])
            self.assertEqual(before, tree_digest(repo))

    def test_snapshot_freshness_is_read_only(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            create = snapshot_preview(repo, "anchor 없는 handoff")
            context_cli.apply_bundle(repo, create["bundle"], create["approval_digest"])
            identifier = create["approval_preview"]["effects"][0]["id"]
            before = tree_digest(repo)
            loaded = context_cli.snapshot_load(repo, identifier)
            self.assertEqual("staging", loaded["authority"])
            self.assertEqual("resume_context", loaded["use_as"])
            self.assertEqual("authority_unknown", loaded["freshness"])
            self.assertEqual(before, tree_digest(repo))

    def test_acceptance_13_discard(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            create = snapshot_preview(repo, "버릴 handoff")
            context_cli.apply_bundle(repo, create["bundle"], create["approval_digest"])
            identifier = create["approval_preview"]["effects"][0]["id"]
            discard = context_cli.build_snapshot_discard_bundle(repo, identifier)
            before = tree_digest(repo)
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.apply_bundle(repo, discard["bundle"], "sha256:" + "0" * 64)
            self.assertEqual("approval_digest_mismatch", caught.exception.code)
            self.assertEqual(before, tree_digest(repo))

            context_cli.apply_bundle(repo, discard["bundle"], discard["approval_digest"])
            self.assertEqual(0, context_cli.snapshot_list(repo)["returned"])
            self.assertEqual([], list((repo / "context/snapshot").glob("retired/*.md")))


if __name__ == "__main__":
    unittest.main()
