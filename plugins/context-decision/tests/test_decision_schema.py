#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/decision/scripts/decision_cli.py"
SPEC = importlib.util.spec_from_file_location("decision_cli", CLI_PATH)
assert SPEC and SPEC.loader
decision_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decision_cli
SPEC.loader.exec_module(decision_cli)


def git_repo() -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", temp.name], check=True)
    return temp


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def candidate(
    *,
    scope: str = "project/auth",
    key: str = "session-owner",
    decision: str = "인증 세션은 BFF가 소유한다.",
    rationale: str = "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
    alternatives: list[str] | None = None,
    title: str = "인증 세션 소유권",
    candidate_id: str = "cand_550e8400e29b41d4a716446655440000",
    revisit_on: str | None = None,
) -> dict:
    values = {
        "decision": decision,
        "rationale": rationale,
        "rejected_alternatives": alternatives or ["SPA token 소유: XSS 노출이 커져 반려"],
        "decision_key": key,
    }
    if revisit_on:
        values["revisit_on"] = revisit_on
    return {
        "schema": "context-capture-candidate/v1",
        "candidate_id": candidate_id,
        "claim_key": "choice-1",
        "title": title,
        "claim": decision,
        "summary": "OAuth callback과 cookie boundary를 한 경계로 통합한다.",
        "captured_from": "conversation",
        "requested_kind": "decision",
        "specialized_kinds": ["decision"],
        "fallback_kind": None,
        "scope_hint": scope,
        "source_refs": ["conversation:test"],
        "evidence": ["결정 권한자가 현재 따를 선택으로 확정했다."],
        "tags": ["auth"],
        "owner_inputs": {"decision": values},
    }


def attestation(value: dict, *, truth: bool = True) -> dict:
    return {
        "schema": "context-semantic-attestation/v1",
        "operation": "claim",
        "input_schema": value["schema"],
        "input_digest": decision_cli.canonical_digest(value),
        "assertions": [
            {"name": "explicit_choice", "value": truth, "evidence_pointers": ["/owner_inputs/decision/decision"]},
            {"name": "scope_identified", "value": truth, "evidence_pointers": ["/scope_hint"]},
            {"name": "commitment_present", "value": truth, "evidence_pointers": ["/evidence/0"]},
        ],
    }


def claim_result(
    value: dict | None = None,
    *,
    identifier: str = "ctx_550e8400e29b41d4a716446655440000",
    created_at: str = "2026-08-13T18:20:00+09:00",
    filename: str | None = None,
    repo: Path | None = None,
    acknowledgements: tuple[str, ...] = (),
) -> dict:
    value = value or candidate()
    return decision_cli.build_claim_result(
        value,
        attestation(value),
        identifier=identifier,
        created_at=created_at,
        filename=filename,
        repo=repo,
        acknowledged_conflicts=acknowledgements,
    )


def _entry(path: str, content: str, state: str) -> str:
    frontmatter, _ = decision_cli.parse_document(content)
    row = {
        "id": frontmatter["id"],
        "path": path,
        "title": frontmatter["title"],
        "summary": frontmatter["summary"],
        "state": state,
        "created_at": frontmatter["created_at"],
        "terms": list(frontmatter.get("tags", [])) + list(frontmatter.get("search_terms", [])),
    }
    if state == "history":
        row["retired_at"] = frontmatter["retired_at"]
        row["retired_reason"] = frontmatter["retired_reason"]
        if "superseded_by" in frontmatter:
            row["superseded_by"] = frontmatter["superseded_by"]
    for field in ("scope", "decision_key", "revisit_on"):
        if field in frontmatter:
            row[field] = frontmatter[field]
    visible = f"- [[{path[:-3]}]] — {frontmatter['title']} — {frontmatter['summary']}"
    return f"{visible} <!-- context-entry {json.dumps(row, ensure_ascii=False, separators=(',', ':'))} -->"


def write_decision_area(
    repo: Path,
    *,
    current: list[tuple[str, str]] | None = None,
    history: list[tuple[str, str]] | None = None,
) -> None:
    current = current or []
    history = history or []
    (repo / "context/decision/retired").mkdir(parents=True, exist_ok=True)
    for path, content in current + history:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    seed = decision_cli.decision_index_seed()
    current_rows = "\n".join(_entry(path, content, "current") for path, content in current)
    history_rows = "\n".join(_entry(path, content, "history") for path, content in history)
    seed = seed.replace(
        "<!-- BEGIN CONTEXT GENERATED:current -->\n<!-- END CONTEXT GENERATED:current -->",
        f"<!-- BEGIN CONTEXT GENERATED:current -->\n{current_rows + chr(10) if current_rows else ''}<!-- END CONTEXT GENERATED:current -->",
    )
    seed = seed.replace(
        "<!-- BEGIN CONTEXT GENERATED:history -->\n<!-- END CONTEXT GENERATED:history -->",
        f"<!-- BEGIN CONTEXT GENERATED:history -->\n{history_rows + chr(10) if history_rows else ''}<!-- END CONTEXT GENERATED:history -->",
    )
    (repo / decision_cli.DECISION_INDEX).write_text(seed, encoding="utf-8")


