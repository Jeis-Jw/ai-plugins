import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "merge" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import closeout  # noqa: E402


class ParseLinkedIssueTests(unittest.TestCase):
    def test_closes(self):
        self.assertEqual(closeout.parse_linked_issue("Closes #42\n\nbody"), 42)

    def test_fixes_and_resolves_case_insensitive(self):
        self.assertEqual(closeout.parse_linked_issue("fixes #7"), 7)
        self.assertEqual(closeout.parse_linked_issue("RESOLVES #9"), 9)

    def test_first_wins(self):
        self.assertEqual(closeout.parse_linked_issue("Closes #1 and closes #2"), 1)

    def test_none_when_absent(self):
        self.assertIsNone(closeout.parse_linked_issue("no linkage here #notnum"))
        self.assertIsNone(closeout.parse_linked_issue(""))

    def test_ignores_bare_hash_without_keyword(self):
        self.assertIsNone(closeout.parse_linked_issue("see #15 for context"))


class ExtractTaskIdTests(unittest.TestCase):
    def test_ascii_slug(self):
        body = "## Wiki Context\nTASK-2026-06-19-105638-session-review-plugin\n"
        self.assertEqual(closeout.extract_task_id(body),
                         "TASK-2026-06-19-105638-session-review-plugin")

    def test_korean_slug_preserved(self):
        # The ASCII-only grep in the old SKILL truncated Korean slugs; we must not.
        tid = "TASK-2026-06-19-125723-wiki-markdown-운용-효율-개선-문서-오버헤드-감소"
        self.assertEqual(closeout.extract_task_id(f"root: {tid} (done)"), tid)

    def test_stops_at_markdown_bracket(self):
        self.assertEqual(closeout.extract_task_id("[[TASK-2026-06-19-120000-abc]]"),
                         "TASK-2026-06-19-120000-abc")

    def test_none_when_absent(self):
        self.assertIsNone(closeout.extract_task_id("no task here"))


class LabelsToRemoveTests(unittest.TestCase):
    def test_intersection_in_order(self):
        self.assertEqual(
            closeout.labels_to_remove(["gear:major", "changes-requested", "in-review"]),
            ["in-review", "changes-requested"])

    def test_preserves_non_state(self):
        self.assertEqual(closeout.labels_to_remove(["gear:micro", "bug"]), [])

    def test_empty(self):
        self.assertEqual(closeout.labels_to_remove([]), [])


if __name__ == "__main__":
    unittest.main()
