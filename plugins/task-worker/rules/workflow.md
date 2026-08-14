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

decomposition 전에 모든 criterion을 executable selector에 연결한다. production public
criterion은 shipped CLI, skill, adapter 또는 artifact layout을 실제 호출한 probe가 있어야
`pass`다. surface가 unavailable이면 pass로 추정하지 않고 `unknown`으로 중단한다.

개발 중 기본값은 targeted/development 또는 delta QA다. full QA는 dependency/shared contract,
영향 범위 불확실성 또는 독립 검증 때문에 필요한 경우에만 machine-readable reason과 함께
실행한다. 독립 hard review와 finding 수정이 끝난 frozen candidate는 같은 addressable reviewer
handle이 확인한다. 그 확인 뒤 fresh final-grade root QA를 한 번 실행한다. final QA가 실패해
source/test/config가 바뀌면 같은 reviewer 확인과 final QA를 다시 거쳐야 한다.

evidence reuse는 `source_tree_pin`으로 확정한 staged/unstaged/untracked relevant bytes, mode,
symlink와 clean submodule 상태에 더해 criteria, exact profile/argv, dependency/lock, toolchain,
selected environment, affected paths와 production public surface digest가 모두 같은 경우만 허용한다.
glob, dirty submodule 또는 읽을 수 없는 source 상태는 `unknown`으로 fail-closed한다. 같은
tree/profile의 여러 selector 결과는 기존 child receipt/evidence ref, result, output digest와
selector coverage를 보존한 batch digest로 투영할 수 있다. child fail/error/missing은 batch
전체 fail이며 별도 batch ledger는 만들지 않는다. integration verify event는 child 본문을
복사하지 않고 이 batch digest 하나만 참조한다.

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
- aggregate coverage가 1보다 작으면 `tokens_total:null`이다. 관측된 부분합은
  `measured_tokens_subtotal`로만 노출하며 mission total처럼 해석하지 않는다.
- elapsed는 lane duration 합이 아니라 mission 시작/종료 wall clock이다. model call과 owner
  intervention 중 하나라도 미측정이면 합계를 0으로 만들지 않고 `null`로 둔다.
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