def bundle(result: dict, *, validation: dict | None = None, priors: list[str] | None = None) -> dict:
    owner_content = decision_cli.canonical_json(result)
    owner_digest = decision_cli.bytes_digest(owner_content.encode("utf-8"))
    plan = {
        "schema": "context-mutation-plan/v1",
        "plan_id": "plan_550e8400e29b41d4a716446655440000",
        "owner": "context-decision",
        "source_type": "owner_result",
        "owner_result_digest": owner_digest,
        "owner_result_material": "material_owner_result",
        "capability_digest": decision_cli.canonical_digest(decision_cli.decision_capability()),
        "transition": result["transition"],
        "owner_descriptor": {"owner": "context-decision", "kind": "decision", "artifact_schema": "context-decision/v1", "authority": "authoritative"},
        "owner_validation": validation,
        "prior_bundle_digests": list(priors or []),
        "read_preconditions": result["proposed_plan"].get("read_preconditions", []),
        "operations": [],
    }
    preview = {"schema": "context-approval-preview/v1", "owner": "context-decision", "candidate_id": result.get("candidate_id"), "artifacts": result["artifact_drafts"], "effects": result["effects"]}
    approval_material = {"preview": preview, "plan": plan}
    approval_digest = decision_cli.canonical_digest(approval_material)
    return {
        "schema": "context-mutation-bundle/v1",
        "approval_material": approval_material,
        "approval_digest": approval_digest,
        "materials": [{"material_id": "material_owner_result", "path": None, "content": owner_content}],
    }


class DecisionSchemaTests(unittest.TestCase):
    def test_acceptance_47_removed_fingerprint_fields_fail_closed(self) -> None:
        content = claim_result()["artifact_drafts"][0]["content"]
        for field in ("claim_fingerprint", "source_claim_fingerprint"):
            with self.subTest(field=field), self.assertRaises(decision_cli.DecisionError) as caught:
                decision_cli.parse_document(content.replace("schema: \"context-decision/v1\"\n", f"schema: \"context-decision/v1\"\n{field}: \"sha256:{'0' * 24}\"\n", 1))
            self.assertEqual("schema_removed_field", caught.exception.code)

    def test_acceptance_25_sections(self) -> None:
        valid = candidate()
        result = claim_result(valid)
        _, sections = decision_cli.parse_document(result["artifact_drafts"][0]["content"])
        self.assertEqual(set(decision_cli.CORE_SECTIONS), set(sections))

        for field in ("decision", "rationale"):
            invalid = candidate()
            invalid["owner_inputs"]["decision"][field] = "..."
            if field == "decision":
                invalid["claim"] = "..."
            with self.assertRaises(decision_cli.DecisionError):
                claim_result(invalid)
        invalid = candidate(alternatives=["TODO"])
        with self.assertRaises(decision_cli.DecisionError):
            claim_result(invalid)

    def test_requested_decision_does_not_bypass_semantic_validation(self) -> None:
        for label in ("idea", "question", "fact", "preference"):
            value = candidate(decision=f"{label} only")
            self.assertEqual("decision", value["requested_kind"])
            with self.assertRaises(decision_cli.DecisionError) as caught:
                decision_cli.build_claim_result(value, attestation(value, truth=False))
            self.assertEqual("semantic_attestation_invalid", caught.exception.code)
            declined = decision_cli.build_decline_result(value, f"{label} is not an accepted choice")
            self.assertEqual("decline", declined["decision"])
            self.assertEqual([], declined["artifact_drafts"])

    def test_complete_draft_binds_candidate_attestation_and_digest(self) -> None:
        value = candidate()
        result = claim_result(value)
        decision_cli.validate_owner_result(result)
        self.assertEqual(value, result["semantic_inputs"][0]["value"])
        self.assertEqual(decision_cli.canonical_digest(value), result["semantic_attestations"][0]["input_digest"])
        altered = json.loads(json.dumps(result))
        altered["semantic_inputs"][0]["value"]["summary"] += " altered"
        with self.assertRaises(decision_cli.DecisionError):
            decision_cli.validate_owner_result(altered)

    def test_acceptance_36_scope_key(self) -> None:
        variants = [
            ("Project/Auth/", "Session Owner"),
            (" project / auth ", "session_owner"),
            ("ＰＲＯＪＥＣＴ/AUTH", "SESSION-OWNER"),
        ]
        for scope, key in variants:
            self.assertEqual("project/auth", decision_cli.canonical_scope(scope))
            self.assertEqual("session-owner", decision_cli.canonical_decision_key(key))
        self.assertTrue(decision_cli.is_ancestor_scope("project", "project/auth"))
        self.assertFalse(decision_cli.is_ancestor_scope("project/a", "project/auth"))
        self.assertFalse(decision_cli.is_ancestor_scope("project/auth", "project/auth"))
        with self.assertRaises(decision_cli.DecisionError):
            decision_cli.canonical_scope("project//auth")
        with self.assertRaises(decision_cli.DecisionError):
            decision_cli.canonical_decision_key("session/owner")

    def test_decision_owner_is_stdlib_only_and_has_no_write_primitive(self) -> None:
        module = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
        allowed = {"__future__", "argparse", "datetime", "hashlib", "json", "pathlib", "re", "subprocess", "sys", "typing", "unicodedata", "uuid"}
        imported = set()
        banned_attributes = {"write_text", "write_bytes", "mkdir", "rename", "unlink", "rmdir", "touch"}
        seen_banned = set()
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Attribute) and node.attr in banned_attributes:
                seen_banned.add(node.attr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                seen_banned.add("open")
        self.assertFalse(imported - allowed, imported - allowed)
        self.assertEqual(set(), seen_banned)


if __name__ == "__main__":
    unittest.main()
