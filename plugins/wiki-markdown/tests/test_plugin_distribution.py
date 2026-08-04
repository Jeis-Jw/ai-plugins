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

    def test_wiki_markdown_distribution_advertises_proactive_context_contract(self):
        plugin = REPO / "plugins" / "wiki-markdown"
        manifest = read_json(plugin / ".codex-plugin" / "plugin.json")
        skill = (plugin / "skills" / "wiki" / "SKILL.md").read_text()
        protocol = (plugin / "rules" / "knowledge-protocol.md").read_text()
        prompts = "\n".join(manifest["interface"]["defaultPrompt"])

        self.assertIn("Use proactively", skill)
        self.assertIn("Proactive durable-context contract", skill)
        self.assertIn("Cross-plugin durable-context 계약", protocol)
        self.assertIn("semantic milestone", prompts)
        self.assertNotIn("Scale capture to the gear", skill + protocol + prompts)
        self.assertNotIn("gear:micro", skill + protocol + prompts)

    def test_task_github_has_codex_manifest_for_skill_discovery(self):
        manifest = read_json(REPO / "plugins" / "task-github" / ".codex-plugin" / "plugin.json")

        self.assertEqual(manifest["name"], "task-github")
        self.assertEqual(manifest["skills"], "./skills/")

    def test_task_worker_exposes_provider_neutral_workflow_skills(self):
        manifest = read_json(REPO / "plugins" / "task-worker" / ".codex-plugin" / "plugin.json")
        skills_root = REPO / "plugins" / "task-worker" / manifest["skills"]

        self.assertEqual(manifest["name"], "task-worker")
        for skill_name in ("define", "start", "run", "verify", "done", "status", "orchestrate"):
            self.assertTrue((skills_root / skill_name / "SKILL.md").exists(), skill_name)

    def test_session_review_exposes_four_skills_and_helper_to_codex(self):
        manifest = read_json(REPO / "plugins" / "session-review" / ".codex-plugin" / "plugin.json")
        skills_root = REPO / "plugins" / "session-review" / manifest["skills"]

        self.assertEqual(manifest["name"], "session-review")
        self.assertEqual(manifest["skills"], "./skills/")
        for skill_name in ("request-review", "address-feedback", "review", "complete"):
            self.assertTrue((skills_root / skill_name / "SKILL.md").exists(), skill_name)
        self.assertTrue((REPO / "plugins" / "session-review" / "scripts" / "session_review.py").exists())

    def test_claude_codex_and_marketplace_versions_are_aligned(self):
        claude_marketplace = read_json(REPO / ".claude-plugin" / "marketplace.json")
        marketplace_versions = {
            plugin["name"]: plugin["version"]
            for plugin in claude_marketplace["plugins"]
        }
        codex_marketplace = read_json(REPO / ".agents" / "plugins" / "marketplace.json")
        codex_marketplace_entries = {
            plugin["name"]: plugin for plugin in codex_marketplace["plugins"]
        }

        for name in ("wiki-markdown", "task-github", "session-review", "studio", "task-worker"):
            plugin_root = REPO / "plugins" / name
            claude = read_json(plugin_root / ".claude-plugin" / "plugin.json")
            codex = read_json(plugin_root / ".codex-plugin" / "plugin.json")

            self.assertEqual(claude["version"], codex["version"])
            self.assertEqual(claude["version"], marketplace_versions[name])
            self.assertIn(name, codex_marketplace_entries)
            self.assertEqual(claude["version"], codex_marketplace_entries[name]["version"])

    def test_studio_is_host_native_with_only_a_spawn_policy_helper(self):
        studio = REPO / "plugins" / "studio"
        producer = (studio / "skills" / "producer" / "SKILL.md").read_text()

        self.assertIn("spawn_agent", producer)
        self.assertIn("followup_task", producer)
        self.assertIn("Agent", producer)
        self.assertIn("SendMessage", producer)
        self.assertIn("scripts/studio_config.py", producer)
        self.assertIn("STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT", producer)
        self.assertNotIn("CLAUDE_SKILL_DIR", producer)
        execute = (studio / "skills" / "execute" / "SKILL.md").read_text()
        self.assertIn("root Producer", execute)
        self.assertIn("--kind work", execute)
        self.assertIn("nested subagent 생성", execute)
        self.assertTrue((studio / "rules" / "casting.md").exists())
        self.assertTrue((studio / "crew" / "planner.md").exists())
        self.assertTrue((studio / "scripts" / "studio_config.py").exists())
        self.assertFalse((studio / "scripts" / "studio.py").exists())
        self.assertFalse((studio / "broker" / "brainstorm.workflow.js").exists())
        self.assertFalse((studio / "contracts" / "studio-verification-contract-v1.json").exists())
        for role in (studio / "crew").glob("*.md"):
            text = role.read_text()
            with self.subTest(role=role.name):
                self.assertNotIn("requested_tools", text)
                self.assertNotIn("activation:", text)


if __name__ == "__main__":
    unittest.main()
