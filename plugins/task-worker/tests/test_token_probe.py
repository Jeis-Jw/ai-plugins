import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


token_probe = load_module("task_worker_token_probe", PLUGIN / "scripts" / "token_probe.py")

SESSION = "11111111-2222-3333-4444-555555555555"


def usage_line(uuid, input_tokens, output_tokens, cache_creation, cache_read):
    return json.dumps({
        "uuid": uuid,
        "message": {"usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        }},
    })


def write_fixture(root: Path) -> None:
    """Main session (2 usage messages, one duplicated line) + 2 subagents (one duplicated)."""
    slug = root / "-Users-x-proj"
    subagents = slug / SESSION / "subagents"
    subagents.mkdir(parents=True)
    main_lines = [
        json.dumps({"uuid": "u0", "type": "user", "message": {"role": "user"}}),  # no usage — skipped
        usage_line("u1", 100, 10, 5, 1),
        usage_line("u2", 200, 20, 0, 2),
        usage_line("u2", 200, 20, 0, 2),  # duplicate uuid — must count once
    ]
    (slug / f"{SESSION}.jsonl").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
    (subagents / "agent-a1.jsonl").write_text(usage_line("s1", 30, 3, 0, 0) + "\n", encoding="utf-8")
    a2 = usage_line("s2", 40, 4, 2, 0)
    (subagents / "agent-a2.jsonl").write_text(a2 + "\n" + a2 + "\n", encoding="utf-8")


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write_fixture(self.root)

    def test_exact_sum_with_dedup_and_agents(self):
        result = token_probe.probe(SESSION, ["a1", "a2"], self.root)
        self.assertEqual(result["token_coverage"], "exact")
        self.assertEqual(result["tokens"], 417)  # 116 + 222 + 33 + 46, duplicates excluded
        self.assertEqual(result["breakdown"], {
            "input": 370, "output": 37, "cache_creation": 7, "cache_read": 3,
        })
        self.assertEqual(result["agents"], [
            {"agent_id": "a1", "tokens": 33},
            {"agent_id": "a2", "tokens": 46},
        ])
        self.assertEqual(result["source"], "claude-code-session-jsonl")

    def test_missing_subagent_forbids_partial_sum(self):
        result = token_probe.probe(SESSION, ["a1", "a2", "a3"], self.root)
        self.assertIsNone(result["tokens"])
        self.assertEqual(result["token_coverage"], "unavailable")
        self.assertIsNone(result["breakdown"])
        self.assertEqual(result["agents"], [])

    def test_missing_projects_root_degrades_the_same_way(self):
        result = token_probe.probe(SESSION, [], self.root / "absent")
        self.assertIsNone(result["tokens"])
        self.assertEqual(result["token_coverage"], "unavailable")

    def test_unparsable_main_file_is_unavailable(self):
        main = next(self.root.glob(f"*/{SESSION}.jsonl"))
        main.write_text("not json\n", encoding="utf-8")
        result = token_probe.probe(SESSION, [], self.root)
        self.assertIsNone(result["tokens"])
        self.assertEqual(result["token_coverage"], "unavailable")

    def test_cli_exits_zero_on_unavailable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = token_probe.main([
                "probe", "--session-id", SESSION, "--agent-id", "a3",
                "--projects-root", str(self.root), "--json",
            ])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIsNone(payload["tokens"])
        self.assertEqual(payload["token_coverage"], "unavailable")


def receipt(run_id, workflow, tokens):
    return {
        "schema": "workflow-receipt/v1", "emitter": workflow, "workflow": workflow,
        "run_id": run_id, "started_at": "2026-07-30T00:00:00Z",
        "finished_at": "2026-07-30T00:00:01Z", "elapsed_ms": 1000,
        "tokens": tokens,
        "token_coverage": "unavailable" if tokens is None else "exact",
        "counters": {}, "quality": {},
    }


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)

    def write(self, name, payload):
        (self.store / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_all_null_store_yields_zero_coverage_and_null_total(self):
        self.write("run-1.json", receipt("run-1", "task-worker", None))
        self.write("run-2.json", receipt("run-2", "session-review", None))
        result = token_probe.aggregate(self.store)
        self.assertEqual(result["runs"], 2)
        self.assertEqual(result["measured_runs"], 0)
        self.assertEqual(result["coverage_ratio"], 0.0)
        self.assertIsNone(result["tokens_total"])
        self.assertIsNone(result["measured_tokens_subtotal"])

    def test_mixed_store_sums_measured_and_groups_by_workflow(self):
        self.write("run-1.json", receipt("run-1", "task-worker", 100))
        self.write("run-2.json", receipt("run-2", "task-worker", None))
        self.write("run-3.json", receipt("run-3", "session-review", 50))
        self.write("junk.json", {"schema": "other/v1"})  # ignored
        result = token_probe.aggregate(self.store)
        self.assertEqual(result["runs"], 3)
        self.assertEqual(result["measured_runs"], 2)
        self.assertEqual(result["coverage_ratio"], 2 / 3)
        self.assertIsNone(result["tokens_total"])
        self.assertEqual(result["measured_tokens_subtotal"], 150)
        self.assertEqual(result["by_workflow"]["task-worker"], {
            "runs": 2, "measured_runs": 1, "coverage_ratio": 0.5,
            "tokens_total": None, "measured_tokens_subtotal": 100,
        })
        self.assertEqual(result["by_workflow"]["session-review"], {
            "runs": 1, "measured_runs": 1, "coverage_ratio": 1.0,
            "tokens_total": 50, "measured_tokens_subtotal": 50,
        })


if __name__ == "__main__":
    unittest.main()
