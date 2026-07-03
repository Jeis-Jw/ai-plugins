"""Skill/rule markdown must resolve script paths portably (cache install + Codex).

Regression guard for the v0.16.0 portability fix: repo-vendored `plugins/task-github/...`
paths and the Claude-only `CLAUDE_SKILL_DIR` don't exist in a cache install or on Codex,
where they caused silent skips of gate/ledger steps. Every script invocation must go
through `${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}` (workflow.md §0).
"""

import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [PLUGIN_ROOT / "skills", PLUGIN_ROOT / "rules"]
FORBIDDEN = ("plugins/task-github/", "CLAUDE_SKILL_DIR")
ANCHOR = "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}"


def _md_files():
    for base in SCAN_DIRS:
        yield from base.rglob("*.md")


def _fenced_code_lines(text):
    """Yield (lineno, line) only for lines inside ``` fenced code blocks.

    Only runnable snippets matter for portability; prose that names the
    anti-pattern to explain it is exempt.
    """
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield i, line


class SkillPathPortabilityTests(unittest.TestCase):
    def test_no_vendored_or_claude_only_paths(self):
        offenders = []
        for path in _md_files():
            for i, line in _fenced_code_lines(path.read_text(encoding="utf-8")):
                for token in FORBIDDEN:
                    if token in line:
                        rel = path.relative_to(PLUGIN_ROOT)
                        offenders.append(f"{rel}:{i}: {token} -> {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "non-portable script paths (use ${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}):\n"
            + "\n".join(offenders),
        )

    def test_anchor_is_actually_used(self):
        # Sanity: the portable anchor exists somewhere, so the guard isn't vacuous.
        self.assertTrue(
            any(ANCHOR in p.read_text(encoding="utf-8") for p in _md_files()),
            "expected the portable resolution anchor to appear in skills/rules",
        )


if __name__ == "__main__":
    unittest.main()
