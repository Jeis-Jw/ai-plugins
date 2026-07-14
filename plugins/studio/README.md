# studio — 살아있는 에이전트 팀

owner가 큰 미션을 주면, **producer**(메인스레드)가 **crew**(페르소나)를 백그라운드
**ritual run**으로 소집하고, 독립 **critic**이 delta 증거로 "비싼 연극"을 걸러낸다.
순차 파이프라인이 아니라 여러 track이 동시에 도는 포트폴리오 운영이다.

> 세계관: **owner가 studio에 mission을 주면, producer가 crew를 convene하고,
> critic이 연극을 걸러낸다.**

## 왜

`task-github orchestrate`는 *일이 정의된 후*의 실행 루프다. studio는 *일의 정의부터
시연까지*를 팀 안으로 들인다. 핵심은 에이전트 간 상호작용(기획끼리 브레인스토밍,
dev↔qa 공방)이 **실제 품질을 만드는가**이며, 그 판정을 critic + delta 증거로
객관화한다. 살아있음은 목적이 아니라 품질 수단이다.

## 구성

| 요소 | 위치 | 역할 |
|---|---|---|
| producer 스킬 | `skills/producer/` | 메인스레드 규약: 소집·중계·게이트, 직접 제작·판단 대리 금지 |
| studio CLI | `scripts/studio.py` | 결정적 상태: schema 2 board, QualityPlan, Context Kernel, fenced lease·budget, WorkPacket/ResultEnvelope, native execution permit/receipt/closeout |
| agent 정책 | `.studio.yml` (repo 루트, `config scaffold`로 생성) | crew 서브에이전트의 model/effort 층별 설정 |
| 브로커 | `broker/brainstorm.workflow.js`, `broker/pairing.workflow.js` | ritual 실행체(Workflow) — transcript 릴레이, 순수 오케스트레이션(fs 없음) |
| crew | `crew/*.md` | 페르소나 데이터(name·role·prior·requested_tools·activation) — init이 `.studio/crew/`로 복사 |
| casting policy | `rules/casting.md` | producer가 mission을 분류해 crew/tool/gate를 고르는 최소 규칙 |
| critic rubric | `critic/rubric.md` | 검증 전용 계약 + anchor 규칙 |
| mission 템플릿 | `templates/mission.md` | 미션 계약(KPI·예산·게이트·완료기준) |

## studio mode

Studio는 단발 명령이 아니라 출근/퇴근형 운영 모드다. `mode start` 후에는 개별 run이나
track이 끝나도 producer가 계속 studio mode로 대화한다. owner가 종료를 지시할 때만
`mode end`를 호출한다.

```bash
python3 plugins/studio/scripts/studio.py mode start
python3 plugins/studio/scripts/studio.py mode status
python3 plugins/studio/scripts/studio.py mode end
```

상태는 `.studio/board.md`의 `studio_mode`에 저장된다. 세션이 이어지면 producer는 먼저
`mode status`를 확인하고 active이면 이전 운영 맥락을 이어간다.

runtime 작업장의 기본 경로는 repo 루트의 `.studio/`이며, 전체 디렉터리가 로컬 상태라
git에 커밋하지 않는다. 예전 `studio/` 작업장이 있다면 자동 이동이나 삭제 없이 직접
한 번만 옮긴다:

```bash
mv studio .studio
```

다른 경로가 필요하면 모든 상태 명령에 `--workspace <path>`를 명시한다. 플러그인 제품
코드 경로인 `plugins/studio/`와 track 브랜치 접두사 `studio/track-*`는 이 작업장과 별개다.

## 개념 (계약 층 — 은유 금지)

- **run I/O 계약**: `{run_id, ritual, participants, synthesis, minority, delta_log[{round, changed_what, anchor, evidence, rejected_alternative}], verdict{alive,reason}, proposals, cost, receipt, aborted}`. receipt는 `workflow-receipt/v1`의 정확한 11필드이며 broker 실행 전후 token delta와 elapsed time을 담는다.
- **pairing integration 계약**: `{worktreePath, branch, changedFiles, verification, blockedChecks, readyForIntegration}`. `readyForIntegration:false`이면 producer는 직접 수정하지 않고 dev/fix → QA loop로 되돌린다.
- **review cycle**: 한 DefinitionArtifact/Issue leaf/track/criteria digest에 결합된 논리적
  검증 단위. 여러 물리 run·fix·retry가 생겨도 finding ID와 evidence pin을 유지한다.
