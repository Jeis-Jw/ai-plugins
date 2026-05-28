import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "wiki" / "scripts" / "wiki_cli.py"


def run_cli(*args, cwd=None, env=None):
    command = [sys.executable, str(CLI), *args]
    merged_env = os.environ.copy()
    merged_env.update(env or {})
    return subprocess.run(
        command,
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class WikiCliTests(unittest.TestCase):
    def test_init_creates_wiki_vault_and_indexes_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("init", cwd=tmp)

            self.assertEqual(result.returncode, 0, result.stderr)
            vault = Path(tmp) / "wiki"
            self.assertTrue((vault / "README.md").exists())
            self.assertTrue((vault / "ssot" / "ssot.md").exists())
            self.assertTrue((vault / "context" / "decision" / "retired").is_dir())
            self.assertTrue((vault / "context" / "observation" / "observation.md").exists())
            self.assertTrue((vault / "context" / "observation" / "retired").is_dir())
            self.assertFalse((Path(tmp) / "docs").exists())

            second = run_cli("init", cwd=tmp)
            self.assertEqual(second.returncode, 0, second.stderr)

    def test_dry_run_write_commands_do_not_modify_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dry_init = run_cli("init", "--dry-run", cwd=tmp)
            self.assertEqual(dry_init.returncode, 0, dry_init.stderr)
            self.assertFalse((Path(tmp) / "wiki").exists())

            run_cli("init", cwd=tmp)
            env_old = {"WIKI_NOW": "2026-04-17T14:30:52"}
            env_new = {"WIKI_NOW": "2026-05-01T09:00:00"}
            run_cli(
                "capture",
                "decision",
                "--title",
                "Old Auth Choice",
                "--summary",
                "Old auth choice.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env_old,
            )
            run_cli(
                "capture",
                "decision",
                "--title",
                "New Auth Choice",
                "--summary",
                "New auth choice.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env_new,
            )

            old_id = "DEC-2026-04-17-143052-old-auth-choice"
            new_id = "DEC-2026-05-01-090000-new-auth-choice"
            result = run_cli(
                "retire",
                old_id,
                "--type",
                "superseded",
                "--superseded-by",
                new_id,
                "--dry-run",
                cwd=tmp,
                env=env_new,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(tmp) / "wiki" / "context" / "decision" / f"{old_id}.md").exists())
            self.assertFalse((Path(tmp) / "wiki" / "context" / "decision" / "retired" / f"{old_id}.md").exists())
            self.assertNotIn(
                "supersedes",
                (Path(tmp) / "wiki" / "context" / "decision" / f"{new_id}.md").read_text(),
            )

    def test_capture_uses_timestamp_ids_and_rejects_hub_relations(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)

            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            intent = run_cli(
                "capture",
                "intent",
                "--title",
                "Signup Speed",
                "--summary",
                "Reduce signup friction.",
                "--tags",
                "growth,conversion",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(intent.returncode, 0, intent.stderr)
            intent_id = "INT-2026-04-17-143052-signup-speed"
            self.assertTrue((Path(tmp) / "wiki" / "context" / "intent" / f"{intent_id}.md").exists())

            decision = run_cli(
                "capture",
                "decision",
                "--title",
                "Switch to BFF",
                "--summary",
                "Move session ownership to the BFF.",
                "--tags",
                "auth,architecture",
                "--intents",
                "signup-speed",
                "--tasks",
                "owner/repo#18",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(decision.returncode, 0, decision.stderr)
            decision_path = Path(tmp) / "wiki" / "context" / "decision" / "DEC-2026-04-17-143052-switch-to-bff.md"
            self.assertTrue(decision_path.exists())
            text = decision_path.read_text()
            self.assertIn("relations:", text)
            self.assertIn(f"intents: [{intent_id}]", text)
            self.assertNotIn("id:", text)
            self.assertIn("- [[DEC-2026-04-17-143052-switch-to-bff]]", (Path(tmp) / "wiki" / "context" / "decision" / "decision.md").read_text())

            bad = run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "Current auth design.",
                "--tags",
                "auth",
                "--intents",
                intent_id,
                cwd=tmp,
                env=env,
            )
            self.assertEqual(bad.returncode, 2)

    def test_record_basename_collision_appends_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            first = run_cli(
                "capture",
                "decision",
                "--title",
                "Switch to BFF",
                "--summary",
                "First.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(
                "capture",
                "decision",
                "--title",
                "Switch to BFF",
                "--summary",
                "Second.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            decision_dir = Path(tmp) / "wiki" / "context" / "decision"
            self.assertTrue((decision_dir / "DEC-2026-04-17-143052-switch-to-bff.md").exists())
            self.assertTrue((decision_dir / "DEC-2026-04-17-143052-switch-to-bff-b.md").exists())

    def test_living_slug_conflict_exits_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            ok = run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "First.",
                "--tags",
                "auth",
                cwd=tmp,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            dup = run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "Second.",
                "--tags",
                "auth",
                cwd=tmp,
            )
            self.assertEqual(dup.returncode, 5)

    def test_capture_observation_metadata_and_rejects_invalid_v1_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            ssot = run_cli(
                "capture",
                "ssot",
                "--title",
                "Webhook Architecture",
                "--summary",
                "Current webhook processing architecture.",
                "--tags",
                "webhook,architecture",
                "--verified-at",
                "2026-05-28",
                "--affects-paths",
                "src/webhook/**",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(ssot.returncode, 0, ssot.stderr)
            runbook = run_cli(
                "capture",
                "runbook",
                "--title",
                "Webhook Deploy",
                "--summary",
                "Webhook deployment procedure.",
                "--tags",
                "webhook,deploy",
                "--verified-at",
                "2026-05-28",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(runbook.returncode, 0, runbook.stderr)
            decision = run_cli(
                "capture",
                "decision",
                "--title",
                "Async Webhook Handler",
                "--summary",
                "Handle webhooks asynchronously.",
                "--tags",
                "webhook,reliability",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(decision.returncode, 0, decision.stderr)

            observation = run_cli(
                "capture",
                "observation",
                "--title",
                "Webhook Timeout Risk",
                "--summary",
                "External webhooks may exceed request time limits.",
                "--tags",
                "webhook,reliability",
                "--verified-at",
                "2026-05-28",
                "--affects-paths",
                "src/webhook/**",
                "--search-terms",
                "timeout,latency",
                "--ssot",
                "webhook-architecture",
                "--runbook",
                "webhook-deploy",
                "--decisions",
                "async-webhook-handler",
                "--tasks",
                "owner/repo#42",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(observation.returncode, 0, observation.stderr)

            obs_id = "OBS-2026-05-28-153000-webhook-timeout-risk"
            obs_path = Path(tmp) / "wiki" / "context" / "observation" / f"{obs_id}.md"
            self.assertTrue(obs_path.exists())
            text = obs_path.read_text()
            self.assertIn("affects_paths: [src/webhook/**]", text)
            self.assertIn("search_terms: [timeout, latency]", text)
            self.assertIn("ssot: [webhook-architecture]", text)
            self.assertIn("runbook: [webhook-deploy]", text)
            self.assertIn("decisions: [DEC-2026-05-28-153000-async-webhook-handler]", text)
            self.assertIn("## 후속 분류 조건", text)

            bad_verified = run_cli(
                "capture",
                "decision",
                "--title",
                "Bad Verified",
                "--summary",
                "Decision cannot carry verified_at.",
                "--tags",
                "webhook",
                "--verified-at",
                "2026-05-28",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(bad_verified.returncode, 2)

            bad_relation = run_cli(
                "capture",
                "observation",
                "--title",
                "Bad Observation Relation",
                "--summary",
                "Observation cannot point directly to intents.",
                "--tags",
                "webhook",
                "--intents",
                "some-intent",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(bad_relation.returncode, 2)

    def test_retire_supersede_moves_record_and_updates_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env_old = {"WIKI_NOW": "2026-04-17T14:30:52"}
            env_new = {"WIKI_NOW": "2026-05-01T09:00:00"}
            run_cli(
                "capture",
                "decision",
                "--title",
                "Old Auth Choice",
                "--summary",
                "Old auth choice.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env_old,
            )
            run_cli(
                "capture",
                "decision",
                "--title",
                "New Auth Choice",
                "--summary",
                "New auth choice.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env_new,
            )

            old_id = "DEC-2026-04-17-143052-old-auth-choice"
            new_id = "DEC-2026-05-01-090000-new-auth-choice"
            retired = run_cli("retire", old_id, "--type", "superseded", "--superseded-by", new_id, cwd=tmp, env=env_new)
            self.assertEqual(retired.returncode, 0, retired.stderr)

            old_path = Path(tmp) / "wiki" / "context" / "decision" / "retired" / f"{old_id}.md"
            new_path = Path(tmp) / "wiki" / "context" / "decision" / f"{new_id}.md"
            self.assertTrue(old_path.exists())
            self.assertIn("retired_type: superseded", old_path.read_text())
            self.assertIn(f"superseded_by: {new_id}", old_path.read_text())
            self.assertIn(f"supersedes: [{old_id}]", new_path.read_text())
            self.assertNotIn(old_id, (Path(tmp) / "wiki" / "context" / "decision" / "decision.md").read_text())

    def test_retire_deprecated_moves_without_successor(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture",
                "trial_error",
                "--title",
                "False Alarm",
                "--summary",
                "Turned out to be wrong.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env,
            )
            tri_id = "TRI-2026-04-17-143052-false-alarm"
            result = run_cli("retire", tri_id, "--type", "deprecated", cwd=tmp, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            retired_path = Path(tmp) / "wiki" / "context" / "trial_error" / "retired" / f"{tri_id}.md"
            self.assertTrue(retired_path.exists())
            text = retired_path.read_text()
            self.assertIn("retired_type: deprecated", text)
            self.assertNotIn("superseded_by", text)

            run_cli(
                "capture",
                "trial_error",
                "--title",
                "Another False Alarm",
                "--summary",
                "Also wrong.",
                "--tags",
                "auth",
                cwd=tmp,
                env={"WIKI_NOW": "2026-04-17T14:30:53"},
            )
            forbidden = run_cli(
                "retire",
                "TRI-2026-04-17-143053-another-false-alarm",
                "--type",
                "deprecated",
                "--superseded-by",
                "whatever",
                cwd=tmp,
            )
            self.assertEqual(forbidden.returncode, 2)

    def test_superseded_by_must_be_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture",
                "decision",
                "--title",
                "Old",
                "--summary",
                "Old.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env,
            )
            run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "Current.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env,
            )
            result = run_cli(
                "retire",
                "DEC-2026-04-17-143052-old",
                "--type",
                "superseded",
                "--superseded-by",
                "auth-architecture",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 2)

    def test_observation_can_be_superseded_by_another_record_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env_obs = {"WIKI_NOW": "2026-05-28T15:30:00"}
            env_tri = {"WIKI_NOW": "2026-06-03T09:30:00"}
            run_cli(
                "capture",
                "observation",
                "--title",
                "Webhook Timeout Risk",
                "--summary",
                "Webhook timeout risk observed.",
                "--tags",
                "webhook",
                cwd=tmp,
                env=env_obs,
            )
            run_cli(
                "capture",
                "trial_error",
                "--title",
                "Webhook Timeout Handler",
                "--summary",
                "Webhook timeout needs async handling.",
                "--tags",
                "webhook",
                cwd=tmp,
                env=env_tri,
            )

            old_id = "OBS-2026-05-28-153000-webhook-timeout-risk"
            new_id = "TRI-2026-06-03-093000-webhook-timeout-handler"
            result = run_cli("retire", old_id, "--type", "superseded", "--superseded-by", new_id, cwd=tmp, env=env_tri)
            self.assertEqual(result.returncode, 0, result.stderr)

            old_path = Path(tmp) / "wiki" / "context" / "observation" / "retired" / f"{old_id}.md"
            new_path = Path(tmp) / "wiki" / "context" / "trial_error" / f"{new_id}.md"
            self.assertTrue(old_path.exists())
            self.assertIn(f"superseded_by: {new_id}", old_path.read_text())
            self.assertIn(f"supersedes: [{old_id}]", new_path.read_text())

    def test_capture_supersedes_missing_ref_does_not_leave_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-05-01T09:00:00"}
            result = run_cli(
                "capture",
                "decision",
                "--title",
                "New Auth Choice",
                "--summary",
                "New auth choice.",
                "--tags",
                "auth",
                "--supersedes",
                "missing-old-choice",
                cwd=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 4)
            partial = Path(tmp) / "wiki" / "context" / "decision" / "DEC-2026-05-01-090000-new-auth-choice.md"
            self.assertFalse(partial.exists())

    def test_recall_and_refresh_report_backlinks_broken_tasks_indexes_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture",
                "intent",
                "--title",
                "Data Sovereignty",
                "--summary",
                "Keep control over user data.",
                "--tags",
                "data",
                cwd=tmp,
                env=env,
            )
            intent_id = "INT-2026-04-17-143052-data-sovereignty"
            run_cli(
                "capture",
                "rejected_decision",
                "--title",
                "Self Hosted Mail",
                "--summary",
                "Self-hosted mail was rejected.",
                "--tags",
                "auth,mail",
                "--intents",
                intent_id,
                cwd=tmp,
                env=env,
            )

            recall = run_cli("recall", "--backlinks-of", intent_id, "--json", cwd=tmp)
            self.assertEqual(recall.returncode, 0, recall.stderr)
            payload = json.loads(recall.stdout)
            self.assertEqual(payload["ok"], True)
            self.assertEqual(payload["results"][0]["id"], "REJ-2026-04-17-143052-self-hosted-mail")

            bad_path = Path(tmp) / "wiki" / "context" / "trial_error" / "TRI-2026-04-18-101500-bad-task.md"
            bad_path.write_text(
                "---\n"
                "title: Bad task\n"
                "created_at: 2026-04-18\n"
                "summary: Bad refs.\n"
                "tags: [unknown]\n"
                "relations:\n"
                "  decisions: [DEC-does-not-exist]\n"
                "  tasks: [not-a-task]\n"
                "---\n"
                "## 교훈\n"
            )
            vocab = Path(tmp) / "wiki" / "ssot" / "tag-vocabulary.md"
            vocab.write_text(
                "---\n"
                "title: Tag vocabulary\n"
                "created_at: 2026-04-18\n"
                "summary: Tags.\n"
                "tags: [meta]\n"
                "---\n"
                "## 어휘\n"
                "- auth\n"
                "- data\n"
                "- mail\n"
                "- meta\n"
            )

            refresh = run_cli("refresh", "--strict", "--json", cwd=tmp)
            self.assertEqual(refresh.returncode, 6)
            report = json.loads(refresh.stdout)
            codes = {issue["check"] for issue in report["issues"]}
            self.assertIn("broken-rel", codes)
            self.assertIn("task-ref", codes)
            self.assertIn("tags", codes)
            self.assertIn("index", codes)

    def test_recall_search_terms_and_batch_read_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "Current auth design.",
                "--tags",
                "auth",
                "--search-terms",
                "session-cookie",
                cwd=tmp,
                env=env,
            )
            run_cli(
                "capture",
                "observation",
                "--title",
                "Cookie Drift",
                "--summary",
                "Cookie settings may drift.",
                "--tags",
                "auth",
                "--ssot",
                "auth-architecture",
                cwd=tmp,
                env=env,
            )

            by_search_terms = run_cli("recall", "session-cookie", "--json", cwd=tmp)
            self.assertEqual(by_search_terms.returncode, 0, by_search_terms.stderr)
            payload = json.loads(by_search_terms.stdout)
            self.assertEqual([item["id"] for item in payload["results"]], ["auth-architecture"])
            self.assertEqual(payload["results"][0]["search_terms"], ["session-cookie"])

            obs_id = "OBS-2026-05-28-153000-cookie-drift"
            backlinks = run_cli("recall", "--backlinks-of", "auth-architecture", "--json", cwd=tmp)
            self.assertEqual(backlinks.returncode, 0, backlinks.stderr)
            backlink_payload = json.loads(backlinks.stdout)
            self.assertEqual(backlink_payload["results"][0]["id"], obs_id)

            batch = run_cli("recall", "--read", f"{obs_id},auth-architecture", "--json", cwd=tmp)
            self.assertEqual(batch.returncode, 0, batch.stderr)
            batch_payload = json.loads(batch.stdout)
            self.assertEqual([item["id"] for item in batch_payload["results"]], [obs_id, "auth-architecture"])

    def test_recall_batch_read_missing_basename_exits_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            result = run_cli("recall", "--read", "does-not-exist", cwd=tmp)
            self.assertEqual(result.returncode, 4)

    def test_stage1_truncation_includes_filter_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            long_summary = " ".join(["longsummary"] * 80)
            for index in range(30):
                result = run_cli(
                    "capture",
                    "ssot",
                    "--title",
                    f"Large Note {index}",
                    "--summary",
                    f"{long_summary} {index}",
                    "--tags",
                    "bulk",
                    cwd=tmp,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            recall = run_cli("recall", "longsummary", "--stage", "1", "--json", cwd=tmp)
            self.assertEqual(recall.returncode, 0, recall.stderr)
            payload = json.loads(recall.stdout)
            self.assertEqual(payload["truncated"], True)
            self.assertIn("Narrow with --type, --tag", payload["hint"])

    def test_stage1_does_not_match_body_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "Auth design.",
                "--tags",
                "auth",
                cwd=tmp,
            )
            path = Path(tmp) / "wiki" / "ssot" / "auth-architecture.md"
            path.write_text(path.read_text() + "\nbody-only-secret-keyword\n")

            result = run_cli("recall", "body-only-secret-keyword", "--stage", "1", "--json", cwd=tmp)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["results"], [])

            stage3 = run_cli("recall", "body-only-secret-keyword", "--stage", "3", "--json", cwd=tmp)
            payload3 = json.loads(stage3.stdout)
            self.assertEqual(len(payload3["results"]), 1)

    def test_recall_read_requires_exact_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture",
                "intent",
                "--title",
                "Signup Speed",
                "--summary",
                "Reduce friction.",
                "--tags",
                "growth",
                cwd=tmp,
                env=env,
            )
            ok = run_cli("recall", "--read", "INT-2026-04-17-143052-signup-speed", cwd=tmp)
            self.assertEqual(ok.returncode, 0)
            fuzzy = run_cli("recall", "--read", "signup-speed", cwd=tmp)
            self.assertEqual(fuzzy.returncode, 4)

    def test_nested_indexes_duplicate_basename_and_refresh_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            vault = Path(tmp) / "wiki"
            nested = vault / "ssot" / "auth"
            nested.mkdir()
            (nested / "auth-session.md").write_text(
                "---\n"
                "title: Auth Session\n"
                "created_at: 2026-05-28\n"
                "summary: Session details.\n"
                "tags: [auth]\n"
                "---\n"
                "## 현재 상태\n"
            )

            stale_index = vault / "ssot" / "ssot.md"
            stale_index.write_text(stale_index.read_text() + "- [[ghost]] — stale\n")

            fixed = run_cli("refresh", "--check", "index", "--fix", "index", "--json", cwd=tmp)
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertTrue((nested / "auth.md").exists())
            self.assertIn("- [[auth-session]] — Session details.", (nested / "auth.md").read_text())
            self.assertNotIn("auth-session", (vault / "ssot" / "ssot.md").read_text())
            self.assertNotIn("ghost", (vault / "ssot" / "ssot.md").read_text())

            (vault / "runbook" / "auth-session.md").write_text(
                "---\n"
                "title: Duplicate Auth Session\n"
                "created_at: 2026-05-28\n"
                "summary: Duplicate basename.\n"
                "tags: [auth]\n"
                "---\n"
                "## 목적\n"
            )
            duplicate = run_cli("refresh", "--check", "duplicate-basename", "--json", cwd=tmp)
            self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
            report = json.loads(duplicate.stdout)
            self.assertEqual(report["issues"][0]["check"], "duplicate-basename")

            bare_fix = run_cli("refresh", "--fix", cwd=tmp)
            self.assertEqual(bare_fix.returncode, 2)

            bad_fix = run_cli("refresh", "--fix", "broken-rel", cwd=tmp)
            self.assertEqual(bad_fix.returncode, 2)

    def test_retired_in_index_uses_wikilinks_not_summary_substrings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env_old = {"WIKI_NOW": "2026-04-17T14:30:52"}
            env_new = {"WIKI_NOW": "2026-05-01T09:00:00"}
            run_cli(
                "capture",
                "decision",
                "--title",
                "Old Auth Choice",
                "--summary",
                "Old auth choice.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env_old,
            )
            run_cli(
                "capture",
                "decision",
                "--title",
                "New Auth Choice",
                "--summary",
                "New auth choice.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env_new,
            )
            old_id = "DEC-2026-04-17-143052-old-auth-choice"
            new_id = "DEC-2026-05-01-090000-new-auth-choice"
            run_cli("retire", old_id, "--type", "superseded", "--superseded-by", new_id, cwd=tmp, env=env_new)

            index_path = Path(tmp) / "wiki" / "context" / "decision" / "decision.md"
            index_path.write_text(index_path.read_text() + f"- [[{new_id}]] — Mentions {old_id} only in summary.\n")

            refresh = run_cli("refresh", "--check", "retired-in-index", "--json", cwd=tmp)
            self.assertEqual(refresh.returncode, 0, refresh.stderr)
            report = json.loads(refresh.stdout)
            self.assertEqual(report["issues"], [])

            index_path.write_text(index_path.read_text() + f"- [[{old_id}]] — Wrongly linked retired record.\n")
            refresh2 = run_cli("refresh", "--check", "retired-in-index", "--json", cwd=tmp)
            report2 = json.loads(refresh2.stdout)
            self.assertEqual([issue["target"] for issue in report2["issues"]], [old_id])

    def test_refresh_changed_path_stale_and_empty_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            run_cli(
                "capture",
                "ssot",
                "--title",
                "Auth Architecture",
                "--summary",
                "Current auth design.",
                "--tags",
                "auth",
                "--verified-at",
                "2026-05-01",
                "--affects-paths",
                "src/auth/**",
                cwd=tmp,
                env=env,
            )
            run_cli(
                "capture",
                "trial_error",
                "--title",
                "Empty Lesson",
                "--summary",
                "Lesson section is empty.",
                "--tags",
                "auth",
                cwd=tmp,
                env=env,
            )

            refresh = run_cli(
                "refresh",
                "--check",
                "all",
                "--changed-path",
                "src/auth/session.ts",
                "--json",
                cwd=tmp,
            )
            self.assertEqual(refresh.returncode, 0, refresh.stderr)
            report = json.loads(refresh.stdout)
            codes = {issue["check"] for issue in report["issues"]}
            self.assertIn("changed-path-stale", codes)
            self.assertIn("empty-lesson", codes)

            stale = run_cli("refresh", "--check", "stale", "--days", "1", "--json", cwd=tmp, env=env)
            self.assertEqual(stale.returncode, 0, stale.stderr)
            stale_report = json.loads(stale.stdout)
            stale_ids = {Path(issue["path"]).stem for issue in stale_report["issues"]}
            self.assertEqual(stale_ids, {"auth-architecture"})

    def test_lifecycle_fields_inside_relations_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            bad = Path(tmp) / "wiki" / "context" / "decision" / "DEC-2026-04-17-143052-bad.md"
            bad.write_text(
                "---\n"
                "title: Bad\n"
                "created_at: 2026-04-17\n"
                "summary: Misplaced lifecycle field.\n"
                "tags: [auth]\n"
                "relations:\n"
                "  superseded_by: DEC-other\n"
                "  classified_as: TRI-other\n"
                "---\n"
                "## 결정\n"
            )
            refresh = run_cli("refresh", "--check", "broken-rel", "--json", cwd=tmp)
            report = json.loads(refresh.stdout)
            messages = [issue["message"] for issue in report["issues"]]
            self.assertTrue(any("superseded_by must be a top-level lifecycle field" in m for m in messages))
            self.assertTrue(any("classified_as" in m for m in messages))

    def test_top_level_classified_as_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            bad = Path(tmp) / "wiki" / "context" / "observation" / "OBS-2026-05-28-153000-x.md"
            bad.write_text(
                "---\n"
                "title: x\n"
                "created_at: 2026-05-28\n"
                "summary: x.\n"
                "tags: [meta]\n"
                "classified_as: TRI-something\n"
                "---\n"
                "## 관찰\n"
            )
            refresh = run_cli("refresh", "--check", "broken-rel", "--json", cwd=tmp)
            report = json.loads(refresh.stdout)
            self.assertTrue(any("classified_as is not part of the v1" in issue["message"] for issue in report["issues"]))

    def test_refresh_flags_orphan_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture",
                "intent",
                "--title",
                "Lonely Intent",
                "--summary",
                "Nothing references this.",
                "--tags",
                "growth",
                cwd=tmp,
                env=env,
            )
            refresh = run_cli("refresh", "--check", "orphan", "--json", cwd=tmp)
            report = json.loads(refresh.stdout)
            ids = {Path(issue["path"]).stem for issue in report["issues"]}
            self.assertIn("INT-2026-04-17-143052-lonely-intent", ids)

            run_cli(
                "capture",
                "decision",
                "--title",
                "Use Lonely",
                "--summary",
                "Now references the intent.",
                "--tags",
                "growth",
                "--intents",
                "lonely-intent",
                cwd=tmp,
                env=env,
            )
            refresh2 = run_cli("refresh", "--check", "orphan", "--json", cwd=tmp)
            report2 = json.loads(refresh2.stdout)
            ids2 = {Path(issue["path"]).stem for issue in report2["issues"]}
            self.assertNotIn("INT-2026-04-17-143052-lonely-intent", ids2)


if __name__ == "__main__":
    unittest.main()
