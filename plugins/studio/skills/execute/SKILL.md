---
name: execute
description: Studio 미션의 작업·리뷰·GitHub delivery command를 `.studio.yml`과 실행 override에서 해석하고, 메인 Producer 세션이 native 또는 외부 command를 선택해 끝까지 오케스트레이션한다. "Studio로 실행", "Studio로 구현", "복잡한 개발을 크루로 수행", "execute", "설정된 task-worker/session-review/task-github를 사용" 요청에 사용한다.
---

# Execute

현재 대화의 root Producer 세션에서만 실행한다. leaf crew로 호출되면 작업을 재분해하거나
subagent를 만들지 말고 원래 Producer에게 반환한다.

Studio는 command runtime이나 상태 저장소를 만들지 않는다. 설정된 command의 own contract와
host native subagent 기능을 직접 사용한다.

## 1. 실행 정책 해석

consumer workspace 루트에서 세 route를 해석한다.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" route \
  --path .studio.yml --kind work
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" route \
  --path .studio.yml --kind review
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" route \
  --path .studio.yml --kind delivery
```

command는 skill/plugin identifier다. shell 문자열로 실행하지 않는다.

- `decision:native|skip`: command를 discovery/probe하지 않는다.
- `decision:invoke-command`: command를 반드시 사용한다.
- `decision:producer-decision`: Producer가 아래 기준으로 선택한 뒤에만 command 가용성을
  확인한다.
- 선택한 command가 없거나 실패하면 `fallback:native|skip`은 해당 native 경로로 계속하고,
  `fallback:stop`은 실제 오류를 보고하고 중단한다.
- 실행 override는 config보다 우선한다. 명시적 command override는 기본적으로
  `activation:always`, `fallback:stop`이다.
- delivery는 Producer가 자동 활성화하지 않는다. operator가 config 또는 실행 override에서
  `enabled:true`로 켠 경우에만 사용한다.

## 2. work 경로 선택

production-public claim, major 변경, acceptance-registry 작업은 route 선택과 decomposition 전에
완료 조건을 executable selector로 audit한다. shipped CLI, skill, adapter 또는 artifact layout을
실제 호출한 probe가 없거나 unavailable이면 `unknown`으로 중단한다. 작은 internal 변경은 동일
criteria digest에 pin된 기존 registry mapping을 재사용한다.

`activation:auto`에서는 실제 work graph 또는 durable execution lifecycle이 필요할 때만
configured work command를 선택한다.

- 둘 이상의 work unit 사이에 dependency graph 또는 유의미한 ready-set 병렬성이 있다.
- leaf 결과가 새 통합 상태를 만들고 별도 integration gate가 필요하다.
- 세션을 넘어 재개할 canonical work state나 외부 실행 handoff가 명시적으로 필요하다.

단일 bounded 작업과 dependency 없는 단순한 역할 분담은 native를 선택한다. 위험도,
독립 review, 선호 worktree, 일반적인 evidence pin이나 중복 실행 방지만으로 work command를
선택하지 않는다. 이들은 각각 review·QA 정책에서 독립 판정한다.

`auto` 선택은 아래 결정적 projection으로 확인한다. 명시적 `activation:always`는 operator
override이므로 work shape와 무관하게 configured command를 유지한다.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" select-work \
  --path .studio.yml --work-units <N> \
  [--dependency-graph] [--parallel-graph] [--integration-gate] \
  [--cross-session-resume] [--external-handoff]
```

### Native

Producer가 미션을 독립 작업으로 나누고 필요한 최소 crew를 직접 소집한다. 각 새 agent는
Producer의 model/effort resolver 결과로 생성한다.

### Configured command

메인 Producer가 configured command의 skill을 직접 사용한다. orchestration을 맡길 별도 crew를
만들지 않는다.

표준 `task-worker` command에서는:

1. Producer가 objective, scope, 완료 조건과 owner gate를 고정한다.
2. 메인 세션에서 `task-worker:define`으로 DefinitionArtifact를 만든다. 작업 분해·dependency
   및 ready planning은 task-worker가 소유하고 Producer는 미션 경계와 완료 조건을 보존한다.
