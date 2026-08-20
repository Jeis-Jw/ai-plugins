#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli_policy", CLI_PATH)
assert SPEC and SPEC.loader
context_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_cli
SPEC.loader.exec_module(context_cli)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PluginContractTests(unittest.TestCase):
    def test_managed_policy_keeps_the_incremental_loop_call_free_and_ephemeral(self) -> None:
        policy = context_cli.POLICY_BODY
        for contract in (
            "같은 response pass",
            "별도 model·tool 호출 없이",
            "session-local ephemeral ledger",
            "metadata 먼저",
            "새 근거가 생기기 전에는 다시 제안하지 않는다",
            "exact `approval_digest`",
        ):
            self.assertIn(contract, policy)
        self.assertLessEqual(len(policy.encode("utf-8")), 2200)

    def test_explicit_init_installs_active_host_policy_and_preserves_external_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            target = repo / "CLAUDE.md"
            outside = "# Existing policy\n\nKeep this text.\n"
            target.write_text(outside, encoding="utf-8")
            target.chmod(0o644)

            first = context_cli.bootstrap_repository(repo, host="claude-code")

            self.assertTrue(first["policy"]["applied"])
            self.assertEqual("CLAUDE.md", first["policy"]["target"])
            self.assertTrue(target.read_text(encoding="utf-8").startswith(outside))
            self.assertIn(context_cli.POLICY_BODY, target.read_text(encoding="utf-8"))
            self.assertEqual(0o644, target.stat().st_mode & 0o777)
            self.assertFalse((repo / "AGENTS.md").exists())

            second = context_cli.bootstrap_repository(repo, host="claude-code")
            self.assertTrue(second["noop"])
            self.assertTrue(second["policy"]["noop"])

            original_build_init = context_cli.build_init_bundle

            def mutate_policy_during_core_phase(current_repo):
                target.write_text("# Concurrent replacement\n", encoding="utf-8")
                return original_build_init(current_repo)

            with mock.patch.object(context_cli, "build_init_bundle", side_effect=mutate_policy_during_core_phase):
                repaired = context_cli.bootstrap_repository(repo, host="claude-code")
            self.assertTrue(repaired["policy"]["applied"])
            self.assertIn(context_cli.POLICY_BODY, target.read_text(encoding="utf-8"))
            self.assertTrue(target.read_text(encoding="utf-8").startswith("# Concurrent replacement\n"))
            self.assertEqual(0o644, target.stat().st_mode & 0o777)

    def test_policy_create_uses_readable_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)

            context_cli.bootstrap_repository(repo, host="codex")

            target = repo / "AGENTS.md"
            self.assertEqual(0o644, target.stat().st_mode & 0o777)

    def test_acceptance_34_policy_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            target = repo / "AGENTS.md"
            outside = b"# Existing policy\n\nKeep these bytes.\n"
            target.write_bytes(outside)
            before = tree_digest(repo)
            preview = context_cli.build_policy_bundle(repo, "AGENTS.md")
            self.assertEqual(before, tree_digest(repo))
            artifact = preview["approval_preview"]["artifacts"][0]
            self.assertTrue(artifact["content"].startswith(outside.decode()))
            self.assertIn(context_cli.POLICY_BEGIN, artifact["content"])
            self.assertEqual("policy_install", preview["bundle"]["approval_material"]["plan"]["transition"])

            tampered = copy.deepcopy(preview["bundle"])
            tampered["approval_material"]["plan"]["operations"][0]["path"] = "README.md"
            tampered["approval_digest"] = context_cli.canonical_digest(tampered["approval_material"])
            with self.assertRaises(context_cli.ContextError):
                context_cli.apply_bundle(repo, tampered, tampered["approval_digest"])
            self.assertEqual(before, tree_digest(repo))

            context_cli.apply_bundle(repo, preview["bundle"], preview["approval_digest"])
            installed = target.read_bytes()
            self.assertTrue(installed.startswith(outside))
            second = context_cli.build_policy_bundle(repo, "AGENTS.md")
            self.assertTrue(second["noop"])

    def test_policy_rejects_non_root_target_and_broken_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            with self.assertRaises(context_cli.ContextError):
                context_cli.build_policy_bundle(repo, "docs/AGENTS.md")
            (repo / "CLAUDE.md").write_text(context_cli.POLICY_BEGIN + "\n", encoding="utf-8")
            before = tree_digest(repo)
            with self.assertRaises(context_cli.ContextError):
                context_cli.bootstrap_repository(repo, host="claude-code")
            self.assertEqual(before, tree_digest(repo))
            self.assertFalse((repo / "context").exists())

            reversed_markers = context_cli.POLICY_END + "\n" + context_cli.POLICY_BEGIN + "\n"
            (repo / "CLAUDE.md").write_text(reversed_markers, encoding="utf-8")
            with self.assertRaises(context_cli.ContextError) as reversed_error:
                context_cli.build_policy_bundle(repo, "CLAUDE.md")
            self.assertEqual("policy_marker_invalid", reversed_error.exception.code)

    def test_init_rejects_non_utf8_policy_before_storage_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            target = repo / "AGENTS.md"
            original = b"\xff\xfe\x00existing"
            target.write_bytes(original)

            with self.assertRaises(context_cli.ContextError) as failure:
                context_cli.bootstrap_repository(repo, host="codex")

            self.assertEqual("policy_file_unsupported", failure.exception.code)
            self.assertEqual("policy_preflight", failure.exception.details["phases"][0]["phase"])
            self.assertEqual(original, target.read_bytes())
            self.assertFalse((repo / "context").exists())


if __name__ == "__main__":
    unittest.main()
