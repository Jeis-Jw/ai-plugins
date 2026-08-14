from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "mission_receipt.py"
WIKI_CLI = PLUGIN.parent / "wiki-markdown" / "skills" / "wiki" / "scripts" / "wiki_cli.py"

SPEC = importlib.util.spec_from_file_location("mission_receipt", SCRIPT)
assert SPEC and SPEC.loader
mission_receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mission_receipt)

TOP_FIELDS = {
    "schema", "mission_id", "objective", "done_when", "status", "lanes",
    "ready_next", "owner_gate", "snapshot_ref", "started_at", "updated_at",
}
LANE_FIELDS = {"lane_id", "role", "work_ref", "agent_id", "state", "updated_at"}


class MissionReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd = Path(tmp.name)

    def run_cli(self, *args: str, env_extra: dict[str, str] | None = None
                ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, STUDIO_WIKI_CLI="off")
        env.pop("WIKI_VAULT", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False, capture_output=True, text=True, cwd=self.cwd, env=env)

    def receipt_path(self, mission_id: str = "m1") -> Path:
        return self.cwd / ".studio" / "receipt" / f"{mission_id}.json"

    def read_receipt(self, mission_id: str = "m1") -> dict:
        return json.loads(self.receipt_path(mission_id).read_text(encoding="utf-8"))

    # ① init→lane(dispatched)→lane(done)→close 후 필드 집합 = 스키마 정확 일치
    def test_lifecycle_field_set_matches_schema_exactly(self) -> None:
        init = self.run_cli(
            "init", "m1", "--objective", "재개 인덱스 검증",
            "--done-when", "receipt CLI green", "--done-when", "SNAP handoff green",
            "--lane", "dev-1=dev")
        self.assertEqual(init.returncode, 0, init.stderr)

        dispatched = self.run_cli(
            "lane", "m1", "dev-1", "--state", "dispatched",
            "--work-ref", "future-work-skill:node-7", "--agent-id", "agent-42",
            "--ready-next", "리뷰 lane 소집")
        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)

        gated = self.run_cli("gate", "m1", "--reason", "외부 배포 승인 대기")
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertEqual(
            json.loads(gated.stdout)["receipt"]["owner_gate"],
            {"reason": "외부 배포 승인 대기"})
        cleared = self.run_cli("gate", "m1", "--clear")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)

        done = self.run_cli("lane", "m1", "dev-1", "--state", "done")
        self.assertEqual(done.returncode, 0, done.stderr)
        closed = self.run_cli("close", "m1")
        self.assertEqual(closed.returncode, 0, closed.stderr)

        receipt = self.read_receipt()
        self.assertEqual(set(receipt), TOP_FIELDS)
        self.assertEqual(receipt["schema"], "studio.mission-receipt/v1")
        self.assertEqual(receipt["status"], "closed")
        self.assertIsNone(receipt["owner_gate"])
        self.assertIsNone(receipt["snapshot_ref"])
        self.assertEqual(len(receipt["lanes"]), 1)
        lane = receipt["lanes"][0]
        self.assertEqual(set(lane), LANE_FIELDS)
        self.assertEqual(lane["state"], "done")
        self.assertEqual(lane["work_ref"], "future-work-skill:node-7")
        self.assertEqual(lane["agent_id"], "agent-42")

    # ② 미허용 필드 주입 → exit 2 + 파일 무변경 (fail-closed)
    def test_unknown_field_injection_fails_closed(self) -> None:
        self.run_cli("init", "m1", "--objective", "x")
        path = self.receipt_path()
        data = self.read_receipt()
        data["crew_context"] = "누적 추론 로그"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = path.read_bytes()

        result = self.run_cli("lane", "m1", "dev-1", "--state", "dispatched", "--role", "dev")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(json.loads(result.stdout)["error_code"], "schema_violation")
        self.assertEqual(path.read_bytes(), before)

    # ② 미허용 state 주입 → exit 2 + 파일 무변경
    def test_unknown_lane_state_injection_fails_closed(self) -> None:
        self.run_cli("init", "m1", "--objective", "x", "--lane", "dev-1=dev")
        path = self.receipt_path()
        data = self.read_receipt()
        data["lanes"][0]["state"] = "meditating"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = path.read_bytes()

        result = self.run_cli("gate", "m1", "--reason", "확인")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(json.loads(result.stdout)["error_code"], "schema_violation")
        self.assertEqual(path.read_bytes(), before)

    # ② CLI 플래그로 미허용 state → argparse exit 2 + 파일 무변경
    def test_invalid_state_flag_rejected_without_write(self) -> None:
        self.run_cli("init", "m1", "--objective", "x", "--lane", "dev-1=dev")
        before = self.receipt_path().read_bytes()
        result = self.run_cli("lane", "m1", "dev-1", "--state", "meditating")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.receipt_path().read_bytes(), before)

    # ③ wiki CLI 미해결 상태 pause → exit 0, snapshot_ref:null, status:paused
    def test_pause_without_wiki_cli_soft_skips_snapshot(self) -> None:
        self.run_cli("init", "m1", "--objective", "x")
        result = self.run_cli(
            "pause", "m1", "--done", "핵심 구현", "--remaining", "문서",
            "--blocker", "-", "--next-step", "테스트 재개")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["snapshot"], "skipped:wiki_cli_unresolved")
        self.assertIsNone(payload["receipt"]["snapshot_ref"])
        self.assertEqual(payload["receipt"]["status"], "paused")
        on_disk = self.read_receipt()
        self.assertIsNone(on_disk["snapshot_ref"])
        self.assertEqual(on_disk["status"], "paused")

    # pause가 실제 wiki CLI로 SNAP을 저장하고, lane 전이 재개가 이를 폐기한다
    def test_pause_saves_snap_and_resume_discards_it(self) -> None:
        (self.cwd / "wiki").mkdir()
        env = {"STUDIO_WIKI_CLI": str(WIKI_CLI)}
        self.run_cli("init", "m1", "--objective", "SNAP 왕복", "--lane", "dev-1=dev")

        paused = self.run_cli(
            "pause", "m1", "--done", "구현", "--next-step", "리뷰", env_extra=env)
        self.assertEqual(paused.returncode, 0, paused.stderr + paused.stdout)
        payload = json.loads(paused.stdout)
        self.assertEqual(payload["snapshot"], "saved")
        self.assertEqual(payload["receipt"]["snapshot_ref"], "SNAP-studio-mission-m1")
        snap_file = self.cwd / "wiki" / "snapshot" / "SNAP-studio-mission-m1.md"
        self.assertTrue(snap_file.is_file(), list((self.cwd / "wiki").rglob("*")))
        self.assertIn("다음 한 걸음: 리뷰", snap_file.read_text(encoding="utf-8"))

        resumed = self.run_cli(
            "lane", "m1", "dev-1", "--state", "dispatched", env_extra=env)
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        receipt = json.loads(resumed.stdout)["receipt"]
        self.assertEqual(receipt["status"], "active")
        self.assertIsNone(receipt["snapshot_ref"])
        self.assertFalse(snap_file.exists())

    def test_missing_receipt_exits_3(self) -> None:
        result = self.run_cli("show", "m1")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["error_code"], "receipt_not_found")

    def test_corrupt_json_exits_4(self) -> None:
        self.receipt_path().parent.mkdir(parents=True)
        self.receipt_path().write_text("{broken", encoding="utf-8")
        result = self.run_cli("show", "m1")
        self.assertEqual(result.returncode, 4)
        self.assertEqual(json.loads(result.stdout)["error_code"], "receipt_corrupt")

    def test_closed_receipt_rejects_all_mutations(self) -> None:
        self.run_cli("init", "m1", "--objective", "x", "--lane", "dev-1=dev")
        self.run_cli("close", "m1")
        before = self.receipt_path().read_bytes()
        for command in (
                ("lane", "m1", "dev-1", "--state", "dispatched"),
                ("gate", "m1", "--reason", "r"),
                ("pause", "m1"),
                ("close", "m1")):
            result = self.run_cli(*command)
            self.assertEqual(result.returncode, 2, command)
            self.assertEqual(json.loads(result.stdout)["error_code"], "mission_closed")
        self.assertEqual(self.receipt_path().read_bytes(), before)
        show = self.run_cli("show", "m1")
        self.assertEqual(show.returncode, 0)

    def test_init_refuses_overwrite_and_bad_work_ref_rejected(self) -> None:
        self.run_cli("init", "m1", "--objective", "x", "--lane", "dev-1=dev")
        dup = self.run_cli("init", "m1", "--objective", "y")
        self.assertEqual(dup.returncode, 2)
        self.assertEqual(json.loads(dup.stdout)["error_code"], "receipt_exists")

        before = self.receipt_path().read_bytes()
        bad_ref = self.run_cli("lane", "m1", "dev-1", "--state", "dispatched",
                               "--work-ref", "missing-prefix")
        self.assertEqual(bad_ref.returncode, 2)
        self.assertEqual(json.loads(bad_ref.stdout)["error_code"], "usage")
        unknown = self.run_cli("lane", "m1", "ghost", "--state", "dispatched")
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(json.loads(unknown.stdout)["error_code"], "unknown_lane")
        self.assertEqual(self.receipt_path().read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
