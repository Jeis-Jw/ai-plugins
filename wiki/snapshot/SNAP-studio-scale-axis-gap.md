---
title: studio 규모 축 부재 — 소형 작업 낭비와 solo 리추얼 필요성
created_at: 2026-07-25
summary: studio는 kind(속성) 축만 구현돼 있고 scale(규모) 축이 없어 오타 수정도 dev+qa 적대 루프를 돈다. 취지(미션 안에서 자율적 역할배분)를 충족하려면 native solo 리추얼 + casting scale 축이 필요. task-*는 도구이므로 규모 축은 native에 있어야 한다.
tags: [studio, casting, scale, waste, plugin-design]
type: snapshot
---
## 현재 논의

studio가 "작업의 규모/속성에 따라 적절한 절차를 오케스트레이션한다"는 취지를 실제로는 충족하지 못한다는 것을 확인한 논의.

## 확인한 현재 동작

**속성(kind) 축은 구현됨.** `rules/casting.md`가 7개 kind(`idea`/`product-direction`/`technical-design`/`ui-build`/`content`/`implementation`/`launch`)를 default cast에 매핑하고 `studio.py cast suggest <kind>`가 helper로 제공한다. producer는 최소 조합만 소집하고 전체 roster 호출은 금지.

**규모(scale) 축은 없음.** 7개 kind 전부 `brainstorm|pairing` 2개 리추얼로만 떨어진다. broker 디렉터리에도 `brainstorm.workflow.js`, `pairing.workflow.js` 둘뿐. `gear|규모|scale|micro|trivial` 토큰이 crew 페르소나 12개·`critic/rubric.md`·브로커 프롬프트 어디에도 없다.

결과: 아무리 작은 구현도 `implementation` → `pairing` → dev+qa 적대 루프를 돈다. `pairing.workflow.js:39`가 qa 페르소나 미지정 시 기본값을 주입하므로 **최소 크루 2명, qa 스킵 경로 없음**. 실제 조직에서 가장 흔한 "담당자 1명이 처리하고 보고" 모드가 studio에 존재하지 않는다.

## 프롬프트 층도 규모 무감 (역할별로 방향이 갈림)

| 층 | 규모 감응 | 방향 |
|---|---|---|
| 리추얼 선택 | 없음 | — |
| dev 프롬프트 | 없음 | 최소화 편향 (문제 없음) |
| qa 프롬프트 | 없음 | 전면 스윕 편향 (부풀림) |
| 테스트 의무 | 없음 | 무조건 |
| critic rubric | 없음 | pairing에서 편법 완화 |
| effort override | 있음 | 트리거가 예산 잔액, 작업 크기 아님 |

- `crew/dev.md`: `prior: 동작하는 최소`, "가장 작은 diff", "투기적 추상 금지". 브로커 round-1도 `'Implement the smallest thing that satisfies every acceptance criterion.'` 하드코딩 → dev가 부풀릴 유인은 이미 막혀 있다.
- `crew/qa.md`: "경계·빈 입력·중첩·유니코드·큰 입력·동시성 등 criteria가 말 안 한 틈을 노린다" = **고정 공격면 리스트, 규모 조건절 없음**. 오타 한 줄 수정에도 전 공격면 스윕이 지시된다. 가짜 결함 제조는 가드("재현 없는 추측성 결함 금지", "못 깼으면 defended 인정")가 막지만 **탐색 토큰은 안 막힌다**.
- 테스트 의무 무조건: dev.md "모든 criteria마다 테스트를 남긴다" + 브로커 `'Add tests for the criteria.'` + rubric의 `repro-test` anchor 강제.
- `pairing.workflow.js:226` 주석 그대로 — `// a clean build qa can't break would leave delta_log empty and read as theatre.` 그래서 dev round-1 요약을 무조건 `anchor:'artifact'` delta로 밀어넣는다. **소형 pairing은 theatre 판정에 구조적으로 안 걸린다** = 낭비 감지기가 이 구간에서 꺼져 있음. rubric의 "애매하면 기각" 기본값이 우회된다.
- producer SKILL의 `overrides: {effort:"low"}` 예시 트리거가 `예: 예산 잔액 부족` — 작업 크기 기반 조임은 문서화된 경로가 없다.

## 낭비 규모 추정

**실측치 1건뿐.** `OBS-2026-07-08-225315` baseline: notes-cli(마크다운 TODO/태그 추출 CLI, 소형) 미션을 brainstorm 3라운드 + pairing 3라운드 = **150k 토큰**. 솔로는 서브에이전트 1회로 12 test green. 현재 mission 템플릿 기본 `total_tokens: 200000` → **소형 미션 하나가 기본 미션예산의 75%**.

단 그 run은 valid delta 45개를 실제 생산(theatre=false)하고 솔로가 놓친 AC를 커버했다. 150k가 곧 낭비는 아니다 — 낭비 여부는 delta/토큰 비율이고, 그 계기가 없다.