3. 메인 세션에서 `task-worker:orchestrate`를 수행해 ready set 전체를 bounded parallel로
   dispatch한다.
4. Producer가 각 ready action에 맞는 crew role을 선택하고 해당 role의 model/effort로 native
   subagent를 생성한다.
5. 각 leaf prompt에 하나의 ready action, worktree, 완료 조건, 검증 방법과 다음 금지를 함께
   전달한다.
   - `studio:execute`, `task-worker:define`, `task-worker:orchestrate` 호출 금지
   - nested subagent 생성과 sibling 작업 점유 금지
6. leaf는 자기 lane의 `start → run → verify → done`만 수행하고 receipt를 Producer에게
   반환한다.
7. Producer가 receipt를 반영해 다음 ready set을 계산하고, 마지막
   `integration_candidates[]` gate까지 완료한다.

task-worker의 artifact, run state, evidence나 receipt를 Studio 상태로 복제하지 않는다.
leaf 개발 QA는 targeted/delta를 기본으로 한다. dependency/shared contract, 영향 범위
불확실성 또는 독립 검증 reason이 있을 때만 full QA를 선택한다. 같은 HEAD의 related profiles 검증은
공통 source/criteria/environment/target과 expected selector set을 pin하고 각 profile fingerprint 및
child refs/result/output digest/selector coverage를 보존한 task-worker batch digest로 전달하고,
integration evidence에는 그 digest 하나만 연결한다.

## 3. review 경로

review가 필요하지 않으면 review command를 사용하지 않는다. `activation:auto`에서는 독립성
요구, major blast radius, 보안·데이터·배포 gate 또는 구현자 자기검증만으로 판정하기 어려운
경우 configured review command를 선택한다.

work command가 reviewer ownership permit을 제공하면 review 직전에 소비한다. 외부 review가
선택된 task-worker 경로에서는 task-worker의 `review-lease` command로 `owner:external`과
resolved review command를 기록하고 binding에 전달한다. Studio가 lease schema나 digest를
직접 만들지 않는다.

- external handoff는 review 완료가 아니다.
- Producer가 native reviewer 또는 configured review command를 소집한다.
- blocking finding은 원래 leaf agent handle로 돌려보낸다.
- approved verdict와 요구 evidence가 확인되기 전에는 integration/delivery closeout을
  진행하지 않는다.
- hard review finding 수정 후에는 최초 hard reviewer의 같은 addressable handle이 final
  candidate commit을 확인한다. 그 뒤 frozen candidate에서 fresh final-grade root QA를 한 번
  실행한다. final QA 실패 뒤 source/test/config를 바꾸면 reviewer 확인과 final QA를 다시
  수행한다.
- Studio는 canonical session-review status와 task-worker final-QA projection만 stateless하게
  합성한다. review/evidence body를 mission receipt에 복사하거나 별도 ledger를 만들지 않는다.

## 4. delivery 경로

delivery는 `enabled:true`일 때만 configured command를 사용한다. work orchestration을
대체하지 않으며, work command가 만든 artifact와 receipt를 projection/delivery 입력으로만
전달한다.

표준 `task-github` command는 task-worker DefinitionArtifact/receipt를 GitHub Issue Tree와
PR에 투영하고 GitHub transport·merge·closeout만 소유한다. Producer는 task-github에 별도
worker orchestration을 만들게 하지 않는다.

delivery가 꺼져 있으면 command를 조회하지 않고 local 결과로 끝낸다.

## 5. 완료

다음을 모두 확인하고 보고한다.

- 선택한 work/review/delivery route와 선택 이유
- 역할별 agent handle과 적용된 model/effort
- work receipt, review verdict, integration gate
- token/model-call/mission wall-clock/owner-intervention telemetry와 coverage. 미측정값은
  `null`, 불완전 token 합은 `measured_tokens_subtotal`이며 0이나 mission total로 바꾸지 않는다.
- delivery가 켜졌다면 provider receipt와 closeout 상태
- 남은 owner gate와 위험
