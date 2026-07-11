"""Wiki skill markdown must resolve its CLI path portably (cache install + Codex).

Regression guard for v0.19.2: `${CLAUDE_SKILL_DIR}` is unset in a marketplace cache
install and on Codex, so `${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py` collapsed to
`/scripts/wiki_cli.py` and every wiki call died with "path not found". Runnable
snippets must resolve through `${WIKI_MARKDOWN_ROOT:-$CLAUDE_PLUGIN_ROOT}` instead
(the same fix task-github shipped in v0.16.0). Prose that *names* the anti-pattern
to warn against it is exempt — only fenced code is scanned.
"""

import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = PLUGIN_ROOT / "skills"
FORBIDDEN = "CLAUDE_SKILL_DIR"
ANCHOR = "${WIKI_MARKDOWN_ROOT:-$CLAUDE_PLUGIN_ROOT}"


def _fenced_code_lines(text):
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield i, line


class SkillPathPortabilityTests(unittest.TestCase):
    def test_no_claude_only_skill_dir_in_runnable_snippets(self):
        offenders = []
        for path in SKILLS_DIR.rglob("*.md"):
            for i, line in _fenced_code_lines(path.read_text(encoding="utf-8")):
                if FORBIDDEN in line:
                    offenders.append(f"{path.relative_to(PLUGIN_ROOT)}:{i}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            f"non-portable wiki CLI paths (use {ANCHOR}):\n" + "\n".join(offenders),
        )

    def test_anchor_is_actually_used(self):
        self.assertTrue(
            any(ANCHOR in p.read_text(encoding="utf-8") for p in SKILLS_DIR.rglob("*.md")),
            "expected the portable resolution anchor to appear in wiki skill markdown",
        )


if __name__ == "__main__":
    unittest.main()
