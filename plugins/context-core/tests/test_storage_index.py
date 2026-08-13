#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CLI_PATH = PLUGIN / "skills/context/scripts/context_cli.py"
SPEC = importlib.util.spec_from_file_location("context_cli", CLI_PATH)
assert SPEC and SPEC.loader
context_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_cli
SPEC.loader.exec_module(context_cli)


def git_repo() -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", temp.name], check=True)
    return temp


def initialize(repo: Path) -> None:
    result = context_cli.build_init_bundle(repo)
    context_cli.apply_bundle(repo, result["bundle"], result["approval_digest"])


def observation(
    identifier: str,
    title: str,
    summary: str,
    created_at: str = "2026-08-13T18:20:00+09:00",
) -> str:
    return context_cli.render_document(
        {
            "schema": "context-observation/v1",
            "id": identifier,
            "title": title,
            "summary": summary,
            "created_at": created_at,
            "captured_from": "workspace",
            "tags": ["auth"],
            "search_terms": ["cookie"],
            "claim_fingerprint": context_cli.claim_fingerprint("observation", "", title),
        },
        {"관찰": title, "근거": "workspace fixture evidence"},
    )


class StorageIndexTests(unittest.TestCase):
    def test_acceptance_03_natural_filename_and_id(self) -> None:
        self.assertEqual("인증-세션-BFF.md", context_cli.natural_filename(" 인증 세션 / BFF "))
        identifier = context_cli.new_context_id()
        self.assertRegex(identifier, r"^ctx_[0-9a-f]{32}$")
        self.assertTrue(context_cli.is_context_id(identifier))
        self.assertFalse(context_cli.natural_filename("인증 세션").startswith(("OBS-", "DEC-", "SNAP-")))

    def test_acceptance_04_path_collision(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            area = repo / "context/observation"
            (area / "Ａuth.md").write_text("fixture\n", encoding="utf-8")
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.resolve_artifact_path(repo, "observation", "Auth.md")
            self.assertEqual("path_exists", caught.exception.code)
            self.assertEqual(["observation.index.md", "retired", "Ａuth.md"], sorted(p.name for p in area.iterdir()))

    def test_acceptance_06_reserved_paths(self) -> None:
        invalid = ["../escape.md", "a/b.md", "a\\b.md", "observation.index.md", "CON.md", "x?.md", "x..md."]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(context_cli.ContextError):
                context_cli.validate_filename(value)

    def test_acceptance_07_index_determinism(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            path = repo / "context/observation/인증.md"
            path.write_text(observation("ctx_550e8400e29b41d4a716446655440000", "인증 관찰", "cookie 관찰"), encoding="utf-8")
            first = context_cli.render_area_index_from_repository(repo, "observation")
            (repo / "context/observation/observation.index.md").write_text(first, encoding="utf-8")
            second = context_cli.render_area_index_from_repository(repo, "observation")
            self.assertEqual(first.encode(), second.encode())
            self.assertNotIn('"path":"context/observation/observation.index.md"', first)

    def test_acceptance_08_stage1_has_zero_artifact_io(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            for index in range(2):
                identifier = f"ctx_550e8400e29b41d4a71644665544{index:04x}"
                (repo / f"context/observation/관찰-{index}.md").write_text(
                    observation(identifier, f"Cookie 관찰 {index}", f"Safari cookie evidence {index}"), encoding="utf-8"
                )
            index_path = repo / "context/observation/observation.index.md"
            index_path.write_text(context_cli.render_area_index_from_repository(repo, "observation"), encoding="utf-8")
            metrics = context_cli.IOMetrics()
            result = context_cli.recall_repository(repo, query="cookie", metrics=metrics)
            self.assertEqual(2, result["returned"])
            self.assertEqual(0, metrics.artifact_opens)
            self.assertEqual(0, metrics.artifact_directory_lists)
            self.assertEqual(0, metrics.artifact_stats)
            self.assertEqual(3, metrics.index_opens)

    def test_acceptance_09_index_fallback_and_strict(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            artifact = repo / "context/observation/관찰.md"
            artifact.write_text(observation("ctx_550e8400e29b41d4a716446655440000", "관찰", "근거"), encoding="utf-8")
            index_path = repo / "context/observation/observation.index.md"
            valid_seed = index_path.read_text(encoding="utf-8")
            index_path.write_text("broken\n", encoding="utf-8")
            result = context_cli.recall_repository(repo, query="관찰")
            self.assertTrue(result["index_fallback"])
            self.assertEqual(1, result["returned"])
            self.assertIn("area_index_invalid", result["warnings"])
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.recall_repository(repo, query="관찰", strict_index=True)
            self.assertEqual(6, caught.exception.exit_code)
            self.assertEqual("index_stale", caught.exception.code)

            index_path.write_text(valid_seed, encoding="utf-8")
            index_path.write_text(context_cli.render_area_index_from_repository(repo, "observation"), encoding="utf-8")
            moved = repo / "context/observation/renamed.md"
            artifact.rename(moved)
            selected = context_cli.recall_repository(
                repo,
                read_ids=["ctx_550e8400e29b41d4a716446655440000"],
            )
            self.assertTrue(selected["index_fallback"])
            self.assertEqual("context/observation/renamed.md", selected["items"][0]["path"])

    def test_acceptance_10_output_limit(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            for index in range(12):
                identifier = f"ctx_550e8400e29b41d4a71644665544{index:04x}"
                (repo / f"context/observation/long-{index}.md").write_text(
                    observation(identifier, f"긴 관찰 {index}", "a" * 120, f"2026-08-13T18:{index:02d}:00+09:00"),
                    encoding="utf-8",
                )
            index_path = repo / "context/observation/observation.index.md"
            index_path.write_text(context_cli.render_area_index_from_repository(repo, "observation"), encoding="utf-8")
            result = context_cli.recall_repository(repo, limit=12, max_bytes=900)
            self.assertTrue(result["truncated"])
            self.assertEqual(12 - result["returned"], result["omitted"])
            for item in result["items"]:
                self.assertEqual({"id", "kind", "state", "title", "summary", "path", "authority", "score"}, set(item))
            self.assertLessEqual(len(context_cli.canonical_json(result["items"]).encode()), 900)

    def test_acceptance_35_frontmatter_grammar(self) -> None:
        raw = """---
schema: \"context-observation/v1\"
id: \"ctx_550e8400e29b41d4a716446655440000\"
title: \"colon: comma, quote \\\"\"
summary: \"summary\"
created_at: \"2026-08-13T18:20:00+09:00\"
captured_from: \"workspace\"
unknown_z: {\"note\":\"kept\",\"flags\":[\"a\",\"b\"]}
---

## 관찰

claim

## 근거

evidence
"""
        document = context_cli.parse_document(raw)
        rendered = context_cli.render_document(document.frontmatter, document.sections)
        reparsed = context_cli.parse_document(rendered)
        self.assertEqual(document.frontmatter, reparsed.frontmatter)
        self.assertEqual({"note": "kept", "flags": ["a", "b"]}, reparsed.frontmatter["unknown_z"])
        duplicate = raw.replace('title: "colon: comma, quote \\\""', 'title: "one"\ntitle: "two"')
        with self.assertRaises(context_cli.ContextError):
            context_cli.parse_document(duplicate)
        unsupported = raw.replace('summary: "summary"', "summary: 123")
        with self.assertRaises(context_cli.ContextError):
            context_cli.parse_document(unsupported)

    def test_acceptance_39_strict_refresh_detects_drift(self) -> None:
        with git_repo() as temp:
            repo = Path(temp)
            initialize(repo)
            area = repo / "context/observation"
            first = area / "first.md"
            second = area / "second.md"
            first.write_text(observation("ctx_550e8400e29b41d4a716446655440000", "첫 관찰", "first"), encoding="utf-8")
            second.write_text(observation("ctx_550e8400e29b41d4a716446655440001", "둘 관찰", "second"), encoding="utf-8")
            index_path = area / "observation.index.md"
            index_path.write_text(context_cli.render_area_index_from_repository(repo, "observation"), encoding="utf-8")
            first.rename(area / "renamed.md")
            third = area / "third.md"
            third.write_text(observation("ctx_550e8400e29b41d4a716446655440002", "셋 관찰", "third"), encoding="utf-8")
            second.write_text(second.read_text(encoding="utf-8").replace("둘 관찰", "변경된 관찰"), encoding="utf-8")
            result = context_cli.refresh_repository(repo, strict=True)
            codes = {issue["code"] for issue in result["issues"]}
            self.assertTrue({"index_ghost_entry", "index_missing_entry", "index_content_drift"}.issubset(codes))
            self.assertEqual(3, len(list(p for p in area.glob("*.md") if not p.name.endswith(".index.md"))))

    def test_context_root_missing_is_storage_error(self) -> None:
        with git_repo() as temp:
            with self.assertRaises(context_cli.ContextError) as caught:
                context_cli.recall_repository(Path(temp))
            self.assertEqual("context_root_missing", caught.exception.code)
            self.assertEqual(3, caught.exception.exit_code)


if __name__ == "__main__":
    unittest.main()
