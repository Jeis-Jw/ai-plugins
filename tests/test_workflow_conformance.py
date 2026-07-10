import importlib.util
import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RECEIPT_FIELDS = {
    "schema", "emitter", "workflow", "run_id", "started_at", "finished_at",
    "elapsed_ms", "tokens", "token_coverage", "counters", "quality",
}
PLUGINS = ("task-github", "session-review", "studio")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class WorkflowReceiptConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task_github = load_module(
            "task_github_definition_artifact",
            REPO / "plugins/task-github/scripts/definition_artifact.py",
        )
        cls.session_review = load_module(
            "session_review_status",
            REPO / "plugins/session-review/scripts/session_review.py",
        )
        cls.studio = load_module(
            "studio_runtime",
            REPO / "plugins/studio/scripts/studio.py",
        )

    def assert_receipt(self, receipt):
        self.assertEqual(set(receipt), RECEIPT_FIELDS)
        self.assertEqual(receipt["schema"], "workflow-receipt/v1")
        self.assertIsInstance(receipt["elapsed_ms"], int)
        self.assertGreaterEqual(receipt["elapsed_ms"], 0)
        if receipt["tokens"] is None:
            self.assertEqual(receipt["token_coverage"], "unavailable")
        else:
            self.assertIsInstance(receipt["tokens"], int)
            self.assertGreaterEqual(receipt["tokens"], 0)
            self.assertNotEqual(receipt["token_coverage"], "unavailable")
        self.assertIsInstance(receipt["counters"], dict)
        self.assertIsInstance(receipt["quality"], dict)

    def test_three_emitters_share_schema_v1_and_null_token_semantics(self):
        task_receipt = self.task_github.build_receipt({
            "schema": self.task_github.RUN_SCHEMA,
            "status": "closed",
            "run_id": "task-60",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:00:01Z",
        })
        review_receipt = self.session_review.receipt_from_status(
            {}, run_id="review-60", started_at="2026-07-10T00:00:00Z",
            finished_at="2026-07-10T00:00:01Z",
        )
        studio_receipt = {
            "schema": "workflow-receipt/v1",
            "emitter": "studio",
            "workflow": "studio-pairing",
            "run_id": "studio-60",
            "started_at": "2026-07-10T00:00:00.000Z",
            "finished_at": "2026-07-10T00:00:01.000Z",
            "elapsed_ms": 1000,
            "tokens": 12,
            "token_coverage": "exact",
            "counters": {"rounds": 1},
            "quality": {"alive": True},
        }
        self.assertEqual(self.studio.workflow_receipt_problems(studio_receipt), [])

        for receipt in (task_receipt, review_receipt, studio_receipt):
            with self.subTest(emitter=receipt["emitter"]):
                self.assert_receipt(receipt)

    def test_central_marketplaces_match_the_three_plugin_manifests(self):
        claude_entries = {
            item["name"]: item for item in read_json(REPO / ".claude-plugin/marketplace.json")["plugins"]
        }
        codex_entries = {
            item["name"]: item for item in read_json(REPO / ".agents/plugins/marketplace.json")["plugins"]
        }
        for name in PLUGINS:
            with self.subTest(plugin=name):
                plugin = REPO / "plugins" / name
                claude = read_json(plugin / ".claude-plugin/plugin.json")
                codex = read_json(plugin / ".codex-plugin/plugin.json")
                self.assertEqual(claude_entries[name]["version"], claude["version"])
                self.assertEqual(claude_entries[name]["description"], claude["description"])
                self.assertEqual(codex_entries[name]["version"], codex["version"])
                self.assertEqual(codex_entries[name]["description"], codex["description"])


if __name__ == "__main__":
    unittest.main()
