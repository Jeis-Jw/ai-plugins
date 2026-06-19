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
        with self.assertRaisesRegex(session_review.StatusError, "requires phase"):
            session_review.validate_complete(requested, user_confirmed=True)


if __name__ == "__main__":
    unittest.main()
