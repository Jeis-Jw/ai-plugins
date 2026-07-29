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
| 초기화/진단 스킬 | `skills/init/`, `skills/doctor/` | workspace+config 단일 초기화와 native-first read-only 진단 |
| agent 정책 | `.studio.yml` (repo 루트, `init`으로 작업장과 함께 생성) | crew 서브에이전트의 model/effort 층별 설정 |
| 브로커 | `broker/solo.workflow.js`, `broker/brainstorm.workflow.js`, `broker/pairing.workflow.js` | 정적 production scale별 ritual 실행체(Workflow) |
| Codex Runner | `scripts/codex_workflow_runner.mjs` | callable Workflow가 없는 Codex에서 기존 broker를 AsyncFunction으로 주입 실행하는 production adapter |
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

## 초기화와 진단

`init`은 `.studio/`와 `.studio.yml`을 한 번에 만든다. 같은 내용으로 다시 실행하면
skip하고, 기존 파일이 다르면 `--force` 없이 아무것도 변경하지 않는다. `--dry-run`은
쓰기 없이 생성 계획과 config validation을 반환한다.

```bash
python3 plugins/studio/scripts/studio.py init --json
python3 plugins/studio/scripts/studio.py init --worker task-worker --json
python3 plugins/studio/scripts/studio.py init --worker task-github --reviewer session-review --json
python3 plugins/studio/scripts/studio.py init --dry-run --json
python3 plugins/studio/scripts/studio.py doctor --json
```

worker/reviewer를 생략하면 native다. 명시한 provider만 `.studio.yml`에 기록하며, init과
doctor 모두 외부 plugin을 discovery/probe하거나 GitHub·배포 서비스를 변경하지 않는다.
`task-github`는 task-worker adapter 책임을 포함하므로 worker 둘을 함께 lease하지 않는다.
`--force`는 live board를 포함한 Studio-owned scaffold를 갱신하므로 명시적 재초기화 때만 쓴다.

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
  통합 불가다. floor 통과는 `quality_complete`이며 delivery/integration 판단에 사용한다.
- **telemetry**: `{tokens, elapsed_ms, avoidable_owner_questions}` 중 하나라도 불완전하거나
  `tokens:null`이면 효율 주장은 incomplete다. 품질 완료를 막지 않으며 알 수 없는 값을
  0으로 바꾸지 않는다. utility는 quality와 telemetry가 모두 완결됐을 때만 계산한다.
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
python3 plugins/studio/scripts/studio.py init              # .studio/ + .studio.yml 생성
python3 plugins/studio/scripts/studio.py config scaffold   # config-only 호환 명령
python3 plugins/studio/scripts/studio.py config validate    # 구조 검증
python3 plugins/studio/scripts/studio.py config resolve --agent-runtime codex --runtime-capability @runtime-capability.json
```

## Codex Workflow Runner

Codex host에 callable Workflow가 없으면 verified runtime capability가 있는 경우에만
production Runner가 기존 `brainstorm.workflow.js` 또는 `pairing.workflow.js`를 그대로
로드하고 `agent/parallel/phase/log/budget` 경계를 주입한다. broker source는 runtime별로
fork하지 않는다.

Read-only brainstorm의 Production 기본 경로는
`persistent_brainstorm_controller.mjs`다. reducer만
phase/order/barrier/maxRounds/dryStop을 전이하고 Controller는 runtime-owned store의 opaque
state ref와 pending action만 실제 bundled Codex app-server에 relay한다. store는 exclusive
create, lock, digest fence, temp+rename update로 stale/replay/tamper를 fail-close한다.

Action은 turn/generation/state digest/transition, exact canonical label, host-valid immutable
`task_name`을 포함한다. structured output은 exact schema로 검증하고 malformed result는
original handle에 한 번만 repair한다. partial failure는 clone-before-commit으로 cancel
전이하며 cancel evidence가 불완전하면 `recovery_required`다. token은 nonnegative integer와
exact coverage가 함께 있을 때만 measured이고 그 외 측정 불가는 null/unavailable이다.

Production adapter는 pinned binary/version/schema/config, 빈 tool inventory, 빈 instruction
source, read-only sandbox를 admission에서 검증한다. 각 action은 durable `request_sent` 뒤
`spawn|followup`하며, 첫 dispatch 뒤 fallback과 replacement spawn을 금지한다. 병렬 sibling은
실패 시에도 drain하고 active turn interrupt 및 role delete를 시도한다. 시작된 workflow lease는
admission TTL을 넘어 wait/resume/interrupt/cleanup할 수 있지만 종료 뒤 새 dispatch는
금지된다. agent tool·sandbox network 차단은 provider model transport 차단을 뜻하지 않는다.

```bash
install -d -m 700 /absolute/dedicated/studio-state /absolute/dedicated/studio-runtime
node plugins/studio/scripts/persistent_brainstorm_controller.mjs \
  --request-file /absolute/path/to/persistent-request.json \
  --state-root /absolute/dedicated/studio-state \
  --runtime-root /absolute/dedicated/studio-runtime \
  --cwd /absolute/path/to/read-only-project
