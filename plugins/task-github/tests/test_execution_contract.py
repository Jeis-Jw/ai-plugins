import sys
import unittest
from pathlib import Path

TASK_GITHUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_GITHUB / "scripts"))
sys.path.insert(0, str(TASK_GITHUB / "skills" / "define" / "scripts"))

import context_bundle  # noqa: E402
import create_issue_tree  # noqa: E402


class ExecutionContractTests(unittest.TestCase):
    def test_contract_round_trip_ignores_unknown_keys(self):
        block = context_bundle.render_execution_contract({
            "wiki_task": "TASK-2026-06-26-024108-task-github-개선",
            "topology": "stacked",
            "gate": "local-merge",
            "parent_branch": "task/root-10",
            "leaf_policy": {"risk_class": "normal"},
            "required_checks": [["python3", "-m", "pytest", "plugins/task-github/tests/", "-q"]],
            "closeout_mode": "local",
            "future_key": "ignored",
        })

        parsed = context_bundle.parse_execution_contract("body\n" + block)

        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["topology"], "stacked")
        self.assertEqual(parsed["gate"], "local-merge")
        self.assertEqual(parsed["parent_branch"], "task/root-10")
        self.assertNotIn("future_key", parsed)
        self.assertEqual(
            sorted(parsed.keys()),
            sorted(["schema_version", *context_bundle.EXECUTION_CONTRACT_KEYS]),
        )

    def test_bundle_reads_contract_from_root_body(self):
        contract = context_bundle.render_execution_contract({
            "topology": "flat",
            "gate": "pr",
            "parent_branch": "main",
            "closeout_mode": "pr",
        })
        root = {
            "number": 10,
            "state": "OPEN",
            "body": "## Wiki Context\n[[TASK-2026-06-26-024108-task-github-개선]]\n" + contract,
        }

        bundle = context_bundle.build_context_bundle(issue=root, root=root)

        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["topology"], "flat")
        self.assertEqual(bundle["gate"], "pr")
        self.assertEqual(bundle["parent_branch"], "main")
        self.assertIsNone(bundle["default_source"])
        self.assertEqual(bundle["execution_contract"]["closeout_mode"], "pr")

    def test_create_issue_tree_materializes_root_execution_contract(self):
        spec = {
            "root": {
                "title": "root",
                "body": "## Wiki Context\n[[TASK-2026-06-26-024108-task-github-개선]]",
                "execution_contract": {
                    "topology": "stacked",
                    "gate": "local-merge",
                    "parent_branch": "task/root-10",
                    "closeout_mode": "local",
                },
            },
            "children": [],
        }

        validated = create_issue_tree.validate_spec(spec)

        parsed = context_bundle.parse_execution_contract(validated["root"]["body"])
        self.assertEqual(parsed["topology"], "stacked")
        self.assertEqual(parsed["gate"], "local-merge")

    def test_strict_deps_preserved_in_plan(self):
        spec = {
            "strict_deps": True,
            "root": {"title": "root", "body": "root body"},
            "children": [
                {
                    "key": "a",
                    "title": "A",
                    "body": "완료 기준\n검증\n영향 경로: a.py",
                    "affects_paths": ["a.py"],
                },
                {
                    "key": "b",
                    "title": "B",
                    "body": "완료 기준\n검증\n영향 경로: b.py",
                    "affects_paths": ["b.py"],
                    "blocked_by": ["a"],
                },
            ],
        }

        plan = create_issue_tree.build_plan(create_issue_tree.validate_spec(spec))

        self.assertTrue(plan["strict_deps"])

    def test_strict_dependency_failure_raises_instead_of_comment_fallback(self):
        calls = []

        def fake_gh(args):
            calls.append(args)
            if args[:2] == ["api", "-H"]:
                return "99"
            if args[:3] == ["api", "-X", "POST"]:
                raise create_issue_tree.IssueTreeError("gh_failed", "dependency unavailable")
            return ""

        with self.assertRaises(create_issue_tree.IssueTreeError) as ctx:
            create_issue_tree.add_dependency("o", "r", 2, 1, strict=True, gh_func=fake_gh)

        self.assertEqual(ctx.exception.error_code, "dep_create_failed")
        self.assertFalse(any(args[:2] == ["issue", "comment"] for args in calls))


