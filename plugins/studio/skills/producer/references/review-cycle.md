# Review cycle contract

이 문서는 tracked implementation/QA cycle을 실제로 열거나 이어갈 때만 읽는다. review
cycle은 새 오케스트레이터가 아니라 `.studio/board.md` 안의 논리적 finding/evidence 원장이다.
Issue/DefinitionArtifact/track의 점유·완료 의미와 physical run 기록은 그대로 유지한다.

## 수명과 경계

- 한 cycle = 한 `DefinitionArtifact + Issue leaf(optional) + track + criteria_digest + QualityPlan`.
- 같은 scope/criteria의 발견·수정·재검증은 physical run이나 worker가 바뀌어도 같은 cycle.
- criteria 또는 Issue scope가 바뀌면 새 cycle. full QA로 덮지 않는다.
- `integration-ready`가 terminal success다. `criteria-gap`은 `blocked`와 새 cycle 판단을 만든다.

## 열기와 조회

```bash
python3 "$STUDIO" review open --json @cycle.json
python3 "$STUDIO" review status RC-issue-58
python3 "$STUDIO" review handoff RC-issue-58
python3 "$STUDIO" review summary RC-issue-58
```

`cycle.json`:

```json
{
  "cycle_id": "RC-issue-58",
  "track_id": "track-parser",
  "criteria_digest": "sha256:<64 hex>",
  "base_head": "<git sha or immutable worktree state ref>",
  "quality_plan_ref": "quality-main",
  "definition_ref": {"schema": "definition-artifact/v1", "ref": "..."},
  "issue_ref": "issue:58",
  "requires_final_qa": true,
  "requires_integration_gate": true
}
```

`definition_ref`, `issue_ref`는 nullable이다. 나머지는 필수다. 같은 `cycle_id` 재호출은 binding이
완전히 같을 때만 no-op다. `handoff`는 활성 finding, 유효 evidence pin, pending full-QA
reason만 반환하며 raw transcript를 포함하지 않는다.

## 이벤트 공통 계약

```bash
python3 "$STUDIO" review event RC-issue-58 --json @event.json
```

모든 event는 다음 envelope를 가진다. `event_id`는 재전송 멱등 키다.

```json
{
  "schema": "studio-review-event/v1",
  "event_id": "REV-58-...",
  "cycle_id": "RC-issue-58",
  "type": "finding-opened|evidence-recorded|fix-submitted|qa-completed|retry-recorded|handoff-recorded"
}
```

타입별 추가 필드:

| type | 필드 |
|---|---|
| `finding-opened` | `head`, `finding:{id?,title,severity,repro,affected_criteria[],evidence_refs[]}` |
| `evidence-recorded` | `evidence` pin |
| `fix-submitted` | `finding_ids[]`, `change` impact |
| `qa-completed` | `qa_mode`, `head`, `passed`, `checks[]`, `blocked_checks[]`, `evidence_refs[]`, `finding_results[]`, `full_qa_reason?` |
| `retry-recorded` | `classification`, `failure`, `attempt`, `finding_ids?` |
| `handoff-recorded` | `fresh_context`, `continuation_ref?`, `reason?` |

Finding id를 생략하면 원장이 `F-0001`부터 부여한다. QA가 finding을 `closed`로 만들려면
`passed:true`이고 유효한 defense `evidence_refs`가 있어야 한다.

## Evidence pin과 impact

Evidence pin:

```json
{
  "ref": "EV-parser-1",
  "head": "<state ref>",
  "criteria_digest": "sha256:<64 hex>",
  "covered_paths": ["tests/test_parser.py"],
  "surface_digest": "sha256:<64 hex>",
  "tool_version": "pytest-9",
  "environment_digest": "sha256:<64 hex>",
  "command_digest": "sha256:<64 hex>"
}
```

Change impact:

```json
{
  "head": "<post-fix state ref>",
  "criteria_digest": "sha256:<64 hex>",
  "changed_paths": ["src/parser.py"],
  "surface_digest": "sha256:<64 hex>",
  "tool_version": "pytest-9",
  "environment_digest": "sha256:<64 hex>",
  "impact_known": true,
  "shared_contract_changed": false
}
```

사전 판정:

```bash
python3 "$STUDIO" review evidence-check --evidence @pin.json --change @change.json
```

