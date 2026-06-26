import json
import os
import tempfile
import unittest

from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import session_review  # noqa: E402


SNAPSHOT_TEXT = """---
title: Session review handoff
created_at: 2026-06-19
summary: Review state.
tags: [session-review]
type: snapshot
---
## 현재 논의
This human note can mention YAML without being the status.

```text
phase: bogus
```

```yaml
phase: awaiting-review
active_actor: none
lock_since: null
next_actor: reviewer
target_mode: diff
target_ref: task/issue-10-review
base_ref: 123456
responding_to: 654321
round: 2
flow_mode: separate
review_strength: hard
```

```yaml
phase: changes-requested
```

## 배경
```yaml
phase: ignored
```
"""


class SessionReviewStatusTests(unittest.TestCase):
    def test_extracts_first_yaml_block_only_from_current_discussion_section(self):
        status = session_review.extract_status(SNAPSHOT_TEXT)

        self.assertEqual(status["phase"], "awaiting-review")
        self.assertEqual(status["active_actor"], "none")
        self.assertIsNone(status["lock_since"])
        self.assertEqual(status["next_actor"], "reviewer")
        self.assertEqual(status["target_ref"], "task/issue-10-review")
        self.assertEqual(status["base_ref"], "123456")
        self.assertEqual(status["responding_to"], "654321")
        self.assertEqual(status["round"], 2)

    def test_render_quotes_string_fields_but_keeps_round_integer_and_null_lock(self):
        rendered = session_review.render_status(
            {
                "phase": "changes-requested",
                "active_actor": "none",
                "lock_since": None,
                "next_actor": "worker",
                "target_mode": "document",
                "target_ref": "wiki/ssot/session-review-plugin.md",
                "base_ref": "123456",
                "responding_to": "654321",
                "round": 3,
                "flow_mode": "self",
                "review_strength": "normal",
            }
        )

        self.assertIn('phase: "changes-requested"', rendered)
        self.assertIn('base_ref: "123456"', rendered)
        self.assertIn("round: 3", rendered)
        self.assertIn("lock_since: null", rendered)

    def test_defaults_target_nature_round_type_and_derives_posture(self):
        status = session_review.parse_status_block(
            """phase: awaiting-review
active_actor: none
lock_since: null
next_actor: reviewer
target_mode: diff
target_ref: branch-review
base_ref: abc123
responding_to: abc123
round: 1
flow_mode: separate
review_strength: normal
"""
        )

        self.assertEqual(status["target_nature"], "code")
        self.assertEqual(status["round_type"], "review")
        self.assertEqual(session_review.effective_review_posture(status), "verify")
        self.assertFalse(session_review.requires_confirm_lock_check(status))

        document = dict(status, target_mode="document")
        document.pop("target_nature")
        self.assertEqual(session_review.normalize_status(document)["target_nature"], "general")

    def test_effective_posture_uses_table_and_optional_override(self):
        process_explore = {"target_nature": "process", "round_type": "explore"}
        self.assertEqual(session_review.effective_review_posture(process_explore), "co-design")

        process_converge = {"target_nature": "process", "round_type": "converge"}
        self.assertEqual(session_review.effective_review_posture(process_converge), "challenge")

        confirm = {"target_nature": "process", "round_type": "confirm"}
        self.assertEqual(session_review.effective_review_posture(confirm), "verify")
        self.assertTrue(session_review.requires_confirm_lock_check(confirm))

        override = {"target_nature": "code", "round_type": "review", "review_posture": "challenge"}
        self.assertEqual(session_review.effective_review_posture(override), "challenge")

    def test_validate_status_rejects_invalid_review_posture_fields(self):
        with self.assertRaisesRegex(session_review.StatusError, "target_nature"):
            session_review.validate_status({"phase": "approved", "target_nature": "memo"})

        with self.assertRaisesRegex(session_review.StatusError, "round_type"):
            session_review.validate_status({"phase": "approved", "round_type": "final"})

        with self.assertRaisesRegex(session_review.StatusError, "review_posture"):
            session_review.validate_status({"phase": "approved", "review_posture": "confirm"})

    def test_render_rejects_invalid_review_posture_override(self):
        with self.assertRaisesRegex(session_review.StatusError, "review_posture"):
            session_review.render_status(
                {"phase": "awaiting-review", "review_posture": "confirm"}
            )

    def test_actor_gate_rejects_wrong_owner_and_existing_lock(self):
        status = session_review.extract_status(SNAPSHOT_TEXT)

        with self.assertRaisesRegex(session_review.StatusError, "next actor is reviewer"):
            session_review.validate_turn(status, actor="worker")

        locked = dict(status, active_actor="worker")
        with self.assertRaisesRegex(session_review.StatusError, "locked by worker"):
            session_review.validate_turn(locked, actor="reviewer")

        with self.assertRaisesRegex(session_review.StatusError, "requires phase"):
            session_review.validate_turn(status, actor="reviewer", allowed_phases={"approved"})

    def test_complete_requires_approved_phase_and_explicit_user_confirmation(self):
        approved = dict(
            session_review.extract_status(SNAPSHOT_TEXT),
            phase="approved",
            next_actor="worker",
        )

        with self.assertRaisesRegex(session_review.StatusError, "blocking_count"):
            session_review.validate_complete(approved, user_confirmed=True)

        approved["blocking_count"] = 0

        with self.assertRaisesRegex(session_review.StatusError, "user confirmation"):
            session_review.validate_complete(approved, user_confirmed=False)

        session_review.validate_complete(approved, user_confirmed=True)

        awaiting_user = dict(
            approved,
            phase="awaiting-user-confirmation",
            next_actor="user",
        )
        session_review.validate_complete(awaiting_user, user_confirmed=True)

        requested = dict(approved, phase="changes-requested")
        requested["blocking_count"] = 1
        with self.assertRaisesRegex(session_review.StatusError, "requires phase"):
            session_review.validate_complete(requested, user_confirmed=True)

    def test_self_profile_defaults_audit_except_turnkey_forces_fast(self):
        auto_rounds = session_review.normalize_status({
            "phase": "awaiting-review",
            "flow_mode": "self",
            "self_automation": "auto-rounds",
        })
        self.assertEqual(auto_rounds["recording_mode"], "audit")

        turnkey = session_review.normalize_status({
            "phase": "approved",
            "flow_mode": "self",
            "self_automation": "turnkey",
        })
        self.assertEqual(turnkey["recording_mode"], "fast")

    def test_self_turnkey_rejects_audit_recording(self):
        with self.assertRaisesRegex(session_review.StatusError, "turnkey"):
            session_review.validate_status({
                "phase": "approved",
                "next_actor": "worker",
                "active_actor": "none",
                "blocking_count": 0,
                "flow_mode": "self",
                "self_automation": "turnkey",
                "recording_mode": "audit",
            })

    def test_separate_flow_rejects_fast_or_self_automation(self):
        with self.assertRaisesRegex(session_review.StatusError, "recording_mode"):
            session_review.validate_status({
                "phase": "awaiting-review",
                "flow_mode": "separate",
                "recording_mode": "fast",
            })

        with self.assertRaisesRegex(session_review.StatusError, "self_automation"):
            session_review.validate_status({
                "phase": "awaiting-review",
                "flow_mode": "separate",
                "self_automation": "auto-rounds",
            })

    def test_self_turnkey_complete_does_not_need_user_confirmation(self):
        approved = {
            "phase": "approved",
            "active_actor": "none",
            "next_actor": "worker",
            "blocking_count": 0,
            "flow_mode": "self",
            "self_automation": "turnkey",
        }
        session_review.validate_complete(approved, user_confirmed=False)