**측정 계기 사망.** board 기록 run 3/3 전부 `tokens: null`, `rounds: null`, `budget.spent_tokens: 0`. producer SKILL이 "`tokens:null`은 incomplete이며 0으로 대체하지 않는다"고 정직하게 처리한 결과 — 정직하지만 낭비를 실측할 데이터가 0. **"낭비가 얼마나 크냐"는 질문이 현재 구조적으로 답 불가.**

**구조적 고정비 (코드에서 계산):**

| ritual | 에이전트 호출 수 | 기본값 |
|---|---|---|
| pairing | `R × 2` (dev+qa) | R=3 → 6 |
| brainstorm | `N + R×(N+1) + 2` (seeds + 라운드×(페르소나+critic) + synth + verdict) | N=3, R=4 → 21 |

최소 바닥: pairing `maxRounds:1` → 2회. brainstorm → `N + (N+1) + 2` = N=3이면 9회.

**낭비 생성기 = dryStop 지연 감지.** `dryStop: 2`는 dry 2회 연속을 요구하므로 **무의미한 run임을 알아내는 비용이 dry 라운드 2개**다. 완전히 무의미한 brainstorm(N=3)도 seeds 3 + dry 2라운드×4 = 8 + synth/verdict 2 = **13회 호출**. 돈을 다 쓴 다음에 "연극이었다"를 안다. 소집 전 싼 게이트가 없다.

## 규모 × 속성 낭비 매트릭스

| 작업 | 팀 payoff | 고정비 | 낭비 위험 |
|---|---|---|---|
| 방향 모호한 기획 | 높음 (반박·기각대안이 실질) | brainstorm 21 | 낮음 — 설계 의도 그대로 |
| 사양 명확한 신규 구현 | 중간 (qa가 AC 틈 발굴) | pairing 6 | 중간 — baseline이 증명한 구간 |
| 답을 이미 아는 질문 | 0 (합의만 나옴) | brainstorm 13~21 | **최악** — dry 감지비 전부 순손실 |
| 오타/문구/주석 수정 | 0 (qa 깰 게 없음) | pairing 2~6 + 워크트리 + record + owner gate | **최악** — payoff 0인데 파이프라인 완주 |
| 비코드 산출물(문서·copy) | 낮음 | pairing 6 (qa가 돌릴 명령 없음) | 높음 — `blockedChecks`만 쌓임 |
| 비가역·고위험 변경 | 높음 (독립 판단이 값) | 무엇이든 | 낮음 |

**패턴: 낭비는 작업 크기에 비례하지 않고 "실질적 이견 표면이 있는가"에 좌우된다.** 작고 명확한 일 = 최악 비율. 크고 모호한 일 = 정상.

## 배경

studio v0.1.0 SHIPPED 이후 owner가 '작업 속성에 따라 크루 배정, 작업 정도에 따라 적절한 워크플로우'가 실제로 작동하는지 물었고, 확인 결과 속성 축만 존재함을 발견. 논의 중 제시된 '소형은 studio 밖에서' 안이 취지 위반임을 owner가 지적해 방향을 native scale 축으로 정정.

## 정해진 것

**아래는 논의에서 합의된 방향이며 아직 DEC 승격 전이다 (owner 게이트 미통과).**

## 1. "소형은 studio를 쓰지 마라"는 오답 — 폐기

논의 중간에 제시했던 두 안 모두 취지 위반으로 철회했다.

- **"소형 작업은 studio 밖에서"** → owner가 라우팅을 대신 하라는 말. `INT-2026-07-08-164552`가 명시적으로 반대한다 — "일감 목록이 아니라 미션을 받는다 — **일을 정의하는 행위 자체가 팀 안에서 일어난다**". 미션 하나 안에 큰 일과 작은 일이 섞여 있고, 미션을 받은 순간 작은 항목은 이미 studio 안에 있다. 옵트아웃 지점이 없다.
- **"소형은 task-github micro로"** → 취지문의 반목표("이슈트리 순차 처리기의 확장이 아니다")를 반대 방향에서 위반. studio를 대형 전용으로 만들고 실행을 다른 도구에 넘기면 사업부가 쪼개진다.

즉 그것들은 설계 구멍에 대한 **운용 우회**였다. 고칠 대상은 구멍 자체.

## 2. task-*는 도구다 — 규모 축의 위치를 결정한다

`rules/casting.md` Tool policy와 producer SKILL §3a가 이미 규정: "Studio native harness가 기본이며 위 crew catalog 전체를 **외부 plugin 없이** 사용할 수 있다", "도구 선택 우선순위는 run parameter > `.studio.yml` > native", "후보 없음: native cast와 critic/reviewer로 **완주**", "미설정 plugin은 discovery/probe 금지".

task-worker/task-github는 optional external executor이고 기본은 꺼져 있다. producer가 쓸지 말지 정한다.

**따라서 규모 축은 native casting에 있어야 한다.** task-* 어댑터에 두면 외부 executor를 설정한 track만 규모 감응이 생기고 **기본 경로인 native run은 계속 규모 무감** — 대다수 경로가 혜택을 못 받는다. `solo` 리추얼이 native여야 하는 이유가 여기서 나온다(우회로가 아니라 기본 lane).