criteria/tool/environment/dependency surface가 달라졌거나 covered path와 changed path가 겹치면
evidence는 무효다. 영향 범위 불명, shared contract 또는 dependency surface 변경은 full QA를
요구한다. 환경/tool 변경은 관련 evidence를 다시 실행하지만 그 자체로 full QA를 요구하지
않는다. 무효화된 `ref`를 되살리지 말고 실제 재실행 결과를 새 ref로 기록한다.

## QA와 retry 전이

QA mode는 `development | delta | full | final | integration`이다.

- 기본은 영향 범위 `delta`.
- `full`은 pending reason과 같은 `impact-unknown | shared-contract-changed |
  cross-track-change | dependency-surface-changed | independence-required`가 필요하다.
- pending full reason이 있으면 `final`/`integration`은 fail-closed다.
- `final`은 passed checks, 유효 evidence, 열린 finding 0개를 요구한다.
- final QA가 필수면 integration 전에 별도 final 통과가 필요하다.

Retry classification은 `product-defect | environment-transient | tool-unavailable |
configuration-error | criteria-gap`이다. transient/tool/config는 같은 cycle self-loop이고 QA
round를 늘리지 않는다. product defect는 기존 finding을 참조한다. criteria gap은 cycle을
block한다.

Fresh context reason은 `context-unavailable | domain-shift | complexity-boundary |
independence-required | cycle-ledger-invalid` 중 하나여야 한다. 나머지는 worker가 바뀌어도
compact handoff를 사용한다.

물리 검증 배치는 `개발 중 변경 범위 최소 검증 → 통합 HEAD full QA 1회 → finding 수정 범위 delta QA`다. full integration gate와 독립 판단을 없애지 않는다. 같은 HEAD/command/environment/tool version의 deterministic evidence만 재사용하며 Release/device/production 환경처럼 fresh execution 자체가 완료 조건인 check는 별도 evidence key로 실행한다.

## Review lease

review가 필요한 edge만 exact `workflow-review-lease/v1`을 가진다. 필드는 `schema, lease_id, owner, provider, episode_id, edge_id, requirement, criteria_digest, evidence_refs, digest`다. owner는 `studio|task-worker`, provider는 `native|session-review`, requirement는 `self|independent`다. 리뷰가 없으면 lease도 없다.

- `owner=studio`: Studio만 reviewer를 dispatch한다. task-worker/task-github는 externally-owned handoff를 반환한다.
- `owner=task-worker`: Studio reviewer dispatch 금지. worker/provider의 기존 review 흐름을 유지한다.
- task-github의 Studio-owned handoff는 PR/CI/preflight/base/head transport를 유지한다. 동일 lease의 approved verdict와 필수 evidence가 ledger에 돌아오기 전 closeout을 금지한다.
- 동일 criteria/finding 후속은 같은 episode와 유효 evidence를 이어받는다. clean session 횟수를 성과로 삼지 않는다.

## Pairing과 physical run 연결

`review handoff` 출력에 `qaMode`만 더해 pairing broker의 `reviewCycle`로 넘긴다. broker가
반환한 `studio-review-feedback/v1`은 관찰값이다. 실제 post-run head/evidence pin을 확인한 뒤
event로 확정한다. cycle mode pairing은 `developmentReady`를 낼 수 있지만 스스로
`readyForIntegration:true`가 되지 않는다.

여러 event와 physical run 비용을 함께 원자적으로 기록하려면 broker 출력에 다음을 붙인다.

```json
{
  "review_cycle_delta": {
    "cycle_id": "RC-issue-58",
    "events": [{"schema": "studio-review-event/v1", "event_id": "...", "cycle_id": "RC-issue-58", "type": "..."}]
  }
}
```

`run record` 반환의 `issue_events`는 `studio-issue-event/v1` projection이다. team/GitHub 기록을
선택한 경우 external worker가 hidden `marker`를 찾아 comment를 create/update한다. handoff,
evidence pin, transient/tool/config retry는 Issue comment로 투영하지 않는다. local-only면 이
projection을 소비하지 않는다.

`review summary`는 QA/retry/handoff/evidence-reuse counters와 cycle에 연결된 physical run의
token/time을 coverage와 함께 반환한다. `unavailable`/`partial`을 0 또는 exact로 바꾸지 않는다.