class BackendResolverTests(unittest.TestCase):
    def test_env_override_none_forces_builtin(self):
        for val in ("", "none", "off"):
            with self.subTest(val=val):
                old = os.environ.get("SESSION_REVIEW_WIKI_CLI")
                os.environ["SESSION_REVIEW_WIKI_CLI"] = val
                try:
                    self.assertIsNone(session_review.resolve_wiki_cli())
                finally:
                    if old is None:
                        os.environ.pop("SESSION_REVIEW_WIKI_CLI", None)
                    else:
                        os.environ["SESSION_REVIEW_WIKI_CLI"] = old

    def test_env_override_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "wiki_cli.py"
            fake.write_text("# fake\n")
            old = os.environ.get("SESSION_REVIEW_WIKI_CLI")
            os.environ["SESSION_REVIEW_WIKI_CLI"] = str(fake)
            try:
                self.assertEqual(session_review.resolve_wiki_cli(), fake)
            finally:
                if old is None:
                    os.environ.pop("SESSION_REVIEW_WIKI_CLI", None)
                else:
                    os.environ["SESSION_REVIEW_WIKI_CLI"] = old


class BuiltinSnapshotTests(unittest.TestCase):
    def _save(self, vault, **kw):
        fields = {"title": "T", "summary": "s", "tags": ["session-review"]}
        fields.update(kw.pop("fields", {}))
        sections = kw.pop("sections", {})
        return session_review.builtin_snapshot_save(
            vault, kw.pop("slug", "thread"), fields, sections, merge=kw.pop("merge", False)
        )

    def test_save_load_discard_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "wiki"
            path = self._save(vault, sections={"discussion": "HELLO STATUS"})
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "SNAP-thread.md")
            loaded = session_review.builtin_snapshot_load(vault, "thread")
            self.assertIn("HELLO STATUS", loaded["text"])
            self.assertIn("type: snapshot", loaded["text"])
            self.assertIn("## 현재 논의", loaded["text"])
            self.assertTrue(session_review.builtin_snapshot_discard(vault, "thread"))
            self.assertFalse(path.exists())

    def test_builtin_maintains_existing_snapshot_index(self):
        # B3a: mirror wiki_cli — update snapshot.md index iff it already exists.
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "wiki"
            snapdir = vault / "snapshot"
            snapdir.mkdir(parents=True)
            (snapdir / "snapshot.md").write_text("# snapshots\n\n## 노트\n\n", encoding="utf-8")
            session_review.builtin_snapshot_save(
                vault, "h", {"title": "T", "summary": "SUMMARY", "tags": ["x"]},
                {"discussion": "d"}, merge=False)
            idx = (snapdir / "snapshot.md").read_text()
            self.assertIn("[[SNAP-h]]", idx)
            self.assertIn("SUMMARY", idx)
            session_review.builtin_snapshot_discard(vault, "h")
            self.assertNotIn("SNAP-h", (snapdir / "snapshot.md").read_text())

    def test_builtin_without_index_does_not_create_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "wiki"
            session_review.builtin_snapshot_save(
                vault, "h", {"title": "T", "summary": "s", "tags": ["x"]},
                {"discussion": "d"}, merge=False)
            self.assertFalse((vault / "snapshot" / "snapshot.md").exists())

    def test_merge_preserves_omitted_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "wiki"
            self._save(vault, sections={"discussion": "ORIG DISC", "decided": "ORIG DEC"})
            self._save(vault, sections={"decided": "NEW DEC"}, merge=True)
            text = session_review.builtin_snapshot_load(vault, "thread")["text"]
            self.assertIn("ORIG DISC", text)
            self.assertIn("NEW DEC", text)
            self.assertNotIn("ORIG DEC", text)


class SetAndValidateStatusTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("SESSION_REVIEW_WIKI_CLI")
        os.environ["SESSION_REVIEW_WIKI_CLI"] = "none"  # force built-in backend

    def tearDown(self):
        if self._old is None:
            os.environ.pop("SESSION_REVIEW_WIKI_CLI", None)
        else:
            os.environ["SESSION_REVIEW_WIKI_CLI"] = self._old

    def _seed(self, vault):
        session_review.builtin_snapshot_save(
            vault, "h", {"title": "T", "summary": "s", "tags": ["x"]},
            {"discussion": "```yaml\n" + session_review.render_status({
                "phase": "awaiting-review", "active_actor": "none", "lock_since": None,
                "next_actor": "reviewer", "target_mode": "diff", "target_ref": "b",
                "base_ref": "a", "responding_to": "a", "round": 1,
                "flow_mode": "self", "review_strength": "normal",
            }).rstrip() + "\n```"}, merge=False,
        )

    def test_set_status_mutates_block_via_builtin(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "wiki"
            self._seed(vault)
            session_review.set_status(vault, "h", {
                "phase": "approved", "active_actor": "none", "lock_since": None,
                "next_actor": "worker", "target_mode": "diff", "target_ref": "b",
                "base_ref": "a", "responding_to": "a", "round": 1,
                "flow_mode": "self", "review_strength": "normal", "blocking_count": 0,
            })
            status = session_review.extract_status(
                session_review.builtin_snapshot_load(vault, "h")["text"])
            self.assertEqual(status["phase"], "approved")
            self.assertEqual(status["next_actor"], "worker")

    def test_validate_status_rejects_approved_with_blocking(self):
        missing = {"phase": "approved", "next_actor": "worker", "active_actor": "none"}
        with self.assertRaisesRegex(session_review.StatusError, "blocking_count"):
            session_review.validate_status(missing)

        bad = {"phase": "approved", "next_actor": "worker", "active_actor": "none",
               "blocking_count": 2}
        with self.assertRaisesRegex(session_review.StatusError, "blocking"):
            session_review.validate_status(bad)

    def test_validate_status_rejects_changes_requested_without_blocking(self):
        missing = {"phase": "changes-requested", "next_actor": "worker",
                   "active_actor": "none"}
        with self.assertRaisesRegex(session_review.StatusError, "blocking_count"):
            session_review.validate_status(missing)

        zero = dict(missing, blocking_count=0)
        with self.assertRaisesRegex(session_review.StatusError, "blocking_count"):
            session_review.validate_status(zero)

    def test_validate_status_rejects_phase_owner_mismatch(self):
        bad = {"phase": "approved", "next_actor": "reviewer", "active_actor": "none"}
        with self.assertRaisesRegex(session_review.StatusError, "next_actor"):
            session_review.validate_status(bad)

    def test_validate_status_accepts_consistent_approved(self):
        ok = {"phase": "approved", "next_actor": "worker", "active_actor": "none",
              "blocking_count": 0}
        session_review.validate_status(ok)


import subprocess  # noqa: E402

CLI = SCRIPT_DIR / "session_review.py"
WIKI_CLI = (SCRIPT_DIR.parents[1] / "wiki-markdown" / "skills" / "wiki"
            / "scripts" / "wiki_cli.py")


def run_cli(*args, cwd=None, env=None):
    merged = os.environ.copy()
    merged.update(env or {})
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, env=merged,
                          text=True, capture_output=True)


