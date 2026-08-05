import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "plugins" / "wiki-markdown" / "hooks" / "capture_checkpoint.py"

EDIT_LINE = json.dumps(
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {}}]}}
)
COMMIT_LINE = json.dumps(
    {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m x"}}
            ]
        },
    }
)
NOISE_LINE = json.dumps(
    {"type": "user", "message": {"content": [{"type": "text", "text": "please Edit git commit"}]}}
)


class CaptureCheckpointHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cwd = self.tmp / "workspace"
        (self.cwd / "wiki").mkdir(parents=True)
        self.transcript = self.tmp / "transcript.jsonl"
        self.state_tmp = self.tmp / "state-tmp"
        self.state_tmp.mkdir()

    def run_hook(self, payload_overrides=None, env_overrides=None):
        payload = {
            "session_id": "test-session",
            "transcript_path": str(self.transcript),
            "cwd": str(self.cwd),
            "stop_hook_active": False,
        }
        payload.update(payload_overrides or {})
        env = dict(os.environ)
        env.pop("WIKI_MARKDOWN_CHECKPOINT", None)
        env.pop("WIKI_MARKDOWN_CHECKPOINT_MIN_EDITS", None)
        env["TMPDIR"] = str(self.state_tmp)  # isolate per-session firing state
        env.update(env_overrides or {})
        return subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def write_transcript(self, lines):
        self.transcript.write_text("\n".join(lines) + "\n")

    def assert_fired(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("[wiki-markdown capture checkpoint]", out["reason"])

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_fires_when_edit_threshold_met(self):
        self.write_transcript([NOISE_LINE] + [EDIT_LINE] * 3)
        self.assert_fired(self.run_hook())

    def test_single_commit_fires_even_below_edit_threshold(self):
        self.write_transcript([NOISE_LINE, COMMIT_LINE])
        self.assert_fired(self.run_hook())

    def test_silent_below_threshold(self):
        self.write_transcript([NOISE_LINE] + [EDIT_LINE] * 2)
        self.assert_silent(self.run_hook())

    def test_prose_mentions_do_not_count_as_work(self):
        self.write_transcript([NOISE_LINE] * 10)
        self.assert_silent(self.run_hook())

    def test_silent_without_vault(self):
        shutil.rmtree(self.cwd / "wiki")
        self.write_transcript([EDIT_LINE] * 5)
        self.assert_silent(self.run_hook())

    def test_silent_when_stop_hook_active(self):
        self.write_transcript([EDIT_LINE] * 5)
        self.assert_silent(self.run_hook({"stop_hook_active": True}))

    def test_env_kill_switch(self):
        self.write_transcript([EDIT_LINE] * 5)
        for value in ("off", "0", "false"):
            self.assert_silent(self.run_hook(env_overrides={"WIKI_MARKDOWN_CHECKPOINT": value}))

    def test_min_edits_env_override(self):
        self.write_transcript([EDIT_LINE])
        self.assert_fired(self.run_hook(env_overrides={"WIKI_MARKDOWN_CHECKPOINT_MIN_EDITS": "1"}))

    def test_fires_once_per_batch_then_again_after_new_work(self):
        self.write_transcript([EDIT_LINE] * 3)
        self.assert_fired(self.run_hook())
        # same batch, no new work since the firing -> silent
        self.assert_silent(self.run_hook())
        # a new batch of work accumulates after the recorded firing line -> fires again
        with self.transcript.open("a") as f:
            for _ in range(3):
                f.write(EDIT_LINE + "\n")
        self.assert_fired(self.run_hook())

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_silent_in_linked_worktree(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(git + ["init", "-q"], check=True)
        (repo / "f").write_text("x")
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        worktree = self.tmp / "lane"
        subprocess.run(git + ["worktree", "add", "-q", str(worktree)], check=True)
        (worktree / "wiki").mkdir()
        self.write_transcript([EDIT_LINE] * 5)
        self.assert_silent(self.run_hook({"cwd": str(worktree)}))
        # sanity: same transcript fires from the main (non-linked) working tree
        (repo / "wiki").mkdir()
        self.assert_fired(self.run_hook({"cwd": str(repo)}))

    def test_plugin_manifest_declares_stop_hook(self):
        manifest = json.loads(
            (REPO / "plugins" / "wiki-markdown" / ".claude-plugin" / "plugin.json").read_text()
        )
        stop = manifest["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(stop["type"], "command")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/capture_checkpoint.py", stop["command"])
        self.assertTrue(HOOK.exists())


if __name__ == "__main__":
    unittest.main()
