# task-worker 설계 계약

## 불변식

1. **분해 품질을 비용 절감 수단으로 축소하지 않는다.** 독립 책임·위험·rollback 경계는 논리 node로 유지한다.
2. **병렬성을 보존한다.** planner는 모든 실행 가능 leaf를 `ready_actions[]`로 반환한다.
3. **동시 write를 격리한다.** 각 leaf는 stable branch/worktree identity를 갖는다.
4. **검증 사실만 재사용한다.** 변경된 scope·criteria·artifact revision은 기존 pin을 무효화한다.
5. **provider 상태를 core에 넣지 않는다.** Issue, PR, label, Studio track, wiki node는 adapter binding이다.
6. **review owner는 edge당 하나다.** review가 필요한 edge만 review lease를 갖고 reviewer dispatch 전에 permit을 소비한다.
7. **추가 agent hop을 만들지 않는다.** plugin 호출 경계와 execution episode 경계는 동일하지 않다.

## 0.2.0 경계

- 새 canonical schema는 `task-worker.definition/v1`, `task-worker.local-run/v1`이다.
- 기존 local artifact/run을 버리지 않도록 task-github v1 schema는 read-compatible하다.
- 새 artifact에는 provider-specific `record`를 허용하지 않는다.
- external delivery는 provider-neutral `external`로만 표현한다.
- provider adapter는 `task-worker.work-graph/v1` snapshot을 공급하고 `task-worker.ready-plan/v1`을 소비한다.
- planner는 모든 ready leaf와 자식 완료로 새 통합 상태가 생긴 container/root를 각각 `ready_actions[]`, `integration_candidates[]`로 반환한다.
- `capabilities`가 지원 command와 exact contract schema를 공개하며 adapter는 불일치 시 fail-closed한다.
- GitHub projection과 remote delivery 코드는 task-github에 남긴다.
- generic evidence cache와 command fingerprint는 별도 후속 기능이다. 0.2.0은 기존 task-github evidence gate를 이동하지 않고 execution core 중복 제거와 planner 위임을 완료한다.

## 상태 모델

```text
started → running → verified → done → closed
```

각 전이는 idempotent하다. `verify` event에는 구조화된 evidence를 붙인다. `ready`는 같은 artifact digest에 pin된 closed blocker만 완료로 인정하며, active run이 중복되면 fail-closed한다. provider snapshot에서는 unknown blocker를 미해결로 유지하고 dependency cycle이면 부분 ready set도 반환하지 않는다.

## token telemetry (관측 전용)

`scripts/token_probe.py`가 플러그인 기계장치의 토큰 비용을 관측한다. 게이트가 아니라 손익분기선 도출 재료다.

- `probe --session-id S [--agent-id A ...] --json` → `{tokens:<int>|null, token_coverage:"exact"|"unavailable", source, breakdown{input,output,cache_creation,cache_read}|null, agents[]}`. tokens는 4개 필드의 합. `--agent-id`는 기대 subagent 집합이며, 그중 하나라도 결손이면 전체가 unavailable로 퇴각한다.
- de-dup 계약: 세션 JSONL에서 동일 usage 블록이 연속 라인·iterations[]로 중복 출현한다(실측). message uuid 기준 중복 제거를 계약으로 고정한다.
- `aggregate --receipts DIR --json` → `{runs, measured_runs, coverage_ratio, tokens_total:<int>|null, by_workflow{}}`. 기존 receipt 스토어를 읽기만 한다.
- receipt 스키마 무변경: `workflow-receipt/v1`의 `tokens`/`token_coverage`를 재사용하며 `breakdown`/`agents[]`는 stdout 전용이다. 소비처(`definition_artifact.py receipt --tokens`, `session_review.py emit-receipt --tokens`)에는 optional resolver로만 연결되고 hard dependency가 없다.
- 기각 대안: OTEL(인프라 과대), SubagentStop 훅(usage 미제공), 별도 ledger(기존 receipt와 중복).

## 0.8.0 generic external review owner

