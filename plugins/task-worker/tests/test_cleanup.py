import importlib.util
import subprocess
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


cleanup = load_module("task_worker_cleanup", PLUGIN / "scripts" / "cleanup.py")
task_config = load_module("task_worker_cleanup_test_config", PLUGIN / "scripts" / "task_config.py")


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


class CleanupTests(unittest.TestCase):
    def make_repo(self, root):
        repo = root / "repo"
        git(root, "init", "-b", "main", str(repo))
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        (repo / ".task-worker.yml").write_text(task_config.render_preset_config("local"), encoding="utf-8")
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "base")
        worktree = root / "feature"
        git(repo, "worktree", "add", "-b", "task/test", str(worktree))
        (worktree / "tracked.txt").write_text("feature\n", encoding="utf-8")
        git(worktree, "add", "tracked.txt")
        git(worktree, "commit", "-m", "feature")
        return repo, worktree

    def test_cleanup_removes_clean_merged_worktree_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, worktree = self.make_repo(root)
            git(repo, "merge", "--ff-only", "task/test")

            payload, code = cleanup.run_cleanup(
                repo=repo,
                branch="task/test",
                base="main",
                config_path=Path(".task-worker.yml"),
            )

            self.assertEqual(code, 0)
            self.assertTrue(payload["removed_worktree"])
            self.assertTrue(payload["deleted_local_branch"])
            self.assertFalse(worktree.exists())
            self.assertNotIn("task/test", git(repo, "branch", "--format=%(refname:short)").stdout)

    def test_cleanup_preserves_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, worktree = self.make_repo(root)
            git(repo, "merge", "--ff-only", "task/test")
            (worktree / "uncommitted.txt").write_text("mine\n", encoding="utf-8")

            payload, code = cleanup.run_cleanup(
                repo=repo,
                branch="task/test",
                base="main",
                config_path=Path(".task-worker.yml"),
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["error_code"], "dirty_worktree")
            self.assertTrue(worktree.exists())
            self.assertIn("task/test", git(repo, "branch", "--format=%(refname:short)").stdout)

    def test_cleanup_preserves_unmerged_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, worktree = self.make_repo(root)

            payload, code = cleanup.run_cleanup(
                repo=repo,
                branch="task/test",
                base="main",
                config_path=Path(".task-worker.yml"),
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["error_code"], "branch_not_merged")
            self.assertTrue(worktree.exists())


if __name__ == "__main__":
    unittest.main()