```

성공은 `ok:true`, root/envelope `status:"completed"`,
`execution_path:"persistent-native-app-server"`, `fallback_allowed:false`, exact Production
workflow receipt가 모두 일치할 때뿐이다. pre-dispatch admission이 명시적으로
`status:"fallback_required"`, `fallback_allowed:true`,
`execution_path:"isolated-runner"`를 모두 반환한 경우만 아래 isolated Runner를 사용한다.
`aborted|failed|error|recovery_required`와 불완전 출력은 STOP한다. 민감한
ContextPack·credential·사용자 데이터는 context-only brainstorm request에서 제외한다.
회의 workflow가 배정된 작업 단위라면 그 완료조건과 outstanding interaction이 모두
해소된 뒤에만 role thread와 rollout을 delete한다. 회의·round·turn·run의 종료 자체는
종료 사유가 아니며 작업 단위 사이의 기억은 보존하지 않는다.

### Native crew instance lifecycle

Studio의 모든 native crew는 **역할 기반으로 인스턴스를 배정하고, 인스턴스 수명은
동적으로 정한 작업 단위 기준으로 관리**한다. 인스턴스 하나는 명확한 단일 역할을 맡는다.
같은 역할이라도 독립 작업 단위가 여러 개면 별도 인스턴스를 둘 수 있지만, 역할명·인원수·
A/B 같은 예시 이름을 topology로 고정하지 않는다.

- 최초 배정에서만 spawn한다. 같은 작업 단위의 후속 의견교류, peer/QA/review 대기,
  feedback 대응, 재작업, 재검증은 original physical handle에 follow-up한다.
- `waiting-for-peer`와 `rework`는 active 상태다. 담당 완료조건 충족과 outstanding
  peer/review interaction 0이 함께 확인될 때만 terminal로 전이하고 cleanup한다.
- 독립 판단이 필요한 reviewer는 별도 역할·작업 단위·인스턴스로 배정한다. reviewer도
  자기 review 단위가 끝날 때까지 유지한다.
- 예를 들어 서로 다른 작업 단위를 맡은 같은 developer 역할 인스턴스가 둘일 수 있다.
  한 단위의 review finding은 그 단위의 original developer에게 follow-up하고 같은 review
  흐름으로 재확인한다. review 대기 중 developer도 active다.

Producer는 owner intent·범위·완료조건을 정본으로 유지하는 Studio control plane이다.
role↔instance↔work-unit mapping과 상태를 관리하고 dependency·질문·산출물·review
feedback을 original instance 사이에 왜곡 없이 relay한다. 전체 상태와 gate는 owner와
대화하되 crew 산출물을 직접 만들거나 crew 판단을 대신 합성하지 않으며, 내부 workflow가
owner 요구를 재정의하거나 범위를 확대하지 못하게 한다.

이 계약은 brainstorm, development/pairing, QA, review, critic 등 모든 native crew에
공통이다. 기존 Workflow/Runner, task-worker, task-github, worktree,
execution-control을 그대로 사용하며, 외부 executor나 continuation handle을 제공하지 않는
호환 경로에는 persistence를 주장하지 않는다.

```bash
node plugins/studio/scripts/codex_workflow_runner.mjs \
  --broker brainstorm \
  --args-file /absolute/path/to/sealed-args.json \
  --timeout-ms 120000