def _leaf(key, parent=None, paths=None, blocked_by=None):
    return {
        "key": key,
        "title": key,
        "body": f"완료 기준: x\n검증: y\n영향 경로: {key}.py",
        "parent": parent,
        "affects_paths": paths or [f"{key}.py"],
        "blocked_by": blocked_by or [],
    }


class TreeShapeTests(unittest.TestCase):
    def _root(self, topology="stacked"):
        return {
            "title": "root",
            "body": "root body",
            "execution_contract": {"topology": topology, "gate": "local-merge",
                                   "parent_branch": "task/root-10", "closeout_mode": "local"},
        }

    def test_flat_spec_regresses_clean(self):
        # No parent keys → every child is a leaf, full gate, no epics/warnings.
        spec = {"root": {"title": "r", "body": "b"},
                "children": [_leaf("a"), _leaf("b", blocked_by=["a"])]}
        validated = create_issue_tree.validate_spec(spec)
        self.assertEqual(validated["epics"], [])
        self.assertEqual(validated["warnings"], [])

    def test_parent_pointer_classifies_epic_and_builds_depth3_plan(self):
        spec = {
            "root": self._root(),
            "children": [
                {"key": "BE", "title": "BE", "body": "백엔드 트랙", "parent": None},
                _leaf("BE-AUTH", parent="BE", paths=["api/auth.py"]),
                _leaf("BE-ORDER", parent="BE", paths=["api/order.py"], blocked_by=["BE-AUTH"]),
            ],
        }
        validated = create_issue_tree.validate_spec(spec)
        self.assertEqual(validated["epics"], ["BE"])
        self.assertEqual(validated["warnings"], [])  # has epic → no stacked/flat warning
        plan = create_issue_tree.build_plan(validated)
        # cross-level dependency survives
        self.assertIn({"child": "BE-ORDER", "blocked_by": "BE-AUTH"}, plan["dependencies"])

    def test_epic_skips_leaf_quality_gate_and_overlap(self):
        # Epic body need not carry 완료기준/검증, and an epic with no
        # affects_paths never triggers path-overlap against its own children.
        spec = {
            "root": self._root(),
            "children": [
                {"key": "BE", "title": "BE", "body": "그냥 컨테이너", "parent": None},
                _leaf("BE-X", parent="BE", paths=["api/x.py"]),
            ],
        }
        validated = create_issue_tree.validate_spec(spec)  # must not raise
        self.assertEqual(validated["epics"], ["BE"])

    def test_cross_tree_blocked_by_resolves(self):
        spec = {
            "root": self._root(),
            "children": [
                {"key": "BE", "title": "BE", "body": "be", "parent": None},
                {"key": "FE", "title": "FE", "body": "fe", "parent": None},
                _leaf("BE-PAY", parent="BE", paths=["api/pay.py"]),
                _leaf("FE-PAY", parent="FE", paths=["mobile/pay.py"], blocked_by=["BE-PAY"]),
            ],
        }
        validated = create_issue_tree.validate_spec(spec)
        self.assertEqual(validated["epics"], ["BE", "FE"])

    def test_stacked_flat_tree_warns(self):
        spec = {"root": self._root("stacked"), "children": [_leaf("a"), _leaf("b")]}
        validated = create_issue_tree.validate_spec(spec)
        self.assertTrue(validated["warnings"])
        self.assertEqual(validated["warnings"][0]["code"], "stacked_without_epics")
        self.assertIn("epic", validated["warnings"][0]["message"])

    def test_flat_single_signal_does_not_warn(self):
        # 6 leaves but a single path cluster ("apps/api") → only leaf_count fires.
        spec = {
            "root": self._root("flat"),
            "children": [_leaf(f"L{i}", paths=[f"apps/api/{i}.py"]) for i in range(6)],
        }
        validated = create_issue_tree.validate_spec(spec)
        self.assertEqual(validated["warnings"], [])

    def test_flat_maybe_understructured_warns_on_two_signals(self):
        # leaf_count>=6 AND path_clusters>=3 (auth/wallet/qr/ops).
        spec = {
            "root": self._root("flat"),
            "children": [
                _leaf("AUTH-1", paths=["apps/auth/a.py"]),
                _leaf("AUTH-2", paths=["apps/auth/b.py"]),
                _leaf("WALLET-1", paths=["apps/wallet/a.py"]),
                _leaf("WALLET-2", paths=["apps/wallet/b.py"]),
                _leaf("QR-1", paths=["apps/qr/a.py"]),
                _leaf("OPS-1", paths=["apps/ops/a.py"]),
            ],
        }
        validated = create_issue_tree.validate_spec(spec)
        self.assertEqual(len(validated["warnings"]), 1)
        warning = validated["warnings"][0]
        self.assertEqual(warning["code"], "flat_maybe_understructured")
        self.assertEqual(
            warning["suggested_epics"],
            ["apps/auth", "apps/ops", "apps/qr", "apps/wallet"],
        )

    def test_flat_cross_cluster_dependency_signal(self):
        # Only 4 leaves / 2 clusters (below leaf_count and cluster thresholds),
        # but 2 cross-cluster blocked_by edges plus the cluster signal (>=... no,
        # 2 clusters < 3) — combine cross_cluster_deps with domain keyword repeats
        # to reach the 2-signal threshold.
        spec = {
            "root": self._root("flat"),
            "children": [
                _leaf("BE-1", paths=["apps/api/a.py"]),
                _leaf("BE-2", paths=["apps/api/b.py"]),
                _leaf("FE-1", paths=["apps/mobile/a.py"], blocked_by=["BE-1"]),
                _leaf("FE-2", paths=["apps/mobile/b.py"], blocked_by=["BE-2"]),
            ],
        }
        for child in spec["children"]:
            child["title"] = "backend" if child["key"].startswith("BE") else "mobile"
        validated = create_issue_tree.validate_spec(spec)
        self.assertEqual(len(validated["warnings"]), 1)
        self.assertEqual(validated["warnings"][0]["code"], "flat_maybe_understructured")

    def test_unknown_parent_rejected(self):
        spec = {"root": self._root(), "children": [_leaf("a", parent="ghost")]}
        with self.assertRaises(create_issue_tree.IssueTreeError) as ctx:
            create_issue_tree.validate_spec(spec)
        self.assertEqual(ctx.exception.error_code, "unknown_parent")

    def test_parent_cycle_rejected(self):
        spec = {
            "root": self._root(),
            "children": [
                {"key": "a", "title": "a", "body": "a", "parent": "b"},
                {"key": "b", "title": "b", "body": "b", "parent": "a"},
            ],
        }
        with self.assertRaises(create_issue_tree.IssueTreeError) as ctx:
            create_issue_tree.validate_spec(spec)
        self.assertEqual(ctx.exception.error_code, "parent_cycle")

    def test_topo_order_places_parents_first(self):
        children = [
            {"key": "leaf", "parent": "epic"},
            {"key": "epic", "parent": None},
        ]
        ordered = [c["key"] for c in create_issue_tree._topo_order(children)]
        self.assertLess(ordered.index("epic"), ordered.index("leaf"))

    def test_execute_passes_epic_node_id_to_grandchild(self):
        captured = []

        def fake_repo_context():
            return ("o", "r", "REPO")

        def fake_create_root_issue(root):
            return 100

        def fake_issue_node_id(owner, repo, number):
            return f"ND-{number}"

        counter = {"n": 100}

        def fake_create_child_issue(repo_id, parent_id, child):
            counter["n"] += 1
            captured.append((child["key"], parent_id, counter["n"]))
            return counter["n"]

        orig = {name: getattr(create_issue_tree, name) for name in
                ("repo_context", "create_root_issue", "issue_node_id", "create_child_issue")}
        create_issue_tree.repo_context = fake_repo_context
        create_issue_tree.create_root_issue = fake_create_root_issue
        create_issue_tree.issue_node_id = fake_issue_node_id
        create_issue_tree.create_child_issue = fake_create_child_issue
        try:
            spec = create_issue_tree.validate_spec({
                "root": self._root(),
                "children": [
                    {"key": "BE", "title": "BE", "body": "be", "parent": None},
                    _leaf("BE-AUTH", parent="BE", paths=["api/auth.py"]),
                ],
            })
            create_issue_tree.execute(spec)
        finally:
            for name, fn in orig.items():
                setattr(create_issue_tree, name, fn)

        parents = {key: parent_id for key, parent_id, _ in captured}
        be_number = next(n for key, _, n in captured if key == "BE")
        self.assertEqual(parents["BE"], "ND-100")             # epic → root node
        self.assertEqual(parents["BE-AUTH"], f"ND-{be_number}")  # grandchild → epic node


if __name__ == "__main__":
    unittest.main()
