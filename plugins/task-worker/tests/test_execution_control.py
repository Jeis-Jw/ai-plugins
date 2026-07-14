import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TASK_WORKER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_WORKER / "scripts"))

import execution_control as control  # noqa: E402


class CanonicalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract_path = Path(os.environ.get(
            "STUDIO_VERIFICATION_CONTRACT",
            TASK_WORKER.parents[1] / "tests" / "fixtures" / "studio-verification-contract-v1.json",
        ))
        if not cls.contract_path.is_file():
            raise unittest.SkipTest(f"canonical fixture unavailable: {cls.contract_path}")
        cls.contract = control.load_contract(cls.contract_path)

    def test_exact_contract_digest(self):
        self.assertEqual(self.contract["digest"], control.CONTRACT_DIGEST)
        self.assertEqual(control.instance_digest(self.contract), control.CONTRACT_DIGEST)

    def test_all_canonical_golden_cases(self):
        for case in self.contract["golden_cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    control.evaluate_request(case["input"], self.contract),
                    case["expected"],
                )

    def _profile(self, **overrides):
        profile = {
            "schema": "command-profile/v1",
            "profile_id": "python:unit",
            "executable": "python3",
            "args": ["-m", "unittest", "plugins/task-worker/tests"],
            "forbidden_args": ["--all", "*full-qa*"],
            "cwd_scope": "repository",
            "environment_inputs": ["PYTHONPATH"],
            "required_capabilities": [],
            "output_contract": {"exit_code": 0},
            "fresh_policy": "reusable",
        }
        profile.update(overrides)
        profile["digest"] = control.instance_digest(profile)
        return profile

    def test_profile_and_impact_policy_fail_closed(self):
        profile = self._profile()
        rules = [{
            "rule_id": "worker-tests",
            "path_globs": ["plugins/task-worker/**"],
            "qa_modes": ["delta", "full"],
            "command_profile_ids": [profile["profile_id"]],
            "purposes": ["delta", "integration-full"],
            "full_qa_reason_codes": ["integration-head-created"],
        }]
        plan = control.select_execution(
            profiles={profile["profile_id"]: profile}, impact_rules=rules,
            changed_paths=["plugins/task-worker/scripts/execution_control.py"],
            qa_mode="delta", profile_id=profile["profile_id"], purpose="delta",
        )
        self.assertEqual(plan["argv"], [profile["executable"], *profile["args"]])
        permit = dict(self.contract["golden_cases"][0]["input"]["permit"])
        permit.update({
            "qa_mode": plan["qa_mode"],
            "purpose": "delta",
            "command_profile_id": plan["profile_id"],
            "command_digest": plan["command_digest"],
            "impact_set": plan["impact_set"],
        })
        permit["digest"] = control.instance_digest(permit)
        control.validate_permit_policy(permit, plan)
        permit["command_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(control.ExecutionControlError) as mismatch:
            control.validate_permit_policy(permit, plan)
        self.assertEqual(mismatch.exception.code, "permit_policy_mismatch")

        with self.assertRaisesRegex(control.ExecutionControlError, "machine-readable") as full:
            control.select_execution(
                profiles={profile["profile_id"]: profile}, impact_rules=rules,
                changed_paths=["plugins/task-worker/scripts/execution_control.py"],
                qa_mode="full", profile_id=profile["profile_id"], purpose="integration-full",
            )
        self.assertEqual(full.exception.code, "full_qa_reason_required")

        with self.assertRaises(control.ExecutionControlError) as forbidden:
            control.select_execution(
                profiles={profile["profile_id"]: profile}, impact_rules=rules,
                changed_paths=["plugins/task-worker/tests/test_execution_control.py"],
                qa_mode="delta", profile_id=profile["profile_id"], purpose="delta",
                argv=[profile["executable"], *profile["args"], "--all"],
            )
        self.assertEqual(forbidden.exception.code, "forbidden_argv")

    def test_loaders_validate_profile_digest_and_rule_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles_path = Path(tmp, "profiles.json")
            rules_path = Path(tmp, "rules.json")
            profile = self._profile()
            profiles_path.write_text(json.dumps({"profiles": [profile]}), encoding="utf-8")
            rules_path.write_text(json.dumps({
                "schema": "impact-rule-set/v1",
                "rules": [{
                    "rule_id": "worker", "path_globs": ["plugins/task-worker/**"],
                    "qa_modes": ["delta"], "command_profile_ids": [profile["profile_id"]],
                }],
            }), encoding="utf-8")
            profiles = control.load_command_profiles(profiles_path, self.contract)
            rules = control.load_impact_rules(rules_path)
        self.assertEqual(list(profiles), ["python:unit"])
        self.assertEqual(rules[0]["rule_id"], "worker")

    def test_cli_claim_enforces_profile_and_impact_before_atomic_claim(self):
        profile = self._profile()
        permit = dict(self.contract["golden_cases"][0]["input"]["permit"])
        permit.update({
            "command_profile_id": profile["profile_id"],
            "command_digest": control.command_digest(profile),
            "impact_set": ["plugins/task-worker/scripts/execution_control.py"],
        })
        permit["digest"] = control.instance_digest(permit)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles = root / "profiles.json"
            rules = root / "rules.json"
            permit_path = root / "permit.json"
            profiles.write_text(json.dumps({"profiles": [profile]}), encoding="utf-8")
            rules.write_text(json.dumps([{
                "rule_id": "worker", "path_globs": ["plugins/task-worker/**"],
                "qa_modes": ["delta"], "command_profile_ids": [profile["profile_id"]],
                "purposes": ["delta"],
            }]), encoding="utf-8")
            permit_path.write_text(json.dumps(permit), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                "execution-claim", "--permit", str(permit_path),
                "--profiles", str(profiles), "--impact-rules", str(rules),
                "--changed-path", "plugins/task-worker/scripts/execution_control.py",
                "--claimed-by", "test-worker", "--state-root", str(root / "state"),
            ], env={**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["decision"]["action"], "claimed")

    def test_atomic_claim_rejects_duplicate_and_enforces_run_cap(self):
        permit = self.contract["golden_cases"][0]["input"]["permit"]
        with tempfile.TemporaryDirectory() as tmp:
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker-A", contract=self.contract,
                now="2026-07-15T00:00:00Z",
            )
            duplicate = control.claim_execution(
                permit, tmp, claimed_by="worker-B", contract=self.contract,
                now="2026-07-15T00:00:01Z",
            )
        self.assertEqual(claimed["action"], "claimed")
        self.assertEqual(duplicate["error"]["code"], "duplicate_active")

    def test_completion_binds_immutable_receipt_and_reuses_stored_evidence(self):
        case = next(case for case in self.contract["golden_cases"] if case["id"] == "success-reuse")
        permit = case["input"]["permit"]
        evidence = dict(case["input"]["evidence"])
        receipt = {
            "schema": "command-receipt/v1",
            "receipt_id": "receipt-complete",
            "permit_id": permit["permit_id"],
            "claim_id": "placeholder",
            "profile_id": permit["command_profile_id"],
            "purpose": permit["purpose"],
            "target": permit["target"],
            "head": permit["head"],
            "command_digest": permit["command_digest"],
            "environment_digest": permit["environment_digest"],
            "tool_version": permit["tool_version"],
            "fresh_requirement_id": permit["fresh_requirement_id"],
            "started_at": "2026-07-15T00:00:00Z",
            "finished_at": "2026-07-15T00:00:01Z",
            "exit_code": 0,
            "result": "pass",
            "output_digest": "sha256:" + "b" * 64,
            "tokens": 10,
            "token_coverage": "exact",
            "executor": "native",
            "spend_consumption_refs": [],
            "external_mutation_receipt_refs": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            claimed = control.claim_execution(permit, tmp, claimed_by="worker", contract=self.contract)
            receipt["claim_id"] = claimed["claim"]["claim_id"]
            receipt["digest"] = control.instance_digest(receipt)
            evidence["source_receipt_id"] = receipt["receipt_id"]
            evidence["digest"] = control.instance_digest(evidence)
            completed = control.complete_execution(
                permit, receipt["claim_id"], receipt, tmp,
                evidence=evidence, contract=self.contract,
            )
            reused = control.claim_execution(permit, tmp, claimed_by="other", contract=self.contract)

        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(completed["evidence_refs"], [evidence["evidence_id"]])
        self.assertEqual(reused["action"], "reuse-evidence")
        self.assertFalse(reused["physical_run_started"])

    def test_capability_probe_and_paid_mutation_are_claimed_once(self):
        capability_case = next(
            case for case in self.contract["golden_cases"]
            if case["id"] == "unavailable-capability-cache"
        )
        spend_case = next(
            case for case in self.contract["golden_cases"]
            if case["id"] == "atomic-spend-consumption"
        )
        preflight = {
            "schema": "preflight-receipt/v1",
            "receipt_id": "preflight-render-worker",
            "adapter_id": "render-worker",
            "target_ref": "lightning-pay-worker",
            "environment_digest": "sha256:" + "1" * 64,
            "manifest_digest": "sha256:" + "2" * 64,
            "checked_keys": ["provider", "resource_kind", "scope"],
            "missing_keys": [],
            "condition_failures": [],
            "topology_drift": [],
            "result": "pass",
            "checked_at": "2026-07-15T00:00:00Z",
        }
        preflight["digest"] = control.instance_digest(preflight)
        with tempfile.TemporaryDirectory() as tmp:
            first = control.capability_plan(
                capability_case["input"]["mission_id"],
                capability_case["input"]["required_capabilities"],
                capability_case["input"]["environment_digest"], tmp,
            )
            pending = control.capability_plan(
                capability_case["input"]["mission_id"],
                capability_case["input"]["required_capabilities"],
                capability_case["input"]["environment_digest"], tmp,
            )
            control.record_capability_snapshot(
                capability_case["input"]["snapshot"], tmp, contract=self.contract,
            )
            blocked = control.capability_plan(
                capability_case["input"]["mission_id"],
                capability_case["input"]["required_capabilities"],
                capability_case["input"]["environment_digest"], tmp,
            )
            spend = control.claim_spend_consumption(
                spend_case["input"]["authorization"], spend_case["input"]["mutation_request"], tmp,
                preflight_receipt=preflight, contract=self.contract, now="2026-07-15T00:00:01Z",
            )
            exhausted = control.claim_spend_consumption(
                spend_case["input"]["authorization"], spend_case["input"]["mutation_request"], tmp,
                preflight_receipt=preflight, contract=self.contract, now="2026-07-15T00:00:02Z",
            )
            consumption = spend["consumption"]
            mutation = spend_case["input"]["mutation_request"]
            mutation_receipt = {
                "schema": "external-mutation-receipt/v1",
                "mutation_id": "mutation-applied-1",
                "mutation_request_ref": consumption["mutation_request_ref"],
                "mutation_request_digest": consumption["mutation_request_digest"],
                "provider": mutation["provider"],
                "operation": mutation["operation"],
                "target_ref": mutation["target_ref"],
                "authorization_id": consumption["authorization_id"],
                "authorization_digest": consumption["authorization_digest"],
                "spend_consumption_ref": consumption["consumption_id"],
                "spend_consumption_digest": consumption["digest"],
                "preflight_receipt_id": preflight["receipt_id"],
                "result": "applied",
                "started_at": "2026-07-15T00:00:02Z",
                "finished_at": "2026-07-15T00:00:03Z",
                "rollback_ref": None,
            }
            mutation_receipt["digest"] = control.instance_digest(mutation_receipt)
            mutation_status = control.record_external_mutation(
                consumption, mutation_receipt, tmp, contract=self.contract,
            )

        self.assertEqual(first["action"], "probe-capability")
        self.assertEqual(pending["action"], "probe-in-progress")
        self.assertEqual(blocked["action"], "block-dispatch")
        self.assertEqual(spend["action"], "claim-spend-consumption")
        self.assertEqual(exhausted["error"]["code"], "external_spend_quota_exhausted")
        self.assertEqual(mutation_status["claim_state"], "consumed")

    def test_null_token_policy_is_fail_closed_or_report_only(self):
        receipt = next(
            case["input"]["receipt"] for case in self.contract["golden_cases"]
            if case["id"] == "telemetry-pause"
        )
        paused = control.evaluate_request(
            {"telemetry_policy": "fail-closed", "receipt": receipt}, self.contract,
        )
        reported = control.evaluate_request(
            {"telemetry_policy": "report-only", "receipt": receipt}, self.contract,
        )
        self.assertEqual(paused["action"], "pause")
        self.assertEqual(reported["action"], "accept-report-only")
        self.assertIsNone(reported["tokens_counted"])


if __name__ == "__main__":
    unittest.main()
