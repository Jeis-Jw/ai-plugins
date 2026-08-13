#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest import mock

import test_decision_schema as helpers


decision_cli = helpers.decision_cli


def pair(result: dict, *, current: bool = True) -> tuple[str, str]:
    drafts = [draft for draft in result["artifact_drafts"] if ("/retired/" not in draft["path"]) == current]
    assert len(drafts) == 1
    return drafts[0]["path"], drafts[0]["content"]


class DecisionRecallTests(unittest.TestCase):
    def test_acceptance_30_revisit(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            due_value = helpers.candidate(revisit_on="2026-08-13")
            due = helpers.claim_result(due_value)
            future_value = helpers.candidate(
                scope="project/payments",
                key="settlement-owner",
                decision="정산은 ledger service가 소유한다.",
                title="정산 소유권",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
                revisit_on="2027-01-01",
            )
            future = helpers.claim_result(future_value, identifier="ctx_123e4567e89b42d3a456426614174001")
            helpers.write_decision_area(repo, current=[pair(due), pair(future)])
            before = helpers.tree_digest(repo)
            result = decision_cli.revisit_decisions(repo, due=True, as_of="2026-08-14")
            self.assertEqual("2026-08-14", result["as_of"])
            self.assertEqual(["ctx_550e8400e29b41d4a716446655440000"], [item["id"] for item in result["items"]])
            self.assertTrue(result["items"][0]["due"])
            self.assertEqual("review_only", result["items"][0]["proposal"])
            self.assertFalse(result["state_changed"])
            self.assertEqual(before, helpers.tree_digest(repo))

    def test_stage1_search_is_index_only_and_brief_reads_selected_decisions(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            first = helpers.claim_result()
            second_value = helpers.candidate(
                scope="project/payments",
                key="settlement-owner",
                decision="정산은 ledger service가 소유한다.",
                title="정산 결정",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            second = helpers.claim_result(second_value, identifier="ctx_123e4567e89b42d3a456426614174001")
            helpers.write_decision_area(repo, current=[pair(first), pair(second)])
            with mock.patch.object(decision_cli, "_record", side_effect=AssertionError("Stage 1 opened an artifact")):
                search = decision_cli.search_decisions(repo, query="정산")
            self.assertEqual(["ctx_123e4567e89b42d3a456426614174001"], [item["id"] for item in search["items"]])

            opened: list[str] = []
            original = decision_cli._record

            def recording(repo_path, row):
                opened.append(row["id"])
                return original(repo_path, row)

            with mock.patch.object(decision_cli, "_record", side_effect=recording):
                brief = decision_cli.brief_decisions(repo, identifiers=["ctx_550e8400e29b41d4a716446655440000"])
            self.assertEqual(["ctx_550e8400e29b41d4a716446655440000"], opened)
            self.assertEqual(set(decision_cli.CORE_SECTIONS), set(brief["items"][0]["sections"]))

    def test_brief_is_bounded_to_8_kib_and_keeps_only_complete_items(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            current: list[tuple[str, str]] = []
            identifiers = (
                "ctx_550e8400e29b41d4a716446655440000",
                "ctx_123e4567e89b42d3a456426614174001",
                "ctx_987e6543e21b42d3a456426614174002",
            )
            for index, identifier in enumerate(identifiers):
                value = helpers.candidate(
                    scope=f"project/area{index}",
                    key=f"owner-{index}",
                    decision=f"결정 {index}: " + "가" * 180,
                    rationale="나" * 180,
                    alternatives=["다" * 180],
                    title=f"결정 {index}",
                    candidate_id=f"cand_550e8400e29b41d4a7164466554400{index:02d}",
                )
                current.append(pair(helpers.claim_result(value, identifier=identifier)))
            helpers.write_decision_area(repo, current=current)
            result = decision_cli.brief_decisions(repo, query="결정", max_bytes=1400)
            self.assertTrue(result["truncated"])
            self.assertGreater(result["omitted"], 0)
            self.assertLessEqual(len(decision_cli.canonical_json(result["items"]).encode("utf-8")), 1400)
            for item in result["items"]:
                self.assertEqual(set(decision_cli.CORE_SECTIONS), set(item["sections"]))
            with self.assertRaises(decision_cli.DecisionError):
                decision_cli.brief_decisions(repo, query="결정", max_bytes=8193)

    def test_history_brief_marks_do_not_follow_and_reason(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            active = helpers.claim_result()
            helpers.write_decision_area(repo, current=[pair(active)])
            withdrawn = decision_cli.build_withdraw_result(
                repo,
                "ctx_550e8400e29b41d4a716446655440000",
                "정책 변경",
                retired_at="2026-08-14T09:00:00+09:00",
            )
            history_path, history_content = pair(withdrawn, current=False)
            helpers.write_decision_area(repo, history=[(history_path, history_content)])
            result = decision_cli.brief_decisions(
                repo,
                identifiers=["ctx_550e8400e29b41d4a716446655440000"],
                include_history=True,
            )
            self.assertTrue(result["items"][0]["do_not_follow"])
            self.assertEqual("withdrawn", result["items"][0]["lifecycle_reason"])
            read = decision_cli.read_decision(repo, "ctx_550e8400e29b41d4a716446655440000")
            self.assertTrue(read["do_not_follow"])


if __name__ == "__main__":
    unittest.main()
