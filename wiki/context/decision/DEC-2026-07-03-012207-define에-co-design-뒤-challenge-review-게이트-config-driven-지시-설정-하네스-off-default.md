---
title: define에 co-design 뒤 challenge review 게이트 — config-driven, 지시>설정>하네스, off-default
created_at: 2026-07-03
summary: task-github:define에 co-design 다음 challenge review 게이트 추가. fresh-context 적대 서브에이전트가 분해 제안을 4 절단규칙+위키 결정그래프에 refute로 감사(분해/의도 에러를 최상류에서 포착). 저-의존 config-driven(orchestrate review-tool 패턴 미러): define.review-tool/review-command, off-default, `--review`로 on, TOOL 우선순위 지시>설정>하네스, terminal=하네스(내장 challenge, STOP 아님 — 사람이 co-design에 present). 대상=분해 제안 문서라 내장이 1급, 외부 슬롯은 옵션.
tags: [task-github, define, review, challenge, decomposition, config, low-dependency]
---

## 결정

task-github:define에 co-design(분해 제안 확정) 다음 단계로 **challenge review 게이트**를 추가한다. fresh-context 적대 서브에이전트가 분해 제안을 4 절단규칙(병렬 이득/위험 격리/정보 가치 경계/병렬 해금)·blocker 직접의존·검증·문서 리프 금지·container 수요·gear 정직성과 위키 결정그래프(REJ/DEC 회귀 여부)에 대해 refute 스탠스로 감사한다. 목적: 분해/의도 에러를 가장 싼 자리(트리 생성 전, upstream)에서 잡는다 — 다운스트림 verify/review가 구조적으로 못 잡는 에러 클래스(worker↔reviewer 상관 때문).

저-의존·config-driven으로, orchestrate의 review-tool 패턴을 그대로 미러링한다: `.task-github.yml`의 `define.review-tool`/`define.review-command`, `compose_tool_command` + `task_config.py` 재사용, 신규 메커니즘 없음.

두 축을 분리한다. (1) ON/OFF: 기본 off, `task-github:define --review` 아규먼트(또는 사령관 지시)로 이번 run만 on. (2) TOOL(on일 때): 이번 지시 도구 > 설정(`define.review-tool`) > 하네스(내장). 이 precedence는 orchestrate와 동일(commander > config > default). 순수 헬퍼 `orchestrator_ops.resolve_review_tool(enabled, directive_tool, config_tool)`이 결정한다.

terminal은 STOP이 아니라 **하네스**다 — orchestrate와 의도적 divergence. orchestrate는 리뷰 도구 없으면 STOP(human_gate, PR 게이트라 멈춤이 안전)이지만, define은 co-design 게이트라 **사람이 이미 present**하므로 도구 없으면 내장 challenge 서브에이전트로 진행한다. harness fallback은 "skip"이 아니라 진짜 challenge(fresh-context, refute, 규칙/위키 grounding) — co-design 에이전트가 자기 제안을 다시 읽는 것(theater)이 아니다.

challenge 대상은 **분해 제안 문서**(아직 이슈도 아님)이지 git PR이 아니다 — orchestrate와 다른 지점. 따라서 내장 challenge가 1급 경로이고, 외부 도구 슬롯은 "제안 아티팩트를 받는 도구"가 있을 때만 쓴다(session-review는 git PR 중심이라 doc-review 모드가 있어야 꽂힘; "그냥 session-review 꽂으면 된다"를 오버셀하지 않는다).

off-default를 존중하되, 복잡도 신호(트리 리프 수/깊이가 임계 초과, plan-time task-count 신호 재사용)가 뜨면 비차단 nudge로 `--review`를 권장한다 — 큰 트리(제일 값나가는 케이스)를 조용히 스킵하지 않게. bounded: challenge 1라운드, 사람(이미 present)이 blocking 판정에 판결, auto-loop 없음. severity bar(blocking만 게이트, advisory는 로그).

