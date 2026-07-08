# 살아있는 에이전트 팀 (가칭 studio) — 구체화 r2

> 상태: session-review co-design — r1(explore)·r2(converge) approved.
> 이 판은 r2 피드백의 [should-reflect] 3건(스코어러 검증-전용 계약, 합성 스텝
> 소유자, tools 명명)을 반영한 confirm 라운드 대상이다.
> 스키마는 계약(필드·의미)까지만, 구현 코드는 다루지 않는다.

## 1. 취지

큰 틀의 미션을 주면, 메인스레드 + 서브에이전트 시스템이 **하나의 스타트업 팀처럼**
그 미션에 관련된 모든 영역을 스스로 수행한다 — 기획, 리서치, 디자인, 개발,
테스트, QA, 마케팅.

### 살아있음의 최소 조건 (r1 피드백 반영 — 정의)

아래 5개를 모두 만족할 때 "살아있는 팀"이라 부른다. 이벤트 드리븐 실행만으로는
부족하다:

1. **자발 제안권** — 역할이 시키지 않은 일을 백로그에 제안할 수 있다.
2. **타 역할 산출물에 대한 반응** — 다른 역할의 산출물을 읽고 반박·수정·확장한다.
3. **증거 기반 delta** — 상호작용이 만든 변화가 기록으로 남는다 (§3.4).
4. **디스크에 남는 팀 기억** — 세션이 죽어도 팀의 상태·인격이 연속된다.
5. **사용자 게이트** — 결정·비가역·외부공개는 사람이 통제한다.

감정 상태·직급·근태 같은 사람 흉내는 명시적으로 배제한다. 살아있음은 목적이
아니라 품질 수단이다.

### 반(反)목표

- 이슈트리 순차 처리기의 확장이 아니다. task-github orchestrate는 패턴 원형일 뿐,
  이슈트리는 선택적 실행 백엔드다 (§9).
- 조직도 시뮬레이터가 아니다.

## 2. 기존 자산과의 관계

| 자산 | 역할 | 의존 |
|---|---|---|
| task-github orchestrate | 루프+서브에이전트 패턴 원형 | 비의존 |
| wiki-markdown | 장기 기억 (결정·기각·관찰 승격처) | 있으면 활용, 없으면 team/ 폴백 |
| session-review | worker↔reviewer 루프 원형 | 패턴 참조 (§10-3) |
| deep-research | 리서치 역할의 도구 | 도구 호출 |
| Workflow(하니스) | 미팅 브로커의 실행체 (백그라운드) | 구현 기반 |

## 3. 개념 모델 — 원시개념 5 + CEO

r1의 3+1에서 **미션 계약**과 **증거**를 승격 (r1 피드백 반영).

### 3.1 미션 계약 (Mission Contract) — 자율성의 정본

`team/mission.md`. 팀이 무엇을 어디까지 스스로 할 수 있는지의 단일 정본.

```yaml
mission: <한 문단>
kpi: [<측정 가능한 목표>...]
done_when: <완료 기준>
budget: {total_tokens: N, per_meeting_default: M}
gates: [new-epic, decision-promotion, external-publish, budget-raise]  # 사용자 게이트
autonomy: <팀이 묻지 않고 해도 되는 것의 서술>
```

- 모든 백로그 항목은 KPI 중 하나에 연결돼야 한다 (백로그 폭주 방지).
- CEO 포함 누구도 이 계약 밖의 자율을 행사할 수 없다. 계약 변경 = 사용자 게이트.

### 3.2 페르소나 (Persona)

역할 프롬프트가 아니라 인격. **페르소나는 데이터, 실행은 generic 서브에이전트 +
페르소나 주입** — 역할마다 에이전트 타입을 만들지 않는다.

`team/roles/<name>.md`:

```yaml
---
name: planner-a            # 소집 식별자
role: 기획                  # 직능
prior: 성장 우선            # 판단 성향 한 줄 — 논쟁의 원료
requested_tools: [WebSearch, Read]  # 요청 도구 (advisory — 프롬프트 규범.
                            # 하니스가 실제 차단하는 범위만 allowed_tools로 부른다)
activation: always          # always | gated  (게이트 조건식 DSL은 셋째 역할 때)
---
(자유 서술: 판단 규범, 반박 의무, 금지 사항, 발언 예시)
```

