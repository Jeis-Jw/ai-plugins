import sys
import unittest
from pathlib import Path

TASK_GITHUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_GITHUB / "skills" / "orchestrate" / "scripts"))

import orchestrator_ops  # noqa: E402


def gate_evidence(paths, **overrides):
    paths = orchestrator_ops.canonical_path_list(paths)
    evidence = {
        "changed_paths": paths,
        "changed_paths_hash": orchestrator_ops.path_list_hash(paths),
        "checked_paths": paths,
        "checked_paths_hash": orchestrator_ops.path_list_hash(paths),
        "drift_surface_hash": "surface-1",
        "gate_version": "changed-path-stale:v1",
        "tool_versions": {"task-github": "0.15.0"},
        "changed_path_stale_issues": [],
        "pr_head_sha": "head-1",
    }
    evidence.update(overrides)
    return evidence


def child_with_evidence(number, paths, **overrides):
    child = {
        "number": number,
        "changed_paths": paths,
        "merge_evidence": {
            "kind": "merged_pr",
            "base": "task/issue-39",
            "parent_contains_child": True,
            "head_sha": "head-1",
        },
        "gate_evidence": gate_evidence(paths),
    }
    child.update(overrides)
    return child


class OrchestratorOpsTests(unittest.TestCase):
    def test_branch_names_and_base_branch(self):
        self.assertEqual(orchestrator_ops.issue_branch(12), "task/issue-12")
        self.assertEqual(orchestrator_ops.issue_base_branch(parent_number=7, base_branch="main"), "task/issue-7")
        self.assertEqual(orchestrator_ops.issue_base_branch(parent_number=None, base_branch="main"), "main")

    def test_ensure_branch_chain_root_only(self):
        chain = orchestrator_ops.ensure_branch_chain(81, parents={81: None}, base_branch="main")
        self.assertEqual(chain, [{"issue": 81, "branch": "task/issue-81", "base": "main"}])

    def test_ensure_branch_chain_multi_level(self):
        parents = {83: 82, 82: 81, 81: None}
        chain = orchestrator_ops.ensure_branch_chain(83, parents=parents, base_branch="main")
        self.assertEqual(
            chain,
            [
                {"issue": 81, "branch": "task/issue-81", "base": "main"},
                {"issue": 82, "branch": "task/issue-82", "base": "task/issue-81"},
                {"issue": 83, "branch": "task/issue-83", "base": "task/issue-82"},
            ],
        )

    def test_ensure_branch_chain_detects_cycle(self):
        with self.assertRaises(ValueError):
            orchestrator_ops.ensure_branch_chain(1, parents={1: 2, 2: 1}, base_branch="main")

    def test_review_policy(self):
        self.assertFalse(orchestrator_ops.review_required("gear", "gear:micro"))
        self.assertFalse(orchestrator_ops.review_required("gear", "gear:normal"))
        self.assertTrue(orchestrator_ops.review_required("gear", "gear:major"))
        self.assertTrue(orchestrator_ops.review_required("gear", None))
        self.assertFalse(orchestrator_ops.review_required("skip", "gear:major"))
        self.assertTrue(orchestrator_ops.review_required("all", "gear:micro"))

    def test_flow_policy_defaults_and_overrides(self):
        self.assertEqual(
            orchestrator_ops.flow_policy("gear:micro"),
            {"plan": False, "verify": True, "pr-review": False},
        )
        self.assertEqual(
            orchestrator_ops.flow_policy("gear:normal"),
            {"plan": True, "verify": True, "pr-review": False},
        )
        self.assertEqual(
            orchestrator_ops.flow_policy("gear:major"),
            {"plan": True, "verify": True, "pr-review": True},
        )

        config = {"normal": {"pr-review": "o"}, "major": {"verify": "x"}}
        commander = {"normal": {"pr-review": False, "plan": False}}

        self.assertEqual(
            orchestrator_ops.flow_policy("gear:normal", gear_options=config, commander_options=commander),
            {"plan": False, "verify": True, "pr-review": False},
        )
        self.assertFalse(orchestrator_ops.verify_required("gear:major", gear_options=config))
        self.assertTrue(orchestrator_ops.review_required("all", "gear:micro", gear_options={"micro": {"pr-review": False}}))

    def test_pr_recovery_reuses_open_exact_base(self):
        result = orchestrator_ops.classify_pr_recovery(
            head="task/issue-3",
            expected_base="task/issue-1",
            prs=[{"number": 8, "head": "task/issue-3", "base": "task/issue-1", "state": "OPEN"}],
        )

        self.assertEqual(result, {"action": "reuse_open", "pr": 8})

    def test_pr_recovery_recovers_merged_exact_base(self):
        result = orchestrator_ops.classify_pr_recovery(
            head="task/issue-3",
            expected_base="task/issue-1",
            prs=[{"number": 8, "head": "task/issue-3", "base": "task/issue-1", "state": "MERGED"}],
        )

        self.assertEqual(result, {"action": "ensure_issue_closed", "pr": 8})

    def test_pr_recovery_stops_on_stale_base_open_pr(self):
        result = orchestrator_ops.classify_pr_recovery(
            head="task/issue-3",
            expected_base="task/issue-2",
            prs=[{"number": 8, "head": "task/issue-3", "base": "task/issue-1", "state": "OPEN"}],
        )

        self.assertEqual(result, {"action": "stop", "stop_reason": "state_mismatch", "pr": 8})

    def test_pr_recovery_creates_when_no_pr_exists(self):
        result = orchestrator_ops.classify_pr_recovery(
            head="task/issue-3",
            expected_base="task/issue-1",
            prs=[],
        )

        self.assertEqual(result, {"action": "create"})

    def test_child_merge_evidence_accepts_no_change_or_merged_pr(self):
        children = [
            {"number": 2, "closed_no_pr": True},
            {"number": 3, "merged_pr": {"number": 9, "base": "task/issue-1"}},
        ]

        result = orchestrator_ops.child_merge_evidence(children, expected_base="task/issue-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])

    def test_child_merge_evidence_stops_when_pr_base_missing(self):
        children = [
            {"number": 2, "merged_pr": {"number": 9, "base": "main"}},
            {"number": 3},
        ]

        result = orchestrator_ops.child_merge_evidence(children, expected_base="task/issue-1")

        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "state_mismatch")
        self.assertEqual(result["missing"], [2, 3])

    def test_tool_command_composition(self):
        self.assertEqual(
            orchestrator_ops.compose_tool_command(
                "session-review:request-review",
                "self turnkey",
                "--target-mode diff --target-ref PR-8",
            ),
            "/session-review:request-review self turnkey --target-mode diff --target-ref PR-8",
        )
        self.assertIsNone(orchestrator_ops.compose_tool_command(None, "self turnkey"))

    def test_review_verdict_actions(self):
        self.assertEqual(
            orchestrator_ops.review_verdict_action({"verdict": "approved"}, round_number=1, round_cap=3),
            {"action": "merge"},
        )
        self.assertEqual(
            orchestrator_ops.review_verdict_action(
                {"verdict": "changes-requested", "findings": ["fix"]},
                round_number=1,
                round_cap=3,
            ),
            {"action": "respawn_worker", "feedback": ["fix"], "next_round": 2},
        )
        self.assertEqual(
            orchestrator_ops.review_verdict_action({"verdict": "changes-requested"}, round_number=3, round_cap=3),
            {"action": "stop", "stop_reason": "human_gate_review"},
        )

    def test_conflict_actions(self):
        self.assertEqual(
            orchestrator_ops.conflict_action(auto_conflict=False, ambiguity=False),
            {"action": "stop", "stop_reason": "merge_conflict"},
        )
        self.assertEqual(
            orchestrator_ops.conflict_action(auto_conflict=True, ambiguity=False),
            {"action": "spawn_conflict_agent"},
        )
        self.assertEqual(
            orchestrator_ops.conflict_action(auto_conflict=True, ambiguity=True),
            {"action": "stop", "stop_reason": "merge_conflict"},
        )

    def test_worker_feedback_handoff(self):
        handoff = orchestrator_ops.worker_feedback_handoff(
            issue=4,
            pr=8,
            branch="task/issue-4",
            feedback=["fix test"],
        )

        self.assertEqual(handoff["issue"], 4)
        self.assertEqual(handoff["pr"], 8)
        self.assertIn("fix test", handoff["prompt"])

    def test_plan_tick_stop_on_not_ok(self):
        plan = orchestrator_ops.plan_tick({"ok": False, "stop_reason": "api_failure"}, review_tool=None)

        self.assertEqual(plan, {"action": "stop", "stop_reason": "api_failure"})

    def test_plan_tick_done_parents_preempt_ready(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": True, "done_parents": [{"number": 2}], "ready": [{"number": 3}]},
            review_tool=None,
        )

        self.assertEqual(plan["action"], "merge_done_parents")
        self.assertEqual(plan["issues"], [2])

    def test_plan_tick_review_waiting_uses_review_tool_when_configured(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": False, "stop_reason": "human_gate_review", "review_waiting": [{"number": 2}]},
            review_tool="session-review:request-review",
            review_command="self turnkey",
        )

        self.assertEqual(plan["action"], "call_review_tool")
        self.assertEqual(plan["issues"], [2])
        self.assertIn("/session-review:request-review self turnkey", plan["command"])

    def test_plan_tick_review_waiting_stops_without_tool(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": False, "stop_reason": "human_gate_review", "review_waiting": [{"number": 2}]},
            review_tool=None,
        )

        self.assertEqual(plan, {"action": "stop", "stop_reason": "human_gate_review"})

    def test_plan_tick_ready_spawns_max_workers(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": True, "ready": [{"number": 2}, {"number": 3}]},
            review_tool=None,
            max_workers=1,
        )

        self.assertEqual(plan, {"action": "spawn_workers", "issues": [2]})

    def test_plan_tick_max_workers_gt_one_dispatches_workers_in_background(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": True, "ready": [{"number": 2}, {"number": 3}]},
            review_tool=None,
            max_workers=2,
        )

        self.assertEqual(plan["action"], "dispatch_background_workers")
        self.assertEqual(plan["issues"], [2, 3])
        self.assertTrue(plan["ledger_required"])
        self.assertEqual(plan["retick_on"], "worker_completion")

    def test_plan_tick_pipeline_reviews_and_spawns_without_barrier(self):
        plan = orchestrator_ops.plan_tick(
            {
                "ok": False,
                "stop_reason": "human_gate_review",
                "review_waiting": [{"number": 2}],
                "ready": [{"number": 3}],
            },
            review_tool="session-review:request-review",
            review_command="self turnkey",
            max_workers=1,
            pipeline=True,
        )

        self.assertEqual(plan["action"], "pipeline")
        self.assertTrue(plan["ledger_required"])
        self.assertEqual([action["action"] for action in plan["actions"]], [
            "dispatch_background_reviews",
            "dispatch_background_workers",
        ])
        self.assertEqual(plan["actions"][0]["issues"], [2])
        self.assertEqual(plan["actions"][1]["issues"], [3])

    def test_plan_tick_stuck_preempts_done_parents(self):
        # evaluate_tree leaves done_parents populated even when it _stop()s for stuck.
        # plan_tick must STOP(stuck), not auto-merge the completed parent (부분진행금지).
        plan = orchestrator_ops.plan_tick(
            {
                "ok": False,
                "stop_reason": "stuck",
                "stuck": [{"number": 9, "reason": "prior_run"}],
                "done_parents": [{"number": 2}],
            },
            review_tool=None,
        )

        self.assertEqual(plan, {"action": "stop", "stop_reason": "stuck"})

    def test_plan_tick_api_failure_preempts_done_parents(self):
        # A hard STOP (ok:false, non-review reason) must win over any actionable set.
        plan = orchestrator_ops.plan_tick(
            {"ok": False, "stop_reason": "api_failure", "done_parents": [{"number": 2}]},
            review_tool=None,
        )

        self.assertEqual(plan, {"action": "stop", "stop_reason": "api_failure"})

    def test_scoped_gate_planner_reuses_valid_child_evidence(self):
        result = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=["plugins/task-github/README.md"],
            children=[
                child_with_evidence(40, [
                    "plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py",
                    "plugins/task-github/skills/orchestrate/scripts/ready_leaves.py",
                ])
            ],
            expected_base="task/issue-39",
            current_gate_version="changed-path-stale:v1",
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hash="surface-1",
            expected_pr_heads={40: "head-1"},
        )

        self.assertEqual(result["target_paths"], ["plugins/task-github/README.md"])
        self.assertEqual(result["reused"], [40])
        self.assertEqual(result["fallback"], [])
        self.assertFalse(result["full_fallback"])

    def test_scoped_gate_planner_falls_back_on_missing_evidence(self):
        result = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=["parent.md"],
            children=[{"number": 40, "changed_paths": ["child.py"]}],
            expected_base="task/issue-39",
            current_gate_version="changed-path-stale:v1",
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hash="surface-1",
        )

        self.assertEqual(result["target_paths"], ["child.py", "parent.md"])
        self.assertEqual(result["fallback"], [{"issue": 40, "reason": "missing_merge_evidence", "paths": ["child.py"]}])
        self.assertTrue(result["full_fallback"])

    def test_scoped_gate_planner_falls_back_on_version_drift(self):
        result = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=[],
            children=[child_with_evidence(40, ["child.py"], gate_evidence=gate_evidence(
                ["child.py"],
                tool_versions={"task-github": "0.14.0"},
            ))],
            expected_base="task/issue-39",
            current_gate_version="changed-path-stale:v1",
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hash="surface-1",
        )

        self.assertEqual(result["target_paths"], ["child.py"])
        self.assertEqual(result["fallback"][0]["reason"], "tool_version_mismatch")

    def test_scoped_gate_planner_allows_deterministic_unknown_tool_policy_token(self):
        result = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=[],
            children=[child_with_evidence(40, ["child.py"], gate_evidence=gate_evidence(
                ["child.py"],
                tool_versions={"task-github": "unknown"},
                tool_version_policy_token="plugin-version-unavailable:v1",
            ))],
            expected_base="task/issue-39",
            current_gate_version="changed-path-stale:v1",
            current_tool_versions={"task-github": "unknown"},
            current_drift_surface_hash="surface-1",
            current_tool_version_policy_token="plugin-version-unavailable:v1",
            expected_pr_heads={40: "head-1"},
        )

        self.assertEqual(result["target_paths"], [])
        self.assertEqual(result["reused"], [40])

    def test_scoped_gate_planner_falls_back_on_drift_surface_mismatch(self):
        result = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=[],
            children=[child_with_evidence(40, ["child.py"])],
            expected_base="task/issue-39",
            current_gate_version="changed-path-stale:v1",
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hash="surface-2",
            expected_pr_heads={40: "head-1"},
        )

        self.assertEqual(result["target_paths"], ["child.py"])
        self.assertEqual(result["fallback"][0]["reason"], "drift_surface_hash_mismatch")

    def test_scoped_gate_planner_falls_back_on_parent_overlap(self):
        result = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=["child.py"],
            children=[child_with_evidence(40, ["child.py"])],
            expected_base="task/issue-39",
            current_gate_version="changed-path-stale:v1",
            current_tool_versions={"task-github": "0.15.0"},
            current_drift_surface_hash="surface-1",
            expected_pr_heads={40: "head-1"},
        )

        self.assertEqual(result["target_paths"], ["child.py"])
        self.assertEqual(result["fallback"][0]["reason"], "parent_overlap")

    def test_project_child_merge_evidence_accepts_v2_ff_merged_shape(self):
        projected = orchestrator_ops.project_child_merge_evidence({
            "number": 40,
            "ff_merged": {"base": "task/issue-39", "sha_range": "aaa..bbb"},
        })

        self.assertEqual(projected["kind"], "ff_merged")
        self.assertEqual(projected["base"], "task/issue-39")
        self.assertEqual(projected["sha_range"], "aaa..bbb")
        self.assertTrue(projected["parent_contains_child"])