```

- CLI 해석: absolute `STUDIO_CODEX_CLI` override → `PATH`의 `codex` → macOS bundled CLI.
- 실행: `shell:false`, prompt stdin, `--ephemeral`, `approval_policy="never"`,
  `--output-schema`, `--output-last-message`; bypass·`--add-dir`는 사용하지 않는다.
- schema: optional property는 required nullable로 정규화한다. `oneOf`는 root type이
  배타적일 때만 `anyOf`로 낮추고, overlap/판정 불가는 dispatch 전에
  `schema_unsupported`로 거부한다.
- 경계: schema/output은 1 MiB 제한과 임시 디렉터리 cleanup을 적용한다. brainstorm은
  전부 read-only다. fallback pairing은 검증된 secondary worktree의 dev만
  workspace-write이며 target과 Runner cwd의 git common-dir가 같아야 한다.
  qa/critic은 read-only다.
- 종료: timeout은 process group에 TERM 후 KILL을 적용하고 recursion을 거부한다.
  dispatch 뒤 generic subagent로 자동 fallback하지 않는다.
- 출력: 성공은
  `{schema:"studio-codex-workflow-runner/v1",dispatch_allowed:true,broker,phases,logs,output}`,
  실패는 같은 schema에 `dispatch_allowed:false,error,message,details`와 nonzero exit다.
  broker 자체가 `error`를 반환해도 `dispatch_allowed:false`다.

Runner는 canonical `studio-runtime-capability/v1`의 exact shape와 digest를 검증하고,
광고된 model/effort가 있으면 각 agent의 resolved 값을 spawn 전에 대조한다. capability가
unknown/unavailable이면 dispatch하지 않는다. CLI output에는 신뢰할 수 있는 token usage가
없으므로 broker receipt는 `tokens:null`, `token_coverage:"unavailable"`을 유지한다.
UI card-title projection과 token telemetry 구현은 이 Runner의 범위가 아니다. 따라서
Runner는 persistent crew 또는 UI title 지원을 주장하지 않는다.

## casting helper

Producer는 `cast suggest`로 기본 crew 조합을 기계적으로 조회한다. 이 helper는 판단을
대체하지 않고, `rules/casting.md`의 기본값을 JSON으로 돌려준다.

```bash
python3 plugins/studio/scripts/studio.py cast list
python3 plugins/studio/scripts/studio.py cast suggest idea
python3 plugins/studio/scripts/studio.py cast suggest implementation
python3 plugins/studio/scripts/studio.py cast suggest implementation --item-scale solo \
  --criterion-source-ref AC-1 --mechanical-measure "pytest tests/test_one.py"
