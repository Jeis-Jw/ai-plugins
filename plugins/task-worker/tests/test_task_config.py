import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


task_config = load_module("task_worker_config", PLUGIN / "scripts" / "task_config.py")


def invoke(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = task_config.main(list(args))
    return code, json.loads(output.getvalue())


class TaskWorkerConfigTests(unittest.TestCase):
    def test_default_config_is_valid_and_owns_execution_policy(self):
        config = task_config.parse_config(task_config.render_default_config())

        self.assertEqual(task_config.validate_config(config), [])
        self.assertEqual(config["dispatch"], "worker")
        self.assertEqual(config["delivery"], "local-ff")
        self.assertEqual(config["orchestrate"]["max-workers"], 3)
        self.assertTrue(config["evidence"]["duplicate-guard"])
        self.assertNotIn("base_branch", config)

    def test_manual_dispatch_is_first_class(self):
        config = task_config.parse_config(
            task_config.render_default_config().replace("dispatch: worker", "dispatch: manual")
        )

        self.assertEqual(task_config.validate_config(config), [])
        self.assertEqual(config["dispatch"], "manual")

    def test_provider_keys_are_rejected_from_worker_config(self):
        config = task_config.parse_config(
            task_config.render_default_config() + "base_branch: main\n"
        )

        findings = task_config.validate_config(config)

        self.assertIn("provider_key_forbidden", {finding["code"] for finding in findings})
        self.assertTrue(any(finding["severity"] == "error" for finding in findings))

    def test_invalid_evidence_and_recovery_limits_fail(self):
        config = task_config.parse_config(task_config.render_default_config())
        config["evidence"]["max-physical-runs"] = 0
        config["recovery"]["lease-ttl-seconds"] = "later"

        errors = {
            finding["code"]
            for finding in task_config.validate_config(config)
            if finding["severity"] == "error"
        }

        self.assertEqual(
            errors,
            {"bad_evidence_max_physical_runs", "bad_recovery_lease_ttl"},
        )

    def test_scaffold_does_not_overwrite_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".task-worker.yml"
            path.write_text("dispatch: manual\n", encoding="utf-8")

            result = task_config.main(["scaffold", "--path", str(path), "--json"])

            self.assertEqual(result, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "dispatch: manual\n")

    def test_legacy_scaffold_remains_config_only_without_dangling_policy_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".task-worker.yml"

            result = task_config.main(["scaffold", "--path", str(path), "--json"])
            config = task_config.load_config(path)

            self.assertEqual(result, 0)
            self.assertIsNone(config["command-profiles"])
            self.assertIsNone(config["impact-rules"])
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_presets_are_deterministic_and_valid(self):
        expected = {
            "local": ("worker", "local-ff", False, True),
            "manual": ("manual", "external", False, True),
            "quality": ("worker", "local-ff", True, True),
            "minimal": ("worker", "local-ff", False, False),
        }
        for preset, (dispatch, delivery, token_required, has_policy) in expected.items():
            with self.subTest(preset=preset):
                first = task_config.render_preset_config(preset)
                self.assertEqual(first, task_config.render_preset_config(preset))
                config = task_config.parse_config(first)
                self.assertEqual(task_config.validate_config(config), [])
                self.assertEqual(config["dispatch"], dispatch)
                self.assertEqual(config["delivery"], delivery)
                self.assertEqual(config["evidence"]["token-coverage-required"], token_required)
                self.assertEqual(bool(config.get("command-profiles")), has_policy)
                self.assertEqual(bool(config.get("impact-rules")), has_policy)

    def test_init_is_idempotent_and_has_common_json_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, first = invoke("init", "--root", tmp, "--preset", "local", "--json")
            second_code, second = invoke("init", "--root", tmp, "--preset", "local", "--json")

            self.assertEqual(code, 0)
            self.assertEqual(second_code, 0)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(
                {"plugin", "action", "changed", "paths", "validation", "dry_run"} - set(first),
                set(),
            )
            self.assertEqual((Path(tmp) / ".gitignore").read_text(encoding="utf-8"), ".task-worker/local/\n")
            self.assertTrue((Path(tmp) / ".task-worker" / "local").is_dir())

    def test_init_conflict_is_atomic_and_force_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".task-worker.yml"
            config.write_text("dispatch: manual\n", encoding="utf-8")

            code, conflict = invoke("init", "--root", tmp, "--preset", "local", "--json")

            self.assertEqual(code, 2)
            self.assertEqual(conflict["error_code"], "path_conflict")
            self.assertFalse(conflict["changed"])
            self.assertEqual(config.read_text(encoding="utf-8"), "dispatch: manual\n")
            self.assertFalse((root / ".task-worker").exists())
            self.assertFalse((root / ".gitignore").exists())

            force_code, forced = invoke("init", "--root", tmp, "--preset", "local", "--force", "--json")
            self.assertEqual(force_code, 0)
            self.assertTrue(forced["changed"])
            self.assertEqual(task_config.load_config(config)["dispatch"], "worker")

    def test_init_parent_type_conflict_is_atomic_and_matches_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocker = root / ".task-worker"
            blocker.write_text("owned by user\n", encoding="utf-8")

            dry_code, dry = invoke(
                "init", "--root", tmp, "--preset", "local", "--dry-run", "--json"
            )
            code, actual = invoke("init", "--root", tmp, "--preset", "local", "--json")

            self.assertEqual(dry_code, 2)
            self.assertEqual(code, 2)
            self.assertEqual(dry["error_code"], "path_conflict")
            self.assertEqual(actual["error_code"], "path_conflict")
            self.assertEqual(dry["conflicts"], actual["conflicts"])
            self.assertTrue(all(item["blocking_path"] == ".task-worker" for item in actual["conflict_details"]))
            self.assertEqual(blocker.read_text(encoding="utf-8"), "owned by user\n")
            self.assertFalse((root / ".task-worker.yml").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_dry_run_does_not_touch_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "consumer"

            code, payload = invoke("init", "--root", str(root), "--preset", "quality", "--dry-run", "--json")

            self.assertEqual(code, 0)
            self.assertTrue(payload["changed"])
            self.assertTrue(payload["dry_run"])
            self.assertFalse(root.exists())

    def test_todo_policy_is_valid_json_but_execution_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = invoke("init", "--root", tmp, "--preset", "quality", "--json")
            self.assertEqual(code, 0)
            control = task_config._load_execution_control()
            with self.assertRaisesRegex(Exception, "at least one command profile"):
                control.load_command_profiles(Path(tmp) / ".task-worker" / "commands.json")
            with self.assertRaisesRegex(Exception, "non-empty list"):
                control.load_impact_rules(Path(tmp) / ".task-worker" / "impact-rules.json")

    def test_doctor_distinguishes_todo_policy_from_minimal_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            invoke("init", "--root", tmp, "--preset", "local", "--json")
            code, payload = invoke("doctor", "--root", tmp, "--json")
            self.assertEqual(code, 1)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["ready"])
            self.assertEqual(payload["validation"]["command_profiles"], "todo")

        with tempfile.TemporaryDirectory() as tmp:
            invoke("init", "--root", tmp, "--preset", "minimal", "--json")
            code, payload = invoke("doctor", "--root", tmp, "--json")
            self.assertEqual(code, 0)
            self.assertTrue(payload["ready"])
            self.assertEqual(payload["validation"]["command_profiles"], "disabled")

    def test_doctor_reports_missing_state_and_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".task-worker.yml").write_text(
                task_config.render_preset_config("local"), encoding="utf-8"
            )

            code, payload = invoke("doctor", "--root", tmp, "--json")

            self.assertEqual(code, 2)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["validation"]["state_root"], "missing")
            self.assertEqual(payload["validation"]["command_profiles"], "missing")


if __name__ == "__main__":
    unittest.main()