- 같은 직능에 상이한 prior 복수 배치 (기획A=성장, 기획B=리스크) — 동일 프롬프트
  둘은 서로 동의만 한다.
- 개인 기억: `team/roles/<name>.notes.md` — 미팅 후 브로커가 각자의 배운 것을
  append. fresh 소집 시 자기 노트 + 작업장을 읽고 온보딩.

### 3.3 미팅 (Meeting) — 공통 I/O 계약

서브에이전트끼리 직접 대화 불가(하니스 제약) → 브로커가 턴테이킹. 브로커는
리추얼별 워크플로 스크립트로 시작하되(§6), **I/O 계약은 지금 통일한다**
(r1 directional 반영):

```yaml
meeting_input:
  ritual: brainstorm | pairing | standup | retro
  agenda: <안건>
  participants: [<persona name>...]
  judge: delta-scorer            # 독립 판정자 — 참석자와 분리 (§3.4)
  budget: {tokens: N, max_rounds: M}
  stop: {dry_rounds: 2}
meeting_output:
  synthesis: <합의안>            # 브로커 합성 스텝 산출 (§6.1 — 페르소나·CEO 아님)
  minority: <소수의견 — 없으면 명시적 none>
  delta_log: [{round, changed_what, anchor, evidence, rejected_alternative}]
  verdict: {alive: bool, reason: <판정자 소견>}
  cost: {tokens, rounds}
  proposals: [<백로그 제안>...]   # 자발 제안권의 출구
```

- `anchor`: `changed_what`이 실제로 가리키는 대상 — `artifact | acceptance-criteria |
  risk | rejected-alternative | repro-test` 중 하나의 참조. anchor 없는 delta는
  delta가 아니다 (§3.4).

- 미팅은 백그라운드 실행. CEO는 회의 도중에도 사용자와 대화한다.
- 산출물 없는 라운드 = dry. dry 2회 폐회. 동의 요약은 산출물이 아니다.

### 3.4 증거 (Evidence) — 연극 판정의 근거

r1 피드백의 핵심 반영. 판정 기준은 말투가 아니라 **delta**다.

- **delta 레코드**: 라운드 n의 합의 상태가 n-1 대비 무엇을 바꿨는가 —
  acceptance criteria / 백로그 / 리스크 / 기각 대안 중 하나 이상. 없으면 dry.
- **독립 판정자 (delta-scorer)**: 참석자가 아닌 별도 에이전트. 임무는 채점뿐.
  참석자 하니스의 자기 판정을 신뢰하지 않는다. 계약은 **검증 전용**:
  - scorer는 delta 레코드를 **생성하거나 보강하지 않는다** — 참가자·합성 스텝이
    제출한 레코드를 검증만 한다 (관대한 재해석으로 연극을 통과시키는 것 방지).
  - 판정 규칙: `changed_what`이 durable artifact / acceptance criteria / risk /
    rejected alternative / repro·test 중 하나에 **실제 anchor를 갖지 못하면
    dry=true**.
- 페어링의 증거는 반박 횟수가 아니라 **재현 가능한 실패 리포트**와
  **방어된 테스트**의 개수다.
- delta 레코드는 미팅 출력에 포함되고, 합성본과 함께 `discussions/`에 남는다.

### 3.5 작업장 (Workspace)

```
team/
  mission.md          # §3.1 미션 계약 (정본)
  backlog.md          # 마크다운 백로그 — 항목마다 kpi 링크 필수
  discussions/        # 합성본 + delta 레코드만. raw transcript는 TTL(기본 7일) 후 삭제
  roles/              # 페르소나 + 개인 노트
```

- 굳은 지식만 wiki 승격 (결정·기각·관찰 — 기존 capture 정책, 사용자 게이트).
- CEO는 raw transcript를 정독하지 않는다 — 합성본과 delta만 소비.

### 3.6 CEO (메인스레드)

- 역할: 사용자 인터페이스 / 소집자 / 중계자 / 게이트키퍼.
- 금지 2건:
  1. **직접 산출물 제작 금지** — 팀 우회 금지.
  2. **판단 대리 합성 금지** (r1 피드백 반영) — 특정 역할의 판단을 CEO가 미리
     합성해 결론을 정하지 않는다. 품질의 주체는 리추얼 산출물이다.

