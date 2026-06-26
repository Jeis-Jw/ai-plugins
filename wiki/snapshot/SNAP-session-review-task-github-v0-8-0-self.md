---
title: session-review: task-github v0.8.0 self
created_at: 2026-06-26
summary: Self-mode review handoff for task-github v0.8.0 4-unit implementation.
tags: [session-review, review, task-github, self]
type: snapshot
updated_at: 2026-06-26
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "diff"
target_nature: "code"
target_ref: "main-review"
base_ref: "7a7302d14c53001544fb96e0d62444a248612fce"
responding_to: "353f1bfed2f08ec82d010ddadfd70637e048020f"
round: 3
round_type: "review"
flow_mode: "self"
review_strength: "normal"
blocking_count: 0
```

### 리뷰 피드백 (round 3)

[directional] 승인합니다. Round 2 blocking은 해결됐습니다. `context_bundle.py --input -` 출력 top-level에 `owner`/`repo`가 포함되고, `task_relation_missing_root`는 해당 값이 있을 때 `wiki relate ... owner/repo#ROOT` action으로 계획됩니다.

[directional] `reconcile --apply`와 `doctor --fix`의 manual/skipped path는 `ok=false`와 CLI exit 1로 실패 처리됩니다. `applied=true`는 apply 시도 여부라서 성공 판정은 `ok`/exit code를 기준으로 봐야 합니다.

[directional] Round 1 blockers sanity check도 회귀 없음으로 봅니다. local closeout은 empty/missing drift·integrity evidence를 실패 처리하고, hard/major leaf policy gate, `## Wiki Context` section-only TASK resolver, argv-array-only `required_checks` 경로가 테스트와 구현에 남아 있습니다. `python3 -m unittest discover -s plugins/task-github/tests -p 'test_*.py'`는 39개 통과했습니다.

## 배경

target_mode=diff, target_ref=main-review, base_ref=7a7302d14c53001544fb96e0d62444a248612fce, review_branch=main-review, flow_mode=self

## 정해진 것

Round 1 feedback 처리:
- accepted: local closeout은 missing drift/integrity evidence와 empty required_checks를 실패로 처리한다. 위키 미가용은 명시적 skip evidence만 허용한다.
- accepted: hard/major leaf risk는 leaf_policy evidence(`self_flow_verified`, `hard_self_flow_verified`) 없으면 local closeout을 차단한다.
- accepted: root TASK resolver와 closeout task completion parser는 `## Wiki Context` section 안의 TASK만 bridge로 인정한다.
- accepted: Execution Contract `required_checks`는 argv array만 실행하고 shell string은 거부한다. CLI extra는 shlex split 후 shell=False로 실행한다.
- accepted: `doctor --fix`는 `reconcile --apply` alias로 연결했다. 기본 `doctor --json`은 diagnose-only를 유지한다.
- accepted: snapshot task done 문서 trailing whitespace를 제거했다.

Round 2 feedback 처리:
- accepted: context bundle output에 `owner`/`repo`를 포함해 `task_relation_missing_root` reconcile이 자동 계획 가능하게 했다.
- accepted: reconcile apply가 manual/skipped action을 성공으로 보고하지 않도록 `returncode=1`, `ok=false`로 판정한다.

## 아직 열린 질문



## 다음에 볼 것

self-mode reviewer가 snapshot-load 후 session-review:review를 실행한다.

## 관련 파일/문서

main-review

## 승격 후보
