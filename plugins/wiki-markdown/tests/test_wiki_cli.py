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
            self.assertFalse((Path(tmp) / "docs").exists())

            second = run_cli("init", cwd=tmp)
            self.assertEqual(second.returncode, 0, second.stderr)

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


class WikiCliAcceptanceTests(unittest.TestCase):
    """§19 추가 수용 기준 — 기본 테스트가 못 잡는 에지 케이스."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_capture_basename_collision_appends_b_suffix(self):
        # §19.1: 동일 TYPE + 동일 초 + 동일 slug → "-b" 접미사 (타임스탬프 위조 금지)
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            first = run_cli(
                "capture", "intent",
                "--title", "Same Topic",
                "--summary", "First entry.",
                "--tags", "x",
                cwd=tmp, env=env,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(
                "capture", "intent",
                "--title", "Same Topic",
                "--summary", "Second entry.",
                "--tags", "x",
                cwd=tmp, env=env,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            intent_dir = Path(tmp) / "wiki" / "context" / "intent"
            self.assertTrue((intent_dir / "INT-2026-04-17-143052-same-topic.md").exists())
            self.assertTrue((intent_dir / "INT-2026-04-17-143052-same-topic-b.md").exists())

    def test_capture_missing_required_fields_exits_2(self):
        # §19.1: --summary 또는 --tags 누락 → exit 2
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            no_summary = run_cli(
                "capture", "intent",
                "--title", "X",
                "--tags", "x",
                cwd=tmp,
            )
            self.assertEqual(no_summary.returncode, 2)
            no_tags = run_cli(
                "capture", "intent",
                "--title", "X",
                "--summary", "x",
                cwd=tmp,
            )
            self.assertEqual(no_tags.returncode, 2)

    def test_capture_living_slug_conflict_exits_5(self):
        # §19.1: living slug 기존 존재 → exit 5
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            first = run_cli(
                "capture", "ssot",
                "--title", "Auth Architecture",
                "--summary", "Auth design.",
                "--tags", "auth",
                cwd=tmp,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(
                "capture", "ssot",
                "--title", "Auth Architecture",
                "--summary", "Auth design v2.",
                "--tags", "auth",
                cwd=tmp,
            )
            self.assertEqual(second.returncode, 5)

    def test_index_excludes_retired_and_is_idempotent(self):
        # §19.2·§19.3: 재실행 결과 동일 (멱등) + retired 문서는 인덱스에 없음
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "decision",
                "--title", "Doomed",
                "--summary", "Will be retired.",
                "--tags", "x",
                cwd=tmp, env=env,
            )
            decision_index = Path(tmp) / "wiki" / "context" / "decision" / "decision.md"
            after_capture = decision_index.read_text()
            # init 재실행은 인덱스 본문을 그대로 유지해야 한다 (멱등)
            run_cli("init", cwd=tmp)
            after_reinit = decision_index.read_text()
            self.assertEqual(after_capture, after_reinit)

            # retire → 인덱스에서 사라져야 한다
            doomed_id = "DEC-2026-04-17-143052-doomed"
            retired = run_cli("retire", doomed_id, "--type", "deprecated", cwd=tmp, env=env)
            self.assertEqual(retired.returncode, 0, retired.stderr)
            self.assertNotIn(doomed_id, decision_index.read_text())

    def test_retire_deprecated_path(self):
        # §19.3: --type deprecated → superseded_by 없음, retired/에 이동, retired_type=deprecated
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "decision",
                "--title", "Wrong Idea",
                "--summary", "Wrong.",
                "--tags", "x",
                cwd=tmp, env=env,
            )
            wrong_id = "DEC-2026-04-17-143052-wrong-idea"
            r = run_cli("retire", wrong_id, "--type", "deprecated", cwd=tmp, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            retired_path = Path(tmp) / "wiki" / "context" / "decision" / "retired" / f"{wrong_id}.md"
            self.assertTrue(retired_path.exists())
            text = retired_path.read_text()
            self.assertIn("retired_type: deprecated", text)
            self.assertNotIn("superseded_by", text)
            # deprecated에 --superseded-by 주면 거부
            bad = run_cli(
                "retire", wrong_id,
                "--type", "deprecated",
                "--superseded-by", "DEC-anything",
                cwd=tmp, env=env,
            )
            self.assertEqual(bad.returncode, 2)

    def test_refresh_clean_vault_reports_zero_issues(self):
        # §19.4: 모든 관계 해소 + tasks 형식 OK → 0건, --strict에서도 exit 0
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "intent",
                "--title", "Speed",
                "--summary", "Be fast.",
                "--tags", "x",
                cwd=tmp, env=env,
            )
            run_cli(
                "capture", "decision",
                "--title", "Cache It",
                "--summary", "Cache the thing.",
                "--tags", "x",
                "--intents", "speed",
                "--tasks", "owner/repo#1",
                cwd=tmp, env=env,
            )
            r = run_cli("refresh", "--strict", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["issues"], [])

    def test_recall_backlinks_excludes_retired_unless_flag(self):
        # §19.5: --backlinks-of 기본은 retired/ 제외, --include-retired로 노출
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "intent",
                "--title", "Target",
                "--summary", "T",
                "--tags", "x",
                cwd=tmp, env=env,
            )
            target_id = "INT-2026-04-17-143052-target"
            run_cli(
                "capture", "trial_error",
                "--title", "Some Pitfall",
                "--summary", "P",
                "--tags", "x",
                "--decisions", target_id,  # decisions 필드 사용은 어색하지만 backlink target은 같다
                cwd=tmp, env=env,
            )
            # 실제로는 trial_error 관계에 intent를 직접 못 적으므로,
            # 다른 record로 백링크를 만들자: rejected_decision → intent
            run_cli(
                "capture", "rejected_decision",
                "--title", "Bad Alt",
                "--summary", "B",
                "--tags", "x",
                "--intents", target_id,
                cwd=tmp, env=env,
            )
            rej_id = "REJ-2026-04-17-143052-bad-alt"

            # rejected_decision을 retire
            env2 = {"WIKI_NOW": "2026-05-01T09:00:00"}
            r = run_cli("retire", rej_id, "--type", "deprecated", cwd=tmp, env=env2)
            self.assertEqual(r.returncode, 0, r.stderr)

            default = run_cli("recall", "--backlinks-of", target_id, "--json", cwd=tmp)
            self.assertEqual(default.returncode, 0, default.stderr)
            payload = json.loads(default.stdout)
            ids = [r["id"] for r in payload["results"]]
            self.assertNotIn(rej_id, ids)

            with_retired = run_cli("recall", "--backlinks-of", target_id, "--include-retired", "--json", cwd=tmp)
            self.assertEqual(with_retired.returncode, 0, with_retired.stderr)
            payload2 = json.loads(with_retired.stdout)
            ids2 = [r["id"] for r in payload2["results"]]
            self.assertIn(rej_id, ids2)

    def test_ssot_runbook_have_no_relations_key(self):
        # §19.6: living은 relations 키 자체를 갖지 않는다 (불변식)
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            run_cli(
                "capture", "ssot",
                "--title", "Some SSOT",
                "--summary", "SSOT.",
                "--tags", "x",
                cwd=tmp,
            )
            run_cli(
                "capture", "runbook",
                "--title", "Deploy",
                "--summary", "Deploy steps.",
                "--tags", "x",
                cwd=tmp,
            )
            ssot_text = (Path(tmp) / "wiki" / "ssot" / "some-ssot.md").read_text()
            runbook_text = (Path(tmp) / "wiki" / "runbook" / "deploy.md").read_text()
            self.assertNotIn("relations:", ssot_text)
            self.assertNotIn("relations:", runbook_text)

    def test_supersedes_lifecycle_fields_are_top_level(self):
        # §19.6: supersedes/superseded_by/retired_at/retired_type는 top-level (relations 안에 있으면 위반)
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env_old = {"WIKI_NOW": "2026-04-17T14:30:52"}
            env_new = {"WIKI_NOW": "2026-05-01T09:00:00"}
            run_cli(
                "capture", "decision",
                "--title", "Old",
                "--summary", "O.",
                "--tags", "x",
                cwd=tmp, env=env_old,
            )
            run_cli(
                "capture", "decision",
                "--title", "New",
                "--summary", "N.",
                "--tags", "x",
                cwd=tmp, env=env_new,
            )
            old_id = "DEC-2026-04-17-143052-old"
            new_id = "DEC-2026-05-01-090000-new"
            r = run_cli("retire", old_id, "--type", "superseded", "--superseded-by", new_id, cwd=tmp, env=env_new)
            self.assertEqual(r.returncode, 0, r.stderr)

            old_text = (Path(tmp) / "wiki" / "context" / "decision" / "retired" / f"{old_id}.md").read_text()
            new_text = (Path(tmp) / "wiki" / "context" / "decision" / f"{new_id}.md").read_text()
            # frontmatter 영역만 검사 (첫 --- 이후 두 번째 --- 까지)
            def frontmatter_block(text):
                parts = text.split("---\n", 2)
                # parts[0]=='' (선두 ---), parts[1]=frontmatter 본문, parts[2]=body
                return parts[1] if len(parts) >= 3 else text

            old_fm = frontmatter_block(old_text)
            new_fm = frontmatter_block(new_text)

            # supersedes/superseded_by/retired_* 가 frontmatter에 들어가 있어야 한다
            self.assertIn("retired_at:", old_fm)
            self.assertIn("retired_type:", old_fm)
            self.assertIn("superseded_by:", old_fm)
            self.assertIn("supersedes:", new_fm)

            # relations: 블록 내부에는 lifecycle 키가 있으면 안 된다
            def relations_block(fm):
                # `relations:` 라인 다음부터 들여쓰기가 풀리는 곳(또는 끝)까지
                lines = fm.splitlines()
                out = []
                inside = False
                for ln in lines:
                    if not inside:
                        if ln.startswith("relations:"):
                            inside = True
                        continue
                    if inside:
                        if ln.startswith("  ") or ln.strip() == "":
                            out.append(ln)
                        else:
                            break
                return "\n".join(out)

            for fm, label in [(old_fm, "old"), (new_fm, "new")]:
                rb = relations_block(fm)
                for forbidden in ("supersedes", "superseded_by", "retired_at", "retired_type"):
                    self.assertNotIn(forbidden, rb, f"{forbidden} leaked into relations of {label}")


class WikiCliV1Tests(unittest.TestCase):
    """v1 §19 추가 수용 기준 — observation, affects_paths, search_terms,
    successor validation, --read batch, 신규 refresh checks, --fix whitelist,
    nested ssot folders."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # ── observation ─────────────────────────────────────────────────────
    def test_observation_capture_with_ssot_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            # First an ssot to point to.
            run_cli(
                "capture", "ssot",
                "--title", "Webhook Architecture",
                "--summary", "How webhooks are processed.",
                "--tags", "webhook",
                cwd=tmp, env=env,
            )
            r = run_cli(
                "capture", "observation",
                "--title", "Webhook Timeout Risk",
                "--summary", "External webhook may stall over 30s.",
                "--tags", "webhook,reliability",
                "--ssot", "webhook-architecture",
                "--affects-paths", "src/webhook/**",
                "--tasks", "owner/repo#42",
                cwd=tmp, env=env,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            obs_path = Path(tmp) / "wiki" / "context" / "observation" / \
                "OBS-2026-05-28-153000-webhook-timeout-risk.md"
            self.assertTrue(obs_path.exists())
            text = obs_path.read_text()
            self.assertIn("affects_paths: [src/webhook/**]", text)
            self.assertIn("ssot: [webhook-architecture]", text)
            self.assertIn("tasks: [owner/repo#42]", text)
            self.assertIn("## 관찰", text)
            self.assertIn("## 후속 분류 조건", text)
            # Index registration
            idx = (Path(tmp) / "wiki" / "context" / "observation" / "observation.md").read_text()
            self.assertIn("[[OBS-2026-05-28-153000-webhook-timeout-risk]]", idx)

    def test_observation_rejects_intent_and_rejected_relations(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            run_cli(
                "capture", "intent",
                "--title", "X", "--summary", "x", "--tags", "x",
                cwd=tmp, env=env,
            )
            bad = run_cli(
                "capture", "observation",
                "--title", "Y", "--summary", "y", "--tags", "x",
                "--intents", "x",
                cwd=tmp, env=env,
            )
            self.assertEqual(bad.returncode, 2)

    # ── verified_at scope ───────────────────────────────────────────────
    def test_verified_at_rejected_for_record_types_without_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            for typ in ("intent", "decision", "rejected_decision"):
                r = run_cli(
                    "capture", typ,
                    "--title", "X", "--summary", "x", "--tags", "x",
                    "--verified-at", "2026-05-28",
                    cwd=tmp,
                )
                self.assertEqual(r.returncode, 2,
                                 f"{typ} should reject --verified-at, got {r.returncode}: {r.stderr}")
            # ssot / runbook / trial_error / observation should accept it
            for typ in ("ssot", "runbook", "trial_error", "observation"):
                r = run_cli(
                    "capture", typ,
                    "--title", f"OK {typ}",
                    "--summary", "x",
                    "--tags", "x",
                    "--verified-at", "2026-05-28",
                    cwd=tmp,
                )
                self.assertEqual(r.returncode, 0,
                                 f"{typ} should accept --verified-at: {r.stderr}")

    # ── affects_paths scope ─────────────────────────────────────────────
    def test_affects_paths_serialized_and_scope_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            ok = run_cli(
                "capture", "ssot",
                "--title", "Auth", "--summary", "s", "--tags", "x",
                "--affects-paths", "src/auth/**,src/session/**",
                cwd=tmp, env=env,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            t = (Path(tmp) / "wiki" / "ssot" / "auth.md").read_text()
            self.assertIn("affects_paths: [src/auth/**, src/session/**]", t)
            bad = run_cli(
                "capture", "intent",
                "--title", "X", "--summary", "x", "--tags", "x",
                "--affects-paths", "src/auth/**",
                cwd=tmp, env=env,
            )
            self.assertEqual(bad.returncode, 2)

    # ── retire successor validation ─────────────────────────────────────
    def test_retire_supersede_target_must_be_active_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "decision",
                "--title", "Old", "--summary", "o", "--tags", "x",
                cwd=tmp, env=env,
            )
            run_cli(
                "capture", "ssot",
                "--title", "Some SSOT", "--summary", "s", "--tags", "x",
                cwd=tmp, env=env,
            )
            old = "DEC-2026-04-17-143052-old"
            # Successor is ssot → exit 2
            bad = run_cli(
                "retire", old, "--type", "superseded", "--superseded-by", "some-ssot",
                cwd=tmp, env=env,
            )
            self.assertEqual(bad.returncode, 2, bad.stderr)

    # ── recall --read batch ─────────────────────────────────────────────
    def test_recall_read_batch_preserves_order_and_fails_on_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli("capture", "intent", "--title", "A", "--summary", "a",
                    "--tags", "x", cwd=tmp, env=env)
            env2 = {"WIKI_NOW": "2026-04-17T14:30:53"}
            run_cli("capture", "intent", "--title", "B", "--summary", "b",
                    "--tags", "x", cwd=tmp, env=env2)
            env3 = {"WIKI_NOW": "2026-04-17T14:30:54"}
            run_cli("capture", "intent", "--title", "C", "--summary", "c",
                    "--tags", "x", cwd=tmp, env=env3)
            a = "INT-2026-04-17-143052-a"
            b = "INT-2026-04-17-143053-b"
            c = "INT-2026-04-17-143054-c"
            # Order: c,a,b
            r = run_cli("recall", "--read", f"{c},{a},{b}", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            ids = [it["id"] for it in payload["results"]]
            self.assertEqual(ids, [c, a, b])
            # Missing → exit 4
            bad = run_cli("recall", "--read", f"{a},nonsense-basename", cwd=tmp)
            self.assertEqual(bad.returncode, 4)

    # ── search_terms matching ───────────────────────────────────────────
    def test_recall_stage1_matches_search_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "ssot",
                "--title", "Cache",
                "--summary", "Caching design.",
                "--tags", "perf",
                "--search-terms", "redis,memoization,LRU",
                cwd=tmp, env=env,
            )
            r = run_cli("recall", "redis", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            ids = [it["id"] for it in payload["results"]]
            self.assertIn("cache", ids)
            self.assertIn("search_terms", payload["results"][0])

    # ── refresh: duplicate-basename ─────────────────────────────────────
    def test_refresh_duplicate_basename_detects_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # Two living docs with same basename in different folders
            nested = Path(tmp) / "wiki" / "ssot" / "auth"
            nested.mkdir(parents=True)
            (nested / "auth.md").write_text(
                "---\ntitle: Auth area\ncreated_at: 2026-05-28\n"
                "summary: Auth area.\ntags: [meta]\n---\n## 노트\n"
            )
            (nested / "session.md").write_text(
                "---\ntitle: Auth session\ncreated_at: 2026-05-28\n"
                "summary: Auth session.\ntags: [auth]\n---\n## 현재 상태\n"
            )
            # Plant a colliding basename at top level
            (Path(tmp) / "wiki" / "ssot" / "session.md").write_text(
                "---\ntitle: Top session\ncreated_at: 2026-05-28\n"
                "summary: Top session.\ntags: [auth]\n---\n## 현재 상태\n"
            )
            r = run_cli("refresh", "--check", "duplicate-basename", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            codes = {it["check"] for it in payload["issues"]}
            self.assertIn("duplicate-basename", codes)

    # ── refresh: empty-lesson ──────────────────────────────────────────
    def test_refresh_empty_lesson_flags_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            tri = Path(tmp) / "wiki" / "context" / "trial_error" / \
                "TRI-2026-04-18-101500-empty.md"
            tri.write_text(
                "---\ntitle: Empty trial\ncreated_at: 2026-04-18\n"
                "summary: nothing.\ntags: [x]\n---\n"
                "## 교훈\n\n<여기에 한 줄 교훈을 적어주세요>\n\n"
                "## 상황\nfoo\n"
            )
            r = run_cli("refresh", "--check", "empty-lesson", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            codes = {it["check"] for it in payload["issues"]}
            self.assertIn("empty-lesson", codes)

    # ── refresh: changed-path-stale ────────────────────────────────────
    def test_refresh_changed_path_stale_with_explicit_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "ssot",
                "--title", "Auth",
                "--summary", "Auth design.",
                "--tags", "auth",
                "--affects-paths", "src/auth/**",
                "--verified-at", "2026-04-17",
                cwd=tmp, env=env,
            )
            # Today is 2026-05-28 (test env), verified_at is older → matched path triggers
            r = run_cli("refresh", "--check", "changed-path-stale",
                        "--changed-path", "src/auth/session.ts", "--json",
                        cwd=tmp, env={"WIKI_NOW": "2026-05-28T09:00:00"})
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            codes = {it["check"] for it in payload["issues"]}
            self.assertIn("changed-path-stale", codes)
            # If verified_at is today and path matches → no issue
            run_cli(
                "capture", "ssot",
                "--title", "Auth2",
                "--summary", "Auth design 2.",
                "--tags", "auth",
                "--affects-paths", "src/auth2/**",
                "--verified-at", "2026-05-28",
                cwd=tmp, env={"WIKI_NOW": "2026-05-28T09:00:00"},
            )
            r2 = run_cli("refresh", "--check", "changed-path-stale",
                         "--changed-path", "src/auth2/x.ts", "--json",
                         cwd=tmp, env={"WIKI_NOW": "2026-05-28T09:00:00"})
            payload2 = json.loads(r2.stdout)
            codes2 = {it.get("check") for it in payload2["issues"]}
            self.assertNotIn("changed-path-stale",
                             {it["check"] for it in payload2["issues"]
                              if "auth2" in it.get("path", "")})

    # ── refresh: --fix whitelist ───────────────────────────────────────
    def test_refresh_fix_whitelist_index_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli(
                "capture", "decision",
                "--title", "X", "--summary", "x", "--tags", "x",
                cwd=tmp, env=env,
            )
            # Break the index manually
            idx = Path(tmp) / "wiki" / "context" / "decision" / "decision.md"
            idx.write_text(idx.read_text().replace(
                "[[DEC-2026-04-17-143052-x]]", "[[DEC-deleted]]"))
            # --fix index should restore it
            r = run_cli("refresh", "--check", "index", "--fix", "index",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("fixed", payload)
            self.assertTrue(any(fx["fix"] == "index" for fx in payload["fixed"]))
            self.assertIn("[[DEC-2026-04-17-143052-x]]", idx.read_text())
            # bare --fix (empty arg) → exit 2
            bad = run_cli("refresh", "--check", "index", "--fix", "", cwd=tmp)
            self.assertEqual(bad.returncode, 2)
            # non-whitelist arg → exit 2
            bad2 = run_cli("refresh", "--check", "stale", "--fix", "stale", cwd=tmp)
            self.assertEqual(bad2.returncode, 2)

    # ── nested ssot folder independence ────────────────────────────────
    def test_nested_ssot_folder_has_independent_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            nested = Path(tmp) / "wiki" / "ssot" / "auth"
            nested.mkdir(parents=True)
            (nested / "auth.md").write_text(
                "---\ntitle: Auth area\ncreated_at: 2026-05-28\n"
                "summary: Auth area index.\ntags: [meta]\n"
                "audience: [human, agent]\n---\n"
                "# Auth area\n\n## 노트\n"
            )
            (nested / "auth-session.md").write_text(
                "---\ntitle: Auth session\ncreated_at: 2026-05-28\n"
                "summary: Session lives in BFF.\ntags: [auth]\n---\n"
                "## 현재 상태\nFoo\n"
            )
            # Drive index refresh via --fix index
            r = run_cli("refresh", "--check", "index", "--fix", "index", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            nested_idx = (nested / "auth.md").read_text()
            top_idx = (Path(tmp) / "wiki" / "ssot" / "ssot.md").read_text()
            self.assertIn("[[auth-session]]", nested_idx)
            # The nested doc must NOT appear in the top-level ssot index.
            self.assertNotIn("[[auth-session]]", top_idx)

    # ── basename global uniqueness ─────────────────────────────────────
    def test_capture_living_global_unique_across_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # Plant a nested ssot folder + doc
            nested = Path(tmp) / "wiki" / "ssot" / "payment"
            nested.mkdir(parents=True)
            (nested / "payment.md").write_text(
                "---\ntitle: Payment area\ncreated_at: 2026-05-28\n"
                "summary: Payment.\ntags: [meta]\n---\n## 노트\n"
            )
            (nested / "checkout.md").write_text(
                "---\ntitle: Checkout\ncreated_at: 2026-05-28\n"
                "summary: Checkout.\ntags: [payment]\n---\n## 현재 상태\n"
            )
            # Now capturing 'ssot' with title 'Checkout' would derive slug 'checkout'.
            # That should collide globally → exit 5.
            r = run_cli(
                "capture", "ssot",
                "--title", "Checkout",
                "--summary", "Another checkout.",
                "--tags", "x",
                cwd=tmp,
            )
            self.assertEqual(r.returncode, 5, r.stderr)


class WikiCliV1_1Tests(unittest.TestCase):
    """v1.1 강화 — argparse 위치, 유니코드 slug + sanitize, --check 검증,
    schema 검사 (forbidden fields / living relations / lifecycle in relations /
    disallowed sub-key / relation target type mismatch), capture --supersedes
    active-only, inline YAML comment parsing."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # ── argparse: subcommand 뒤에서도 --vault/--json 동작 ─────────────
    def test_vault_accepted_after_each_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "v"
            # init --vault X
            r = run_cli("init", "--vault", str(vault))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((vault / "README.md").exists())
            # capture <type> --vault X (subcommand 뒤)
            r = run_cli("capture", "intent",
                        "--title", "T", "--summary", "s", "--tags", "x",
                        "--vault", str(vault))
            self.assertEqual(r.returncode, 0, r.stderr)
            # refresh --vault X --json
            r = run_cli("refresh", "--vault", str(vault), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            json.loads(r.stdout)  # valid JSON
            # recall --vault X
            r = run_cli("recall", "--vault", str(vault), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            json.loads(r.stdout)

    def test_vault_accepted_before_subcommand_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "v"
            r = run_cli("--vault", str(vault), "init")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((vault / "README.md").exists())

    # ── slugify: 유니코드 보존 + sanitize ─────────────────────────────
    def test_capture_korean_title_default_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            r = run_cli("capture", "intent",
                        "--title", "가입 전환 속도",
                        "--summary", "마찰을 줄여 가입을 빠르게.",
                        "--tags", "growth",
                        cwd=tmp, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(tmp) / "wiki" / "context" / "intent"
                             / "INT-2026-05-28-153000-가입-전환-속도.md").exists())

    def test_capture_user_slug_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            for bad in ("../etc/passwd", "a/b", ".hidden", "x..y", "a\\b"):
                r = run_cli("capture", "intent",
                            "--title", "X", "--summary", "s", "--tags", "x",
                            "--slug", bad,
                            cwd=tmp)
                self.assertEqual(r.returncode, 2,
                                 f"slug {bad!r} should be rejected; got {r.returncode}")

    # ── refresh --check 검증 ──────────────────────────────────────────
    def test_refresh_check_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            r = run_cli("refresh", "--check", "totally-bogus", cwd=tmp)
            self.assertEqual(r.returncode, 2)
            r2 = run_cli("refresh", "--check", "stale,bogus,index", cwd=tmp)
            self.assertEqual(r2.returncode, 2)

    def test_refresh_check_empty_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            r = run_cli("refresh", "--check", "", cwd=tmp)
            self.assertEqual(r.returncode, 2)
            r2 = run_cli("refresh", "--check", ",,,", cwd=tmp)
            self.assertEqual(r2.returncode, 2)

    def test_refresh_check_all_explicit_equivalent_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            a = run_cli("refresh", "--json", cwd=tmp)
            b = run_cli("refresh", "--check", "all", "--json", cwd=tmp)
            self.assertEqual(a.returncode, 0)
            self.assertEqual(b.returncode, 0)
            self.assertEqual(a.stdout, b.stdout)

    # ── refresh schema check ─────────────────────────────────────────
    def test_schema_check_flags_forbidden_top_level_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            dec = Path(tmp) / "wiki" / "context" / "decision" / \
                "DEC-2026-04-17-143052-x.md"
            dec.write_text(
                "---\n"
                "title: X\ncreated_at: 2026-04-17\nsummary: x\ntags: [x]\n"
                "id: DEC-2026-04-17-143052-x\n"   # forbidden
                "status: active\n"                  # forbidden
                "classified_as: TRI-foo\n"          # forbidden
                "---\n## 결정\nx\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            fields = {it.get("field") for it in payload["issues"]
                      if it["check"] == "schema"}
            self.assertTrue({"id", "status", "classified_as"}.issubset(fields))

    def test_schema_check_flags_living_with_relations_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            ssot = Path(tmp) / "wiki" / "ssot" / "auth.md"
            ssot.write_text(
                "---\ntitle: Auth\ncreated_at: 2026-05-28\nsummary: s\ntags: [x]\n"
                "relations:\n  intents: [INT-foo]\n"
                "---\n## 현재 상태\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertTrue(any(it["field"] == "relations"
                                for it in payload["issues"]
                                if it["check"] == "schema"))

    def test_schema_check_flags_lifecycle_inside_relations(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            dec = Path(tmp) / "wiki" / "context" / "decision" / \
                "DEC-2026-04-17-143052-y.md"
            dec.write_text(
                "---\ntitle: Y\ncreated_at: 2026-04-17\nsummary: y\ntags: [x]\n"
                "relations:\n"
                "  intents: []\n"
                "  retired_at: 2026-04-20\n"      # lifecycle MUST be top-level
                "  superseded_by: DEC-other\n"
                "---\n## 결정\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            fields = {it["field"] for it in payload["issues"]
                      if it["check"] == "schema"}
            self.assertIn("relations.retired_at", fields)
            self.assertIn("relations.superseded_by", fields)

    def test_schema_check_flags_disallowed_relation_subkey(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            obs = Path(tmp) / "wiki" / "context" / "observation" / \
                "OBS-2026-05-28-153000-x.md"
            obs.write_text(
                "---\ntitle: X\ncreated_at: 2026-05-28\nsummary: x\ntags: [x]\n"
                "relations:\n  intents: [INT-foo]\n"     # not allowed on obs
                "---\n## 관찰\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            self.assertTrue(any(it["field"] == "relations.intents"
                                for it in payload["issues"]
                                if it["check"] == "schema"))

    def test_schema_check_flags_relation_target_type_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            # Create a real INT
            run_cli("capture", "intent", "--title", "A", "--summary", "a",
                    "--tags", "x", cwd=tmp, env=env)
            # Plant a TRI whose relations.decisions points to that INT (type mismatch)
            tri = Path(tmp) / "wiki" / "context" / "trial_error" / \
                "TRI-2026-04-18-100000-mis.md"
            tri.write_text(
                "---\ntitle: Mis\ncreated_at: 2026-04-18\nsummary: m\ntags: [x]\n"
                "relations:\n  decisions: [INT-2026-04-17-143052-a]\n"
                "---\n## 교훈\nx\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            mismatches = [it for it in payload["issues"]
                          if it["check"] == "schema"
                          and it["field"] == "relations.decisions"
                          and "타입 불일치" in it["message"]]
            self.assertEqual(len(mismatches), 1, payload)

    # ── capture: relation target type guard ──────────────────────────
    def test_capture_decisions_arg_rejects_non_decision_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli("capture", "intent", "--title", "A", "--summary", "a",
                    "--tags", "x", cwd=tmp, env=env)
            r = run_cli("capture", "trial_error",
                        "--title", "T", "--summary", "t", "--tags", "x",
                        "--decisions", "INT-2026-04-17-143052-a",
                        cwd=tmp, env=env)
            self.assertEqual(r.returncode, 4, r.stderr)

    # ── capture: --supersedes 대상은 active context record만 ─────────
    def test_capture_supersedes_rejects_retired_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            envs = [{"WIKI_NOW": "2026-04-17T14:30:52"},
                    {"WIKI_NOW": "2026-05-01T09:00:00"},
                    {"WIKI_NOW": "2026-06-01T09:00:00"}]
            run_cli("capture", "decision", "--title", "Old",
                    "--summary", "o", "--tags", "x", cwd=tmp, env=envs[0])
            old = "DEC-2026-04-17-143052-old"
            # First supersede retires old
            run_cli("capture", "decision", "--title", "Mid",
                    "--summary", "m", "--tags", "x",
                    "--supersedes", old, cwd=tmp, env=envs[1])
            # Now try to supersede the already-retired old again → must be rejected
            r = run_cli("capture", "decision", "--title", "Re",
                        "--summary", "r", "--tags", "x",
                        "--supersedes", old, cwd=tmp, env=envs[2])
            self.assertIn(r.returncode, (2, 4), r.stderr)
            # Confirm old's lifecycle stamps were NOT overwritten (still mid as successor)
            old_text = (Path(tmp) / "wiki" / "context" / "decision"
                        / "retired" / f"{old}.md").read_text()
            self.assertIn("superseded_by: DEC-2026-05-01-090000-mid", old_text)

    # ── parser: inline YAML comment stripped ─────────────────────────
    def test_parser_strips_inline_yaml_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            ssot = Path(tmp) / "wiki" / "ssot" / "with-comments.md"
            ssot.write_text(
                "---\ntitle: T   # 제목 옆 주석\n"
                "created_at: 2026-05-28      # 날짜 옆 주석\n"
                "summary: s   # 요약 옆 주석\n"
                "tags: [a, b]   # 태그 옆 주석\n"
                "verified_at: 2026-05-28       # 권장 필드\n"
                "---\n## 현재 상태\n"
            )
            # Stage 1 over all docs; the planted ssot must be present with
            # comment-stripped scalar values.
            r = run_cli("recall", "--type", "ssot", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            doc = next((it for it in payload["results"]
                        if it["id"] == "with-comments"), None)
            self.assertIsNotNone(doc, payload)
            self.assertEqual(doc["summary"], "s")
            self.assertEqual(doc["verified_at"], "2026-05-28")
            self.assertEqual(doc["tags"], ["a", "b"])

    # task ref containing '#' must NOT be treated as a YAML comment
    def test_parser_preserves_hash_in_task_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli("capture", "decision", "--title", "D",
                    "--summary", "d", "--tags", "x",
                    "--tasks", "owner/repo#42",
                    cwd=tmp, env=env)
            r = run_cli("refresh", "--check", "task-ref", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual([it for it in payload["issues"]
                              if it["check"] == "task-ref"], [])


class WikiCliV1_2Tests(unittest.TestCase):
    """v1.2 — templates frontmatter 시작, sanitize_slug 강화,
    schema 필수 필드 + 타입별 필드 scope."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # ── templates: 모두 '---'로 시작하고 파싱 가능 ───────────────────
    def test_all_templates_start_with_frontmatter_and_parse(self):
        scripts_dir = ROOT / "skills" / "wiki" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import wiki_cli as mod  # noqa: WPS433 (test-only import)

        templates_dir = ROOT / "templates"
        required_keys = {"title", "created_at", "summary", "tags"}
        for p in sorted(templates_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            first_line = text.splitlines()[0] if text else ""
            self.assertEqual(first_line, "---",
                             f"{p.name}: 첫 줄은 '---' 이어야 함, got {first_line!r}")
            fm_text, body = mod.split_frontmatter(text)
            self.assertIsNotNone(fm_text,
                                 f"{p.name}: frontmatter 파싱 실패")
            fm = mod.parse_frontmatter(fm_text)
            self.assertTrue(required_keys.issubset(fm.keys()),
                            f"{p.name}: 필수 키 누락 — present={sorted(fm.keys())}")
            # 본문에 적어도 한 개의 H2 섹션이 있어야 함
            self.assertIn("## ", body, f"{p.name}: 본문 H2 섹션 없음")

    # ── sanitize_slug: kebab-case 계약 강제 ─────────────────────────
    def test_sanitize_slug_rejects_non_kebab_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            bad_inputs = [
                "with space",      # 공백
                "with:colon",      # 콜론
                "has*wildcard",    # 와일드카드
                "a@b",             # @
                "---",             # 순수 하이픈
                "foo--bar",        # 연속 하이픈
                "-leading",        # leading -
                "trailing-",       # trailing -
                ".hidden",         # leading .
                "x..y",            # ..
                "ALL.CAPS",        # .
            ]
            for bad in bad_inputs:
                r = run_cli("capture", "intent",
                            "--title", "T", "--summary", "s", "--tags", "x",
                            "--slug", bad, cwd=tmp)
                self.assertEqual(r.returncode, 2,
                                 f"slug {bad!r}는 거부되어야 함; got {r.returncode}")

    def test_sanitize_slug_accepts_kebab_alnum(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-05-28T15:30:00"}
            good_inputs = [
                "simple",
                "with-hyphen",
                "한글-kebab",
                "alpha-1-2-3",
                "korean-한국어-mixed",
            ]
            for i, good in enumerate(good_inputs):
                env_i = {"WIKI_NOW": f"2026-05-28T15:30:{i:02d}"}
                r = run_cli("capture", "intent",
                            "--title", "T", "--summary", "s", "--tags", "x",
                            "--slug", good, cwd=tmp, env=env_i)
                self.assertEqual(r.returncode, 0,
                                 f"slug {good!r}는 통과해야 함: {r.stderr}")

    # ── schema check: 필수 필드 누락 ────────────────────────────────
    def test_schema_check_flags_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # frontmatter는 있지만 필수 필드가 빠짐
            bad = Path(tmp) / "wiki" / "context" / "decision" / \
                "DEC-2026-04-17-143052-missing.md"
            bad.write_text(
                "---\n"
                "title: \n"                   # empty title
                "created_at: not-a-date\n"    # bad format
                # summary 누락
                "tags: []\n"                  # empty list
                "---\n## 결정\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            fields = {it["field"] for it in payload["issues"]
                      if it["check"] == "schema"
                      and "missing" in it["path"]}
            self.assertIn("title", fields)
            self.assertIn("created_at", fields)
            self.assertIn("summary", fields)
            self.assertIn("tags", fields)

    def test_schema_check_flags_missing_frontmatter_entirely(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # '---'로 시작 안 함
            bad = Path(tmp) / "wiki" / "context" / "intent" / \
                "INT-2026-04-17-143052-no-fm.md"
            bad.write_text("# 그냥 본문만\n\nfrontmatter 없음\n")
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            self.assertTrue(any(it["field"] == "frontmatter"
                                for it in payload["issues"]
                                if it["check"] == "schema"))

    # ── schema check: 타입별 필드 scope ─────────────────────────────
    def test_schema_check_flags_verified_at_on_wrong_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # intent에 verified_at 있음 (capture는 거부하지만, 손편집 시)
            bad = Path(tmp) / "wiki" / "context" / "intent" / \
                "INT-2026-04-17-143052-x.md"
            bad.write_text(
                "---\ntitle: X\ncreated_at: 2026-04-17\nsummary: s\ntags: [x]\n"
                "verified_at: 2026-04-17\n"
                "---\n## 취지\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            self.assertTrue(any(it["field"] == "verified_at"
                                for it in payload["issues"]
                                if it["check"] == "schema"))

    def test_schema_check_flags_affects_paths_on_wrong_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            bad = Path(tmp) / "wiki" / "context" / "decision" / \
                "DEC-2026-04-17-143052-x.md"
            bad.write_text(
                "---\ntitle: X\ncreated_at: 2026-04-17\nsummary: s\ntags: [x]\n"
                "affects_paths: [src/foo/**]\n"
                "---\n## 결정\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            self.assertTrue(any(it["field"] == "affects_paths"
                                for it in payload["issues"]
                                if it["check"] == "schema"))


class WikiCliV1_3Tests(unittest.TestCase):
    """v1.3 — index 파일 보호, 날짜 유효성, placeholder 패턴, NFC 정규화."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # ── relation target이 인덱스 파일이면 거부 ───────────────────────
    def test_capture_rejects_relation_pointing_at_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # --ssot ssot → 'ssot' basename은 폴더 인덱스 → resolve 실패 (exit 4)
            r = run_cli("capture", "decision",
                        "--title", "X", "--summary", "x", "--tags", "x",
                        "--ssot", "ssot", cwd=tmp)
            self.assertEqual(r.returncode, 4, r.stderr)
            r2 = run_cli("capture", "trial_error",
                         "--title", "Y", "--summary", "y", "--tags", "x",
                         "--decisions", "decision", cwd=tmp)
            self.assertEqual(r2.returncode, 4, r2.stderr)

    def test_refresh_broken_rel_flags_index_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # 손편집: relations.ssot가 인덱스 'ssot'를 가리킴
            bad = Path(tmp) / "wiki" / "context" / "decision" / \
                "DEC-2026-04-17-143052-bad.md"
            bad.write_text(
                "---\ntitle: Bad\ncreated_at: 2026-04-17\nsummary: b\ntags: [x]\n"
                "relations:\n  ssot: [ssot]\n"
                "---\n## 결정\n"
            )
            r = run_cli("refresh", "--check", "broken-rel", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            broken = [it for it in payload["issues"]
                      if it["check"] == "broken-rel" and it.get("target") == "ssot"]
            self.assertEqual(len(broken), 1, payload)

    # ── 날짜 schema 검사 ────────────────────────────────────────────
    def test_schema_check_flags_invalid_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            cases = [
                ("created_at", "2026-99-99",   # invalid calendar
                 "DEC-2026-04-17-143052-ca.md", "decision", "## 결정"),
                ("verified_at", "nope",
                 "ssot-vp.md", "ssot", "## 현재 상태"),
                ("retired_at", "not-a-date",
                 "DEC-2026-04-17-143053-rt.md", "decision", "## 결정"),
            ]
            for field, badv, fname, folder_t, body_hdr in cases:
                if folder_t == "ssot":
                    path = Path(tmp) / "wiki" / "ssot" / fname
                else:
                    path = Path(tmp) / "wiki" / "context" / folder_t / fname
                # Build minimal frontmatter; for retired_at case put it top-level.
                lines = [
                    "---",
                    "title: T",
                    "created_at: 2026-04-17" if field != "created_at" else f"created_at: {badv}",
                    "summary: s",
                    "tags: [x]",
                ]
                if field == "verified_at":
                    lines.append(f"verified_at: {badv}")
                if field == "retired_at":
                    lines.append(f"retired_at: {badv}")
                    lines.append("retired_type: deprecated")
                lines += ["---", body_hdr, ""]
                path.write_text("\n".join(lines))

            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            fields = {(Path(it["path"]).name, it["field"])
                      for it in payload["issues"] if it["check"] == "schema"}
            self.assertIn(("DEC-2026-04-17-143052-ca.md", "created_at"), fields)
            self.assertIn(("ssot-vp.md", "verified_at"), fields)
            self.assertIn(("DEC-2026-04-17-143053-rt.md", "retired_at"), fields)

    # ── placeholder 검사 ────────────────────────────────────────────
    def test_schema_check_flags_placeholder_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # 사용자가 template을 그대로 복사한 시나리오
            ph = Path(tmp) / "wiki" / "context" / "intent" / \
                "INT-2026-04-17-143052-ph.md"
            ph.write_text(
                "---\n"
                "title: <이 취지의 한 줄 이름>\n"
                "created_at: 2026-04-17\n"
                "summary: <상황이 바뀌어도 유지돼야 하는 원칙을 한 줄로>\n"
                "tags: [<통제 어휘에서>]\n"
                "---\n## 취지\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            ph_issues = [it for it in payload["issues"]
                         if it["check"] == "schema" and "ph.md" in it["path"]]
            fields = {it["field"] for it in ph_issues}
            self.assertIn("title", fields)
            self.assertIn("summary", fields)
            self.assertIn("tags", fields)
            # Messages should mention placeholder
            for it in ph_issues:
                if it["field"] in ("title", "summary"):
                    self.assertIn("placeholder", it["message"])

    # ── NFC 정규화 ─────────────────────────────────────────────────
    def test_nfc_round_trip_for_korean_input(self):
        # Capture with NFD title; refresh/recall should still resolve via NFC ref.
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            nfc_title = "가입 전환 속도"
            nfd_title = unicodedata.normalize("NFD", nfc_title)
            self.assertNotEqual(nfc_title, nfd_title)  # sanity: 실제 다름

            # capture with NFD-formed title → 저장 시 NFC로 정규화
            r = run_cli("capture", "intent",
                        "--title", nfd_title,
                        "--summary", "s", "--tags", "x",
                        cwd=tmp, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)

            # 파일이 NFC basename으로 저장되어 NFC ref로 찾아져야 함
            nfc_basename = f"INT-2026-04-17-143052-{slugify_nfc('가입-전환-속도')}"
            # 위 slug는 이미 NFC. capture에서 NFC normalize됨.
            expected_id = "INT-2026-04-17-143052-가입-전환-속도"

            # NFC ref로 backlinks/read 조회 (slug 단편)
            r2 = run_cli("recall", "--read", expected_id, "--json", cwd=tmp)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            payload = json.loads(r2.stdout)
            self.assertEqual(payload["id"], expected_id)

            # NFD ref도 capture가 NFC로 정규화하므로 resolve 가능
            nfd_ref = unicodedata.normalize("NFD", "가입-전환-속도")
            env2 = {"WIKI_NOW": "2026-04-17T14:30:53"}
            r3 = run_cli("capture", "decision",
                         "--title", "D", "--summary", "d", "--tags", "x",
                         "--intents", nfd_ref,
                         cwd=tmp, env=env2)
            self.assertEqual(r3.returncode, 0, r3.stderr)


def slugify_nfc(s):
    # Helper used by the NFC test above.
    return s


class WikiCliV1_4Tests(unittest.TestCase):
    """v1.4 — P1 index 덮어쓰기 회귀 차단, P2 strict 날짜 / NFD fallback,
    P3 duplicate-basename NFC 정규화."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # ── P1: living slug가 폴더 인덱스를 덮어쓰지 못함 ────────────────
    def test_capture_ssot_with_slug_ssot_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            r = run_cli("capture", "ssot",
                        "--title", "Sneaky", "--summary", "BAD",
                        "--tags", "x", "--slug", "ssot",
                        cwd=tmp)
            self.assertEqual(r.returncode, 5, r.stderr)
            # 인덱스 파일은 그대로
            idx = (Path(tmp) / "wiki" / "ssot" / "ssot.md").read_text()
            self.assertIn("## 노트", idx)  # 인덱스 헤더 보존
            self.assertNotIn("title: Sneaky", idx)

    def test_capture_runbook_with_slug_runbook_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            r = run_cli("capture", "runbook",
                        "--title", "Sneaky", "--summary", "BAD",
                        "--tags", "x", "--slug", "runbook",
                        cwd=tmp)
            self.assertEqual(r.returncode, 5, r.stderr)
            idx = (Path(tmp) / "wiki" / "runbook" / "runbook.md").read_text()
            self.assertIn("## 노트", idx)

    def test_capture_living_slug_matching_nested_index_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # Plant a nested ssot area: ssot/auth/auth.md (index)
            nested = Path(tmp) / "wiki" / "ssot" / "auth"
            nested.mkdir(parents=True)
            (nested / "auth.md").write_text(
                "---\ntitle: Auth area\ncreated_at: 2026-05-28\n"
                "summary: Auth area.\ntags: [meta]\n---\n## 노트\n"
            )
            # 'auth' 슬러그로 ssot 캡처 시 충돌 — 전역 basename uniqueness 위반
            r = run_cli("capture", "ssot",
                        "--title", "Auth top", "--summary", "x",
                        "--tags", "x", "--slug", "auth",
                        cwd=tmp)
            self.assertEqual(r.returncode, 5, r.stderr)
            # 인덱스 파일 보존
            self.assertIn("## 노트", (nested / "auth.md").read_text())

    # ── P2-2: strict YYYY-MM-DD (regex + strptime) ─────────────────
    def test_schema_check_rejects_loose_iso_date_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            for fname, body in [
                ("DEC-2026-04-17-143052-loose-ca.md",
                 "---\ntitle: T\ncreated_at: 2026-1-1\nsummary: s\ntags: [x]\n---\n## 결정\n"),
                ("DEC-2026-04-17-143053-loose-va.md",
                 "---\ntitle: T\ncreated_at: 2026-04-17\nsummary: s\ntags: [x]\n"
                 "---\n## 결정\n"),
            ]:
                (Path(tmp) / "wiki" / "context" / "decision" / fname).write_text(body)
            # ssot에 verified_at loose
            (Path(tmp) / "wiki" / "ssot" / "loose-vrf.md").write_text(
                "---\ntitle: T\ncreated_at: 2026-04-17\nsummary: s\ntags: [x]\n"
                "verified_at: 2026-1-1\n---\n## 현재 상태\n"
            )
            r = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            fields = {(Path(it["path"]).name, it["field"])
                      for it in payload["issues"] if it["check"] == "schema"}
            self.assertIn(("DEC-2026-04-17-143052-loose-ca.md", "created_at"), fields)
            self.assertIn(("loose-vrf.md", "verified_at"), fields)

    # ── P3: duplicate-basename NFC key ─────────────────────────────
    def test_duplicate_basename_detects_nfc_nfd_pair(self):
        # macOS APFS는 normalization-insensitive하므로 같은 폴더에 NFC/NFD를
        # 동시에 둘 수 없다. 다른 폴더(top vs nested)에 두면 OS와 무관하게
        # 별도 파일이 생성되고, NFC-key 기반 duplicate 검사가 둘을 한 묶음으로
        # 잡는지 확인할 수 있다.
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            # NFC at ssot/세션.md
            nfc = vault / "ssot" / "세션.md"
            nfc.write_text(
                "---\ntitle: NFC\ncreated_at: 2026-05-28\nsummary: s\ntags: [x]\n"
                "---\n## 현재 상태\n"
            )
            # NFD at nested ssot/auth/<NFD>.md
            nested = vault / "ssot" / "auth"
            nested.mkdir(parents=True)
            (nested / "auth.md").write_text(
                "---\ntitle: Auth area\ncreated_at: 2026-05-28\n"
                "summary: x\ntags: [meta]\n---\n## 노트\n"
            )
            nfd_stem = unicodedata.normalize("NFD", "세션")
            nfd = nested / f"{nfd_stem}.md"
            nfd.write_text(
                "---\ntitle: NFD\ncreated_at: 2026-05-28\nsummary: s\ntags: [x]\n"
                "---\n## 현재 상태\n"
            )
            # Sanity: 두 파일이 실제로 별도 존재 (OS와 무관)
            self.assertTrue(nfc.is_file() and nfd.is_file())
            r = run_cli("refresh", "--check", "duplicate-basename", "--json",
                        cwd=tmp)
            payload = json.loads(r.stdout)
            dups = [it for it in payload["issues"]
                    if it["check"] == "duplicate-basename"
                    and it.get("basename") == "세션"]
            self.assertEqual(len(dups), 1, payload)
            self.assertEqual(len(dups[0]["paths"]), 2)

    # ── P2-1: NFD on-disk file resolved via NFC ref (fallback) ────
    def test_nfd_filename_resolved_via_nfc_ref(self):
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            nfc_slug = "가입-전환-속도"
            nfd_slug = unicodedata.normalize("NFD", nfc_slug)
            nfd_file = (vault / "context" / "intent"
                        / f"INT-2026-04-17-143052-{nfd_slug}.md")
            nfd_file.write_text(
                "---\ntitle: T\ncreated_at: 2026-04-17\nsummary: s\ntags: [x]\n"
                "---\n## 취지\n"
            )
            # NFC ref로 read — fallback이 NFD 파일을 찾아냄
            nfc_ref = f"INT-2026-04-17-143052-{nfc_slug}"
            r = run_cli("recall", "--read", nfc_ref, "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["id"], nfc_ref)
            self.assertIn("취지", payload["text"])

    # ── P2-1 보강: capture 시 NFD target 못 찾으면 즉시 거부 ──────
    def test_capture_relation_type_check_no_silent_skip(self):
        # 정상 흐름: ssot 캡처 후 decision이 그 ssot를 NFC ref로 가리킴 → type check 정상.
        # 만약 target_path를 못 찾으면 ref_unresolvable로 즉시 거부됨을 간접 확인.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            run_cli("capture", "ssot", "--title", "Auth area",
                    "--summary", "s", "--tags", "x", cwd=tmp, env=env)
            r = run_cli("capture", "decision", "--title", "D",
                        "--summary", "d", "--tags", "x",
                        "--ssot", "auth-area",  # 정상 NFC ref
                        cwd=tmp, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)


class WikiCliV1_5Tests(unittest.TestCase):
    """v1.5 — NFD index 누수 차단, capture 입력 strict 검증,
    stale/changed-path-stale가 schema와 같은 date helper 사용."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # ── P2-1: NFD 인덱스 누수 차단 ──────────────────────────────────
    def test_nfd_index_not_returned_as_relation_target(self):
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            # NFC 폴더명 '가입', 안의 인덱스는 NFD '가입.md'
            folder = vault / "ssot" / "가입"
            folder.mkdir(parents=True)
            nfd_idx = unicodedata.normalize("NFD", "가입") + ".md"
            (folder / nfd_idx).write_text(
                "---\ntitle: NFD index\ncreated_at: 2026-05-28\n"
                "summary: idx\ntags: [meta]\n---\n## 노트\n"
            )

            # find_doc_anywhere(default = include_indexes=False)는
            # NFC stem fallback에서 인덱스로 식별되어 반환 안 됨
            scripts_dir = ROOT / "skills" / "wiki" / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            import wiki_cli as m

            res = m.find_doc_anywhere(vault, "가입")
            self.assertIsNone(res,
                              f"NFD index가 relation target으로 새어나옴: {res}")

            # iter_active_docs도 NFD 인덱스를 일반 노트로 포함하지 않아야 함
            docs = m.iter_active_docs(vault, ("ssot", "가입"))
            self.assertEqual(docs, [],
                             f"iter_active_docs가 NFD 인덱스를 노트로 포함: {docs}")

            # capture가 이 인덱스를 relation으로 받아도 거부
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            r = run_cli("capture", "decision",
                        "--title", "T", "--summary", "s", "--tags", "x",
                        "--ssot", "가입",
                        cwd=tmp, env=env)
            self.assertEqual(r.returncode, 4, r.stderr)

    def test_nfd_index_blocks_living_slug_via_include_indexes_path(self):
        # include_indexes=True 경로(living slug 충돌)에서도 NFD 인덱스를 잡아야 함
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            folder = vault / "ssot" / "도메인"
            folder.mkdir(parents=True)
            nfd_idx = unicodedata.normalize("NFD", "도메인") + ".md"
            (folder / nfd_idx).write_text(
                "---\ntitle: NFD index\ncreated_at: 2026-05-28\n"
                "summary: idx\ntags: [meta]\n---\n## 노트\n"
            )
            r = run_cli("capture", "ssot",
                        "--title", "T", "--summary", "s", "--tags", "x",
                        "--slug", "도메인",
                        cwd=tmp)
            self.assertEqual(r.returncode, 5, r.stderr)

    # ── P2-2: capture가 schema 위반 값을 직접 생성하지 못함 ──────────
    def test_capture_rejects_loose_verified_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            for bad in ("2026-1-1", "nope", "2026-99-99", "01/01/2026"):
                r = run_cli("capture", "ssot",
                            "--title", "T", "--summary", "s", "--tags", "x",
                            "--slug", f"s-{bad.replace('/', '-').replace('-', 'x')}",
                            "--verified-at", bad,
                            cwd=tmp)
                self.assertEqual(r.returncode, 2,
                                 f"verified_at={bad!r}는 거부되어야 함; got {r.returncode}")

    def test_capture_rejects_placeholder_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            # title placeholder
            r1 = run_cli("capture", "intent",
                         "--title", "<이 취지의 한 줄 이름>",
                         "--summary", "real summary",
                         "--tags", "growth",
                         cwd=tmp)
            self.assertEqual(r1.returncode, 2, r1.stderr)
            # summary placeholder
            r2 = run_cli("capture", "intent",
                         "--title", "Real title",
                         "--summary", "<상황이 바뀌어도 유지돼야 하는 원칙을 한 줄로>",
                         "--tags", "growth",
                         cwd=tmp)
            self.assertEqual(r2.returncode, 2, r2.stderr)
            # tag placeholder
            r3 = run_cli("capture", "intent",
                         "--title", "Real title",
                         "--summary", "Real summary",
                         "--tags", "real,<통제 어휘에서>,other",
                         cwd=tmp)
            self.assertEqual(r3.returncode, 2, r3.stderr)

    def test_capture_then_refresh_schema_is_clean(self):
        # capture가 만든 문서는 refresh schema가 자기 자신을 invalid로 보고하면 안 됨
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            r = run_cli("capture", "ssot",
                        "--title", "Auth Architecture",
                        "--summary", "Auth via BFF.",
                        "--tags", "auth",
                        "--verified-at", "2026-05-28",
                        cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            rs = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            payload = json.loads(rs.stdout)
            our = [it for it in payload["issues"]
                   if "auth-architecture.md" in it["path"]]
            self.assertEqual(our, [], f"capture가 만든 문서가 schema 위반: {our}")

    # ── P3: stale + changed-path-stale가 strict helper 사용 ─────────
    def test_stale_skips_loose_verified_at(self):
        # loose date ('2024-1-1')는 stale도 silent skip; schema가 단독 보고
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            (Path(tmp) / "wiki" / "ssot" / "loose.md").write_text(
                "---\ntitle: T\ncreated_at: 2026-04-17\nsummary: s\ntags: [x]\n"
                "verified_at: 2024-1-1\n---\n## 현재 상태\n"
            )
            # stale check
            r = run_cli("refresh", "--check", "stale", "--days", "90", "--json",
                        cwd=tmp, env={"WIKI_NOW": "2026-05-28T09:00:00"})
            payload = json.loads(r.stdout)
            stale_hits = [it for it in payload["issues"]
                          if it["check"] == "stale" and "loose" in it["path"]]
            self.assertEqual(stale_hits, [],
                             f"stale이 loose date를 통과시킴: {stale_hits}")
            # schema check는 보고
            rs = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            schema_payload = json.loads(rs.stdout)
            schema_hits = [it for it in schema_payload["issues"]
                           if it["check"] == "schema"
                           and "loose" in it["path"]
                           and it["field"] == "verified_at"]
            self.assertEqual(len(schema_hits), 1, schema_payload)

    def test_changed_path_stale_skips_invalid_verified_at(self):
        # Policy (frontmatter-schema.md): invalid verified_at은 schema가 단독
        # 보고하고 changed-path-stale은 silent skip. 같은 문서가 두 check에서
        # 중복 보고되지 않게 함.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            (Path(tmp) / "wiki" / "ssot" / "auth.md").write_text(
                "---\ntitle: Auth\ncreated_at: 2026-04-17\nsummary: s\ntags: [auth]\n"
                "verified_at: 2024-1-1\n"   # loose date
                "affects_paths: [src/auth/**]\n---\n## 현재 상태\n"
            )
            # changed-path-stale: 경로 매칭 + invalid date → skip
            r = run_cli("refresh", "--check", "changed-path-stale",
                        "--changed-path", "src/auth/session.ts", "--json",
                        cwd=tmp, env={"WIKI_NOW": "2026-05-28T09:00:00"})
            payload = json.loads(r.stdout)
            cps = [it for it in payload["issues"]
                   if it["check"] == "changed-path-stale" and "auth.md" in it["path"]]
            self.assertEqual(cps, [],
                             f"invalid date를 silent skip 안 함: {cps}")
            # schema는 단독으로 보고
            rs = run_cli("refresh", "--check", "schema", "--json", cwd=tmp)
            sp = json.loads(rs.stdout)
            self.assertTrue(any(it["check"] == "schema"
                                and it["field"] == "verified_at"
                                and "auth.md" in it["path"]
                                for it in sp["issues"]),
                            f"schema가 loose verified_at을 보고하지 않음: {sp}")

    def test_changed_path_stale_reports_when_verified_at_missing(self):
        # verified_at 자체가 없으면 (None) drift signal로 changed-path-stale 발생 — 정상.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            (Path(tmp) / "wiki" / "ssot" / "nover.md").write_text(
                "---\ntitle: NoVer\ncreated_at: 2026-04-17\nsummary: s\ntags: [auth]\n"
                "affects_paths: [src/auth/**]\n---\n## 현재 상태\n"
            )
            r = run_cli("refresh", "--check", "changed-path-stale",
                        "--changed-path", "src/auth/session.ts", "--json",
                        cwd=tmp, env={"WIKI_NOW": "2026-05-28T09:00:00"})
            payload = json.loads(r.stdout)
            cps = [it for it in payload["issues"]
                   if it["check"] == "changed-path-stale" and "nover.md" in it["path"]]
            self.assertEqual(len(cps), 1, payload)


class WikiCliV1_6Tests(unittest.TestCase):
    """v1.6 — fast path index 누수 차단(NFD 폴더), find_index_file로
    index 관리 경로 일원화, changed-path-stale 정책 일치."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _import_wiki_cli(self):
        scripts_dir = ROOT / "skills" / "wiki" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import wiki_cli  # noqa: WPS433 — test-only import
        return wiki_cli

    # ── P2-1: fast path가 NFD 폴더명 + NFC 인덱스를 누수하지 않음 ──
    def test_find_doc_anywhere_blocks_index_in_nfd_folder(self):
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            # NFD 폴더 + NFC 인덱스
            folder_nfd = unicodedata.normalize("NFD", "가입")
            folder = vault / "ssot" / folder_nfd
            folder.mkdir(parents=True)
            (folder / "가입.md").write_text(
                "---\ntitle: NFC index in NFD folder\ncreated_at: 2026-05-28\n"
                "summary: idx\ntags: [meta]\n---\n## 노트\n"
            )
            m = self._import_wiki_cli()
            res = m.find_doc_anywhere(vault, "가입")
            self.assertIsNone(res, f"NFD 폴더 + NFC 인덱스 fast path 누수: {res}")
            # capture도 거부
            env = {"WIKI_NOW": "2026-04-17T14:30:52"}
            r = run_cli("capture", "decision",
                        "--title", "T", "--summary", "s", "--tags", "x",
                        "--ssot", "가입", cwd=tmp, env=env)
            self.assertEqual(r.returncode, 4, r.stderr)

    # ── P2-2: refresh check index / --fix index가 NFD 인덱스 발견 ──
    def test_refresh_index_fix_uses_existing_nfd_index(self):
        # NFC 폴더 + NFD 인덱스 + 일반 노트 → --fix index가 NFD 인덱스 본문 동기화
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            folder = vault / "ssot" / "가입"  # NFC
            folder.mkdir(parents=True)
            nfd_idx_name = unicodedata.normalize("NFD", "가입") + ".md"
            nfd_idx = folder / nfd_idx_name
            nfd_idx.write_text(
                "---\ntitle: NFD index\ncreated_at: 2026-05-28\n"
                "summary: idx\ntags: [meta]\n---\n## 노트\n"
            )
            (folder / "session.md").write_text(
                "---\ntitle: Session\ncreated_at: 2026-05-28\n"
                "summary: bff session.\ntags: [auth]\n---\n## 현재 상태\n"
            )
            r = run_cli("refresh", "--check", "index", "--fix", "index",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            # NFD 인덱스 파일 본문에 session note line이 들어가야 함
            text = nfd_idx.read_text(encoding="utf-8")
            self.assertIn("[[session]]", text,
                          f"NFD 인덱스에 derive 결과가 안 들어감: {text!r}")

    def test_refresh_check_index_locates_nfd_index(self):
        # NFD 폴더 + NFC 인덱스
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            folder_nfd = unicodedata.normalize("NFD", "가입")
            folder = vault / "ssot" / folder_nfd
            folder.mkdir(parents=True)
            nfc_idx = folder / "가입.md"
            nfc_idx.write_text(
                "---\ntitle: NFC index\ncreated_at: 2026-05-28\n"
                "summary: idx\ntags: [meta]\n---\n## 노트\n"
            )
            (folder / "note.md").write_text(
                "---\ntitle: Note\ncreated_at: 2026-05-28\n"
                "summary: a note\ntags: [auth]\n---\n## 현재 상태\n"
            )
            # --check index가 누락된 행을 잡아야 함
            r = run_cli("refresh", "--check", "index", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            missing = [it for it in payload["issues"]
                       if it["check"] == "index"
                       and "[[note]]" in it["message"]]
            self.assertEqual(len(missing), 1, payload)
            # --fix로 실제 동기화
            r2 = run_cli("refresh", "--check", "index", "--fix", "index",
                         "--json", cwd=tmp)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("[[note]]", nfc_idx.read_text(encoding="utf-8"))


class WikiCliV1_7Tests(unittest.TestCase):
    """v1.7 — index_path canonical NFC, find_index_file deterministic,
    refresh check/fix가 missing nested index 처리."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _import_wiki_cli(self):
        scripts_dir = ROOT / "skills" / "wiki" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import wiki_cli  # noqa: WPS433
        return wiki_cli

    # ── P3-2: index_path가 canonical NFC ────────────────────────────
    def test_index_path_returns_canonical_nfc_even_for_nfd_parts(self):
        import unicodedata
        m = self._import_wiki_cli()
        folder_nfd = unicodedata.normalize("NFD", "가입")
        result = m.index_path(Path("/tmp/x"), ("ssot", folder_nfd))
        # 파일명 부분이 NFC여야 함
        self.assertTrue(unicodedata.is_normalized("NFC", result.name),
                        f"index_path가 canonical NFC 미보장: {result.name!r}")

    # ── P3-1: find_index_file 결정성 ────────────────────────────────
    def test_find_index_file_is_deterministic(self):
        # 같은 파일을 두 번 부르면 같은 결과 (정상 케이스에서도 stable)
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            vault = Path(tmp) / "wiki"
            m = self._import_wiki_cli()
            r1 = m.find_index_file(vault, ("ssot",))
            r2 = m.find_index_file(vault, ("ssot",))
            self.assertEqual(r1, r2)
            self.assertIsNotNone(r1)
            # canonical NFC 파일명 우선 정책 검증
            import unicodedata
            self.assertTrue(unicodedata.is_normalized("NFC", r1.name))

    # ── P2-1: missing nested index를 refresh가 보고/생성 ───────────
    def test_refresh_check_index_reports_missing_nested_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            nested = Path(tmp) / "wiki" / "ssot" / "auth"
            nested.mkdir(parents=True)
            (nested / "session.md").write_text(
                "---\ntitle: Session\ncreated_at: 2026-05-28\n"
                "summary: Session lives in BFF.\ntags: [auth]\n---\n"
                "## 현재 상태\n"
            )
            # check index — auth.md 누락 보고
            r = run_cli("refresh", "--check", "index", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            missing = [it for it in payload["issues"]
                       if it["check"] == "index"
                       and it.get("field") == "index"
                       and "auth.md" in it["message"]]
            self.assertEqual(len(missing), 1, payload)

    def test_refresh_fix_index_creates_missing_nested_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            nested = Path(tmp) / "wiki" / "ssot" / "auth"
            nested.mkdir(parents=True)
            (nested / "session.md").write_text(
                "---\ntitle: Session\ncreated_at: 2026-05-28\n"
                "summary: Session lives in BFF.\ntags: [auth]\n---\n"
                "## 현재 상태\n"
            )
            r = run_cli("refresh", "--check", "index", "--fix", "index",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            created = [fx for fx in payload.get("fixed", [])
                       if fx["fix"] == "index" and "auth.md" in fx["path"]]
            self.assertEqual(len(created), 1, payload)
            # 실제 파일 + summary 행 확인
            auth_idx = nested / "auth.md"
            self.assertTrue(auth_idx.is_file())
            text = auth_idx.read_text(encoding="utf-8")
            self.assertIn("[[session]]", text)
            self.assertIn("## 노트", text)

    def test_refresh_fix_does_not_create_index_for_empty_folder(self):
        # 노트 0개인 폴더에서는 인덱스 자동 생성하지 않음
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            nested = Path(tmp) / "wiki" / "ssot" / "empty-area"
            nested.mkdir(parents=True)
            r = run_cli("refresh", "--check", "index", "--fix", "index",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((nested / "empty-area.md").exists())


class WikiCliV1_8Tests(unittest.TestCase):
    """v1.8 — 표준 인덱스가 삭제된 빈 폴더도 refresh --check/--fix index가
    감지/복구. INIT_INDEX_FOLDERS의 인덱스는 vault 구조 일부."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_index_reports_missing_standard_index_in_empty_folder(self):
        # ssot/ssot.md 삭제 + 노트 0개 → missing 보고
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            (Path(tmp) / "wiki" / "ssot" / "ssot.md").unlink()
            r = run_cli("refresh", "--check", "index", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            miss = [it for it in payload["issues"]
                    if it["check"] == "index"
                    and "ssot/ssot.md" in it["message"]]
            self.assertEqual(len(miss), 1, payload)

    def test_fix_index_recreates_deleted_standard_index(self):
        # ssot.md 삭제 → --fix index가 표준 skeleton으로 복구
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            ssot_idx = Path(tmp) / "wiki" / "ssot" / "ssot.md"
            ssot_idx.unlink()
            self.assertFalse(ssot_idx.exists())
            r = run_cli("refresh", "--check", "index", "--fix", "index",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            created = [fx for fx in payload.get("fixed", [])
                       if fx["fix"] == "index" and "ssot/ssot.md" in fx["path"]]
            self.assertEqual(len(created), 1, payload)
            self.assertTrue(ssot_idx.is_file())
            text = ssot_idx.read_text(encoding="utf-8")
            # INDEX_FILE_DESC의 표준 title
            self.assertIn("SSOT", text)
            self.assertIn("## 노트", text)

    def test_fix_index_recreates_deleted_context_intent_index(self):
        # context/intent/intent.md 삭제 → 복구
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            intent_idx = Path(tmp) / "wiki" / "context" / "intent" / "intent.md"
            intent_idx.unlink()
            r = run_cli("refresh", "--check", "index", "--fix", "index",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(intent_idx.is_file())
            self.assertIn("Intents", intent_idx.read_text(encoding="utf-8"))

    def test_check_index_reports_all_deleted_standard_indexes(self):
        # 여러 표준 인덱스 동시 삭제 → 모두 보고
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            (Path(tmp) / "wiki" / "ssot" / "ssot.md").unlink()
            (Path(tmp) / "wiki" / "runbook" / "runbook.md").unlink()
            (Path(tmp) / "wiki" / "context" / "intent" / "intent.md").unlink()
            r = run_cli("refresh", "--check", "index", "--json", cwd=tmp)
            payload = json.loads(r.stdout)
            miss = {it["message"] for it in payload["issues"]
                    if it["check"] == "index" and "누락" in it["message"]}
            # 3개 표준 인덱스 누락이 모두 보고됨
            self.assertTrue(any("ssot/ssot.md" in m for m in miss))
            self.assertTrue(any("runbook/runbook.md" in m for m in miss))
            self.assertTrue(any("intent/intent.md" in m for m in miss))


class WikiCliCodexParityTests(unittest.TestCase):
    """Scenarios grafted from the Codex-side test suite to keep parity."""

    def test_init_dry_run_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_cli("init", "--dry-run", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((Path(tmp) / "wiki").exists())

    def test_retire_dry_run_does_not_move_or_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env_old = {"WIKI_NOW": "2026-04-17T14:30:52"}
            env_new = {"WIKI_NOW": "2026-05-01T09:00:00"}
            run_cli("capture", "decision", "--title", "Old Auth Choice",
                    "--summary", "Old auth choice.", "--tags", "auth",
                    cwd=tmp, env=env_old)
            run_cli("capture", "decision", "--title", "New Auth Choice",
                    "--summary", "New auth choice.", "--tags", "auth",
                    cwd=tmp, env=env_new)
            old_id = "DEC-2026-04-17-143052-old-auth-choice"
            new_id = "DEC-2026-05-01-090000-new-auth-choice"
            r = run_cli("retire", old_id, "--type", "superseded",
                        "--superseded-by", new_id, "--dry-run",
                        cwd=tmp, env=env_new)
            self.assertEqual(r.returncode, 0, r.stderr)
            old_path = Path(tmp) / "wiki" / "context" / "decision" / f"{old_id}.md"
            retired_path = (Path(tmp) / "wiki" / "context" / "decision"
                            / "retired" / f"{old_id}.md")
            new_path = Path(tmp) / "wiki" / "context" / "decision" / f"{new_id}.md"
            self.assertTrue(old_path.exists())
            self.assertFalse(retired_path.exists())
            self.assertNotIn("supersedes", new_path.read_text(encoding="utf-8"))

    def test_capture_supersedes_missing_ref_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            env = {"WIKI_NOW": "2026-05-01T09:00:00"}
            r = run_cli("capture", "decision", "--title", "New Auth Choice",
                        "--summary", "New auth choice.", "--tags", "auth",
                        "--supersedes", "missing-old-choice",
                        cwd=tmp, env=env)
            self.assertEqual(r.returncode, 4)
            partial = (Path(tmp) / "wiki" / "context" / "decision"
                       / "DEC-2026-05-01-090000-new-auth-choice.md")
            self.assertFalse(partial.exists())


class WikiCliFuzzyReadTests(unittest.TestCase):
    """Coverage for the new --fuzzy opt-in flag on `recall --read`."""

    def test_recall_read_strict_rejects_slug_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            run_cli("capture", "intent", "--title", "Auth refactor",
                    "--summary", "rework", "--tags", "auth", cwd=tmp,
                    env={"WIKI_NOW": "2026-05-01T09:00:00"})
            r = run_cli("recall", "--read", "auth-refactor", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 4, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["error_code"], "read_missing")

    def test_recall_read_fuzzy_resolves_slug_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init", cwd=tmp)
            run_cli("capture", "intent", "--title", "Auth refactor",
                    "--summary", "rework", "--tags", "auth", cwd=tmp,
                    env={"WIKI_NOW": "2026-05-01T09:00:00"})
            r = run_cli("recall", "--read", "auth-refactor", "--fuzzy",
                        "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("INT-2026-05-01-090000-auth-refactor", payload["path"])


class WikiCliTaskTests(unittest.TestCase):
    """task — 제3 범주 (record/living 아님): 이진 상태(활성/done), 순수 잎,
    relations(intents/decisions/ssot/tasks), complete/reopen 생명주기."""

    def _init(self, tmp):
        result = run_cli("init", cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _seed_decision(self, tmp):
        """intent + decision 시드. (full basenames 반환)"""
        run_cli("capture", "intent", "--slug", "ship-fast",
                "--title", "Ship fast", "--summary", "Be fast.",
                "--tags", "flow", cwd=tmp, env={"WIKI_NOW": "2026-05-29T10:00:00"})
        run_cli("capture", "decision", "--slug", "move-bff",
                "--title", "Move BFF", "--summary", "BFF owns sessions.",
                "--tags", "arch", "--intents", "ship-fast", cwd=tmp,
                env={"WIKI_NOW": "2026-05-29T10:00:01"})
        return ("INT-2026-05-29-100000-ship-fast",
                "DEC-2026-05-29-100001-move-bff")

    def _capture_task(self, tmp, *extra):
        args = ["capture", "task", "--slug", "pay-bff",
                "--title", "결제 BFF", "--summary", "결제 세션 BFF 이관.",
                "--tags", "payment", "--decisions", "move-bff",
                "--intents", "ship-fast", "--tasks", "owner/repo#42", *extra]
        return run_cli(*args, cwd=tmp, env={"WIKI_NOW": "2026-05-29T10:00:02"})

    def test_init_creates_task_folder_index_done_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            v = Path(tmp) / "wiki"
            self.assertTrue((v / "task" / "task.md").is_file())
            self.assertTrue((v / "task" / "done").is_dir())
            self.assertTrue((v / "task" / "retired").is_dir())

    def test_capture_task_writes_relations_and_timestamp_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            intent_id, dec_id = self._seed_decision(tmp)
            r = self._capture_task(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            tid = "TASK-2026-05-29-100002-pay-bff"
            tpath = Path(tmp) / "wiki" / "task" / f"{tid}.md"
            self.assertTrue(tpath.is_file())
            text = tpath.read_text()
            self.assertIn(f"intents: [{intent_id}]", text)
            self.assertIn(f"decisions: [{dec_id}]", text)
            self.assertIn("tasks: [owner/repo#42]", text)
            self.assertNotIn("id:", text)
            for sec in ("## 개요", "## 근거", "## 범위와 완료 기준"):
                self.assertIn(sec, text)

    def test_task_is_backlink_of_decision_and_intent(self):
        # 핵심 기능: "이 결정이 낳은 작업" — task가 파생 백링크로 잡힌다.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            intent_id, dec_id = self._seed_decision(tmp)
            self._capture_task(tmp)
            tid = "TASK-2026-05-29-100002-pay-bff"
            r = run_cli("recall", "--backlinks-of", dec_id, "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(tid, [x["id"] for x in json.loads(r.stdout)["results"]])
            r2 = run_cli("recall", "--backlinks-of", intent_id, "--json", cwd=tmp)
            ids2 = [x["id"] for x in json.loads(r2.stdout)["results"]]
            self.assertIn(tid, ids2)
            self.assertIn(dec_id, ids2)  # decision도 같은 intent를 가리킴

    def test_complete_moves_to_done_and_reopen_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            self._seed_decision(tmp)
            self._capture_task(tmp)
            tid = "TASK-2026-05-29-100002-pay-bff"
            v = Path(tmp) / "wiki"
            active = v / "task" / f"{tid}.md"
            done = v / "task" / "done" / f"{tid}.md"
            r = run_cli("complete", tid, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(done.is_file())
            self.assertFalse(active.is_file())
            self.assertNotIn(f"[[{tid}]]", (v / "task" / "task.md").read_text())
            self.assertNotEqual(run_cli("complete", tid, cwd=tmp).returncode, 0)
            r2 = run_cli("reopen", tid, cwd=tmp)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertTrue(active.is_file())
            self.assertFalse(done.is_file())
            self.assertNotEqual(run_cli("reopen", tid, cwd=tmp).returncode, 0)

    def test_complete_rejects_non_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            _, dec_id = self._seed_decision(tmp)
            self.assertEqual(run_cli("complete", dec_id, cwd=tmp).returncode, 2)

    def test_task_rejects_supersedes_and_superseded_retire(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            self._seed_decision(tmp)
            bad = run_cli("capture", "task", "--slug", "x",
                          "--title", "X", "--summary", "x.", "--tags", "t",
                          "--supersedes", "move-bff", cwd=tmp,
                          env={"WIKI_NOW": "2026-05-29T10:00:03"})
            self.assertEqual(bad.returncode, 2, bad.stderr)
            run_cli("capture", "task", "--slug", "badt",
                    "--title", "Bad", "--summary", "invalid.", "--tags", "t",
                    cwd=tmp, env={"WIKI_NOW": "2026-05-29T10:00:04"})
            badid = "TASK-2026-05-29-100004-badt"
            sup = run_cli("retire", badid, "--type", "superseded",
                          "--superseded-by", "move-bff", cwd=tmp)
            self.assertEqual(sup.returncode, 2, sup.stderr)
            dep = run_cli("retire", badid, "--type", "deprecated", cwd=tmp)
            self.assertEqual(dep.returncode, 0, dep.stderr)
            self.assertTrue((Path(tmp) / "wiki" / "task" / "retired"
                             / f"{badid}.md").is_file())

    def test_refresh_strict_clean_with_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            self._seed_decision(tmp)
            self._capture_task(tmp)
            r = run_cli("refresh", "--strict", "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(r.stdout)["issues"], [])

    def test_done_task_is_backlink_of_decision_by_default(self):
        # 회귀(Codex #2): 완료된 task도 기본 backlinks에 나와야 한다 —
        # done은 유효한 terminal 상태이지 retired가 아니다.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            _, dec_id = self._seed_decision(tmp)
            self._capture_task(tmp)
            tid = "TASK-2026-05-29-100002-pay-bff"
            self.assertEqual(run_cli("complete", tid, cwd=tmp).returncode, 0)
            # complete 후에도 기본(플래그 없이) backlinks에 task가 보여야 함
            r = run_cli("recall", "--backlinks-of", dec_id, "--json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(tid, [x["id"] for x in json.loads(r.stdout)["results"]])

    def test_capture_after_complete_no_basename_collision(self):
        # 회귀(Codex #1a): done/으로 옮긴 뒤 같은 시각·slug로 재캡처해도
        # basename이 충돌하지 않고 -b suffix가 붙어야 하며 vault는 clean.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            self._seed_decision(tmp)
            self._capture_task(tmp)              # WIKI_NOW 10:00:02 pay-bff
            tid = "TASK-2026-05-29-100002-pay-bff"
            self.assertEqual(run_cli("complete", tid, cwd=tmp).returncode, 0)
            r = self._capture_task(tmp, "--json")  # 동일 WIKI_NOW + slug 재캡처
            self.assertEqual(r.returncode, 0, r.stderr)
            new_id = json.loads(r.stdout)["id"]
            self.assertNotEqual(new_id, tid)      # 같은 basename 재사용 금지
            self.assertTrue(new_id.endswith("-b"))
            # duplicate-basename 검출 0
            chk = run_cli("refresh", "--check", "duplicate-basename",
                          "--strict", "--json", cwd=tmp)
            self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)
            self.assertEqual(json.loads(chk.stdout)["issues"], [])

    def test_complete_refuses_to_clobber_existing_done_file(self):
        # 회귀(Codex #1b): done/에 동명 파일이 이미 있으면 complete가 덮어쓰지
        # 않고 conflict(exit 5)로 거부해야 한다.
        with tempfile.TemporaryDirectory() as tmp:
            self._init(tmp)
            self._seed_decision(tmp)
            self._capture_task(tmp)
            tid = "TASK-2026-05-29-100002-pay-bff"
            v = Path(tmp) / "wiki"
            # done/에 동명 파일을 손으로 심어 충돌 상태를 만든다
            (v / "task" / "done").mkdir(parents=True, exist_ok=True)
            (v / "task" / "done" / f"{tid}.md").write_text(
                "---\ntitle: planted\ncreated_at: 2026-05-29\n"
                "summary: planted.\ntags: [x]\n---\n## 개요\n", encoding="utf-8")
            r = run_cli("complete", tid, cwd=tmp)
            self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
            # 원본은 active에 그대로 남아 있어야 함(이동 안 됨)
            self.assertTrue((v / "task" / f"{tid}.md").is_file())


if __name__ == "__main__":
    unittest.main()
