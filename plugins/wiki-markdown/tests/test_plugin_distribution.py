import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


def read_json(path):
    return json.loads(path.read_text())


class PluginDistributionTests(unittest.TestCase):
    def test_wiki_markdown_exposes_wiki_and_agent_policy_skills_to_codex(self):
        manifest = read_json(REPO / "plugins" / "wiki-markdown" / ".codex-plugin" / "plugin.json")
        skills_root = REPO / "plugins" / "wiki-markdown" / manifest["skills"]

        self.assertTrue((skills_root / "wiki" / "SKILL.md").exists())
        self.assertTrue((skills_root / "agent-policy" / "SKILL.md").exists())

    def test_task_github_has_codex_manifest_for_skill_discovery(self):
        manifest = read_json(REPO / "plugins" / "task-github" / ".codex-plugin" / "plugin.json")

        self.assertEqual(manifest["name"], "task-github")
        self.assertEqual(manifest["skills"], "./skills/")

    def test_claude_codex_and_marketplace_versions_are_aligned(self):
        claude_marketplace = read_json(REPO / ".claude-plugin" / "marketplace.json")
        marketplace_versions = {
            plugin["name"]: plugin["version"]
            for plugin in claude_marketplace["plugins"]
        }

        for name in ("wiki-markdown", "task-github"):
            plugin_root = REPO / "plugins" / name
            claude = read_json(plugin_root / ".claude-plugin" / "plugin.json")
            codex = read_json(plugin_root / ".codex-plugin" / "plugin.json")

            self.assertEqual(claude["version"], codex["version"])
            self.assertEqual(claude["version"], marketplace_versions[name])


if __name__ == "__main__":
    unittest.main()
