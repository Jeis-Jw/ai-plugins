import importlib.util
import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RECEIPT_FIELDS = {
    "schema", "emitter", "workflow", "run_id", "started_at", "finished_at",
    "elapsed_ms", "tokens", "token_coverage", "counters", "quality",
}
PLUGINS = ("task-github", "session-review", "studio", "task-worker")


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
        cls.task_worker = load_module(
            "task_worker_definition_artifact",
            REPO / "plugins/task-worker/scripts/definition_artifact.py",
        )
        cls.session_review = load_module(
            "session_review_status",
            REPO / "plugins/session-review/scripts/session_review.py",
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
            self.assertEqual(receipt["token_coverage"], "exact")
        self.assertIsInstance(receipt["counters"], dict)
        self.assertIsInstance(receipt["quality"], dict)

    def test_runtime_emitters_share_schema_v1_and_null_token_semantics(self):
        worker_state = {
            "schema": self.task_worker.RUN_SCHEMA,
            "status": "closed",
            "run_id": "worker-60",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:00:01Z",
        }
        worker_receipts = (
            self.task_worker.build_receipt(worker_state),
            self.task_worker.build_receipt(worker_state, tokens=6),
        )
        review_receipts = (
            self.session_review.receipt_from_status(
                {}, run_id="review-60", started_at="2026-07-10T00:00:00Z",
                finished_at="2026-07-10T00:00:01Z",
            ),
            self.session_review.receipt_from_status(
                {}, run_id="review-60", started_at="2026-07-10T00:00:00Z",
                finished_at="2026-07-10T00:00:01Z", tokens=8,
            ),
        )
        for receipt in (*worker_receipts, *review_receipts):
            with self.subTest(emitter=receipt["emitter"], tokens=receipt["tokens"]):
                self.assert_receipt(receipt)

    def test_central_marketplaces_match_workflow_plugin_manifests(self):
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
