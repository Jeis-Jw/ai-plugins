# task-worker workflow

## 실행 단위

- container node는 실행하지 않는다.
- direct dependency가 닫힌 leaf만 ready다.
- `ready_actions[]`는 순서가 아니라 집합이다. write-set이나 resource lock이 겹치지 않으면 동시에 실행한다.
- 동시에 실행되는 leaf마다 별도 worktree와 branch를 사용한다.
- plugin 위임만으로 새 agent나 clean session을 추가하지 않는다.

## 검증 단위

- leaf: 변경 범위의 test/typecheck/diff와 완료 조건
- parent/integration: 병합으로 새로 생긴 interface와 통합 상태
- finding 수정: 무효화된 scope만 delta 검증
- 독립 검토가 명시된 edge: caller가 선택한 reviewer provider 사용

## review lease

review가 필요한 edge만 exact `workflow-review-lease/v1`을 binding의 `review_leases[]`에 둔다.
리뷰가 없으면 lease도 없다. owner/provider는 path-safe opaque identifier이고 requirement는
`self|independent`다. `owner=task-worker`만 local owner이며 나머지는 external owner다.
같은 `lease_id` 또는 `edge_id`에 다른 내용이 들어오면 fail-closed한다.

모든 reviewer dispatch 전에 `review-permit`을 조회한다. external owner는
`externally-owned/skip`, `owner=task-worker`나 lease 없음은 기존 local review policy다.
이 계약은 reviewer 중복 소집만 막으며 run/verify/done/integration gate를 줄이지 않는다.

동일 physical command를 줄이기 위해 논리 node를 합치거나 integration gate를 생략하지 않는다.

## token telemetry

관측 전용이다 — 게이트가 아니며 수치 때문에 non-zero exit하지 않는다.

- capture 지점: Claude Code 세션 JSONL `~/.claude/projects/<slug>/<session_id>.jsonl` + `<session_id>/subagents/agent-*.jsonl`의 `message.usage`. 테스트는 `--projects-root`로 주입한다.
- de-dup: 동일 usage 블록이 연속 라인·iterations[]로 중복 출현하므로 message uuid 기준으로 1회만 합산한다. 단순 줄 합산 금지.
- null-not-0: 대상 파일이 하나라도 결손이거나 파싱에 실패하면 부분합을 내지 않는다 → `tokens:null` + `token_coverage:"unavailable"`. Codex 호스트나 경로 부재도 동일하게 퇴각한다.
- 기록 시점: receipt 방출 직전 1회(closeout). 루프 중 기록 없음.
- 저장: 기존 `workflow-receipt/v1`의 `tokens`/`token_coverage` 필드만 재사용한다. 필드 추가 금지, 신규 ledger 없음. `breakdown`/`agents[]`는 probe stdout 전용이다.
- 소비: `definition_artifact.py receipt --tokens`, `session_review.py emit-receipt --tokens`에 probe 결과를 전달한다. optional resolver — hard dependency가 아니다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/token_probe.py" probe --session-id "$SID" --json
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/token_probe.py" aggregate --receipts .task-worker/local/receipts --json
```

## portable script path

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" --help
```
