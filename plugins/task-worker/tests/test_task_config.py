import importlib.util
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


if __name__ == "__main__":
    unittest.main()