## 3. production scale·검증 독립성·task gear는 서로 다른 대상 — 커플링 금지

| 축 | 지배 대상 |
|---|---|---|
| Studio item `scale` | **제작 노동** — production crew 수, 리추얼, 라운드, 상호작용 critic |
| verification independence | **결과 검증** — 별도 reviewer 필요 여부와 freshness |
| task-* `gear` | **배송 세리머니** — PR, review ownership, merge·rollback edge |

task-*의 gear는 산출물 배송 절차를, Studio scale은 산출물을 만드는 노동 투입을
정한다. 독립 reviewer는 production cast가 아니라 verification edge다. 파급력·비가역성·
owner 계약이 verification independence를 요구할 수 있고 task gear가 그 신호 중 하나일
수 있지만, gear 값에서 production scale을 파생하거나 그 반대로 유추하지 않는다.
`DEC-2026-06-19-190302`에서 가져올 것은 "파급력에 비례" 원리뿐이고 gear→PR 표는
production casting 표가 아니다.

Producer가 어떤 track에 task-github를 lease하면 backlog item의 production scale과
track/배송 edge의 gear가 함께 존재한다. **서로 파생되지 않는다.** production cast가
1명인 item도 비가역이면 별도 reviewer와 major delivery gear를 가질 수 있다. 이때
reviewer 호출은 `solo` production ritual의 crew cardinality에 포함하지 않는다.

## 4. 규모 판정은 producer 권한 안이다