- **anchor**: delta가 실제로 닿는 대상 — `artifact | acceptance-criteria | risk | rejected-alternative | repro-test`. anchor 없는 delta는 delta가 아니다.
- **dry**: 유효 delta 없는 라운드. dry 2회 = 폐회.
- **theatre**: 팀 run인데 valid delta 0 → 연극 판정.
- **integration**: QA pass 뒤 main 반영은 owner gate 후 integrator worker 또는 결정적 CLI가 수행한다. producer는 `git apply`/`apply_patch`로 직접 통합하지 않는다.

## v0.2 품질·컨텍스트·외부 실행 계약

Studio가 mission·QualityPlan·context·owner gate의 정본을 소유한다. 실행은 track마다
`native`, `task-worker`, `task-github` 중 하나만 lease로 점유하며, 외부 workflow의 issue/branch/PR
상태나 raw transcript를 board에 복제하지 않는다.

- **QualityPlan**: artifact/context criterion은 각각 `{id, kind, weight, floor, measure}`를
  가진다. criterion-bound evidence가 없거나 `score < floor`이면 비용 점수와 무관하게
  통합 불가다. floor 통과 후에만 quality 최고 비중의 utility를 계산한다.
- **telemetry**: `{tokens, elapsed_ms, avoidable_owner_questions}` 중 하나라도 불완전하거나
  `tokens:null`이면 incomplete다. 알 수 없는 값을 0으로 바꾸지 않는다.
- **receipt**: broker는 `budget.spent()`의 실행 전후 차이를 `tokens/exact`로 기록하고
  wall-clock `elapsed_ms`를 함께 반환한다. 측정 불가 token은 `null/unavailable`이며
  `run record`가 budget spend를 변경하지 않는다. `--receipt-log` JSONL append 실패는
  run/minutes/ledger 기록을 되돌리지 않고 `warnings`로만 보고한다.
- **Context Kernel**: `.studio/context/{items,bundles,deltas,outbox}`에 digest가 결합된
  ContextItem/ContextPack/ContextDelta와 promotion candidate를 보존한다. schema 1 board는
  읽을 때 schema 2로 lazy projection되고 다음 mutation에서만 저장된다.
- **lease/budget**: `reserve → dispatch → settle|release`는 reservation/lease 기준으로
  idempotent하며, track당 active lease는 1개다. 모든 전이는 `lease_id` fencing을 검증한다.
- **external adapter**: WorkPacket을 별도 worker에 넘기고 ResultEnvelope만 회수한다.
  GitHub 기록이 없으면 `task-worker:*`, GitHub delivery가 필요하면 `task-github:*` facade를
  사용한다. callable API를 만들지 않으며 producer가 agent-visible catalog와 read-only
  doctor/preflight 결과로 capability snapshot을 만든다.
- **review provider**: session-review는 major/independence-required edge에만 선택한다. clean
  session 횟수를 품질 지표로 삼지 않고 동일 criteria/context digest의 review episode를 재개한다.
- **fallback**: dispatch 전 worker unavailable/unknown이면 정책에 따라 native로 전환한다.
  signed session-review lease가 unavailable이면 provider만 바꾸지 않고
  `review-lease-replan-required`가 제시한 exact native target lease로 pending reservation을
  accepted binding으로 전이한다. dispatch 뒤
  실패는 resume 또는 cancel-confirm+budget release 전에는 다른 executor로 전환하지 않는다.
- **wiki provider**: wiki-markdown은 optional이다. 없으면 owner-gated promotion candidate가
  local outbox에 남고, 있어도 owner 승인 뒤 agent-visible provider handoff만 만든다.

핵심 결정적 명령:

```bash
python3 plugins/studio/scripts/studio.py quality evaluate --plan @plan.json --evidence @evidence.json --telemetry @telemetry.json
python3 plugins/studio/scripts/studio.py context put item --json @item.json
python3 plugins/studio/scripts/studio.py budget reserve <reservation> --lease-id <lease> --tokens <n>
python3 plugins/studio/scripts/studio.py workflow validate-packet --json @packet.json
python3 plugins/studio/scripts/studio.py routing plan --mission-id <mission> --environment-digest <digest> --runtime-capability @runtime-capability.json
python3 plugins/studio/scripts/studio.py workflow dispatch --packet @packet.json --plan @plan.json --capabilities @snapshot.json --lease-id <lease>
python3 plugins/studio/scripts/studio.py workflow result --packet @packet.json --plan @plan.json --json @result.json --lease-id <lease>
```

## v0.4 반복 QA·handoff 비용 제어

작업 분해와 독립 검증은 유지하되, 그 주변의 반복 비용을 logical review cycle로 줄인다.
Issue tree를 사용하는 경우 Issue는 여전히 팀원이 점유하고 완료할 수 있는 업무 단위이며,
cycle은 그 Issue 안의 finding/수정/QA 이력이다. GitHub 기록을 선택하지 않으면 같은
DefinitionArtifact와 cycle을 `.studio/`에서만 소비한다.

- finding은 `F-xxxx`로 고정되어 새 run/agent에서도 이어진다.
- handoff에는 활성 finding과 유효 evidence pin만 들어가며 transcript는 들어가지 않는다.
- evidence는 criteria/head/path/dependency surface/tool/environment/command pin이 같고 수정
  영향과 겹치지 않을 때만 재사용한다.
- 기본 재검증은 delta QA다. full QA는 shared contract·dependency surface 변화, 영향 범위
  불명, 독립성 요구처럼 구조화된 사유가 있어야 한다. criteria/scope 변경은 새 cycle이며,
  환경/tool 변경은 관련 evidence만 다시 실행한다.
- transient/tool/config failure는 같은 cycle의 retry이며 새 finding이나 QA round가 아니다.
- summary는 cycle에 연결된 physical run의 measured token/time만 coverage와 함께 합산한다.
  미측정 값은 0으로 추정하지 않는다.
- final QA와 integration gate는 fail-closed이고, pending full-QA 사유를 우회할 수 없다.
- team mode에서는 중요한 cycle 이벤트를 `studio-issue-event/v1`로 반환한다. external
  worker가 event marker를 기준으로 Issue comment를 멱등 투영하며 Studio가 GitHub 상태를
  중복 보관하지 않는다.

```bash
python3 plugins/studio/scripts/studio.py review open --json @cycle.json
python3 plugins/studio/scripts/studio.py review handoff RC-issue-58
python3 plugins/studio/scripts/studio.py review event RC-issue-58 --json @event.json
python3 plugins/studio/scripts/studio.py review evidence-check --evidence @pin.json --change @change.json
python3 plugins/studio/scripts/studio.py review summary RC-issue-58
```

`pairing.workflow.js`에 `reviewCycle` handoff를 넘기면 기존 finding ID를 이어받은
`studio-review-feedback/v1`을 반환한다. 이는 development/delta 관찰값이라 실제 post-run
head/evidence와 결합해 `review event` 또는 `run record`의 `review_cycle_delta`로 확정해야
한다. cycle mode pairing만으로는 integration-ready가 되지 않는다.

## v0.5 선택적 도구 라우팅과 review owner

Studio의 native harness는 `strategist`, `planner-a/b`, `researcher`, `product-designer`, `visual-designer`, `architect`, `dev`, `creator`, `qa`, `reviewer`, `critic`, `curator`, `summarizer` 역할을 기본 제공한다. 외부 도구가 없어도 리서치→기획→설계→구현→QA→독립 판단→통합을 완주한다.

- 도구 선택은 **run parameter > `.studio.yml` > native**다. 설정·파라미터에 이름이 없는 plugin을 discovery/probe하지 않는다.
- worker는 track당 `native|task-worker|task-github` 하나만 lease한다. task-github는 내부 task-worker adapter 책임을 포함하므로 Studio가 task-worker를 별도 probe/lease하지 않는다.
- `activation:auto|always|never`의 `auto`는 설정된 후보를 사용할 필요를 Studio가 판단한다는 뜻이지 미설정 plugin 자동 탐색이 아니다.
- 명시 run override가 unavailable이면 STOP한다. 설정 provider unavailable은 해당 설정의 `fallback:native|stop`을 따른다.
- capability는 선택된 외부 provider만 `(mission_id, provider, environment_digest)`당 한 번 확인하고 `studio-capability-snapshot/v1`으로 재사용한다.

