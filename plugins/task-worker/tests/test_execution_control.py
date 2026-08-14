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

    def test_command_and_physical_identity_golden_vector(self):
        command = self._command()
        expected_command_digest = "sha256:f627a1f81afaa6d418f18d1da598520ca34b81be72462d478c23e5c5fc996376"
        self.assertEqual(control.command_digest(command), expected_command_digest)

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

    def test_execution_evaluate_never_reuses_caller_evidence_without_live_fingerprint(self):
        case = next(case for case in self.contract["golden_cases"] if case["id"] == "success-reuse")
        decision = control.evaluate_request(case["input"], self.contract)
        self.assertEqual("claim", decision["action"])
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp, "request.json")
            request.write_text(json.dumps(case["input"]), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                 "execution-evaluate", "--request", str(request)],
                env={**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        self.assertEqual("claim", json.loads(completed.stdout)["decision"]["action"])

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

    def _command(self, profile=None, *, cwd="plugins/task-worker"):
        profile = profile or self._profile()
        return {
            "executable": profile["executable"],
            "args": profile["args"],
            "cwd": cwd,
            "environment": {"PYTHONPATH": "plugins/task-worker"},
        }

    def _reuse_fingerprint(self, permit, **overrides):
        values = {
            "commit_ref": permit["head"],
            "source_tree_digest": "sha256:" + "a" * 64,
            "criteria_digest": permit["criteria_digest"],
            "impact_set": permit["impact_set"],
            "dependency_digest": "sha256:" + "d" * 64,
            "command_profile_digest": "sha256:" + "e" * 64,
            "command_digest_value": permit["command_digest"],
            "tool_version": permit["tool_version"],
            "tool_identity_digest": "sha256:" + "9" * 64,
            "environment_digest": permit["environment_digest"],
            "public_surface_digest": "sha256:" + "f" * 64,
        }
        values.update(overrides)
        return control.build_reuse_fingerprint(**values)

    def _live_execution_context(
        self, root, *, purpose="delta", qa_mode="delta", repository_tool=False,
    ):
        repo = Path(root) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
        for name, body in (("src.py", "print('one')\n"), ("deps.lock", "v1\n"), ("public.txt", "v1\n")):
            (repo / name).write_text(body, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            text=True, stdout=subprocess.PIPE,
        ).stdout.strip()
        profile_overrides = {"args": ["-m", "unittest", "selector-1", "selector-2"]}
        if repository_tool:
            runner = repo / "runner"
            runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            runner.chmod(0o755)
            subprocess.run(["git", "-C", str(repo), "add", "runner"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "runner"], check=True)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                text=True, stdout=subprocess.PIPE,
            ).stdout.strip()
            profile_overrides.update({
                "executable": str(runner), "args": ["selector-1", "selector-2"],
            })
        profile = self._profile(**profile_overrides)
        command = self._command(profile, cwd=".")
        permit = dict(self.contract["golden_cases"][0]["input"]["permit"])
        permit.update({
            "permit_id": "permit-" + purpose,
            "head": head,
            "purpose": purpose,
            "qa_mode": qa_mode,
            "target": "repository",
            "fresh_requirement_id": "fresh-live-1" if control.fresh_required({"purpose": purpose}) else None,
            "command_profile_id": profile["profile_id"],
            "command_digest": control.command_digest(command),
            "impact_set": ["src.py"],
        })
        permit["digest"] = control.instance_digest(permit)
        resolver = {
            "schema": control.REUSE_RESOLVER_SCHEMA,
            "repo_root": str(repo),
            "relevant_paths": ["src.py"],
            "dependency_paths": ["deps.lock"],
            "public_surface_paths": ["public.txt"],
            "selectors": ["selector-1", "selector-2"],
        }
        plan = {"command": command, "command_profile_digest": profile["digest"]}
        fingerprint, _ = control.resolve_reuse_fingerprint(permit, plan, resolver)
        return repo, permit, resolver, plan, fingerprint

    def _verification_evidence(self, permit, receipt, fingerprint, *, evidence_id="EV-live", result="pass"):
        evidence = dict(next(
            case["input"]["evidence"] for case in self.contract["golden_cases"]
            if case["id"] == "success-reuse"
        ))
        evidence.update({
            "evidence_id": evidence_id,
            "source_receipt_id": receipt["receipt_id"],
            "purpose": permit["purpose"],
            "head": permit["head"],
            "command_digest": permit["command_digest"],
            "environment_digest": permit["environment_digest"],
            "tool_version": permit["tool_version"],
            "fresh_requirement_id": permit["fresh_requirement_id"],
            "criteria_digest": permit["criteria_digest"],
            "target": permit["target"],
            "covered_paths": permit["impact_set"],
            "impact_set": permit["impact_set"],
            "surface_digest": fingerprint["digest"],
            "result": result,
        })
        evidence["digest"] = control.instance_digest(evidence)
        return evidence

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
            "expires_at": "2099-07-16T00:00:00Z",
        }
        value["digest"] = control.instance_digest(value)
        return value

    def _command_receipt(
        self, permit, claim_id, *, mutation_ref=None, consumption_ref=None, **overrides,
    ):
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
        value.update(overrides)
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

    @staticmethod
    def _make_base_era_claim_fixture(state_root, claim_id):
        """Model a stored pre-migration claim that lacks mutation_receipt_digest."""
        for path in Path(state_root, "execution-control", "executions").glob("*.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            for claim in state["claims"]:
                if claim["claim_id"] == claim_id:
                    claim.pop("mutation_receipt_digest", None)
                    path.write_text(json.dumps(state), encoding="utf-8")
                    return
        raise AssertionError(f"claim not found: {claim_id}")

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

    def test_cli_rejects_deprecated_caller_authored_reuse_fingerprint(self):
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
            paths = {
                "profiles": root / "profiles.json", "rules": root / "rules.json",
                "permit": root / "permit.json", "fingerprint": root / "fingerprint.json",
            }
            paths["profiles"].write_text(json.dumps({"profiles": [profile]}), encoding="utf-8")
            paths["rules"].write_text(json.dumps([{
                "rule_id": "worker", "path_globs": ["plugins/task-worker/**"],
                "qa_modes": ["delta"], "command_profile_ids": [profile["profile_id"]],
                "purposes": ["delta"],
            }]), encoding="utf-8")
            paths["permit"].write_text(json.dumps(permit), encoding="utf-8")
            paths["fingerprint"].write_text("{}", encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                "execution-claim", "--permit", str(paths["permit"]),
                "--profiles", str(paths["profiles"]), "--impact-rules", str(paths["rules"]),
                "--changed-path", "plugins/task-worker/scripts/execution_control.py",
                "--cwd", "plugins/task-worker",
                "--environment", json.dumps({"PYTHONPATH": "plugins/task-worker"}),
                "--claimed-by", "test-worker", "--state-root", str(root / "state"),
                "--reuse-fingerprint", str(paths["fingerprint"]),
            ], env={**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            complete_result = subprocess.run([
                sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                "execution-complete", "--permit", str(paths["permit"]),
                "--claim-id", "legacy-claim", "--receipt", str(paths["fingerprint"]),
                "--reuse-fingerprint", str(paths["fingerprint"]),
                "--state-root", str(root / "state"),
            ], env={**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(2, result.returncode, result.stderr or result.stdout)
        self.assertEqual("reuse_fingerprint_deprecated", json.loads(result.stdout)["error_code"])
        self.assertEqual(2, complete_result.returncode, complete_result.stderr or complete_result.stdout)
        self.assertEqual(
            "reuse_fingerprint_deprecated", json.loads(complete_result.stdout)["error_code"],
        )

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
        with tempfile.TemporaryDirectory() as tmp:
            _, permit, resolver, plan, fingerprint = self._live_execution_context(tmp)
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
            evidence = self._verification_evidence(permit, receipt, fingerprint)
            completed = control.complete_execution(
                permit, receipt["claim_id"], receipt, tmp, evidence=evidence,
                contract=self.contract,
            )
            reused = control.claim_execution(
                permit, tmp, claimed_by="other", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )

        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(completed["evidence_refs"], [evidence["evidence_id"]])
        self.assertEqual(reused["action"], "reuse-evidence")
        self.assertFalse(reused["physical_run_started"])

    def test_source_tree_pin_covers_staged_unstaged_untracked_mode_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            staged = control.source_tree_pin(repo, ["tracked.txt"])

            tracked.write_text("two\n", encoding="utf-8")
            unstaged = control.source_tree_pin(repo, ["tracked.txt"])
            self.assertNotEqual(staged["digest"], unstaged["digest"])
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            restaged = control.source_tree_pin(repo, ["tracked.txt"])
            self.assertNotEqual(unstaged["digest"], restaged["digest"])

            untracked = repo / "new.txt"
            untracked.write_text("new\n", encoding="utf-8")
            with_untracked = control.source_tree_pin(repo, ["tracked.txt", "new.txt"])
            untracked.write_text("changed\n", encoding="utf-8")
            self.assertNotEqual(
                with_untracked["digest"],
                control.source_tree_pin(repo, ["tracked.txt", "new.txt"])["digest"],
            )

            tracked.chmod(0o755)
            executable = control.source_tree_pin(repo, ["tracked.txt"])
            self.assertNotEqual(restaged["digest"], executable["digest"])
            link = repo / "link.txt"
            link.symlink_to("tracked.txt")
            linked = control.source_tree_pin(repo, ["link.txt"])
            link.unlink()
            link.symlink_to("new.txt")
            self.assertNotEqual(linked["digest"], control.source_tree_pin(repo, ["link.txt"])["digest"])

    def test_source_tree_pin_fails_closed_for_dirty_submodule_and_unexpanded_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            nested = repo / "nested"
            subprocess.run(["git", "init", "-q", str(nested)], check=True)
            subprocess.run(["git", "-C", str(nested), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(nested), "config", "user.email", "test@example.com"], check=True)
            (nested / "file.txt").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(nested), "add", "file.txt"], check=True)
            subprocess.run(["git", "-C", str(nested), "commit", "-qm", "init"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "nested"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "submodule"], check=True)
            clean = control.source_tree_pin(repo, ["nested"])
            self.assertEqual(clean["status"], "canonical")
            (nested / "file.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(control.ExecutionControlError) as dirty:
                control.source_tree_pin(repo, ["nested"])
            self.assertEqual(dirty.exception.code, "source_tree_unknown")
            relocated = repo / "nested-real"
            nested.rename(relocated)
            nested.symlink_to(relocated, target_is_directory=True)
            with self.assertRaises(control.ExecutionControlError) as linked_submodule:
                control.source_tree_pin(repo, ["nested"])
            self.assertEqual(linked_submodule.exception.code, "source_tree_unknown")
            with self.assertRaises(control.ExecutionControlError):
                control.source_tree_pin(repo, ["plugins/**"])

            escaped = repo / "escaped"
            escaped.symlink_to(repo.parent / "definitely-outside-source-tree-pin")
            with self.assertRaises(control.ExecutionControlError) as path_escape:
                control.source_tree_pin(repo, ["escaped"])
            self.assertEqual(path_escape.exception.code, "source_tree_unknown")

    def test_completion_recomputes_live_source_and_rejects_stale_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, permit, resolver, plan, _ = self._live_execution_context(tmp)
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
            (repo / "src.py").write_text("print('changed')\n", encoding="utf-8")
            with self.assertRaises(control.ExecutionControlError) as stale:
                control.complete_execution(
                    permit, receipt["claim_id"], receipt, tmp, contract=self.contract,
                )
        self.assertEqual("reuse_pin_stale", stale.exception.code)

    def test_reuse_claim_rejects_dirty_relevant_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, permit, resolver, plan, _ = self._live_execution_context(tmp)
            (repo / "src.py").write_text("print('dirty')\n", encoding="utf-8")
            with self.assertRaises(control.ExecutionControlError) as dirty:
                control.claim_execution(
                    permit, tmp, claimed_by="worker", contract=self.contract,
                    reuse_resolver=resolver, policy_plan=plan,
                )
        self.assertEqual("source_tree_dirty", dirty.exception.code)

    def test_completion_invalidates_live_dependency_and_public_surface_axes(self):
        for path in ("deps.lock", "public.txt"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                repo, permit, resolver, plan, _ = self._live_execution_context(tmp)
                claimed = control.claim_execution(
                    permit, tmp, claimed_by="worker", contract=self.contract,
                    reuse_resolver=resolver, policy_plan=plan,
                )
                receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
                (repo / path).write_text("changed\n", encoding="utf-8")
                with self.assertRaises(control.ExecutionControlError) as stale:
                    control.complete_execution(
                        permit, receipt["claim_id"], receipt, tmp, contract=self.contract,
                    )
                self.assertEqual("reuse_pin_stale", stale.exception.code)

    def test_reuse_fingerprint_invalidates_every_material_axis(self):
        permit = dict(self.contract["golden_cases"][0]["input"]["permit"])
        permit["head"] = "sha256:" + "a" * 64
        permit["digest"] = control.instance_digest(permit)
        base_values = {
            "commit_ref": permit["head"],
            "source_tree_digest": "sha256:" + "a" * 64,
            "criteria_digest": permit["criteria_digest"],
            "impact_set": permit["impact_set"],
            "dependency_digest": "sha256:" + "d" * 64,
            "command_profile_digest": "sha256:" + "e" * 64,
            "command_digest_value": permit["command_digest"],
            "tool_version": permit["tool_version"],
            "tool_identity_digest": "sha256:" + "9" * 64,
            "environment_digest": permit["environment_digest"],
            "public_surface_digest": "sha256:" + "f" * 64,
        }
        before = control.build_reuse_fingerprint(**base_values)
        cases = {
            "commit_ref": "another-commit",
            "source_tree_digest": "sha256:" + "1" * 64,
            "criteria_digest": "sha256:" + "2" * 64,
            "impact_set": ["another/path"],
            "dependency_digest": "sha256:" + "3" * 64,
            "command_profile_digest": "sha256:" + "4" * 64,
            "command_digest_value": "sha256:" + "5" * 64,
            "tool_version": "python/next",
            "tool_identity_digest": "sha256:" + "8" * 64,
            "environment_digest": "sha256:" + "6" * 64,
            "public_surface_digest": "sha256:" + "7" * 64,
        }
        for field, changed in cases.items():
            with self.subTest(field=field):
                after = control.build_reuse_fingerprint(**{**base_values, field: changed})
                self.assertNotEqual(before["digest"], after["digest"])

    def test_completion_invalidates_live_tool_bytes_without_running_version_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, permit, resolver, plan, _ = self._live_execution_context(
                tmp, repository_tool=True,
            )
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
            runner = Path(plan["command"]["executable"])
            runner.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            runner.chmod(0o755)
            with self.assertRaises(control.ExecutionControlError) as stale:
                control.complete_execution(
                    permit, receipt["claim_id"], receipt, tmp, contract=self.contract,
                )
        self.assertEqual("reuse_pin_stale", stale.exception.code)

    def test_tool_identity_resolves_relative_executable_and_path_from_physical_command_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "repo")
            tools = repo / "tools"
            tools.mkdir(parents=True)
            runner = tools / "runner"
            runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            runner.chmod(0o755)
            controller = Path(tmp, "controller")
            controller.mkdir()
            commands = (
                {"executable": "./runner", "args": [], "cwd": "tools", "environment": {}},
                {"executable": "runner", "args": [], "cwd": "tools", "environment": {"PATH": ""}},
                {"executable": "runner", "args": [], "cwd": ".", "environment": {"PATH": "tools"}},
            )
            previous = Path.cwd()
            try:
                os.chdir(controller)
                identities = [control.resolve_tool_identity(repo.resolve(), command) for command in commands]
            finally:
                os.chdir(previous)
            escaping = {
                "executable": "runner", "args": [], "cwd": ".",
                "environment": {"PATH": "../../outside"},
            }
            with self.assertRaises(control.ExecutionControlError) as escaped:
                control.resolve_tool_identity(repo.resolve(), escaping)

        self.assertEqual(
            ["repo:tools/runner"] * 3,
            [identity["resolved_path"] for identity in identities],
        )
        self.assertEqual(1, len({identity["content_digest"] for identity in identities}))
        self.assertEqual("tool_identity_unknown", escaped.exception.code)

    def test_development_fingerprint_reuses_across_fresh_labels_but_final_does_not(self):
        permit = dict(self.contract["golden_cases"][0]["input"]["permit"])
        permit.update({"head": "sha256:" + "a" * 64, "fresh_requirement_id": "dev-1"})
        permit["digest"] = control.instance_digest(permit)
        fingerprint = self._reuse_fingerprint(permit)
        another = {**permit, "fresh_requirement_id": "dev-2"}
        another["digest"] = control.instance_digest(another)
        self.assertEqual(
            control.physical_identity(permit, fingerprint),
            control.physical_identity(another, fingerprint),
        )
        final = {**permit, "purpose": "integration-full", "qa_mode": "final"}
        final["digest"] = control.instance_digest(final)
        final_fingerprint = self._reuse_fingerprint(final)
        final_next = {**final, "fresh_requirement_id": "final-2"}
        final_next["digest"] = control.instance_digest(final_next)
        self.assertNotEqual(
            control.physical_identity(final, final_fingerprint),
            control.physical_identity(final_next, final_fingerprint),
        )

    @staticmethod
    def _batch_child(receipt, evidence):
        return {
            "evidence_id": evidence["evidence_id"],
            "evidence_digest": evidence["digest"],
            "receipt_id": receipt["receipt_id"],
            "receipt_digest": receipt["digest"],
        }

    def test_evidence_batch_resolves_canonical_refs_and_rejects_duplicate_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, permit, resolver, plan, fingerprint = self._live_execution_context(tmp)
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
            evidence = self._verification_evidence(permit, receipt, fingerprint)
            control.complete_execution(
                permit, receipt["claim_id"], receipt, tmp,
                evidence=evidence, contract=self.contract,
            )
            child = self._batch_child(receipt, evidence)
            kwargs = {
                "state_root": tmp,
                "source_tree_digest": fingerprint["source_tree_digest"],
                "command_profile_digest": plan["command_profile_digest"],
                "criteria_digest": permit["criteria_digest"],
                "target": permit["target"],
                "reuse_fingerprint_digest": fingerprint["digest"],
                "expected_selectors": ["selector-1", "selector-2"],
                "contract": self.contract,
            }
            passed = control.build_evidence_batch(**kwargs, children=[child])
            projection = control.project_receipts(
                receipt, None, tmp, self.contract,
                evidence_batch_request={
                    key: value for key, value in kwargs.items()
                    if key not in {"state_root", "contract"}
                } | {"children": [child]},
            )
            receipt_path = Path(tmp, "receipt.json")
            batch_path = Path(tmp, "fabricated-batch.json")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            batch_path.write_text(json.dumps(passed), encoding="utf-8")
            fabricated = subprocess.run([
                sys.executable, str(TASK_WORKER / "scripts" / "definition_artifact.py"),
                "execution-project", "--receipt", str(receipt_path),
                "--evidence-batch", str(batch_path), "--state-root", tmp,
            ], env={**os.environ, "STUDIO_VERIFICATION_CONTRACT": str(self.contract_path)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with self.assertRaises(control.ExecutionControlError) as duplicated:
                control.build_evidence_batch(**kwargs, children=[child, child])
            missing = control.build_evidence_batch(
                **kwargs,
                children=[{
                    **child, "evidence_id": "EV-missing",
                    "evidence_digest": "sha256:" + "9" * 64,
                }],
            )
            with self.assertRaises(control.ExecutionControlError) as fabricated_projection:
                control.project_receipts(
                    receipt, None, tmp, self.contract,
                    evidence_batch_request={
                        key: value for key, value in kwargs.items()
                        if key not in {"state_root", "contract"}
                    } | {"children": [{
                        **child, "evidence_id": "EV-missing",
                        "evidence_digest": "sha256:" + "9" * 64,
                    }]},
                )
        self.assertEqual("pass", passed["result"])
        self.assertEqual(receipt["output_digest"], passed["children"][0]["output_digest"])
        self.assertEqual({"batch_digest": passed["digest"]}, projection["evidence_ref"])
        self.assertEqual(2, fabricated.returncode, fabricated.stderr or fabricated.stdout)
        self.assertEqual("evidence_batch_body_deprecated", json.loads(fabricated.stdout)["error_code"])
        self.assertEqual("evidence_batch_invalid", duplicated.exception.code)
        self.assertEqual("fail", missing["result"])
        self.assertEqual(["EV-missing"], missing["failed_evidence_refs"])
        self.assertEqual("execution_projection_invalid", fabricated_projection.exception.code)

    def test_final_qa_projection_resolves_only_canonical_task_worker_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, permit, resolver, plan, fingerprint = self._live_execution_context(
                tmp, purpose="integration-full", qa_mode="final",
            )
            claimed = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
            evidence = self._verification_evidence(permit, receipt, fingerprint)
            control.complete_execution(
                permit, receipt["claim_id"], receipt, tmp,
                evidence=evidence, contract=self.contract,
            )
            value = {
                "candidate_ref": permit["head"], "state_root": tmp,
                "source_tree_digest": fingerprint["source_tree_digest"],
                "criteria_digest": permit["criteria_digest"],
            }
            accepted = control.final_qa_projection(value, self.contract)
            with self.assertRaises(control.ExecutionControlError) as caller_attempts:
                control.final_qa_projection({**value, "attempts": []}, self.contract)
            (repo / "src.py").write_text("print('after-final')\n", encoding="utf-8")
            with self.assertRaises(control.ExecutionControlError) as changed_after_final:
                control.final_qa_projection(value, self.contract)

        self.assertEqual("pass", accepted["result"])
        self.assertEqual(control.instance_digest(accepted), accepted["digest"])
        self.assertEqual("final_qa_invalid", caller_attempts.exception.code)
        self.assertEqual("final_qa_stale", changed_after_final.exception.code)

    def test_final_qa_projection_preserves_failed_attempt_before_one_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, permit, resolver, plan, fingerprint = self._live_execution_context(
                tmp, purpose="integration-full", qa_mode="final",
            )
            first_claim = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            failed_receipt = self._command_receipt(
                permit, first_claim["claim"]["claim_id"], receipt_id="receipt-final-failed",
                exit_code=1, result="fail",
            )
            control.complete_execution(
                permit, failed_receipt["claim_id"], failed_receipt, tmp, contract=self.contract,
            )
            base = {
                "candidate_ref": permit["head"], "state_root": tmp,
                "source_tree_digest": fingerprint["source_tree_digest"],
                "criteria_digest": permit["criteria_digest"],
            }
            failed = control.final_qa_projection(base, self.contract)

            second_claim = control.claim_execution(
                permit, tmp, claimed_by="worker", contract=self.contract,
                reuse_resolver=resolver, policy_plan=plan,
            )
            passed_receipt = self._command_receipt(
                permit, second_claim["claim"]["claim_id"], receipt_id="receipt-final-pass",
                started_at="2026-07-15T00:00:04Z", finished_at="2026-07-15T00:00:05Z",
            )
            evidence = self._verification_evidence(
                permit, passed_receipt, fingerprint, evidence_id="EV-final-pass",
            )
            control.complete_execution(
                permit, passed_receipt["claim_id"], passed_receipt, tmp,
                evidence=evidence, contract=self.contract,
            )
            confirmed = control.final_qa_projection(base, self.contract)
            with self.assertRaises(control.ExecutionControlError) as omitted_failure:
                control.final_qa_projection({
                    **base, "attempts": [self._batch_child(passed_receipt, evidence)],
                }, self.contract)

        self.assertEqual("fail", failed["result"])
        self.assertEqual("pass", confirmed["result"])
        self.assertEqual(["fail", "pass"], [item["result"] for item in confirmed["attempts"]])
        self.assertEqual("final_qa_invalid", omitted_failure.exception.code)

    def test_task_worker_execution_control_imports_without_session_review_sibling(self):
        with self.assertRaises(control.ExecutionControlError) as legacy:
            control.evaluate_request({"final_candidate": {}}, self.contract)
        with tempfile.TemporaryDirectory() as tmp:
            standalone = Path(tmp, "execution_control.py")
            standalone.write_bytes((TASK_WORKER / "scripts" / "execution_control.py").read_bytes())
            spec = importlib.util.spec_from_file_location("standalone_execution_control", standalone)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertFalse(hasattr(module, "final_candidate_gate"))
        self.assertEqual("final_candidate_provider_boundary_changed", legacy.exception.code)

    def test_completed_claim_rejects_a_second_physical_receipt(self):
        permit = self.contract["golden_cases"][0]["input"]["permit"]
        with tempfile.TemporaryDirectory() as tmp:
            claimed = control.claim_execution(permit, tmp, claimed_by="worker", contract=self.contract)
            receipt = self._command_receipt(permit, claimed["claim"]["claim_id"])
            first = control.complete_execution(
                permit, receipt["claim_id"], receipt, tmp, contract=self.contract,
            )
            repeated = control.complete_execution(
                permit, receipt["claim_id"], receipt, tmp, contract=self.contract,
            )
            second = {**receipt, "receipt_id": "another-receipt"}
            second["digest"] = control.instance_digest(second)
            with self.assertRaises(control.ExecutionControlError) as duplicate:
                control.complete_execution(
                    permit, second["claim_id"], second, tmp, contract=self.contract,
                )
        self.assertEqual(first["state"], "succeeded")
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(duplicate.exception.code, "claim_already_completed")

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
            self._make_base_era_claim_fixture(tmp, claim["claim_id"])
            replayed = control.complete_execution(
                permit, claim["claim_id"], receipt, tmp,
                mutation_receipt=mutation_receipt, contract=self.contract,
            )
            another_mutation_receipt = {
                **mutation_receipt, "mutation_id": "another-mutation-receipt",
            }
            another_mutation_receipt["digest"] = control.instance_digest(another_mutation_receipt)
            with self.assertRaises(control.ExecutionControlError) as changed_replay:
                control.complete_execution(
                    permit, claim["claim_id"], receipt, tmp,
                    mutation_receipt=another_mutation_receipt, contract=self.contract,
                )

        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(completed["external_mutation_receipt_ref"], mutation_receipt["mutation_id"])
        self.assertEqual(completed["spend_status"]["claim_state"], "consumed")
        self.assertTrue(replayed["idempotent"])
        self.assertEqual(completed["spend_status"], replayed["spend_status"])
        self.assertEqual(
            completed["external_mutation_receipt_ref"], replayed["external_mutation_receipt_ref"],
        )
        self.assertEqual("external_mutation_receipt_mismatch", changed_replay.exception.code)

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
            self._make_base_era_claim_fixture(tmp, claimed["claim"]["claim_id"])
            replayed = control.complete_execution(
                permit, claimed["claim"]["claim_id"], receipt, tmp,
                contract=self.contract,
            )
            stored = Path(tmp, "execution-control", "mutation-receipts").exists()

        self.assertEqual(completed["external_mutation_receipt_ref"], mutation_receipt["mutation_id"])
        self.assertIsNone(completed["spend_status"])
        self.assertIsNone(replayed["spend_status"])
        self.assertEqual(completed["external_mutation_receipt_ref"], replayed["external_mutation_receipt_ref"])
        self.assertTrue(replayed["idempotent"])
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
