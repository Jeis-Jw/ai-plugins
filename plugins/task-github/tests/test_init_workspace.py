import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import init_workspace  # noqa: E402


class TaskGithubInitTests(unittest.TestCase):
    def test_create_then_idempotent_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created, code = init_workspace.initialize(root=root, base_branch="develop")
            skipped, second_code = init_workspace.initialize(root=root, base_branch="develop")

            self.assertEqual(code, 0)
            self.assertEqual(created["action"], "create")
            self.assertTrue(created["changed"])
            self.assertTrue(created["validation"]["ok"])
            self.assertEqual(
                set(created),
                {
                    "plugin", "action", "changed", "would_change", "paths",
                    "conflicts", "validation", "dry_run",
                },
            )
            self.assertIn("base_branch: develop", (root / ".task-github.yml").read_text())
            self.assertTrue((root / ".task-github/local/projections").is_dir())
            self.assertEqual((root / ".gitignore").read_text(), ".task-github/local/\n")
            self.assertEqual(second_code, 0)
            self.assertEqual(skipped["action"], "skip")
            self.assertFalse(skipped["changed"])
            self.assertFalse(skipped["would_change"])

    def test_dry_run_reports_plan_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, code = init_workspace.initialize(root=root, dry_run=True)

            self.assertEqual(code, 0)
            self.assertEqual(result["action"], "plan")
            self.assertTrue(result["would_change"])
            self.assertFalse(result["changed"])
            self.assertFalse((root / ".task-github.yml").exists())
            self.assertFalse((root / ".task-github").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_custom_state_root_is_rendered_into_provider_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom = Path(".provider-state/projections")

            result, code = init_workspace.initialize(root=root, state_root=custom)

            self.assertEqual(code, 0)
            self.assertEqual(result["paths"]["state_root"], custom.as_posix())
            config = (root / ".task-github.yml").read_text(encoding="utf-8")
            self.assertIn("state-root: .provider-state/projections", config)
            self.assertTrue((root / custom).is_dir())

    def test_conflict_is_fail_closed_before_any_other_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".task-github.yml"
            config.write_text("base_branch: custom\n", encoding="utf-8")

            result, code = init_workspace.initialize(root=root)

            self.assertEqual(code, 2)
            self.assertEqual(result["action"], "conflict")
            self.assertFalse(result["changed"])
            self.assertEqual(config.read_text(), "base_branch: custom\n")
            self.assertFalse((root / ".task-github").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_collects_all_path_type_conflicts_without_partial_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".task-github.yml"
            config.mkdir()
            state = root / ".task-github" / "local" / "projections"
            state.parent.mkdir(parents=True)
            state.write_text("not a directory\n", encoding="utf-8")
            gitignore = root / ".gitignore"
            gitignore.mkdir()

            result, code = init_workspace.initialize(root=root, force=True)

            self.assertEqual(code, 2)
            self.assertEqual(result["action"], "conflict")
            self.assertFalse(result["changed"])
            self.assertEqual(
                {item["path"] for item in result["conflicts"]},
                {".task-github.yml", ".task-github/local/projections", ".gitignore"},
            )
            self.assertTrue(config.is_dir())
            self.assertEqual(state.read_text(encoding="utf-8"), "not a directory\n")
            self.assertTrue(gitignore.is_dir())

    def test_parent_path_type_conflict_prevents_sibling_config_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".task-github").write_text("blocks state root\n", encoding="utf-8")

            result, code = init_workspace.initialize(root=root)

            self.assertEqual(code, 2)
            self.assertEqual(result["conflicts"][0]["blocking_path"], ".task-github")
            self.assertFalse((root / ".task-github.yml").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_force_replaces_conflicting_config_and_preserves_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".task-github.yml").write_text("base_branch: custom\n", encoding="utf-8")
            (root / ".gitignore").write_text("dist/\n", encoding="utf-8")

            result, code = init_workspace.initialize(root=root, force=True)

            self.assertEqual(code, 0)
            self.assertEqual(result["action"], "update")
            self.assertIn("base_branch: main", (root / ".task-github.yml").read_text())
            self.assertEqual((root / ".gitignore").read_text(), "dist/\n.task-github/local/\n")

    def test_json_cli_uses_common_result_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                code = init_workspace.main(["--root", tmp, "--dry-run", "--json"])

        self.assertEqual(code, 0)
        self.assertIn('"plugin": "task-github"', output.getvalue())
        self.assertIn('"dry_run": true', output.getvalue())

    def test_setup_reuses_own_init_and_keeps_legacy_worker_scaffold(self):
        setup = (Path(__file__).resolve().parents[1] / "skills/setup/SKILL.md").read_text()

        self.assertIn("scripts/init_workspace.py", setup)
        self.assertIn("task-worker}/scripts/task_config.py\" scaffold", setup)
        self.assertNotIn("task-worker:init", setup)


if __name__ == "__main__":
    unittest.main()
