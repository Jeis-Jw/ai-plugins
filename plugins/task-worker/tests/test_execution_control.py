import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TASK_WORKER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_WORKER / "scripts"))

import execution_control as control  # noqa: E402


STUDIO_CONTROL_PATH = TASK_WORKER.parent / "studio" / "scripts" / "execution_control.py"
STUDIO_SPEC = importlib.util.spec_from_file_location("studio_execution_control", STUDIO_CONTROL_PATH)
studio_control = importlib.util.module_from_spec(STUDIO_SPEC)
assert STUDIO_SPEC.loader is not None
STUDIO_SPEC.loader.exec_module(studio_control)


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

    def test_cross_surface_command_and_physical_identity_golden_vector(self):
        command = self._command()
        expected_command_digest = "sha256:f627a1f81afaa6d418f18d1da598520ca34b81be72462d478c23e5c5fc996376"
        self.assertEqual(control.command_digest(command), expected_command_digest)
        self.assertEqual(studio_control.command_digest(command), expected_command_digest)

        permit = {
            "head": "abc1234",
            "command_digest": expected_command_digest,
            "environment_digest": "sha256:" + "c" * 64,
            "tool_version": "tool/1.0",
            "purpose": "delta",
            "fresh_requirement_id": "fresh-1",
            "target": "repository",
            "cycle_id": "cycle-A",
            "unit_id": "unit-A",
            "command_profile_id": "profile-A",
        }
        expected_physical_key = "sha256:a515fe2c20c0daa7454835789e0a1286c6ef93f7234f770a99cffc3742bf5a60"
        self.assertEqual(control.physical_identity(permit), expected_physical_key)
        self.assertEqual(studio_control.physical_key(permit), expected_physical_key)

        attribution_changed = {
            **permit,
            "target": "another-target",
            "cycle_id": "cycle-B",
            "unit_id": "unit-B",
            "command_profile_id": "profile-B",
        }
        self.assertEqual(control.physical_identity(attribution_changed), expected_physical_key)
        self.assertNotEqual(control.physical_identity({**permit, "purpose": "finding-delta"}), expected_physical_key)
        self.assertNotEqual(control.physical_identity({**permit, "fresh_requirement_id": "fresh-2"}), expected_physical_key)

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

    def _command(self, profile=None):
        profile = profile or self._profile()
        return {
            "executable": profile["executable"],
            "args": profile["args"],
            "cwd": "plugins/task-worker",
            "environment": {"PYTHONPATH": "plugins/task-worker"},
        }

    def _preflight(self, permit, mutation):
        value = {
            "schema": "preflight-receipt/v1",
            "receipt_id": "preflight-" + mutation["mutation_request_id"],
            "adapter_id": "provider-adapter",
            "target_ref": mutation["target_ref"],
            "environment_digest": permit["environment_digest"],
            "manifest_digest": "sha256:" + "2" * 64,
            "checked_keys": ["provider", "resource_kind", "scope"],
            "missing_keys": [],
            "condition_failures": [],
            "topology_drift": [],
            "result": "pass",
            "checked_at": "2026-07-15T00:00:00Z",
        }
        value["digest"] = control.instance_digest(value)
        return value

    def _mutation_permit(self, *, paid=True):
        permit = dict(self.contract["golden_cases"][0]["input"]["permit"])
        mutation = {
            "mutation_request_id": "mutation-worker-create" if paid else "mutation-free-label",
            "provider": "render" if paid else "github",
            "operation": "create" if paid else "label",
            "resource_kind": "background-worker" if paid else "issue-label",
            "target_ref": "lightning-pay-worker" if paid else "issue-67",
            "one_time_usd": 0,
            "monthly_usd": 7 if paid else 0,
        }
        mutation["digest"] = control.instance_digest(mutation)
        permit.update({
            "permit_id": "permit-paid-mutation" if paid else "permit-free-mutation",
            "purpose": "production-preflight",
            "fresh_requirement_id": "fresh-paid-1" if paid else "fresh-free-1",
            "mutation_request": mutation,
            "external_authorization_refs": ["AUTH-worker"] if paid else [],
        })
        permit["digest"] = control.instance_digest(permit)
        return permit, mutation

    def _authorization(self, permit, mutation):
        value = {
            "schema": "external-spend-authorization/v1",
            "authorization_id": "AUTH-worker",
            "mission_id": permit["mission_id"],
            "mutation_request_ref": mutation["mutation_request_id"],
            "mutation_request_digest": mutation["digest"],
            "provider": mutation["provider"],
            "resource_kind": mutation["resource_kind"],
            "scope": mutation["target_ref"],
            "one_time_usd": mutation["one_time_usd"],
            "monthly_usd": mutation["monthly_usd"],
            "max_occurrences": 1,
            "owner_approved": True,
            "approved_by": "owner",
            "approved_at": "2026-07-15T00:00:00Z",
            "expires_at": "2026-07-16T00:00:00Z",
        }
        value["digest"] = control.instance_digest(value)
        return value

    def _command_receipt(self, permit, claim_id, *, mutation_ref=None, consumption_ref=None):
        value = {
            "schema": "command-receipt/v1",
            "receipt_id": "receipt-" + permit["permit_id"],
            "permit_id": permit["permit_id"],
            "claim_id": claim_id,
            "profile_id": permit["command_profile_id"],
            "purpose": permit["purpose"],
            "target": permit["target"],
            "head": permit["head"],
            "command_digest": permit["command_digest"],
            "environment_digest": permit["environment_digest"],
            "tool_version": permit["tool_version"],
            "fresh_requirement_id": permit["fresh_requirement_id"],
            "started_at": "2026-07-15T00:00:01Z",
            "finished_at": "2026-07-15T00:00:02Z",
            "exit_code": 0,
            "result": "pass",
            "output_digest": "sha256:" + "b" * 64,
            "tokens": 1,
            "token_coverage": "exact",
            "executor": "native",
            "spend_consumption_refs": [consumption_ref] if consumption_ref else [],
            "external_mutation_receipt_refs": [mutation_ref] if mutation_ref else [],
        }
        value["digest"] = control.instance_digest(value)
        return value

    def _mutation_receipt(self, mutation, preflight, *, consumption=None):
        mutation_id = "applied-" + mutation["mutation_request_id"]
        final_consumption = None
        if consumption is not None:
            final_consumption = {
                **consumption,
                "claim_state": "consumed",
                "mutation_receipt_ref": mutation_id,
                "consumed_at": "2026-07-15T00:00:02Z",
            }
            final_consumption["digest"] = control.instance_digest(final_consumption)
        value = {
            "schema": "external-mutation-receipt/v1",
            "mutation_id": mutation_id,
            "mutation_request_ref": mutation["mutation_request_id"],
            "mutation_request_digest": mutation["digest"],
            "provider": mutation["provider"],
            "operation": mutation["operation"],
            "target_ref": mutation["target_ref"],
            "authorization_id": consumption["authorization_id"] if consumption else None,
            "authorization_digest": consumption["authorization_digest"] if consumption else None,
            "spend_consumption_ref": consumption["consumption_id"] if consumption else None,
            "spend_consumption_digest": final_consumption["digest"] if final_consumption else None,
            "preflight_receipt_id": preflight["receipt_id"],
            "result": "applied",
            "started_at": "2026-07-15T00:00:01Z",
            "finished_at": "2026-07-15T00:00:02Z",
            "rollback_ref": None,
        }
        value["digest"] = control.instance_digest(value)
        return value

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
            cwd="plugins/task-worker", environment={"PYTHONPATH": "plugins/task-worker"},
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
                cwd="plugins/task-worker", environment={"PYTHONPATH": "plugins/task-worker"},
            )
        self.assertEqual(full.exception.code, "full_qa_reason_required")

        with self.assertRaises(control.ExecutionControlError) as forbidden:
            control.select_execution(
                profiles={profile["profile_id"]: profile}, impact_rules=rules,
                changed_paths=["plugins/task-worker/tests/test_execution_control.py"],
                qa_mode="delta", profile_id=profile["profile_id"], purpose="delta",
                argv=[profile["executable"], *profile["args"], "--all"],
                cwd="plugins/task-worker", environment={"PYTHONPATH": "plugins/task-worker"},
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
            "command_digest": control.command_digest(self._command(profile)),
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
                "--cwd", "plugins/task-worker",
                "--environment", json.dumps({"PYTHONPATH": "plugins/task-worker"}),
                "--claimed-by", "test-worker", "--state-root", str(root / "state"),
            ], env={**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["decision"]["action"], "claimed")

    def test_cli_paid_mutation_requires_atomic_gate_and_completion_receipt(self):
        profile = self._profile()
        command = self._command(profile)
        permit, mutation = self._mutation_permit(paid=True)
        permit.update({
            "command_profile_id": profile["profile_id"],
            "command_digest": control.command_digest(command),
            "impact_set": ["plugins/task-worker/scripts/execution_control.py"],
        })
        permit["digest"] = control.instance_digest(permit)
        preflight = self._preflight(permit, mutation)
        authorization = self._authorization(permit, mutation)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "profiles": root / "profiles.json",
                "rules": root / "rules.json",
                "permit": root / "permit.json",
                "preflight": root / "preflight.json",
                "authorization": root / "authorization.json",
                "receipt": root / "receipt.json",
                "mutation_receipt": root / "mutation-receipt.json",
            }
            paths["profiles"].write_text(json.dumps({"profiles": [profile]}), encoding="utf-8")
            paths["rules"].write_text(json.dumps([{
                "rule_id": "worker", "path_globs": ["plugins/task-worker/**"],
                "qa_modes": ["delta"], "command_profile_ids": [profile["profile_id"]],
                "purposes": ["production-preflight"],
            }]), encoding="utf-8")
            for key, value in (
                ("permit", permit), ("preflight", preflight), ("authorization", authorization),
            ):
                paths[key].write_text(json.dumps(value), encoding="utf-8")
            claim_args = [
                sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                "execution-claim", "--permit", str(paths["permit"]),
                "--profiles", str(paths["profiles"]), "--impact-rules", str(paths["rules"]),
                "--changed-path", "plugins/task-worker/scripts/execution_control.py",
                "--cwd", command["cwd"], "--environment", json.dumps(command["environment"]),
                "--claimed-by", "test-worker", "--state-root", str(root / "state"),
            ]
            environment = {**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)}
            rejected = subprocess.run(
                claim_args, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(rejected.returncode, 2, rejected.stderr or rejected.stdout)
            self.assertEqual(json.loads(rejected.stdout)["error_code"], "preflight_required")

            claimed_result = subprocess.run(
                [*claim_args, "--preflight-receipt", str(paths["preflight"]),
                 "--authorization", str(paths["authorization"])],
                env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(claimed_result.returncode, 0, claimed_result.stderr or claimed_result.stdout)
            claimed = json.loads(claimed_result.stdout)["decision"]
            consumption = claimed["spend_consumption"]
            mutation_receipt = self._mutation_receipt(mutation, preflight, consumption=consumption)
            receipt = self._command_receipt(
                permit, claimed["claim"]["claim_id"], mutation_ref=mutation_receipt["mutation_id"],
                consumption_ref=consumption["consumption_id"],
            )
            paths["receipt"].write_text(json.dumps(receipt), encoding="utf-8")
            paths["mutation_receipt"].write_text(json.dumps(mutation_receipt), encoding="utf-8")
            complete_args = [
                sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                "execution-complete", "--permit", str(paths["permit"]),
                "--claim-id", claimed["claim"]["claim_id"], "--receipt", str(paths["receipt"]),
                "--state-root", str(root / "state"),
            ]
            incomplete = subprocess.run(
                complete_args, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(incomplete.returncode, 2, incomplete.stderr or incomplete.stdout)
            self.assertEqual(
                json.loads(incomplete.stdout)["error_code"], "external_mutation_receipt_required",
            )
            completed_result = subprocess.run(
                [*complete_args, "--mutation-receipt", str(paths["mutation_receipt"])],
                env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        self.assertEqual(completed_result.returncode, 0, completed_result.stderr or completed_result.stdout)
        self.assertEqual(json.loads(completed_result.stdout)["completion"]["state"], "succeeded")

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

    def test_paid_mutation_claim_atomically_binds_preflight_spend_and_execution(self):
        permit, mutation = self._mutation_permit(paid=True)
        preflight = self._preflight(permit, mutation)
        authorization = self._authorization(permit, mutation)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(control.ExecutionControlError) as missing_preflight:
                control.claim_execution(
                    permit, tmp, claimed_by="worker", authorization=authorization,
                    contract=self.contract, now="2026-07-15T00:00:00Z",
                )
            self.assertEqual(missing_preflight.exception.code, "preflight_required")
            self.assertFalse(Path(tmp, "execution-control", "executions").exists())
            self.assertFalse(Path(tmp, "execution-control", "spend").exists())

            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", authorization=authorization,
                preflight_receipt=preflight, contract=self.contract,
                now="2026-07-15T00:00:00Z",
            )
            consumption = claimed["spend_consumption"]
            claim = claimed["claim"]
            self.assertEqual(consumption["claim_id"], claim["claim_id"])
            self.assertEqual(claim["preflight_receipt_ref"], preflight["receipt_id"])
            self.assertEqual(claim["spend_consumption_ref"], consumption["consumption_id"])

            mutation_receipt = self._mutation_receipt(
                mutation, preflight, consumption=consumption,
            )
            receipt = self._command_receipt(
                permit, claim["claim_id"], mutation_ref=mutation_receipt["mutation_id"],
                consumption_ref=consumption["consumption_id"],
            )
            with self.assertRaises(control.ExecutionControlError) as missing_receipt:
                control.complete_execution(
                    permit, claim["claim_id"], receipt, tmp, contract=self.contract,
                )
            self.assertEqual(missing_receipt.exception.code, "external_mutation_receipt_required")
            completed = control.complete_execution(
                permit, claim["claim_id"], receipt, tmp,
                mutation_receipt=mutation_receipt, contract=self.contract,
            )

        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(completed["external_mutation_receipt_ref"], mutation_receipt["mutation_id"])
        self.assertEqual(completed["spend_status"]["claim_state"], "consumed")

    def test_free_mutation_requires_receipt_without_spend_binding(self):
        permit, mutation = self._mutation_permit(paid=False)
        preflight = self._preflight(permit, mutation)
        with tempfile.TemporaryDirectory() as tmp:
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", preflight_receipt=preflight,
                contract=self.contract, now="2026-07-15T00:00:00Z",
            )
            self.assertIsNone(claimed["spend_consumption"])
            mutation_receipt = self._mutation_receipt(mutation, preflight)
            receipt = self._command_receipt(
                permit, claimed["claim"]["claim_id"], mutation_ref=mutation_receipt["mutation_id"],
            )
            completed = control.complete_execution(
                permit, claimed["claim"]["claim_id"], receipt, tmp,
                mutation_receipt=mutation_receipt, contract=self.contract,
            )
            stored = Path(tmp, "execution-control", "mutation-receipts").exists()

        self.assertEqual(completed["external_mutation_receipt_ref"], mutation_receipt["mutation_id"])
        self.assertIsNone(completed["spend_status"])
        self.assertTrue(stored)

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
            available_snapshot = dict(capability_case["input"]["snapshot"])
            available_snapshot.update({
                "snapshot_id": "CAP-browser-available",
                "mission_id": "mission-available",
                "status": "available",
                "reason": None,
            })
            available_snapshot["digest"] = control.instance_digest(available_snapshot)
            control.capability_plan(
                "mission-available", [available_snapshot["capability_id"]],
                available_snapshot["environment_digest"], tmp,
            )
            control.record_capability_snapshot(available_snapshot, tmp, contract=self.contract)
            available = control.capability_plan(
                "mission-available", [available_snapshot["capability_id"]],
                available_snapshot["environment_digest"], tmp,
            )
            unknown_snapshot = dict(capability_case["input"]["snapshot"])
            unknown_snapshot.update({
                "snapshot_id": "CAP-browser-unknown",
                "mission_id": "mission-unknown",
                "status": "unknown",
                "reason": "provider did not advertise capability",
            })
            unknown_snapshot["digest"] = control.instance_digest(unknown_snapshot)
            control.capability_plan(
                "mission-unknown", [unknown_snapshot["capability_id"]],
                unknown_snapshot["environment_digest"], tmp,
            )
            control.record_capability_snapshot(unknown_snapshot, tmp, contract=self.contract)
            unknown = control.capability_plan(
                "mission-unknown", [unknown_snapshot["capability_id"]],
                unknown_snapshot["environment_digest"], tmp,
            )
            unknown_pending = control.capability_plan(
                "mission-unknown", [unknown_snapshot["capability_id"]],
                unknown_snapshot["environment_digest"], tmp,
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
            mutation_receipt = self._mutation_receipt(
                mutation, preflight, consumption=consumption,
            )
            mutation_status = control.record_external_mutation(
                consumption, mutation_receipt, tmp, contract=self.contract,
            )

        self.assertEqual(first["action"], "probe-capability")
        self.assertEqual(pending["action"], "probe-in-progress")
        self.assertEqual(blocked["action"], "block-dispatch")
        self.assertEqual(available["action"], "dispatch")
        self.assertEqual(unknown["action"], "probe-capability")
        self.assertEqual(unknown_pending["action"], "probe-in-progress")
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