`workflow-review-lease/v1`의 owner/provider는 path-safe opaque identifier다.
`owner=task-worker`만 local reviewer dispatch를 뜻하고 다른 owner는 모두 external handoff다.
`review-lease` command가 canonical digest와 stable lease id를 생성하므로 caller는 schema를
복제하지 않는다.

## 0.7.0 deterministic cleanup

`cleanup` policy는 merge/FF가 확인된 clean task worktree, local branch와 stale metadata 정리를
task-worker가 소유하게 한다. `cleanup.py`는 primary/dirty/unmerged 대상을 fail-closed하고
`task-worker.cleanup-receipt/v1`을 반환한다. provider는 이 receipt를 재사용하고 로컬 정리를
중복 실행하지 않는다.

## 0.6.0 workspace onboarding

`task-worker:init`은 consumer workspace에 provider-neutral policy와 local state를 초기화한다. `local`, `manual`, `quality`, `minimal` preset은 실행·delivery·telemetry 축만 결정하며, Studio/GitHub/Wiki/reviewer provider를 발견하거나 설정하지 않는다.

`local`, `manual`, `quality`은 command profile과 impact rule의 위치를 고정하고 빈 TODO skeleton을 만든다. 이 skeleton은 JSON으로는 정상이나 canonical loader에는 실행 불가능하다. 프로젝트별 command를 추측한 약한 QA가 조용히 허용되는 대신, policy가 채워질 때까지 fail-closed 한다. `minimal`은 command policy를 명시적으로 사용하지 않는다.

init은 전체 대상의 충돌을 먼저 확인한다. 같은 내용은 skip하고 다른 기존 config/policy는 `--force` 없이는 어떤 파일도 변경하지 않는다. `.task-worker/local/`만 gitignore하며 policy는 추적 가능한 프로젝트 계약으로 남긴다. `task-worker:doctor`는 config validator, state-root, canonical policy loader를 읽기 전용으로 검사하고 TODO와 오류를 구분한다.

이 onboarding 표면은 DefinitionArtifact, ready-set planner, worker lane, worktree lease, verify evidence, independent review edge, root integration gate를 변경하지 않는다.

## 0.5.0 execution control

task-worker가 execution control과 canonical fixture를 단독 소유한다. 기존 consumer와 저장된
artifact 호환을 위해 `studio-verification-contract-set/v1` schema id와
`tests/fixtures/studio-verification-contract-v1.json` 파일명은 유지하지만 Studio runtime
복제본이나 cross-package parity 검사는 없다. task-worker는 command profile과 impact rule로
허용 QA mode/명령을 결정하고, profile과 다른 argv·forbidden argv·machine-readable reason
없는 full QA·동일 physical identity의 중복 claim을 실행 전에 거부한다.

`command_digest`의 canonical preimage는 실제 실행 직전 해석된
`{executable,args,cwd,environment}`다. profile/cycle/unit/target 같은 attribution은 command
digest나 physical identity에 넣지 않는다.

physical identity는 `head + command_digest + environment_digest + tool_version + purpose + optional fresh_requirement_id`만 사용한다. definition/node/cycle/unit/target/profile id는 attribution이며 identity에 섞지 않는다. 성공 결과는 immutable command receipt와 verification evidence의 digest/source binding이 유효할 때만 재사용한다. 이 제어층은 logical node 분해, 전체 ready set, worktree 격리, 독립 review와 root integration gate를 줄이지 않는다.

## 0.4.0 review lease

`review_leases[]`는 provider dependency가 아니라 reviewer 소유권 fencing이다. exact fields는 `schema, lease_id, owner, provider, episode_id, edge_id, requirement, criteria_digest, evidence_refs, digest`이며 canonical digest와 `lease_id`/`edge_id` 유일성을 검증한다.

- `owner=task-worker`: task-worker가 선택한 reviewer와 feedback loop 유지
- 그 밖의 opaque owner: task-worker reviewer dispatch 금지, `externally-owned/skip` handoff 반환
- lease 없음: standalone 기존 local review policy 유지

lease는 review를 제거하지 않고 중복 dispatch만 막는다. node run, verification evidence, done, integration candidate gate는 기존 계약대로 실행한다.