class FacadeCliTests(unittest.TestCase):
    BUILTIN = {"SESSION_REVIEW_WIKI_CLI": "none"}

    def test_builtin_end_to_end_save_load_setstatus_validate_discard(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = str(Path(tmp) / "wiki")
            status = {"phase": "awaiting-review", "active_actor": "none",
                      "lock_since": None, "next_actor": "reviewer",
                      "target_mode": "diff", "target_ref": "b", "base_ref": "a",
                      "responding_to": "a", "round": 1, "flow_mode": "self",
                      "review_strength": "normal", "blocking_count": 0}
            disc = "```yaml\n" + session_review.render_status(status).rstrip() + "\n```"
            save = run_cli("snapshot-save", "--vault", vault, "--slug", "h",
                           "--title", "T", "--summary", "s", "--tags", "x",
                           "--discussion", disc, env=self.BUILTIN)
            self.assertEqual(save.returncode, 0, save.stderr)

            approved = dict(status, phase="approved", next_actor="worker")
            sett = run_cli("set-status", "--vault", vault, "--slug", "h",
                           "--status-json", json.dumps(approved), env=self.BUILTIN)
            self.assertEqual(sett.returncode, 0, sett.stderr)

            val = run_cli("validate-status", "--vault", vault, "--slug", "h",
                          env=self.BUILTIN)
            self.assertEqual(val.returncode, 0, val.stderr)

            load = run_cli("snapshot-load", "--vault", vault, "--slug", "h",
                           env=self.BUILTIN)
            self.assertIn("approved", json.loads(load.stdout)["text"])

            disc2 = run_cli("snapshot-discard", "--vault", vault, "--slug", "h",
                            env=self.BUILTIN)
            self.assertTrue(json.loads(disc2.stdout)["discarded"])

    def test_set_status_rejects_inconsistent_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = str(Path(tmp) / "wiki")
            status = {"phase": "awaiting-review", "next_actor": "reviewer",
                      "active_actor": "none", "round": 1}
            disc = "```yaml\n" + session_review.render_status(status).rstrip() + "\n```"
            run_cli("snapshot-save", "--vault", vault, "--slug", "h", "--title", "T",
                    "--summary", "s", "--tags", "x", "--discussion", disc,
                    env=self.BUILTIN)
            bad = dict(status, phase="approved", next_actor="worker", blocking_count=3)
            r = run_cli("set-status", "--vault", vault, "--slug", "h",
                        "--status-json", json.dumps(bad), env=self.BUILTIN)
            self.assertEqual(r.returncode, 2, r.stdout)
            self.assertIn("blocking", r.stderr)

    def test_snapshot_load_accepts_json_flag(self):
        # SKILL.md and wiki_cli muscle-memory pass --json; it must be accepted.
        with tempfile.TemporaryDirectory() as tmp:
            vault = str(Path(tmp) / "wiki")
            run_cli("snapshot-save", "--vault", vault, "--slug", "h", "--title", "T",
                    "--summary", "s", "--tags", "x", "--discussion", "hi",
                    env=self.BUILTIN)
            r = run_cli("snapshot-load", "--vault", vault, "--slug", "h", "--json",
                        env=self.BUILTIN)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("hi", json.loads(r.stdout)["text"])

    def test_merge_reuses_existing_frontmatter_when_omitted(self):
        # nit #1: a status/feedback-only --merge should not require re-passing
        # --title/--summary/--tags.
        with tempfile.TemporaryDirectory() as tmp:
            vault = str(Path(tmp) / "wiki")
            run_cli("snapshot-save", "--vault", vault, "--slug", "h",
                    "--title", "Original Title", "--summary", "orig", "--tags", "a,b",
                    "--discussion", "FIRST", env=self.BUILTIN)
            r = run_cli("snapshot-save", "--vault", vault, "--slug", "h", "--merge",
                        "--decided", "ONLY DECIDED", env=self.BUILTIN)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = json.loads(run_cli("snapshot-load", "--vault", vault, "--slug", "h",
                                      env=self.BUILTIN).stdout)["text"]
            self.assertIn("title: Original Title", text)   # preserved
            self.assertIn("FIRST", text)                    # discussion kept
            self.assertIn("ONLY DECIDED", text)

    def test_merge_on_missing_snapshot_without_fields_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = str(Path(tmp) / "wiki")
            r = run_cli("snapshot-save", "--vault", vault, "--slug", "nope", "--merge",
                        "--decided", "x", env=self.BUILTIN)
            self.assertEqual(r.returncode, 2, r.stdout)

    def test_render_fenced_wraps_in_yaml_fence(self):
        r = run_cli("render", "--fenced", "--status-json",
                    '{"phase":"approved","next_actor":"worker","round":1}')
        self.assertTrue(r.stdout.startswith("```yaml\n"), r.stdout)
        self.assertIn("phase: \"approved\"", r.stdout)
        self.assertIn("```", r.stdout.rstrip()[-3:])

    def test_validate_complete_allows_self_turnkey_without_user_confirmed_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = str(Path(tmp) / "wiki")
            status = {"phase": "approved", "active_actor": "none",
                      "lock_since": None, "next_actor": "worker",
                      "target_mode": "diff", "target_ref": "b", "base_ref": "a",
                      "responding_to": "a", "round": 1, "flow_mode": "self",
                      "self_automation": "turnkey", "blocking_count": 0}
            disc = "```yaml\n" + session_review.render_status(status).rstrip() + "\n```"
            save = run_cli("snapshot-save", "--vault", vault, "--slug", "h",
                           "--title", "T", "--summary", "s", "--tags", "x",
                           "--discussion", disc, env=self.BUILTIN)
            self.assertEqual(save.returncode, 0, save.stderr)

            r = run_cli("validate-complete", "--vault", vault, "--slug", "h",
                        env=self.BUILTIN)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_self_locates_regardless_of_cwd(self):
        # Run from a foreign cwd; script must still work via __file__/--vault.
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cwd:
            vault = str(Path(tmp) / "wiki")
            r = run_cli("snapshot-save", "--vault", vault, "--slug", "h", "--title", "T",
                        "--summary", "s", "--tags", "x", "--discussion", "hi",
                        cwd=cwd, env=self.BUILTIN)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(vault) / "snapshot" / "SNAP-h.md").exists())

    @unittest.skipUnless(WIKI_CLI.exists(), "wiki_cli not present")
    def test_builtin_file_is_readable_by_wiki_cli(self):
        # Format parity (DEC-2026-06-18): a built-in-written snapshot must be a
        # valid wiki snapshot the real wiki_cli can load.
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "wiki"
            session_review.builtin_snapshot_save(
                vault, "h", {"title": "T", "summary": "s", "tags": ["x"]},
                {"discussion": "PARITY CHECK"}, merge=False)
            r = subprocess.run(
                [sys.executable, str(WIKI_CLI), "snapshot", "load", "h",
                 "--vault", str(vault), "--json"], text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("PARITY CHECK", json.loads(r.stdout)["text"])


if __name__ == "__main__":
    unittest.main()
