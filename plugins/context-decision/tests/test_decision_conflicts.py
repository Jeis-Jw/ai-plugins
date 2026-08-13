#!/usr/bin/env python3
from __future__ import annotations

import unittest

import test_decision_schema as helpers


decision_cli = helpers.decision_cli


def draft_pair(result: dict) -> tuple[str, str]:
    draft = result["artifact_drafts"][0]
    return draft["path"], draft["content"]


class DecisionConflictTests(unittest.TestCase):
    def test_acceptance_26_duplicate_slot(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            existing = helpers.claim_result()
            helpers.write_decision_area(repo, current=[draft_pair(existing)])
            second_value = helpers.candidate(
                decision="인증 세션은 API gateway가 소유한다.",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            second = helpers.claim_result(second_value, identifier="ctx_550e8400e29b41d4a716446655440001")
            with self.assertRaises(decision_cli.DecisionError) as physical:
                decision_cli.validate_batch(repo, second)
            self.assertEqual("decision_slot_conflict", physical.exception.code)

        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            helpers.write_decision_area(repo)
            first = helpers.claim_result()
            first_bundle = helpers.bundle(first)
            second_value = helpers.candidate(
                decision="인증 세션은 API gateway가 소유한다.",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            second = helpers.claim_result(second_value, identifier="ctx_550e8400e29b41d4a716446655440001")
            with self.assertRaises(decision_cli.DecisionError) as virtual:
                decision_cli.validate_batch(repo, second, [first_bundle])
            self.assertEqual("decision_slot_conflict", virtual.exception.code)

    def test_duplicate_fingerprint_is_independent_of_decision_key(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            existing = helpers.claim_result()
            helpers.write_decision_area(repo, current=[draft_pair(existing)])
            duplicate_value = helpers.candidate(
                key="auth-owner-alias",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            duplicate = helpers.claim_result(duplicate_value, identifier="ctx_550e8400e29b41d4a716446655440001")
            with self.assertRaises(decision_cli.DecisionError) as caught:
                decision_cli.validate_batch(repo, duplicate)
            self.assertEqual("duplicate_claim", caught.exception.code)

    def test_acceptance_27_scope_overlap(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            existing = helpers.claim_result()
            existing_path, existing_content = draft_pair(existing)
            helpers.write_decision_area(repo, current=[(existing_path, existing_content)])
            ancestor_value = helpers.candidate(
                scope="project",
                decision="프로젝트 인증 세션은 서버 경계가 소유한다.",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            unacknowledged = helpers.claim_result(ancestor_value, identifier="ctx_550e8400e29b41d4a716446655440001")
            conflicts = decision_cli.conflict_candidates(repo, "project", "session-owner")
            self.assertEqual(["ctx_550e8400e29b41d4a716446655440000"], [item["id"] for item in conflicts["overlap"]])
            with self.assertRaises(decision_cli.DecisionError) as caught:
                decision_cli.validate_batch(repo, unacknowledged)
            self.assertEqual("conflict_ack_required", caught.exception.code)

            acknowledged = helpers.claim_result(
                ancestor_value,
                identifier="ctx_550e8400e29b41d4a716446655440001",
                repo=repo,
                acknowledgements=("ctx_550e8400e29b41d4a716446655440000",),
            )
            receipt = decision_cli.validate_batch(repo, acknowledged)
            self.assertEqual(["ctx_550e8400e29b41d4a716446655440000"], receipt["validated_facts"]["acknowledged_conflicts"])
            self.assertEqual(decision_cli.canonical_digest({key: value for key, value in receipt.items() if key != "receipt_digest"}), receipt["receipt_digest"])

    def test_same_batch_overlap_requires_virtual_read_precondition(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            helpers.write_decision_area(repo)
            child = helpers.claim_result()
            child_bundle = helpers.bundle(child)
            parent_value = helpers.candidate(
                scope="project",
                decision="프로젝트 인증 세션은 서버가 소유한다.",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            parent = helpers.claim_result(parent_value, identifier="ctx_550e8400e29b41d4a716446655440001")
            virtual_conflict = child["artifact_drafts"][0]
            parent["effects"][0]["acknowledged_conflicts"] = ["ctx_550e8400e29b41d4a716446655440000"]
            parent["proposed_plan"]["read_preconditions"] = [{
                "id": "ctx_550e8400e29b41d4a716446655440000",
                "path": virtual_conflict["path"],
                "sha256": decision_cli.file_digest(virtual_conflict["content"]),
            }]
            receipt = decision_cli.validate_batch(repo, parent, [child_bundle])
            self.assertEqual([child_bundle["approval_digest"]], receipt["prior_same_area_bundle_digests"])

            parent["proposed_plan"]["read_preconditions"][0]["sha256"] = "sha256:" + "0" * 64
            with self.assertRaises(decision_cli.DecisionError) as caught:
                decision_cli.validate_batch(repo, parent, [child_bundle])
            self.assertEqual("conflict_read_precondition_required", caught.exception.code)

    def test_receipt_binds_exact_ordered_prior_chain(self) -> None:
        with helpers.git_repo() as temp:
            repo = helpers.Path(temp)
            helpers.write_decision_area(repo)
            first = helpers.claim_result()
            first_bundle = helpers.bundle(first)
            second_value = helpers.candidate(
                scope="project/payments",
                key="settlement-owner",
                decision="정산은 ledger service가 소유한다.",
                title="정산 소유권",
                candidate_id="cand_550e8400e29b41d4a716446655440001",
            )
            second = helpers.claim_result(second_value, identifier="ctx_550e8400e29b41d4a716446655440001")
            second_bundle = helpers.bundle(second, priors=[first_bundle["approval_digest"]])
            third_value = helpers.candidate(
                scope="project/notifications",
                key="delivery-owner",
                decision="알림 전송은 notification service가 소유한다.",
                title="알림 전송 소유권",
                candidate_id="cand_550e8400e29b41d4a716446655440002",
            )
            third = helpers.claim_result(third_value, identifier="ctx_550e8400e29b41d4a716446655440002")
            receipt = decision_cli.validate_batch(repo, third, [first_bundle, second_bundle])
            self.assertEqual([first_bundle["approval_digest"], second_bundle["approval_digest"]], receipt["prior_same_area_bundle_digests"])
            with self.assertRaises(decision_cli.DecisionError) as caught:
                decision_cli.validate_batch(repo, third, [second_bundle, first_bundle])
            self.assertEqual("prior_bundle_order_invalid", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