관련: [[DEC-2026-07-02-224910-orchestrate-세리머니를-merge-edge-gear로-이동-분해를-payoff-원리로-재정의]](이번에 define에 넣은 분해 규칙 — challenge가 그 집행 레이어), [[DEC-2026-07-02-190102-define은-topology-판단을-제안-게이트에-필수-포함]](co-design 제안 게이트가 challenge의 앞단), [[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]](review-tool relay 패턴의 원본).

## 취지

이번 세션 시작 병목(과분해 → orchestrate 느림)을 자동 감사한다. 이번에 define에 넣은 분해 규칙은 "co-design이 규칙을 따르길 바람"에 그치는데, challenge가 그 규칙 준수를 적대적으로 **검증**하는 집행 레이어다. 솔로 fire-and-forget 관점: 사람은 co-design을 high-level로 하고, challenger가 디테일(과분해·가짜 blocker·검증-as-리프)을 감사하고, 사람은 blocking flag에만 판결한다 — 자기 분해를 손으로 정독 감사하는 것보다 적은 일. 자율성은 실행을 스케일하지 판단을 대신 못 하지만, decompose-challenge가 판단존을 "모든 의도"에서 "목표 자체가 옳은지" 하나로 축소한다.

## 배경

대화 co-design에서 도출: verify/review는 적합성(conformance) 품질만 max하고 의도(intent)/분해 품질은 못 잡는다 — worker와 reviewer가 같은 모델·맥락·사각을 공유하면 "approved" 합의가 독립 검증이 아니라 상관된 합의이기 때문. challenge를 define(제일 upstream)에 두면 트리당 1회로 최고 레버(트리 전체 shape 결정)·최저 집계비용이고, 사람이 co-design에 이미 present라 terminal=harness가 STOP보다 자연스럽다. 순서는 co-design→challenge: 반쯤 된 설계 challenge는 노이즈, 굳은 제안 stress가 signal이며, co-design 후 사람+에이전트 합의 상태가 정확히 사각이 숨는 순간이라 fresh challenger가 그 합의를 깬다.

## 고려한 대안

- plan-time challenge(major 리프별, plan 뒤) — define보다 하류이고 리프마다라 집계비용 큼. define challenge가 트리 전체 shape를 트리당 1회로 잡아 우위. 단 둘은 배타 아님(major plan challenge 병행 가능).
- 무차별 challenge(모든 기어·모든 define run) — 방금 깎은 오버헤드를 도로 부풀림. off-default + 복잡도 nudge로 기각.
- session-review 하드 의존 — 저-의존 원칙 위배. config relay + harness fallback로 loose coupling(import 없음, standalone 동작, 도구 있으면 업그레이드).
- challenge를 co-design 안에 섞기 — 반쯤 된 설계 challenge는 노이즈. 순서를 co-design→challenge로 분리.
- terminal=STOP(orchestrate처럼) — define은 사람이 이미 present라 불필요. harness 진행이 자연.

## 트레이드오프

얻음: 최고 레버 에러클래스(분해/구조)를 upstream에서 감사, 저-의존(harness fallback이 standalone 보장, 외부 도구는 옵션 업그레이드), off-path 무영향(기본 off), 사람 부하↓(co-design high-level + blocking 판결). 비용/포기: on일 때 킥오프 전 critical-path 1패스(그러나 그게 곧 front-load라 fire-and-forget엔 OK), 외부 도구 슬롯은 proposal-target 지원이 있어야 실효(내장이 메인 경로). blast radius = define SKILL + task_config.py(define.* 키) + orchestrator_ops(resolve_review_tool) + rules/DESIGN/README = medium.

## 재평가 조건

복잡도 nudge 임계(리프 수/깊이/task-count) 조정. 외부 proposal-review 도구(예: session-review의 doc-review 모드)가 생기면 외부 슬롯 실효화. challenge false-positive 마찰이 크면 severity bar/round-cap 조정. plan-time challenge와의 중복/보완 관계를 실사용으로 관찰 — 둘 다 켜면 이중인지, 상보인지.
