import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import task_config  # noqa: E402


class TaskGithubConfigTests(unittest.TestCase):
    def test_default_provider_config_is_valid_and_has_no_execution_policy(self):
        config = task_config.parse_config(task_config.render_default_config(base_branch="main"))

        self.assertEqual(task_config.validate_config(config), [])
        self.assertEqual(config["projection"]["record"], "github")
        self.assertEqual(config["closeout"]["branch-prefix"], "task/issue-")
        self.assertTrue(config["closeout"]["delete-merged-remote-branches"])
        for moved in ("mode", "verify-tool", "orchestrate", "define"):
            self.assertNotIn(moved, config)

    def test_legacy_execution_keys_are_accepted_with_deprecation_findings(self):
        config = task_config.parse_config(
            "mode: solo\nbase_branch: main\norchestrate:\n  max-workers: 4\n"
        )

        findings = task_config.validate_config(config)

        self.assertEqual(
            [item["code"] for item in findings],
            ["legacy_execution_config", "legacy_execution_config"],
        )
        self.assertTrue(all(item["severity"] == "warning" for item in findings))

    def test_validate_provider_specific_values(self):
        config = task_config.parse_config(
            "base_branch: main\nprojection:\n  record: jira\ncloseout:\n  delete-merged-remote-branches: maybe\n"
        )

        errors = {
            item["code"]
            for item in task_config.validate_config(config)
            if item["severity"] == "error"
        }

        self.assertEqual(errors, {"bad_projection_record", "bad_closeout_delete_branches"})

    def test_combined_validate_loads_adjacent_worker_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            github = root / ".task-github.yml"
            worker = root / ".task-worker.yml"
            github.write_text(task_config.render_default_config(), encoding="utf-8")
            worker.write_text(
                "mode: solo\nstate-root: .task-worker/local\ndispatch: worker\ndelivery: local-ff\n"
                "orchestrate:\n  review-mode: gear\n  max-workers: 3\n"
                "define:\n  review-required: false\n"
                "evidence:\n  max-physical-runs: 3\n"
                "recovery:\n  lease-ttl-seconds: 3600\n",
                encoding="utf-8",
            )

            config, findings, source = task_config.load_worker_config(github)

        self.assertEqual(config["dispatch"], "worker")
        self.assertFalse([item for item in findings if item["severity"] == "error"])
        self.assertTrue(source.endswith(".task-worker.yml"))

    def test_get_routes_execution_keys_to_worker_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            github = root / ".task-github.yml"
            worker = root / ".task-worker.yml"
            github.write_text(task_config.render_default_config(base_branch="develop"), encoding="utf-8")
            worker.write_text("dispatch: manual\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                rc = task_config.main(["get", "dispatch", "--path", str(github)])

        self.assertEqual(rc, 0)
        self.assertEqual(output.getvalue().strip(), "manual")

    def test_legacy_combined_config_is_worker_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".task-github.yml"
            path.write_text(
                "mode: solo\nbase_branch: main\ndefine:\n  review-required: true\n",
                encoding="utf-8",
            )

            worker, findings, source = task_config.load_worker_config(path)

        self.assertTrue(worker["define"]["review-required"])
        self.assertIn("legacy_worker_config_fallback", {item["code"] for item in findings})
        self.assertEqual(source, str(path))


if __name__ == "__main__":
    unittest.main()
