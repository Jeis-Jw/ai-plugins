from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "studio_config.py"
SPEC = importlib.util.spec_from_file_location("studio_config", SCRIPT)
assert SPEC and SPEC.loader
studio_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(studio_config)


class StudioConfigTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_scaffold_is_valid_and_inherits_by_default(self) -> None:
        config = studio_config.parse_yaml_subset(studio_config.render_default_config())
        self.assertEqual(studio_config.validate_config(config), [])
        profile = studio_config.resolve_profile(
            config,
            provider="codex",
            role="architect",
        )
        self.assertIsNone(profile["model"])
        self.assertIsNone(profile["effort"])
        self.assertFalse(profile["configured"])
        self.assertEqual(profile["sources"]["model"], "host-session-inherit")

    def test_provider_role_resolves_field_by_field(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
defaults:
  model: common-model
  effort: low
roles:
  architect:
    effort: medium
providers:
  codex:
    defaults:
      model: provider-model
    roles:
      architect:
        model: role-model
        effort: high
"""
        )
        self.assertEqual(studio_config.validate_config(config), [])
        profile = studio_config.resolve_profile(
            config,
            provider="codex",
            role="architect",
        )
        self.assertEqual(profile["model"], "role-model")
        self.assertEqual(profile["effort"], "high")
        self.assertEqual(profile["sources"]["model"], "provider-role")
        self.assertEqual(profile["sources"]["effort"], "provider-role")

    def test_explicit_override_wins_without_erasing_other_field(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
providers:
  claude:
    roles:
      reviewer:
        model: opus
        effort: high
"""
        )
        profile = studio_config.resolve_profile(
            config,
            provider="claude",
            role="reviewer",
            effort_override="max",
        )
        self.assertEqual(profile["model"], "opus")
        self.assertEqual(profile["effort"], "max")
        self.assertEqual(profile["sources"]["model"], "provider-role")
        self.assertEqual(profile["sources"]["effort"], "explicit-override")

    def test_model_and_effort_are_provider_owned_strings(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
providers:
  codex:
    roles:
      dev:
        model: future-model-id
        effort: ultra
"""
        )
        self.assertEqual(studio_config.validate_config(config), [])

    def test_unknown_structure_and_non_string_profile_fail(self) -> None:
        unknown = studio_config.parse_yaml_subset(
            """
defaults:
  model:
surprise:
  value: true
"""
        )
        self.assertTrue(studio_config.validate_config(unknown))
        invalid = studio_config.parse_yaml_subset(
            """
roles:
  dev:
    effort: 7
"""
        )
        self.assertTrue(studio_config.validate_config(invalid))

    def test_tabs_and_duplicate_keys_fail_parse(self) -> None:
        with self.assertRaisesRegex(studio_config.ConfigError, "tab indentation"):
            studio_config.parse_yaml_subset("roles:\n\tdev:\n\t\teffort: high\n")
        with self.assertRaisesRegex(studio_config.ConfigError, "duplicate key"):
            studio_config.parse_yaml_subset("defaults:\n  model: one\n  model: two\n")

    def test_missing_config_resolves_to_session_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            present, config = studio_config.load_config(
                Path(directory) / ".studio.yml",
                missing_ok=True,
            )
        self.assertFalse(present)
        profile = studio_config.resolve_profile(
            config,
            provider="codex",
            role="dev",
        )
        self.assertFalse(profile["configured"])

    def test_missing_execute_routes_never_probe_optional_commands(self) -> None:
        for kind, decision in (("work", "native"), ("review", "native"), ("delivery", "skip")):
            with self.subTest(kind=kind):
                route = studio_config.resolve_execute_route({}, kind=kind)
                self.assertEqual(route["decision"], decision)
                self.assertEqual(route["probe"], "forbidden")
                self.assertFalse(route["configured"])

    def test_auto_work_and_review_defer_selection_to_producer(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
execute:
  work:
    command: task-worker
    activation: auto
    fallback: native
  review:
    command: session-review
    activation: always
    fallback: stop
"""
        )
        self.assertEqual(studio_config.validate_config(config), [])
        work = studio_config.resolve_execute_route(config, kind="work")
        review = studio_config.resolve_execute_route(config, kind="review")
        self.assertEqual(work["decision"], "producer-decision")
        self.assertEqual(work["probe"], "after-producer-selection")
        self.assertEqual(review["decision"], "invoke-command")
        self.assertEqual(review["probe"], "required")

    def test_delivery_requires_explicit_operator_enable(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
execute:
  delivery:
    command: task-github
    enabled: false
    fallback: skip
"""
        )
        disabled = studio_config.resolve_execute_route(config, kind="delivery")
        enabled = studio_config.resolve_execute_route(
            config,
            kind="delivery",
            enabled_override=True,
        )
        self.assertEqual(disabled["decision"], "skip")
        self.assertEqual(disabled["probe"], "forbidden")
        self.assertEqual(enabled["decision"], "invoke-command")
        self.assertEqual(enabled["source"], "run-override")

    def test_execute_commands_are_opaque_but_never_shell_strings(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
execute:
  work:
    command: future-worker:execute
    activation: auto
"""
        )
        self.assertEqual(studio_config.validate_config(config), [])
        unsafe = studio_config.parse_yaml_subset(
            """
execute:
  work:
    command: task-worker --force
    activation: always
"""
        )
        self.assertTrue(studio_config.validate_config(unsafe))

    def test_active_route_without_command_is_invalid(self) -> None:
        config = studio_config.parse_yaml_subset(
            """
execute:
  work:
    command:
    activation: always
  delivery:
    enabled: true
"""
        )
        problems = studio_config.validate_config(config)
        self.assertEqual(
            [problem["where"] for problem in problems],
            ["execute.work.command", "execute.delivery.command"],
        )

    def test_run_command_override_is_exact_and_fail_closed(self) -> None:
        route = studio_config.resolve_execute_route(
            {},
            kind="work",
            command_override="task-worker",
        )
        self.assertEqual(route["command"], "task-worker")
        self.assertEqual(route["activation"], "always")
        self.assertEqual(route["fallback"], "stop")
        self.assertEqual(route["decision"], "invoke-command")

    def test_example_config_is_valid(self) -> None:
        present, _ = studio_config.load_config(
            PLUGIN / "config.example.yml",
            missing_ok=False,
        )
        self.assertTrue(present)

    def test_cli_scaffold_validate_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".studio.yml"
            scaffold = self.run_cli("scaffold", "--path", str(path))
            self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
            self.assertTrue(json.loads(scaffold.stdout)["created"])

            validate = self.run_cli("validate", "--path", str(path))
            self.assertEqual(validate.returncode, 0, validate.stderr)
            self.assertEqual(json.loads(validate.stdout)["problems"], [])

            resolve = self.run_cli(
                "resolve",
                "--path",
                str(path),
                "--provider",
                "codex",
                "--role",
                "dev",
                "--model",
                "gpt-5.6-sol",
                "--effort",
                "high",
            )
            self.assertEqual(resolve.returncode, 0, resolve.stderr)
            profile = json.loads(resolve.stdout)["profile"]
            self.assertEqual(profile["model"], "gpt-5.6-sol")
            self.assertEqual(profile["effort"], "high")
            self.assertEqual(profile["sources"]["model"], "explicit-override")

            route = self.run_cli(
                "route",
                "--path",
                str(path),
                "--kind",
                "work",
                "--command",
                "task-worker",
            )
            self.assertEqual(route.returncode, 0, route.stderr)
            route_payload = json.loads(route.stdout)["route"]
            self.assertEqual(route_payload["decision"], "invoke-command")
            self.assertEqual(route_payload["fallback"], "stop")

    def test_cli_rejects_invalid_config_with_stable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".studio.yml"
            path.write_text("roles:\n  dev:\n    effort: 7\n", encoding="utf-8")
            result = self.run_cli(
                "resolve",
                "--path",
                str(path),
                "--provider",
                "codex",
                "--role",
                "dev",
            )
        self.assertEqual(result.returncode, 6)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "invalid_config")
        self.assertEqual(payload["problems"][0]["where"], "roles.dev.effort")


if __name__ == "__main__":
    unittest.main()