결정 결과는 `studio-routing-plan/v1`의 canonical fields `worker.selected`, `worker.provider`, `reviewer.owner`, `reviewer.provider`, `reviewer.dispatch`, `reviewer.selected`, `review_lease`, `action`, `digest`로 고정한다. reviewer가 필요한 edge만 exact `workflow-review-lease/v1`을 만든다. 필드는 `schema, lease_id, owner, provider, episode_id, edge_id, requirement, criteria_digest, evidence_refs, digest`이고 owner는 `studio|task-worker`, provider는 `native|session-review`만 허용한다. `owner=studio`이면 외부 worker/adapter는 reviewer를 소집하지 않고 Studio가 native/session-review를 실행한다. `owner=task-worker`이면 Studio는 reviewer를 추가 소집하지 않는다. Edge ledger는 capability 확인 전 `pending` reservation과 dispatch 가능한 `accepted` binding을 구분한다. Studio-owned session-review capability가 unavailable이고 fallback이 native이면 동일 mission/edge/lease identity의 provider만 `native`로 바꾼 exact target lease를 `review-lease-replan-required`에 명시한다. 그 target만 pending→accepted로 원자 전이하며 임의 mission/edge/provider/digest 변경과 accepted 재바인딩은 거부한다. 구형 digest-only entry는 accepted immutable binding으로 해석한다.

최적화 단위는 논리 gate가 아니라 물리 실행이다. ready-set 병렬성, worktree 격리, 독립 판단, 통합 HEAD full gate는 유지하고 검증을 다음처럼 배치한다.

```text
개발 중 변경 범위 최소 검증
→ 통합 HEAD full QA 1회
→ finding 수정 범위 delta QA
```

같은 HEAD/command/environment/tool version의 성공 evidence는 재사용한다. fresh Release/device/production 환경 확인처럼 완료 조건 자체가 새 실행을 요구하는 gate만 별도 evidence key를 쓴다. handoff는 criteria, open finding, changed paths, valid evidence, next action만 전달하고 transcript/repo 재탐색을 반복하지 않는다.

## agent runtime/model/effort 정책 (`.studio.yml`)

crew 서브에이전트가 어떤 모델·에포트로 돌지는 `.task-worker.yml`/`.task-github.yml`과 분리된 repo
루트 설정파일 `.studio.yml`로 정한다. 현재 runtime profile은 `claude|codex`만 지원하며 agent별 stable id를 사용할 수 있다. 해석 순서(most→least specific):

```
run override
> providers.<runtime>.rituals.<ritual>.<step>
> rituals.<ritual>.<step>
> providers.<runtime>.agents.<agent-id>
> agents.<agent-id>
> providers.<runtime>.roles.<role>
> roles.<role>
> providers.<runtime>.defaults
> defaults
> omit(세션 상속)
```

blank/null은 다음 층으로 넘어가고, 아무 층도 안 정하면 producer 세션 모델·에포트를
그대로 상속한다. model/effort 값은 문자열 구조만 검사하며 global allowlist로 특정 provider 지원을 과장하지 않는다. `studio-runtime-capability/v1`의 verified runtime과 advertised model/effort set이 있으면 resolved non-null 값을 그 집합으로 fail-closed 검증하고, 광고 집합이 없으면 지원 상태는 `unknown`이다. runtime override는 profile 선택일 뿐 해당 harness capability를 새로 만들지 않는다. non-null profile은 verified host runtime과 일치할 때만 dispatch할 수 있다. producer는 broker에 matching `runtimeCapability`가 있을 때만 `agentRuntime`을 주입하고, brainstorm/pairing broker는 stable `agentId`와 canonical `roleId || name`으로 같은 resolver를 적용한다. `role`은 표시용이다.
예: critic=high(연극 판정 날카롭게), summarizer=low(중립 압축은 싸게), diverge=low.