## 4. 롤 구성 (MVP 로스터)

| 이름 | 직능 | prior | 비고 |
|---|---|---|---|
| planner-a | 기획 | 성장 우선 | |
| planner-b | 기획 | 리스크 우선 | |
| dev | 개발 | 동작하는 최소 | |
| qa | 검증 | adversarial — 깨는 게 임무 | acceptance criteria는 만들기 전 고정 |

- **delta-scorer는 로스터 밖이다.** 페르소나가 아니라 미팅 파라미터(`judge:`)로
  주입되는 기능 에이전트. 페르소나로 승격하면 팀 정치의 일원이 되어 독립
  판정자 성격을 잃는다.
- CEO는 로스터가 아니다 (메인스레드 자체).
- 후순위 역할(리서치·디자인·마케팅)은 `activation: gated`로 정의만 두고
  MVP에서 비활성. 마케팅의 외부 발행은 활성화돼도 상시 사용자 게이트.
- **동적 채용** (MVP 이후): planner가 필요 역할 제안 → 사용자 승인 → 페르소나
  파일 생성. 채용도 백로그 제안의 한 형태로 취급.

## 5. 제어 모델

### 5.1 게이트 (자율 vs 사용자)

| 팀 자율 | 사용자 게이트 |
|---|---|
| 미팅 소집·진행·폐회 | 신규 에픽 / 방향 전환 |
| 초안·리서치·구현+검증 | 결정·기각의 wiki 승격 |
| 백로그 제안, 역할 노트 | 외부 공개 (발행·배포·계정 행위) |
| 미팅별 예산 배분 (계약 한도 내) | 총예산 상향, 미션 계약 변경 |

### 5.2 개입 수단 (사용자 → 팀)

1. **상시 인터럽트**: 미팅이 백그라운드라 CEO는 항상 응답 가능. 지시는 다음
   소집에 반영되거나, 필요시 진행 중 미팅 kill.
2. **미팅 kill**: 백그라운드 태스크 중단. 미완료 출력은 폐기하되 delta 레코드는
   회수한다. 회수된 delta는 **aborted evidence**로 표시 — accepted evidence와
   구분해 이후 합성 오염을 막는다.
3. **자동 폐회**: 예산 소진 or dry 2회 — 브로커가 강제. 초과 진행 불가.
4. **질문 큐**: 게이트 대기로 한 레인이 막혀도 나머지 레인 계속. CEO가 질문을
   모아 배치로 사용자에 제시.

### 5.3 예산 체계

- `mission.md`의 `budget.total_tokens`가 상한. CEO가 미팅별로 배분,
  브로커가 미팅 예산을 강제. 소진 시 미션은 `paused` — 사용자 게이트로만 재개.

## 6. 리추얼 사양 v0

공통: 입력/출력은 §3.3 계약. 브로커 = 리추얼별 워크플로 스크립트 2개로 시작,
셋째 리추얼에서 공통화 판단.

### 6.1 brainstorm

```
diverge : 참석자 전원 병렬 — 안건에 독립 제안 (서로 안 보임)
debate  : 라운드마다 순차 발언 — 직전 transcript에 반박/수정/신규만 허용
judge   : 매 라운드 delta-scorer가 delta 레코드 검증, dry 판정
converge: 브로커의 합성 스텝(generic summarizer — 페르소나도 CEO도 아님)이
          synthesis + minority + delta_log 생성. 출력은 delta-scorer가 검증
          (CEO의 판단 대리 합성 금지·scorer의 검증 전용 계약과 충돌 없음)
```

### 6.2 pairing (dev↔QA)

```
setup : acceptance criteria 고정 (변경은 재소집 사유)
loop  : dev 구현 → qa 공격(재현 가능한 실패 생산 시도) → dev 방어
exit  : qa가 예산 내 못 깸 (증거: 실패 리포트 각각에 방어 테스트 대응)
judge : delta-scorer가 "방어된 테스트 수 / 재현 실패 수" 채점
```

standup / retro / demo는 r1 정의 유지 (1라운드 고정, 각각 상태요약 / wiki 후보 /
사용자 미리보기).

