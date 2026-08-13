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
            with self.assertRaises(context_cli.ContextError):
                context_cli.build_policy_bundle(repo, "CLAUDE.md")


if __name__ == "__main__":
    unittest.main()