```bash
python3 plugins/studio/scripts/studio.py config scaffold   # .studio.yml 생성
python3 plugins/studio/scripts/studio.py config validate    # 구조 검증
python3 plugins/studio/scripts/studio.py config resolve --agent-runtime codex --runtime-capability @runtime-capability.json
```

## casting helper

Producer는 `cast suggest`로 기본 crew 조합을 기계적으로 조회한다. 이 helper는 판단을
대체하지 않고, `rules/casting.md`의 기본값을 JSON으로 돌려준다.

```bash
python3 plugins/studio/scripts/studio.py cast list
python3 plugins/studio/scripts/studio.py cast suggest idea
python3 plugins/studio/scripts/studio.py cast suggest implementation
```

`critic`은 일반 persona가 아니라 ritual의 검증 역할이다. `participants`에는 broker에
넘길 실제 persona만 들어가고, `critic: true`이면 critic rubric을 함께 붙인다.

## 흐름

1. owner 미션 → producer가 `.studio/missions/<slug>.md` 계약화 → **owner 게이트**.
2. producer가 `studio.py cast suggest <kind>`와 `rules/casting.md`로 일을 분류하고
   최소 crew/tool/gate를 고른다.
3. 백로그 분해(KPI 링크 강제, `studio.py backlog check`).
4. producer가 페르소나·안건·rubric을 `args`로 실어 브로커 Workflow를 **백그라운드**
   소집. 회의형(brainstorm)은 무제한 병렬, 작업형(pairing)은 producer가 준비한
   track 워크트리에서 격리 실행.
5. 완료 회수 → native ritual은 `run record`, external executor는 `workflow result`로 기록.
6. post-QA 결함은 같은 review cycle/finding ID로 dev/fix → 영향 범위 delta QA를 이어간다.
   전체 handoff/full QA는 구조화된 사유가 있을 때만 사용한다.
7. verification·criterion evidence·quality floor·telemetry·gate가 모두 완결돼
   `readyForIntegration:true`일 때만 owner에게 반영 게이트를 묻는다.
8. 검증(baseline): 같은 소형 미션을 솔로 vs 팀으로 돌려 `studio.py evidence`로
   추가 delta를 센다. theatre면 리추얼 재설계.

## MVP crew

| 영역 | crew |
|---|---|
| 운영 | `producer` (메인스레드 전용 이름, crew role로 재사용 금지) |
| 전략/기획 | `planner-a`(growth), `planner-b`(risk), `strategist` |
| 자료수집/분석 | `researcher` |
| 제품/설계 | `product-designer`, `visual-designer`, `architect` |
| 제작/실행 | `dev`, `creator` |
| 검수/검증 | `qa`, `reviewer`, `critic` |
| 기록/지식 | `curator` |

## 게이트 (owner 전권)

미션 계약 확정·변경 / 신규 에픽·방향 전환 / 머지 등 비가역 / 결정·기각 wiki 승격 /
외부 공개(발행·배포·계정) / 예산 상향.

## 상태

v0.6.0 — canonical command profile·impact permit, atomic physical execution claim, immutable receipt/evidence, run cap·telemetry·external spend gate를 추가했다. 분해·ready-set 병렬성·독립 검증·통합 HEAD full gate는 유지하고 동일 물리 실행과 stale context 재수집만 차단한다.

v0.5.0 — native 기본·명시적 외부 도구 라우팅, Claude/Codex agent profile, 단일 review lease owner, capability/evidence 재사용과 development→integration full→finding delta QA 계약.

v0.4.0 — stable review cycle·delta/full QA gate·evidence reuse·compact handoff·Issue event projection.
기존 schema-v1 workflow receipt·QualityPlan·Context Kernel·optional external executor도 유지한다. 설계 정본은 이 repo
위키(INT/DEC studio) + `drafts/agent-team-concept.md`.
검증 테스트: `python3 plugins/studio/tests/test_studio.py`와
`node --test plugins/studio/tests/test_broker_semantics.js`.

후순위(정의만, MVP 비활성): 마케팅/판매 운영 역할, 동적 채용(casting), standup/retro/demo
리추얼과 추가 external workflow adapter.
