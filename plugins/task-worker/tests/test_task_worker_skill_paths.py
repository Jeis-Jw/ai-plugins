import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
ANCHOR = "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}"


class SkillPathPortabilityTests(unittest.TestCase):
    def test_runnable_snippets_use_plugin_root_anchor(self):
        offenders = []
        seen_anchor = False
        for path in [*PLUGIN.joinpath("skills").rglob("*.md"), *PLUGIN.joinpath("rules").rglob("*.md")]:
            in_fence = False
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if not in_fence:
                    continue
                seen_anchor = seen_anchor or ANCHOR in line
                if "plugins/task-worker/" in line or "CLAUDE_SKILL_DIR" in line:
                    offenders.append(f"{path.relative_to(PLUGIN)}:{number}: {line}")
        self.assertTrue(seen_anchor)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
