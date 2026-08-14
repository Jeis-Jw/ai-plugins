#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "acceptance-matrix.json"
FORBIDDEN = {"skip", "skipped", "xfail", "pending", "todo"}


class AcceptanceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        corpus_path = HERE / cls.registry["fixture_corpus"]
        cls.corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    def test_registry_contains_each_acceptance_id_exactly_once(self) -> None:
        entries = self.registry["entries"]
        ids = [entry["id"] for entry in entries]
        self.assertEqual(list(range(1, 44)), sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual("context-v1-acceptance-registry/v1", self.registry["schema"])

    def test_registry_and_corpus_are_one_to_one_and_complete(self) -> None:
        entries = self.registry["entries"]
        case_names = [entry["case"] for entry in entries]
        self.assertEqual(len(case_names), len(set(case_names)))
        self.assertEqual(set(case_names), set(self.corpus["cases"]))
        for name, contract in self.corpus["cases"].items():
            self.assertIsInstance(contract.get("input"), str, name)
            self.assertTrue(contract.get("expected"), name)

    def test_every_entry_has_named_downstream_selector_and_no_deferred_state(self) -> None:
        modules = {}
        for entry in self.registry["entries"]:
            self.assertEqual("executable", entry["status"])
            self.assertFalse(FORBIDDEN.intersection(str(v).casefold() for v in entry.values()))
            self.assertRegex(
                entry["selector"],
                re.compile(r"^[^:]+\.py::[A-Za-z_][A-Za-z0-9_]*::test_acceptance_\d{2}_[A-Za-z0-9_]+$"),
            )
            self.assertTrue(entry["owner"].startswith("p"))
            path_text, class_name, method_name = entry["selector"].split("::")
            if path_text not in modules:
                module = ast.parse((HERE.parents[1] / path_text).read_text(encoding="utf-8"))
                modules[path_text] = {
                    node.name: node for node in module.body if isinstance(node, ast.ClassDef)
                }
            self.assertIn(class_name, modules[path_text], entry["selector"])
            selected_class = modules[path_text][class_name]
            self.assertIn("unittest.TestCase", {ast.unparse(base) for base in selected_class.bases})
            methods = {
                node.name for node in selected_class.body
                if isinstance(node, ast.FunctionDef)
            }
            self.assertIn(method_name, methods, entry["selector"])


if __name__ == "__main__":
    unittest.main()