class MergeEdgeGearTests(unittest.TestCase):
    def test_gear_of_labels(self):
        self.assertEqual(orchestrator_ops.gear_of_labels(["gear:normal", "in-review"]), "normal")
        self.assertEqual(orchestrator_ops.gear_of_labels([{"name": "gear:major"}]), "major")
        self.assertIsNone(orchestrator_ops.gear_of_labels(["in-progress"]))
        self.assertIsNone(orchestrator_ops.gear_of_labels(None))

    def test_container_gear_promotion_max_of_children(self):
        self.assertEqual(orchestrator_ops.container_gear_promotion(["micro"]), "micro")
        self.assertEqual(orchestrator_ops.container_gear_promotion(["gear:normal"]), "normal")
        self.assertEqual(orchestrator_ops.container_gear_promotion(["micro", "major"]), "major")

    def test_container_gear_promotion_accumulates(self):
        # 3+ micro → normal
        self.assertEqual(orchestrator_ops.container_gear_promotion(["micro", "micro", "micro"]), "normal")
        self.assertEqual(orchestrator_ops.container_gear_promotion(["micro", "micro"]), "micro")
        # 2+ normal → major
        self.assertEqual(orchestrator_ops.container_gear_promotion(["normal", "normal"]), "major")
        self.assertEqual(orchestrator_ops.container_gear_promotion(["normal"]), "normal")

    def test_container_gear_promotion_defaults_unknown_to_micro(self):
        self.assertEqual(orchestrator_ops.container_gear_promotion([]), "micro")
        self.assertEqual(orchestrator_ops.container_gear_promotion([None, "weird"]), "micro")
        # An unlabeled child must not inflate the container.
        self.assertEqual(orchestrator_ops.container_gear_promotion([None, "normal"]), "normal")

    def test_ff_merge_command(self):
        self.assertEqual(
            orchestrator_ops.ff_merge_command(child_branch="task/issue-4", parent_branch="task/issue-2"),
            ["git", "fetch", ".", "task/issue-4:task/issue-2"],
        )

    def test_child_merge_evidence_accepts_ff_merged_with_sha_range(self):
        children = [
            {"number": 2, "ff_merged": {"base": "task/issue-1", "sha_range": "aaa..bbb"}},
            {"number": 3, "closed_no_pr": True},
        ]
        result = orchestrator_ops.child_merge_evidence(children, expected_base="task/issue-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])

    def test_child_merge_evidence_rejects_ff_merged_without_sha_range(self):
        children = [{"number": 2, "ff_merged": {"base": "task/issue-1"}}]
        result = orchestrator_ops.child_merge_evidence(children, expected_base="task/issue-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], [2])

    def test_child_merge_evidence_rejects_ff_merged_wrong_base(self):
        children = [{"number": 2, "ff_merged": {"base": "main", "sha_range": "aaa..bbb"}}]
        result = orchestrator_ops.child_merge_evidence(children, expected_base="task/issue-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], [2])

    def test_plan_tick_merge_container_carries_gear(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": True, "container_done": {"number": 5, "gear": "major"}},
            review_tool=None,
        )
        self.assertEqual(plan, {"action": "merge_container", "issue": 5, "gear": "major"})

    def test_plan_tick_merge_container_omits_absent_gear(self):
        plan = orchestrator_ops.plan_tick(
            {"ok": True, "container_done": {"number": 5}},
            review_tool=None,
        )
        self.assertEqual(plan, {"action": "merge_container", "issue": 5})

    def test_resolve_review_tool_off_by_default(self):
        self.assertEqual(
            orchestrator_ops.resolve_review_tool(enabled=False, directive_tool="x", config_tool="y"),
            {"mode": "off", "tool": None},
        )

    def test_resolve_review_tool_directive_beats_config(self):
        self.assertEqual(
            orchestrator_ops.resolve_review_tool(enabled=True, directive_tool="D", config_tool="C"),
            {"mode": "tool", "tool": "D"},
        )

    def test_resolve_review_tool_config_when_no_directive(self):
        self.assertEqual(
            orchestrator_ops.resolve_review_tool(enabled=True, config_tool="C"),
            {"mode": "tool", "tool": "C"},
        )

    def test_resolve_review_tool_harness_terminal(self):
        # Absent tool → harness (built-in challenge), NOT stop.
        self.assertEqual(
            orchestrator_ops.resolve_review_tool(enabled=True),
            {"mode": "harness", "tool": None},
        )
        # Blank/whitespace tool strings fall through to harness too.
        self.assertEqual(
            orchestrator_ops.resolve_review_tool(enabled=True, directive_tool="  ", config_tool=""),
            {"mode": "harness", "tool": None},
        )


if __name__ == "__main__":
    unittest.main()