producer 절대금지 2번(판단 대리 합성 금지)은 **특정 역할의 판단**을 미리 합성하지 말라는 것 — architect가 뭐라 할지 producer가 정하면 안 된다. 규모 판정·cast 선정·리추얼 선택은 producer 본업이고 행동 경계 표가 이미 허용한다(`mode`, mission/QualityPlan/context/budget/backlog/**cast** 준비).

단, Producer가 criteria와 QualityPlan을 "준비한다"는 말은 domain 의미를 새로 저작한다는
뜻이 아니다. Owner mission이나 선행 crew artifact가 이미 결정한 objective·constraint·
criterion을 스키마에 전사·정규화·연결할 수 있을 뿐이다. mission에 없는 사실, 설계,
수용 임계, verification measure를 새로 결정해야 하면 해당 domain crew를 먼저 소집한다.
이 의미 보존 판별 테스트는 scale과 무관한 Producer hard invariant다.

**즉 owner가 규모를 알려줄 필요 없다.** producer가 분류하고 비가역 경계를 넘을 때만 owner 게이트. 그게 취지에 맞는 자율성.

## 5. 최소 메커니즘 (합의 방향, 세부 계약은 DEC gate 전)

```
production casting:
  kind(속성) × item-scale(제작 노동) → ritual × production cast × rounds × critic

verification:
  independence requirement → reviewer attachment
```

`micro|normal|major`는 아직 **작업용 이름**이다. task gear와 같은 라벨을 쓰면 운영에서
두 축을 유추할 위험이 있으므로 최종 계약명은 DEC에서 별도로 정한다.

| provisional scale | production ritual | production cast | rounds / interaction judge |
|---|---|---|---|
| micro | `solo` (신규) | 담당 crew 1명 | 1회, critic off |
| normal | 현행 | 현행 default production cast | maxRounds 축소, ritual critic |
| major | 현행 | full production cast | 현행 rounds, ritual critic |

별도 reviewer는 이 표에 들어가지 않는다. verification independence가 필요할 때 production
run 뒤에 부착한다. 새로 필요한 production primitive는 **`broker/solo.workflow.js` 하나**다.
담당 crew 1명 호출 → 산출물과 결정적 verification 반환. 적대 루프와 interaction critic은
없지만 criterion-bound evidence는 생략하지 않는다.

효과:
- 작은 항목도 studio 안에서 처리된다 (취지 충족)
- 고정비 21회/6회 → 1회
- micro는 multi-agent 상호작용 가치를 주장하지 않으므로 theatre 판정 대상에서 제외하고,
  pairing의 강제 `artifact` interaction delta 편법도 함께 제거할 수 있다
- 앞서 검토한 `scaleHint` 프롬프트 주입(qa 공격면을 diff로 한정, 테스트 의무 완화)은 `normal` 구간 절감으로 축소 — 별건

casting scale의 직접 근거는 owner의 mission-internal 자율 배치 취지와 이 snapshot에서
확인한 고정 production 호출비다. `DEC-2026-07-10-133541`이 예약한 것은
"QualityPlan 작성·검증 오버헤드가 소형 mission 비용을 지배하면 축약 프로필을
도입한다"는 **계약·검증 층의 인접 재평가 조건**이다. 현재 telemetry로는 그 전건이
실제로 성립했는지 측정할 수 없으므로 casting scale의 직접 발동 근거로 사용하지 않는다.

blast radius: `rules/casting.md` + 신규 broker + `producer/SKILL.md` + mission/backlog 스키마 = **major, DEC 게이트 필요**.

## 아직 열린 질문

## 1. backlog item의 scale을 무엇으로 판정하나 (미결)

- 판정 단위는 **dispatch 가능한 backlog item**으로 고정한다. mission이나 track 전체에
  하나의 scale을 전파하지 않는다.
- track은 scale이 다른 item/run을 담는 worktree·integration 컨테이너다.
- **(a) 결정적 규칙** — criteria 결정성, 실제 이견 표면, 필요한 role diversity와
  coordination surface를 Producer가 판정한다. 공짜지만 오분류 위험이 있다.
- **(b) triage run 1회** — crew 1명이 분류. 정확, 항목당 1 호출 추가.

논의 시점 권고: micro 오분류 비용이 낮으니 (a)로 시작하고 오분류가 실측되면 (b)로 승격(승격 비용 낮음).

## 2. 착수 순서 (미결)

- **(A) receipt 토큰 계측 복구** — 현재 3/3 run이 `tokens:null`이라 낭비 실측 자체가 불가. 이게 없으면 scale 프로필의 효과도 못 잰다.
- **(B) solo 리추얼 + scale 축** — 취지 충족의 본체.

논의 시점 권고: (A)→(B). 단 (B)가 취지 위반을 고치는 본체이므로 owner가 (B) 우선을 택할 수도 있다.

## 3. backlog item에 scale을 어떻게 싣나 (미검토)

backlog 현행 형식은 `- [ ] 항목 설명 (kpi: k1)`이고 `studio.py backlog check`가 KPI 링크 없는 항목에 exit 6. scale을 `(kpi: k1, scale: micro)`처럼 같은 괄호에 실을지, 별도 필드로 둘지, 파서 영향 범위가 얼마인지 확인하지 않았다.

## 4. scale이 다른 item이 한 track에 섞일 때 integration/review cycle 단위 (미결)

track worktree 안에서 `solo`와 `pairing` run이 교차할 때 `readyForIntegration`, criteria
digest, `F-xxxx` review cycle을 item별로 둘지 track integration edge에서 합칠지
확인하지 않았다. `solo.workflow.js` 구현 전에 정해야 하는 계약이다.

## 5. critic/evidence를 micro에서 어떻게 다루나 (방향 확정, 집계 영향 미검토)

micro는 interaction critic과 theatre 판정에서 면제하지만 evidence 면제가 아니다.
최소 evidence는 실행된 verification 명령과 결과, `changedFiles`/diff, criterion별 pass
근거다. 주관적 판단이 필요한 criterion은 이 프로필에 들어올 수 없다. 이 규칙과 함께
`pairing.workflow.js:226`의 강제 `artifact` interaction delta를 제거하고 `studio.py
evidence` 집계가 solo artifact와 team interaction delta를 구분해야 한다.

## 6. scaleHint 프롬프트 주입의 최종 범위 (보류)

`solo` 리추얼이 micro를 흡수하면 `scaleHint`는 `normal` 구간(qa 공격면을 변경 diff로 한정, criteria가 요구하지 않으면 테스트 생략 허용)만 담당한다. 이 범위가 별도 작업으로 값이 있는지, `maxRounds` 축소만으로 충분한지 미결.

## 7. production scale의 최종 계약명 (owner/DEC gate)

`micro|normal|major`는 task gear와 충돌한다. `solo|pair|ensemble`도 normal brainstorm이
2명을 넘을 수 있어 정확한 계약명이 아니다. production cardinality와 collaboration
profile을 오해 없이 드러내는 이름은 DEC에서 결정한다.

## 8. dryStop 사전 게이트 (후속 최적화)

무의미한 run 감지 비용이 dry 라운드 2개(brainstorm N=3에서 13회 호출)라는 문제는 scale 축으로 부분 완화되지만 근본 해결은 아니다. "이견 표면이 있는가"를 소집 **전에** 싸게 판정하는 게이트는 이번 논의에서 설계하지 않았다.

## 다음에 볼 것

owner 결정 대기: (A) receipt 토큰 계측 복구 먼저 vs (B) solo 리추얼 + scale 축 먼저. 착수하면 DEC 게이트(blast radius major) 통과 후 설계.

## 관련 파일/문서

plugins/studio/rules/casting.md, plugins/studio/skills/producer/SKILL.md, plugins/studio/broker/pairing.workflow.js (39, 214, 226), plugins/studio/broker/brainstorm.workflow.js (29-30), plugins/studio/crew/dev.md, plugins/studio/crew/qa.md, plugins/studio/critic/rubric.md, plugins/studio/templates/mission.md, .studio/board.md, INT-2026-07-08-164552-studio-살아있는-에이전트-팀, DEC-2026-07-10-133541-studio-최적화-우선순위-artifact-context-품질-hard-floor와-가중-효용, DEC-2026-06-19-190302-ceremony를-파급력-gear-에-비례시킨다, OBS-2026-07-08-225315-studio-v0-1-0-baseline-검증

## 승격 후보

DEC 후보: backlog item별 production scale과 native solo 리추얼 도입
(`kind × item-scale → ritual × production cast × rounds × critic`, reviewer independence와
task gear는 직교). Producer는 scale/casting을 결정하지만 domain criteria는 Owner나
담당 crew가 결정한 의미만 구조화한다. blast radius major — owner 확인 필요.
OBS 후보: 소형 미션 1건이 기본 미션예산 75% 소모 + board run 3/3 tokens:null로 낭비 실측 불가.

---

## 독립 challenge review 대상 — Codex가 이해한 Studio의 제품 취지

아래는 2026-07-26 owner 대화에서 Codex가 복구·정리한 Studio의 제품 모델이다.
기존 문구를 다시 요약하는 것이 아니라, 다음 scale 설계와 구현의 판단 기준으로 사용할
수 있을 정도로 취지를 명시한다. reviewer는 문서와 코드의 현재 상태를 설명하는 데
그치지 말고, 이 모델이 owner의 의도를 잘못 축소하거나 과도하게 확장한 지점을
공격적으로 찾아야 한다.

### 한 문장 모델

**Owner가 상위 mission을 주면, Producer가 mission을 운영 가능한 work system으로
구조화하고 domain work 정의와 산출·검증은 담당 crew에게 맡긴다. Producer는 필요한
조직·리추얼·실행 도구·예산을 배치하고 Studio는 증거·맥락·owner gate를 유지해
mission을 끝까지 완주한다. 팀 비용은 관성적으로 쓰지 않고 추가 관점이 품질을 바꿀
때만 쓴다.**

Studio는 "여러 agent를 호출하는 workflow"가 아니다. 제품의 핵심은 mission을
실행 단계 목록으로 받은 뒤 처리하는 것이 아니라, **무슨 일이 필요한지와 어떤 조직
형태가 적절한지를 Studio 내부에서 계속 판단하는 능력**이다.

### 1. Hard invariant — Producer는 언제나 manager다

Owner가 이번 대화에서 다시 고정한 불변식이다.

- Producer는 어떤 규모에서도 코드·문서·기획안·조사 결과·테스트·통합 산출물을 직접
  만들지 않는다.
- Producer의 책임은 Owner/crew가 결정한 의미를 mission 계약, QualityPlan, ContextPack,
  backlog/track 구조에 보존하고, scale·casting·ritual·executor 선택, 예산 배치,
  run 회수, gate, 상태와 결과 보고를 수행하는 것이다.
- 특정 역할이 내려야 할 domain 판단을 Producer가 미리 합성하지 않는다. 그 판단이
  필요하면 해당 crew를 소집한다.
- QA 뒤 사소한 수정, 문구 한 줄, merge conflict 같은 작은 일도 Producer가 대신
  처리하지 않는다. 담당 crew 또는 integrator에게 넘긴다.
- native workflow나 external executor가 unavailable이어도 Producer 직접 실행으로
  fallback하지 않는다. 다른 crew lane으로 재계획하거나 owner-visible blocker로
  올린다.

Producer가 contract를 준비할 수 있는 경계는 **의미 보존 변환**이다.

- 가능: Owner mission이나 승인된 crew artifact의 문장을 criterion으로 전사, ID 부여,
  중복 제거, KPI/context/evidence reference 연결, 스키마 검증
- 불가: mission에 없는 사실·설계·risk acceptance·quality floor·verification measure를
  새로 결정하거나 문구를 바꿔 pass/fail 의미를 변경
- 판별 테스트: Producer의 변경으로 산출물의 허용 여부나 구현 선택이 달라질 수 있다면
  그것은 managerial normalization이 아니라 domain work이며 담당 crew가 해야 한다

acceptance criteria는 구현 crew가 시작하기 전에 고정한다는 계약을 유지한다. 다만 그
의미의 저자는 Owner 또는 선행 discovery/planning/domain crew다. 명확한 micro item은
Owner mission에 충분한 criterion이 있어 Producer가 그대로 전사할 수 있는 경우다.
criterion을 새로 만들어야 한다면 먼저 담당 crew가 정의해야 하며, 아직 micro
implementation-ready item이 아니다.

따라서 작업용 라벨 `micro`의 의미는 "Producer가 직접 처리"가 아니다.

```text
micro  = solo production ritual, 담당 production crew 1명, 1회, critic off
normal = 현행 default production cast, 축소된 maxRounds, ritual critic
major  = full production cast, 현행 rounds, ritual critic
```

별도 reviewer는 production cardinality에 포함하지 않는다. `solo`는 Producer mode가
아니라 **production crew cardinality가 1인 native ritual**이다. Producer와 worker의
역할 분리는 scale에 의해 완화되지 않는다.

### 2. Mission-driven — 일의 정의도 팀 안에 있다

Owner가 주는 입력은 잘게 나뉜 task list가 아니라 목적·제약·성공 기준을 가진
mission이다. Studio는 Producer의 관리 판단과 담당 crew의 domain 판단을 조합해 다음을
내부에서 결정해야 한다.

- 성공을 위해 어떤 product/research/design/implementation/QA/delivery 일이 필요한가
- 어떤 workstream이 독립 track이고 무엇이 선행 조건인가
- 어디에 실제 이견·탐색·검증 가치가 있는가
- 어떤 track을 병렬로 실행하고 어느 시점에 합칠 것인가
- 어떤 판단이 owner 전권이고 무엇은 Studio가 자율 결정할 수 있는가

이 때문에 Studio를 Issue Tree processor나 task-github의 상위 wrapper로 환원할 수 없다.
Issue/PR/worktree/CI는 Studio가 이미 정의한 work를 배송할 때 선택적으로 빌리는 실행
도구다. 일의 정의와 mission/quality/context/gate 소유권은 Studio에 남는다.

### 3. Producer의 본질은 자원 배치 판단이다

Producer가 제공해야 하는 핵심 지능은 "많은 crew를 부르는 능력"이 아니라 다음
질문에 답하는 능력이다.

- 이 일은 한 명이면 충분한가
- 서로 다른 prior가 실제 결론을 바꿀 가능성이 있는가
- dev↔QA 공방이 재현 가능한 결함을 만들 가능성이 있는가
- critic의 독립 판정 비용이 허위 수렴 위험보다 싼가
- 더 진행했을 때 기대되는 delta가 다음 round 비용보다 큰가
- 현재 item의 production profile은 무엇이어야 하는가
- native crew로 충분한가, 외부 executor/reviewer capability를 lease해야 하는가

Owner가 매번 `micro`, `pairing`, `QA 포함`, `task-github 사용`을 골라야 한다면
Studio가 routing 책임을 Owner에게 되돌린 것이다. Owner는 mission·방향·예산·비가역
행위의 권한자이지 일상적인 casting operator가 아니다.

### 4. "살아있는 팀"은 품질 수단이며, 항상 켜는 기능이 아니다

에이전트가 서로 말하고 반박하는 모양 자체에는 가치가 없다. 추가 crew나 round가
정당화되려면 최소한 다음 중 하나의 evidence-bearing delta를 만들어야 한다.

- durable artifact의 실질적 변화
- acceptance criteria의 보강 또는 수정
- 새로 확인된 risk와 대응
- 근거가 남는 rejected alternative
- 재현 가능한 실패와 이를 방어한 test/evidence

동의 반복·칭찬·역할극·일반론 요약은 delta가 아니다. critic은 참가자의 성실함이나
문체를 평가하는 사람이 아니라 제출된 delta와 anchor를 검증하는 독립 judge다.

반대로 추가 관점이 결과를 바꾸지 못할 것이 명확한 일은 팀 상호작용을 생략해야 한다.
이때 solo crew를 선택하는 것은 Studio를 우회하는 것이 아니라 **Studio가 올바른 조직
형태를 선택한 결과**다.

### 5. production scale의 판정 단위와 실질

판정 단위는 mission이나 track이 아니라 **dispatch 가능한 backlog item**이다. 하나의
track에 큰 item과 작은 item이 섞여 있어도 가장 큰 item의 profile을 나머지에 전파하지
않는다. track은 서로 다른 production scale의 item/run을 담는 worktree·integration
컨테이너다.

현재 snapshot의 `micro|normal|major`는 작업용 coarse profile 이름일 뿐 최종 계약명이
아니다. 판정의 더 본질적인 질문은 다음과 같다.

> 이 backlog item에 다른 production 역할 또는 한 round를 더 투입했을 때, 결과가 유의미하게 달라질
> 가능성과 그 변화의 가치가 비용보다 큰가?

따라서 scale을 파일 수·줄 수·작업 시간만으로 결정하면 취지를 놓친다.

| 사례 | 예상 Studio 판단 |
|---|---|
| 명확한 오타·문구 한 줄 | 담당 crew 1명, loop/critic 없이 필요한 최소 검증 |
| 산출물은 작지만 product 방향이 모호함 | 서로 다른 prior를 가진 planning/strategy ritual |
| 대규모지만 결정적인 기계적 변환 | item별 solo production profile × 독립 item N개 병렬; 병렬도는 별도 축 |
| 작은 인증·권한 변경 | 제작 cast는 작을 수 있지만 비가역 위험 때문에 독립 review 필요 |
| 방향이 열린 신규 product mission | 다역할 탐색·반박·critic의 기대 delta가 커 full ritual |

snapshot에서 확인된 것처럼 낭비는 작업 크기에 선형 비례하지 않는다. **실질적 이견
표면(disagreement surface)이 없는데 상호작용을 강제할 때 비율상 최악**이 된다.

### 6. production scale·verification independence·task gear·병렬도는 직교한다

- Studio item `scale`: production cast 수, 역할 조합, ritual, rounds, interaction critic
- verification independence: production 결과에 별도 reviewer가 필요한지와 freshness
- task-* `gear`: PR, review ownership, integration/rollback/merge 세리머니
- parallelism: 독립 backlog item/run을 몇 개 동시에 실행할지

관련 신호를 공유할 수 있지만 한 값을 다른 값에서 파생하면 안 된다.

- 한 줄 auth policy 변경: solo production일 수 있지만 independent reviewer와
  `gear=major`가 필요
- 큰 low-risk mechanical migration: item별 solo production을 N개 병렬 실행할 수 있고
  배송·rollback 단위는 별도 gear 판단

따라서 solo production run 뒤에 파급력·비가역성·owner 계약이 요구한 별도 reviewer를
붙여도 production ritual은 여전히 crew 1명 1회다. reviewer는 production cast의 두
번째 멤버가 아니라 별도의 verification edge다.

`micro|normal|major`를 task gear와 똑같이 쓰면 운영상 암묵적 결합이 생기므로 이
라벨은 잠정적이다. `solo|pair|ensemble`도 normal brainstorm의 실제 cardinality를
정확히 표현하지 못하므로 최종 이름은 DEC/owner gate에서 정한다.

### 7. Native-first이고 외부 plugin은 도구다

Studio는 native crew만으로 research부터 implementation, QA, review, synthesis까지
완주할 수 있어야 한다. task-worker, task-github, session-review는 특정 실행·배송·독립
review edge가 필요할 때 선택하는 capability다.

- Studio는 mission, QualityPlan, context, track, 완료 판정, owner gate를 소유한다.
- track당 executor는 하나만 lease해 중복 실행을 막는다.
- 외부 workflow 내부 상태를 Studio에 복제하지 않고 reference, coarse status,
  ResultEnvelope와 evidence만 회수한다.
- 외부 plugin이 없다는 이유로 mission의 일부를 Owner에게 수동 처리하도록 넘기지 않는다.
- 미설정 plugin을 자동 discovery/probe하며 workflow를 흔들지 않는다.

즉 도구의 가용성이 Studio의 조직 원리를 결정하지 않는다. Producer가 필요를 먼저
판단하고, 그 필요를 충족할 설정된 capability가 있을 때만 lease한다.

### 8. Studio는 산출만이 아니라 완주 가능한 운영 상태를 소유한다

Studio는 단발 응답이 아니라 출근/퇴근형 operating mode다. 여러 mission/track을
백그라운드에서 운영하면서도 Owner와 계속 대화할 수 있어야 한다.

- 상태는 `.studio/`에 남고 세션은 교체 가능한 cache다.
- raw transcript를 매번 재소비하지 않고 minutes, delta, open finding, valid evidence,
  compact handoff만 이어받는다.
- 한 track이 owner gate를 기다려도 독립 track은 계속 진행한다.
- 실제 artifact evidence, context quality, verification, review, integration/cleanup 상태가
  닫혀야 완료다.
- Owner에게는 전체 회의록이 아니라 synthesis, evidence-bearing delta, 열린 gate를
  보고한다.

최종 목표는 많은 run을 기록하는 것이 아니라, 세션이 끊겨도 자율적으로 이어지고
결과의 이유와 검증을 복원할 수 있는 작은 조직의 운영 상태다.

### 9. 품질과 효율의 관계

비용 절감은 품질 floor를 낮춰 얻으면 안 된다. artifact quality와 context quality의
required criterion은 통과해야 하며, 같은 품질 수준을 달성하는 후보 사이에서 token,
elapsed time, 중복 physical execution, 불필요한 owner intervention을 줄인다.

다만 "동일한 품질 floor"가 항상 동일한 리추얼·테스트 목록·문서량을 뜻하지는 않는다.
micro는 그 criterion을 입증하는 가장 싼 evidence profile을 사용하고, major는 fresh
independent evidence와 넓은 integration surface를 요구할 수 있다. 축약 대상은 품질
그 자체가 아니라 **그 품질을 안전하게 증명하기 위한 조직·절차 비용**이다.

현재 `tokens:null` 상태는 단순 dashboard 누락이 아니다. 어떤 casting이 같은 품질을
더 싸게 만들었는지 비교할 수 없으므로 Studio의 adaptive allocation을 검증할 feedback
loop가 끊긴 상태다.

#### micro contract profile

`solo.workflow.js`만으로는 Producer·계약 층의 고정비가 줄지 않는다. micro profile은
품질 floor와 evidence를 없애는 것이 아니라, 승인된 mission의 의미를 중복 문서화하지
않고 기계적으로 상속·생성해야 한다.

| 계약 요소 | micro profile의 목표 |
|---|---|
| mission/owner gate | 승인된 mission 안의 item은 KPI·자율성·gate를 상속해 item마다 승인 절차를 반복하지 않는다. standalone micro mission은 Owner가 말한 objective·constraint를 의미 추가 없이 compact contract로 전사해 한 번 확인한다. 방향 변경·예산 상향·비가역 행위 gate는 유지한다. |
| backlog | KPI-linked item 하나에 production profile과 criterion source ref를 함께 둔다. 별도 work-order 문서를 만들지 않는다. |
| QualityPlan | Owner/선행 crew가 결정한 criterion을 참조하고 필수 schema는 자동 materialize한다. Producer가 floor/measure 의미를 새로 저작하지 않는다. |
| ContextPack | 직접 source ref로 충분하면 새 장문 synthesis 없이 최소 ref+digest만 만든다. |
| budget/record | mission ledger에서 per-run reservation과 compact receipt를 자동 생성한다. 회의가 없으므로 의사 회의록을 만들지 않는다. |
| integration/cleanup | mission이 미리 승인한 reversible autonomy 범위는 중복 질문하지 않는 방향을 검토하되, 현재 owner integration gate를 바꾸는 일은 별도 DEC/owner gate다. |

`DEC-2026-07-10-133541`은 QualityPlan 작성·검증 오버헤드가 실제로 소형 mission 비용을
지배할 때 계약 축약 프로필을 재검토하라고 예약했다. 현재 `tokens:null`이라 그 전건은
검증되지 않았다. 이 결정은 casting scale의 직접 근거가 아니라 위 micro contract
profile을 검토하게 하는 인접 근거다.

#### micro minimum evidence

micro는 interaction critic과 theatre 판정에서 면제되지만 evidence 자체는 면제되지
않는다. 최소 evidence는 다음과 같다.

- 실제 실행된 verification command와 결과
- `changedFiles`와 inspectable diff/artifact ref
- 각 required criterion의 pass 근거
- blocked check와 환경 제약의 정직한 보고

주관적 판단이나 새 domain 해석이 필요한 criterion은 critic-off micro profile에
적합하지 않다. pairing에서 dev artifact를 강제로 interaction delta로 주입하는 편법은
solo theatre 면제와 함께 제거하고, evidence 집계는 solo artifact evidence와
multi-agent interaction delta를 구분해야 한다.

### 10. 현재 gap을 고칠 때 피해야 할 축소

새 `solo.workflow.js`는 필요하지만 그것만 추가하면 고정 ritual이 둘에서 셋으로 늘어날
뿐이다.

**v1의 의미적 필수 범위:**

1. Producer가 Owner 입력 없이 backlog item의 production scale을 판정한다.
2. `kind × item-scale`로 production crew, ritual, rounds, interaction critic을 선택한다.
3. reviewer independence와 task gear, 병렬도를 production scale에서 분리한다.
4. 모든 profile에서 실제 work는 담당 crew가 한다. domain criteria의 신규 의미는
   Owner 또는 담당 crew만 정하며 Producer는 manager로 남는다.
5. micro contract/evidence profile로 ritual 밖의 고정비도 다룬다.

**효율 주장과 후속 adaptive routing의 선행 조건:**

6. receipt telemetry로 품질 floor 통과 여부와 비용을 비교할 수 있어야 한다. telemetry
   전에도 static solo routing은 구현할 수 있지만 비용 개선을 검증했다고 선언하거나
   측정 없는 dynamic tuning을 해서는 안 된다.

**후속 최적화:**

7. run evidence에 따른 동적 profile 승격·축소는 telemetry와 오분류 관찰 뒤 도입한다.
8. dry 2라운드 전에 멈추는 pre-convene gate는 scale과 독립된 별도 메커니즘으로 다룬다.

### 11. 반목표

Codex는 다음을 Studio의 목표로 이해하지 않는다.

- 모든 일에 여러 agent를 붙이는 multi-agent demo
- 에이전트가 감정·직급·조직 문화를 연기하는 simulator
- Owner가 만든 Issue Tree를 빠르게 소화하는 scheduler
- task-github/task-worker를 자동으로 찾아 호출하는 plugin router
- 높은 test count나 긴 논쟁을 품질로 간주하는 시스템
- 비용이 싸다는 이유로 artifact/context quality floor를 누락하는 시스템
- Producer가 급할 때 직접 수정까지 해주는 super-worker

### 12. Round 2 reviewer에게 요구하는 challenge

`separate / challenge / hard` reviewer는 최소한 다음 질문에 명시적으로 답해야 한다.

1. 위 모델이 `INT-2026-07-08-164552`의 mission-driven 팀 취지를 정확히 보존하는가?
2. Producer의 의미 보존 변환 테스트가 criteria/QualityPlan 저작 구멍을 실제로 닫는가?
   명확한 micro와 criteria-definition crew가 필요한 item의 경계가 결정 가능한가?
3. backlog item 단위 production scale과 track integration container 구분이 B3을
   해결하는가? mixed-scale track에서 구현 전에 더 고정해야 할 계약은 무엇인가?
4. production scale, verification independence, task gear, parallelism 분리가 B1의
   reviewer 슬롯 충돌을 해결하는가?
5. micro contract profile이 mission/QualityPlan/context/record 고정비를 실질적으로
   줄이는 방향인가? owner gate를 무단 약화한 부분은 없는가?
6. critic-off micro의 결정적 minimum evidence가 quality hard floor를 지키기에 충분한가?
7. v1 필수, telemetry 선행 조건, 후속 dynamic/pre-convene 최적화의 분리가 과잉 추론을
   제거했는가?
8. Round 1 B1~B3와 S1~S3, D1~D2, N1이 각각 해소·유예 사유와 일치하는가?

승인은 `blocking_count=0`을 뜻할 뿐 의견이 없다는 뜻이 아니다. 승인하더라도 구현 전에
반영해야 할 방향성 의견은 `[should-reflect-before-implementation]` 또는 `[directional]`로
남긴다.
