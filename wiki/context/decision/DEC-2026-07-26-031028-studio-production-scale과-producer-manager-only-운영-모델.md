---
title: Studio production scale과 Producer manager-only 운영 모델
created_at: 2026-07-26
summary: Producer는 항상 manager로 남고 backlog item별 production scale이 제작 crew·ritual·rounds·critic을 정하며 verification independence·task gear·parallelism은 직교한다.
tags: [studio, producer, orchestration, casting, production-scale]
search_terms: [studio scale, producer manager-only, solo ritual, production cast, verification independence]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
  ssot: [studio-plugin]
---

## 결정

1. Producer는 모든 규모에서 manager다. 코드·문서·기획·조사·테스트·통합 산출물을 직접 만들지 않고, 실제 work는 담당 crew가 수행한다. Producer는 mission·QualityPlan·ContextPack·backlog/track을 구조화하고 casting·ritual·executor·예산·gate·회수·보고를 관리한다.

2. Producer가 contract를 준비할 수 있는 경계는 의미 보존 변환이다. Owner mission이나 승인된 crew artifact의 criterion을 전사·정규화·연결할 수 있지만, pass/fail이나 구현 선택을 바꾸는 사실·설계·risk acceptance·quality floor·verification measure를 새로 결정하면 domain work이므로 Owner 또는 담당 crew가 정해야 한다.

3. production scale의 판정 단위는 dispatch 가능한 backlog item이다. `kind × item-scale`이 production ritual, production cast, rounds, interaction critic을 결정한다. track은 서로 다른 scale의 item/run을 담는 worktree·integration container다.

4. production scale, verification independence, task-* gear, parallelism은 직교한다. 별도 reviewer는 production cast가 아니라 verification edge이며, task gear나 reviewer 요구에서 production scale을 파생하지 않는다.

5. 최소 production profile은 native solo ritual이다. Producer가 담당 production crew 1명을 1회 소집하며 interaction critic과 theatre 판정은 적용하지 않는다. 다만 실행된 verification command/result, changedFiles·diff, criterion별 pass 근거, blocked check는 필수다. 주관적 판단이나 새 domain 해석이 필요한 item은 critic-off solo admission 대상이 아니다.

6. Studio는 native-first이며 외부 executor·reviewer는 선택적 도구다. Owner는 mission·방향·예산·비가역 gate의 권한자이고 일상적인 scale·casting·routing을 직접 지정하지 않는다.

7. v1은 정적 item 분류, production profile 선택, Producer hard invariant, micro contract/evidence profile을 구현한다. token telemetry가 복구되기 전에는 비용 개선을 검증했다고 선언하거나 측정 없는 dynamic tuning을 하지 않는다. 동적 승격·축소와 pre-convene dry gate는 후속 최적화다.

`micro|normal|major`는 task gear와 충돌하는 임시 이름이며 최종 계약명은 구현 DEC에서 별도로 정한다.

## 취지

Owner가 상위 mission만 주면 Studio 내부에서 필요한 일을 정의하고 적절한 조직 형태를 선택해 끝까지 완주하게 한다. 살아있는 상호작용은 목적이 아니라 evidence-bearing delta를 만드는 품질 수단이다. 추가 관점이 결과를 바꾸지 못하는 item에는 solo production을 선택해 작은 일도 Studio 안에서 과도한 리추얼 없이 처리한다. Producer가 직접 작업하거나 Owner에게 routine routing을 돌려주는 우회는 허용하지 않는다.

## 배경

현재 casting은 kind 축만 있고 7개 kind가 brainstorm 또는 pairing으로 고정된다. 작은 구현도 dev+QA 적대 루프를 타며 pairing 기본 6회, brainstorm 기본 21회의 고정 호출비가 생긴다. 소형 mission baseline은 150k tokens를 사용했고 현재 board의 최근 run은 tokens:null이라 비용 비교 feedback loop도 끊겼다. 별도 hard challenge session-review 2라운드에서 micro crew cardinality, Producer criteria 저작권, scale 판정 단위의 blocking 3건을 수정한 뒤 approved/blocking 0으로 수렴했다. 근거는 SNAP-studio-scale-axis-gap과 complete commit 632352e다.

## 고려한 대안

소형 작업을 Studio 밖에서 직접 처리하는 안은 mission 안에서 일의 정의가 일어난다는 취지를 깨므로 기각했다. 소형을 task-github micro로 보내는 안은 Studio를 대형 전용 상위 레이어로 쪼개고 optional tool에 핵심 routing을 의존시켜 기각했다. Producer가 micro 작업을 직접 처리하는 안은 manager-only hard invariant를 깨므로 기각했다. track 전체에 하나의 scale을 주는 안은 가장 큰 item의 profile을 작은 item에 전파해 현재 낭비를 재현하므로 기각했다. reviewer를 production cast에 넣는 안은 scale과 delivery/review 축을 결합하므로 verification edge로 분리했다.

## 트레이드오프

production scale 도입은 rules/casting.md, broker/solo.workflow.js, producer/SKILL.md, mission/backlog schema뿐 아니라 scripts/studio.py의 evidence 집계·minutes 생성·backlog parser와 critic/rubric.md까지 건드리는 major 변경이다. solo 호출을 1회로 줄여도 mission·QualityPlan·ContextPack·record·integration gate의 계약 고정비가 남으므로 compact contract profile이 함께 필요하다. mixed-scale item이 같은 track worktree에 섞일 때 criteria digest, review cycle, readyForIntegration, write 직렬화 단위는 아직 미결이다.

## 재평가 조건

static 분류가 반복적으로 잘못되어 quality floor 미달이나 불필요한 multi-role 호출을 만들면 admission signal과 triage run을 재설계한다. criterion source와 기계적 measure가 없는 item은 solo 1회 비용 주장의 대상에서 제외하고 정의 crew 1회 + 실행 crew 1회로 계측한다. token telemetry가 복구되어 QualityPlan·계약 층이 실제 비용을 지배한다고 확인되면 compact profile 범위를 확대한다. production scale과 gear를 운영자가 반복적으로 혼동하면 최종 계약명과 CLI 필드를 더 강하게 분리한다.

## 구현 결과

v1 계약명은 `solo|standard|major`로 고정했다. static cast, 1-call solo broker,
outcome-linked standard brainstorm 수렴과 exact call/elapsed 계측을 구현했다. controlled
benchmark는 calls 41.18%, elapsed 40.74% 절감, quality drop 0%로 Owner gate
30%/5%를 통과했다. token coverage는 unavailable이므로 token 절감은 주장하지 않는다.
