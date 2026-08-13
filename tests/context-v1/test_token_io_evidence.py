#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "plugins/context-core/skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli_token", CLI_PATH)
assert SPEC and SPEC.loader
context_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_cli
SPEC.loader.exec_module(context_cli)


def candidate(number: int) -> dict:
    return {
        "schema": "context-capture-candidate/v1",
        "candidate_id": f"cand_550e8400e29b41d4a71644665544{number:04x}",
        "claim_key": f"c{number}",
        "title": f"관찰 {number}",
        "claim": f"재사용 가능한 관찰 {number}",
        "summary": f"후속 판단에 쓰는 근거 {number}",
        "captured_from": "conversation",
        "requested_kind": "observation",
        "specialized_kinds": ["observation"],
        "fallback_kind": None,
        "owner_inputs": {"observation": {"observation": f"재사용 가능한 관찰 {number}", "evidence": [f"fixture {number}"]}},
    }


class TokenIOEvidenceTests(unittest.TestCase):
    def test_candidate_count_batch_and_owner_input_budgets(self) -> None:
        for count in (0, 1, 8):
            batch = [candidate(number) for number in range(count)]
            result = context_cli.validate_candidate_batch(batch, context_cli.capabilities_result())
            self.assertEqual(count, len(result))
            self.assertLessEqual(len(context_cli.canonical_json(batch).encode("utf-8")), 16 * 1024)
            for item in batch:
                owner_input = item["owner_inputs"]["observation"]
                self.assertLessEqual(len(context_cli.canonical_json(owner_input).encode("utf-8")), 2 * 1024)
        with self.assertRaises(context_cli.ContextError) as caught:
            context_cli.validate_candidate_batch([candidate(number) for number in range(9)], context_cli.capabilities_result())
        self.assertEqual("candidate_batch_too_large", caught.exception.code)

    def test_grouped_preview_budget_does_not_truncate_semantic_content(self) -> None:
        preview = {
            "schema": "context-approval-preview/v1",
            "owner": "context-core",
            "candidate_id": None,
            "artifacts": [{"effect_id": "effect", "path": "context/observation/x.md", "content": "가" * (33 * 1024)}],
            "effects": [],
        }
        with self.assertRaises(context_cli.ContextError) as caught:
            context_cli._bundle_result(preview, {}, [])
        self.assertEqual("approval_preview_too_large", caught.exception.code)

    def test_stdlib_only_imports(self) -> None:
        allowed = set(sys.stdlib_module_names) | {"__future__"}
        for path in (
            ROOT / "plugins/context-core/skills/context/scripts/context_cli.py",
            ROOT / "plugins/context-decision/skills/decision/scripts/decision_cli.py",
        ):
            import ast

            tree = ast.parse(path.read_text(encoding="utf-8"))
            roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])
            self.assertEqual(set(), roots - allowed, f"non-stdlib imports in {path}")


if __name__ == "__main__":
    unittest.main()