## 7. 운영 루프

- **소집형 확정** (r1 directional): 팀원은 회의 때만 fresh 소집, 상태는 전부
  디스크. 세션은 캐시일 뿐 상태가 아니다. SendMessage 상주는 CEO 루프 등
  제한적 최적화로만 남긴다.
- 이벤트 드리븐: 회의 종료 알림 / 사용자 응답 / 타이머 폴백 → CEO가 다음 소집 판단.
- 미션 라이프사이클: `draft → active → (pivot | paused) → done`. pivot은 결정 기록.

## 8. 실패모드와 대응 (r2 갱신)

1. **비싼 연극** → 상이한 prior + 독립 판정자 + delta 기반 dry 판정 (§3.4).
   자기 판정 불신이 원칙.
2. **백로그 폭주** → KPI 연결 강제 + 에픽 게이트.
3. **토큰 화재** → 미션 총예산 → 미팅 예산 → 브로커 강제 (§5.3).
4. **에코챔버 품질** → adversarial QA + 사전 고정 acceptance criteria + 방어된
   테스트만 증거로 인정.
5. **CEO 컨텍스트 고갈** → 회의 백그라운드, 합성본+delta만 소비, 상태는 디스크.

## 9. MVP 슬라이스와 검증 프로토콜

재료 (플러그인화 전, 이 repo에서):

1. 페르소나 5 파일 (§4 로스터)
2. 브로커 워크플로 2 (`brainstorm`, `pairing`) — §3.3 계약 준수
3. `team/` 스캐폴드 + `mission.md` 계약
4. CEO 행동규약 스킬 1 (소집·중계·게이트·금지 2건)

### 검증 프로토콜 — baseline 비교 (r1 피드백 반영)

같은 장난감 미션을 두 번 수행한다:

- **A (baseline)**: 솔로 에이전트 1회.
- **B (팀)**: 브레인스토밍 → 합의안 → dev↔QA 페어링 → 데모 풀사이클.

판정: B가 A 대비 추가로 만든 것 — 수용된 반박, 발견·재현된 실패, 기각 대안
기록, acceptance criteria 변화 — 를 센다. **delta가 0이면 연극 판정**: 컨셉
기각 또는 리추얼 재설계. 미션은 산출물·검증이 단순한 것(문서 or 소형 CLI)으로
선정한다 — task-github이 섞이면 컨셉 검증이 실행 백엔드 검증으로 흐른다.

## 10. 결정된 것 / 남은 논점

### 결정된 것 (r1·r2 피드백 수용 누적)

- 소집형 (상주는 제한적 최적화)
- 브로커: 리추얼별 스크립트 2개 + 공통 I/O 계약 선통일
- 독립 판정자(delta-scorer) + delta 기반 연극 판정 — scorer는 **검증 전용**
  (생성·보강 금지), anchor 없는 delta는 dry
- 합성 소유자: 브로커의 generic summarizer 스텝 (페르소나·CEO 아님, scorer 검증)
- delta-scorer는 로스터 밖 미팅 파라미터 — 동일 모델 티어로 시작, rubric이
  먼저. false positive가 MVP 로그에서 반복될 때만 상위 모델/2차 scorer 검토
- pairing은 신규 경량 브로커 — session-review는 사람 게이트·audit trail이
  필요한 외부 리뷰 전용 (같은 엔진으로 묶으면 세레머니 과잉)
- team/은 consumer repo 안 — 멀티 repo 미션은 MVP 밖
- MVP 실험 미션은 **소형 CLI** (실패 재현·방어 테스트가 남아 pairing delta
  검증이 쌈), task-github는 붙이지 않음
- 페르소나 도구 선언은 `requested_tools`(advisory) — `allowed_tools`는 하니스가
  실제 차단 가능한 범위에만 (플러그인화 때)
- discussions/는 합성본+delta만, raw는 TTL. kill된 미팅 delta는 aborted evidence
- MVP 검증에 baseline 비교. CEO 금지 2건 (직접 제작, 판단 대리 합성)

### 남은 논점

1. **네이밍 확정**: `studio` 우선 후보 (r1 reviewer 추천). 사용자 게이트 사안 —
   구현 착수 전 확정 필요 (디렉토리·스킬 이름에 영향).
