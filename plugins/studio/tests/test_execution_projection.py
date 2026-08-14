from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "scripts" / "execution_projection.py"
SPEC = importlib.util.spec_from_file_location("studio_execution_projection", SCRIPT)
assert SPEC and SPEC.loader
projection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(projection)


class ExecutionProjectionTests(unittest.TestCase):
    candidate = "candidate-1"

    def review(self, confirmed_at="2026-07-15T00:00:03Z"):
        return {
            "phase": "approved", "active_actor": "none", "lock_since": None,
            "next_actor": "worker", "target_mode": "diff", "target_nature": "code",
            "target_ref": "task/economics", "base_ref": "base", "responding_to": "finding-1",
            "round": 2, "round_type": "confirm", "flow_mode": "self",
            "self_automation": "turnkey", "recording_mode": "fast",
            "review_strength": "hard", "blocking_count": 0, "lease_id": "lease-1",
            "reviewer_ref": "agent-1", "reviewed_ref": self.candidate,
            "scope_digest": "sha256:" + "8" * 64,
            "finding_digest": "sha256:" + "7" * 64,
            "lease_started_at": "2026-07-14T23:59:00Z", "lease_updated_at": confirmed_at,
            "lease_target_ref": "task/economics", "lease_base_ref": "base",
            "lease_risk": "hard", "lease_expires_round": 4, "fresh_required": False,
            "fresh_fallback_reason": "episode_start", "fresh_count": 1, "reuse_count": 1,
        }

    @staticmethod
    def attempt(result="pass", started="2026-07-15T00:00:04Z",
                finished="2026-07-15T00:00:05Z"):
        return {
            "receipt_ref": {"receipt_id": "receipt-1", "digest": "sha256:" + "1" * 64},
            "evidence_ref": (
                {"evidence_id": "evidence-1", "digest": "sha256:" + "2" * 64}
                if result == "pass" else None
            ),
            "result": result, "started_at": started, "finished_at": finished,
        }

    def qa(self, attempts=None, result="pass"):
        value = {
            "schema": projection.QA_SCHEMA, "candidate_ref": self.candidate,
            "source_tree_digest": "sha256:" + "3" * 64,
            "criteria_digest": "sha256:" + "4" * 64,
            "attempts": attempts if attempts is not None else [self.attempt()],
            "result": result,
        }
        value["digest"] = projection.instance_digest(value)
        return value

    def project(self, review, qa, reviewer="agent-1"):
        return projection.project_final_candidate(
            review, {"final_qa": {"canonical_refs": True}}, reviewer,
            task_worker_projector=lambda request: qa,
        )

    def test_same_reviewer_confirmation_then_one_fresh_final_qa_accepts(self):
        accepted = self.project(self.review(), self.qa())
        self.assertEqual("accept", accepted["action"])
        self.assertEqual(projection.instance_digest(accepted), accepted["digest"])

        with self.assertRaisesRegex(ValueError, "original addressable reviewer"):
            self.project(self.review(), self.qa(), "another-agent")
        with self.assertRaisesRegex(ValueError, "complete canonical"):
            self.project({"phase": "approved", "reviewed_ref": self.candidate}, self.qa())

        with self.assertRaises(TypeError):
            projection.project_final_candidate(self.review(), self.qa(), "agent-1")

    def test_qa_failure_after_confirmation_requires_reconfirmation(self):
        failed_after = self.attempt(
            "fail", started="2026-07-15T00:00:04Z", finished="2026-07-15T00:00:05Z",
        )
        qa = self.qa([failed_after], result="fail")
        result = self.project(self.review(), qa)
        self.assertEqual("review-reconfirmation-required", result["reason"])

        failed_before = self.attempt(
            "fail", started="2026-07-15T00:00:01Z", finished="2026-07-15T00:00:02Z",
        )
        passed = self.attempt()
        accepted = self.project(self.review(), self.qa([failed_before, passed]))
        self.assertEqual("accept", accepted["action"])

    def test_studio_projection_imports_in_standalone_installed_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            standalone = Path(tmp, "execution_projection.py")
            standalone.write_bytes(SCRIPT.read_bytes())
            spec = importlib.util.spec_from_file_location("standalone_studio_projection", standalone)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        accepted = module.project_final_candidate(
            self.review(), {"final_qa": {"canonical_refs": True}}, "agent-1",
            task_worker_projector=lambda request: self.qa(),
        )
        self.assertEqual("accept", accepted["action"])


if __name__ == "__main__":
    unittest.main()