```

기본 `standard`는 최소 cast와 brainstorm 2 rounds/dryStop 1을 사용한다. `major`는 기존
full ritual(4/2)을 보존한다. `solo`는 upstream criterion source와 mechanical measure가
모두 있을 때 crew 1명·1회만 호출하며 interaction theatre 집계에서 제외한다.
production scale과 independent review edge는 별도 축이다.

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
7. verification·criterion evidence·quality floor·gate가 모두 완결돼
   `readyForIntegration:true`일 때만 owner에게 반영 게이트를 묻는다. telemetry 누락은
   효율 주장만 unavailable로 만들며 통합 readiness를 막지 않는다.
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

v0.11.0 — 효율을 token 최소화가 아니라 **고정된 품질·거버넌스 하에서 불필요한 작업을
구조적으로 만들지 않고 terminal outcome에 착지하는 것**으로 정의한다. 새 WorkPacket v2는
`retrieval | judgment | construction | verifier-hardening | integration`을 기존 production
scale·QA mode와 결합하며 mixed/unknown은 standard judgment로 fail-closed한다.
`quality_complete`는 delivery, `telemetry_complete`는 효율 주장에만 사용한다. review cycle은
materiality·content/surface digest·attempt 상한이 결합된 최신 1회용 continuation decision과
delivered/decision/blocker-resolution/quality-defense outcome 및 reopen 상계를 기록한다.
실제 repro·bounded verifier hardening, strict critic, judgment 다인 검토, 통합 HEAD gate는
완화하지 않는다. WorkPacket v1과 기존 review ledger/resume은 읽기 호환을 유지한다.
실행 telemetry가 없는 구조 검증으로 token 절감률을 주장하지 않으며, 사용량 수치는 후속
운영 피드백의 관찰값이다.

v0.10.0 — pinned bundled Codex app-server의 read-only persistent brainstorm를 Production
route로 활성화하고, 모든 native crew에 역할 기반 배정·작업 단위 기준 instance lifecycle·
original-handle rework continuation 계약을 명시했다. 새 write runtime 없이 기존
Workflow/Runner와 task-worker/task-github/worktree/execution-control 경계를 유지한다.
Brainstorm sealed replay는 full 21 calls 대비 standard 13 calls(38.10%), criterion floor
100점, quality degradation 0%를 유지한다. 작업 단위 완료와 outstanding interaction 0이
확인된 뒤 cleanup하며 cross-work-unit 기억은 제공하지 않는다.

v0.9.0 — workflow-scoped persistent crew의 read-only brainstorm canary와 item별
`solo|standard|major` 정적 production scale, 1-call solo, outcome-linked brainstorm
수렴, exact model-call 계측을 추가했다. Standard 기술 설계는 QA를 보존하고 summarizer가
고정 agenda 요구사항을 누락하지 않도록 한다.

v0.8.1 — 설치 artifact 내부 canonical execution contract를 기본으로 사용하고,
직렬화 경계의 physical claim 상태와 timezone-aware timestamp 검증을 정합화했다.

v0.8.0 — callable Workflow가 없는 Codex에서도 verified runtime capability와 fail-closed
경계를 유지하며 기존 brainstorm/pairing broker를 실행하는 production Runner를 추가했다.

v0.7.1 — native track은 integrator가 merged-clean worktree/local branch를 정리하고,
외부 worker track은 provider cleanup receipt를 재사용해 중복 cleanup을 막는다.

v0.7.0 — workspace와 config를 합친 idempotent `studio:init`, explicit worker/reviewer 설정,
dry-run/force/validation JSON 계약과 native-first read-only `studio:doctor`를 추가했다. init은
미설정 외부 plugin을 탐색하지 않으며 기존 `config scaffold`는 호환 표면으로 유지한다.

v0.6.0 — canonical command profile·impact permit, atomic physical execution claim, immutable receipt/evidence, run cap·telemetry·external spend gate를 추가했다. 분해·ready-set 병렬성·독립 검증·통합 HEAD full gate는 유지하고 동일 물리 실행과 stale context 재수집만 차단한다.

v0.5.0 — native 기본·명시적 외부 도구 라우팅, Claude/Codex agent profile, 단일 review lease owner, capability/evidence 재사용과 development→integration full→finding delta QA 계약.

v0.4.0 — stable review cycle·delta/full QA gate·evidence reuse·compact handoff·Issue event projection.
기존 schema-v1 workflow receipt·QualityPlan·Context Kernel·optional external executor도 유지한다. 설계 정본은 이 repo
위키(INT/DEC studio) + `drafts/agent-team-concept.md`.
검증 테스트: `python3 plugins/studio/tests/test_studio.py`,
`python3 plugins/studio/tests/test_execution_control.py`,
`python3 plugins/studio/tests/test_routing_contracts.py`,
`node --test plugins/studio/tests/test_broker_semantics.js`,
`node --test plugins/studio/tests/test_codex_runner.js`,
`node --test plugins/studio/tests/test_persistent_brainstorm_broker.js`,
`node --test plugins/studio/tests/test_persistent_brainstorm_controller.js`,
`node --test plugins/studio/tests/test_persistent_native_app_server.js`,
`node --test plugins/studio/tests/test_persistent_native_live_canary.js`,
`node --test plugins/studio/tests/test_production_profiles_benchmark.js`.

후순위(정의만, MVP 비활성): 마케팅/판매 운영 역할, 동적 채용(casting), standup/retro/demo
리추얼과 추가 external workflow adapter.
