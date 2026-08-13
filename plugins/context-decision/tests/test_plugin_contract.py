#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
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


def digest_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


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
        for token in ("identity", "enabled", "protocol", "doctor.repository_state=ready"):
            self.assertIn(token, protocol)
        for forbidden in ("install", "enable", "update", "marketplace add", "context-core:init", "cache probing", "embedded core"):
            self.assertIn(forbidden, protocol)
        self.assertIn("먼저 context-core 설치", init)


if __name__ == "__main__":
    unittest.main()
