#!/usr/bin/env python3
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PHASE0 = ROOT / "tests/context-v1/phase0/phase0_contract.py"
PLUGIN_NAMES = ("context-core", "context-decision")
FORBIDDEN_KEYS = {
    "dependencies",
    "dependency",
    "requires",
    "implicit_install",
    "implicitInstall",
    "default_install",
    "defaultInstall",
    "installed_by_default",
    "installedByDefault",
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phase0 = load("phase0_distribution_proof", PHASE0)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def recursive_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(recursive_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value), set())
    return set()


def digest_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class DistributionProofTests(unittest.TestCase):
    def test_acceptance_41_dependency_matrix(self) -> None:
        fixtures = ROOT / "tests/context-v1/fixtures/host-inventory"
        required = read_json(fixtures / "required-plugin.json")
        corpus = read_json(fixtures / "preflight-cases.json")
        expected = {
            "core_missing",
            "core_source_mismatch",
            "core_disabled",
            "core_incompatible",
            "core_uninitialized",
            "partial_core_init",
            "ready",
        }
        observed: set[str] = set()
        for case in corpus["cases"]:
            inventory = copy.deepcopy(case["inventory"])
            doctor = copy.deepcopy(case["doctor"])
            before = json.dumps({"inventory": inventory, "doctor": doctor}, sort_keys=True)
            with tempfile.TemporaryDirectory() as temp:
                repo = Path(temp) / "repository"
                host = Path(temp) / "host-config"
                repo.mkdir()
                host.mkdir()
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                (repo / "keep.txt").write_text("repository bytes\n", encoding="utf-8")
                (host / "config.json").write_text('{"keep":true}\n', encoding="utf-8")
                byte_before = (digest_tree(repo), digest_tree(host))
                result = phase0.classify_preflight(inventory, doctor, required)
                rendered = phase0.render_preflight(result, case["host"], required)
                self.assertEqual(byte_before, (digest_tree(repo), digest_tree(host)))
            observed.add(rendered["code"])
            self.assertEqual(required, rendered["required_plugin"])
            self.assertEqual({"repository": "none", "host_configuration": "none"}, rendered["write_policy"])
            self.assertEqual(before, json.dumps({"inventory": inventory, "doctor": doctor}, sort_keys=True))
        self.assertEqual(expected, observed)

        readme = (ROOT / "plugins/context-decision/README.md").read_text(encoding="utf-8")
        for code in expected - {"ready"}:
            self.assertIn(f"`{code}`", readme)
        for token in (
            "jeis-ai-plugins",
            "context-core@jeis-ai-plugins",
            "Jeis-Jw/ai-plugins",
            "scope",
            "reload",
            "새 session",
            "context-decision:init",
        ):
            self.assertIn(token, readme)
        for code in expected - {"ready", "core_uninitialized"}:
            line = next(line for line in readme.splitlines() if line.startswith(f"- `{code}`:"))
            for token in ("Jeis-Jw/ai-plugins", "scope", "reload", "새 session", "context-decision:init", "재시도"):
                self.assertIn(token, line)
        absent_line = next(line for line in readme.splitlines() if line.startswith("- `core_uninitialized`:"))
        for token in ("installed", "context-core", "bootstrap", "같은 호출", "decision"):
            self.assertIn(token, absent_line)

    def test_acceptance_42_repository_absent(self) -> None:
        fixtures = ROOT / "tests/context-v1/fixtures/host-inventory"
        required = read_json(fixtures / "required-plugin.json")
        corpus = read_json(fixtures / "preflight-cases.json")["cases"]
        case = next(item for item in corpus if item["expected_code"] == "core_uninitialized")
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repository"
            host = Path(temp) / "host"
            repo.mkdir()
            host.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "keep.txt").write_text("keep\n", encoding="utf-8")
            (host / "config.json").write_text("{}\n", encoding="utf-8")
            before = (digest_tree(repo), digest_tree(host))
            rendered = phase0.render_preflight(
                phase0.classify_preflight(case["inventory"], case["doctor"], required),
                case["host"],
                required,
            )
            self.assertEqual("core_uninitialized", rendered["code"])
            self.assertNotEqual("core_missing", rendered["code"])
            self.assertIn("public bootstrap surface", " ".join(rendered["manual_actions"]))
            self.assertEqual(before, (digest_tree(repo), digest_tree(host)))

            context_cli = load(
                "context_cli_distribution_direct_init",
                ROOT / "plugins/context-core/skills/context/scripts/context_cli.py",
            )
            initialized = context_cli.bootstrap_repository(repo, host=case["host"])
            self.assertEqual(
                [("core_init", "applied"), ("policy_install", "applied")],
                [(phase["phase"], phase["status"]) for phase in initialized["phases"]],
            )
            self.assertEqual("ready", initialized["doctor"]["repository_state"])
            self.assertEqual("AGENTS.md", initialized["policy"]["target"])
            self.assertTrue(initialized["policy"]["applied"])
            self.assertIn(context_cli.POLICY_BODY, (repo / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("keep\n", (repo / "keep.txt").read_text(encoding="utf-8"))
            self.assertEqual(before[1], digest_tree(host))

        context_cli = load(
            "context_cli_distribution_storage_error",
            ROOT / "plugins/context-core/skills/context/scripts/context_cli.py",
        )
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.recall_repository(repo)
            self.assertEqual("context_root_missing", caught.exception.code)

    def test_acceptance_43_manifests(self) -> None:
        claude_marketplace = read_json(ROOT / ".claude-plugin/marketplace.json")
        codex_marketplace = read_json(ROOT / ".agents/plugins/marketplace.json")
        self.assertEqual("jeis-ai-plugins", claude_marketplace["name"])
        self.assertEqual("jeis-ai-plugins", codex_marketplace["name"])
        claude_entries = {item["name"]: item for item in claude_marketplace["plugins"]}
        codex_entries = {item["name"]: item for item in codex_marketplace["plugins"]}

        for name in PLUGIN_NAMES:
            root = ROOT / "plugins" / name
            claude = read_json(root / ".claude-plugin/plugin.json")
            codex = read_json(root / ".codex-plugin/plugin.json")
            self.assertEqual("0.2.0", claude["version"])
            self.assertEqual(claude["version"], codex["version"])
            self.assertEqual(claude["version"], claude_entries[name]["version"])
            self.assertEqual(claude["version"], codex_entries[name]["version"])
            self.assertEqual(f"./plugins/{name}", claude_entries[name]["source"])
            self.assertEqual({"source": "local", "path": f"./plugins/{name}"}, codex_entries[name]["source"])
            self.assertEqual("AVAILABLE", codex_entries[name]["policy"]["installation"])
            for document in (claude, codex, claude_entries[name], codex_entries[name]):
                self.assertFalse(FORBIDDEN_KEYS & recursive_keys(document))

            skills = root / codex["skills"]
            self.assertTrue(skills.is_dir())
            with tempfile.TemporaryDirectory() as temp:
                cached = Path(temp) / name
                shutil.copytree(root, cached)
                owner_skill = "context" if name == "context-core" else "decision"
                for relative in ("skills/init/SKILL.md", f"skills/{owner_skill}/SKILL.md"):
                    self.assertTrue((cached / relative).is_file())
                if name == "context-decision":
                    loaded_skill = cached / "skills/init/SKILL.md"
                    sibling_entrypoint = loaded_skill.parent / "scripts/decision_init.py"
                    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
                    environment.pop("CLAUDE_PLUGIN_ROOT", None)
                    resolved = subprocess.run(
                        [sys.executable, str(sibling_entrypoint), "--help"],
                        cwd=temp,
                        env=environment,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(0, resolved.returncode, resolved.stdout + resolved.stderr)

        self.assertTrue((ROOT / "plugins/context-core/skills/context/SKILL.md").is_file())
        self.assertTrue((ROOT / "plugins/context-decision/skills/decision/SKILL.md").is_file())
        decision_root = ROOT / "plugins/context-decision"
        init_entrypoint = decision_root / "skills/init/scripts/decision_init.py"
        init_skill = (decision_root / "skills/init/SKILL.md").read_text(encoding="utf-8")
        default_prompt = "\n".join(read_json(decision_root / ".codex-plugin/plugin.json")["interface"]["defaultPrompt"])
        self.assertTrue(init_entrypoint.is_file())
        self.assertIn("decision_init.py", init_skill)
        self.assertIn("--core-cli", init_skill)
        for token in (
            "context-core@jeis-ai-plugins",
            "context-common/v2",
            "repository_state=ready or absent",
            "managed policy",
            "compare actual Current bodies",
            "Never install, enable, or update plugins",
            "context-core coordinator",
        ):
            self.assertIn(token, default_prompt)
        self.assertFalse((decision_root / "skills/context").exists())
        self.assertFalse(any(path.name == "context_cli.py" for path in decision_root.rglob("*.py")))

    def test_forbidden_install_and_host_mutation_calls_are_absent(self) -> None:
        targets = [
            ROOT / "plugins/context-core/.claude-plugin/plugin.json",
            ROOT / "plugins/context-core/.codex-plugin/plugin.json",
            ROOT / "plugins/context-decision/.claude-plugin/plugin.json",
            ROOT / "plugins/context-decision/.codex-plugin/plugin.json",
            ROOT / ".claude-plugin/marketplace.json",
            ROOT / ".agents/plugins/marketplace.json",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in targets).casefold()
        for forbidden in (
            "installed_by_default",
            "installedbydefault",
            "implicit_install",
            "implicitinstall",
            "auto_install",
            "auto_enable",
            "auto_update",
        ):
            self.assertNotIn(forbidden, text)

        scripts = (
            ROOT / "plugins/context-core/skills/context/scripts/context_cli.py",
            ROOT / "plugins/context-decision/skills/decision/scripts/decision_cli.py",
        )
        for script in scripts:
            tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
            imported = {
                node.names[0].name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
            } | {
                node.module.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            self.assertLessEqual(imported - {"__future__", "typing"}, sys.stdlib_module_names)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call = ast.unparse(node.func)
                self.assertNotIn(call, {"os.system", "subprocess.Popen"})
                if call == "subprocess.run":
                    self.assertTrue(node.args and isinstance(node.args[0], (ast.List, ast.Tuple)))
                    command = node.args[0].elts[0]
                    self.assertIsInstance(command, ast.Constant)
                    self.assertEqual("git", command.value)

        decision_source = scripts[1].read_text(encoding="utf-8")
        for physical_write in (".write_text(", ".write_bytes(", ".mkdir(", ".unlink(", "os.replace("):
            self.assertNotIn(physical_write, decision_source)


if __name__ == "__main__":
    unittest.main()
