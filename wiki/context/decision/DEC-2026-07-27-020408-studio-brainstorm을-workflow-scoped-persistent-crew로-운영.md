---
title: Studio brainstorm을 workflow-scoped persistent crew로 운영
created_at: 2026-07-27
summary: verified native capability에서 brainstorm crew를 한 번 spawn하고 same-handle follow-up하며 canonical broker action ledger만 orchestration 정본으로 사용한다.
tags: [studio, brainstorm, persistent-crew, orchestration, token-efficiency]
relations:
  rejected_decisions: [REJ-2026-07-08-164619-crew-상주-에이전트-sendmessage-지속-대화-방식]
  ssot: [studio-plugin]
---

## 결정

verified `spawn`, `followup`, `wait_barrier`, `interrupt_cancel`,
`structured_result` capability가 있는 native host에서는 brainstorm crew를 workflow 범위로
유지한다. participant, critic, summarizer는 자신의 최초 assigned turn에 한 번만 spawn하고
이후 모든 round는 original host handle에 follow-up한다.
현재 구현 상태는 deterministic canary harness이며 actual collaboration host evidence가 없다.
명시적 `canary` 값도 harness admission일 뿐 live dispatch나 production default 채택을
의미하지 않는다. 실제 채택은 owner-approved fresh host receipt 이후 별도 gate다.

`persistent_brainstorm_broker.mjs`의 reducer가 phase, action ordinal, barrier, `maxRounds`,
`dryStop`, actor lifecycle의 유일한 정본이다. Producer/main은 broker action을 exact relay하고
result를 동일 순서의 barrier receipt로 돌려준다. Producer/main이 prompt, schema, ordering,
converge 결과를 합성하거나 암묵적으로 다음 round를 만드는 것은 금지한다.

Canonical label은
`[studio:{crew}] {워크플로우이름} - {워크플로우에서의 역할}`이며 action ledger,
envelope, initial/current-task summary에 남긴다. host API용 `task_name`은 path-safe immutable
identity로 분리한다. phase/round는 mutable ledger와 summary 상태이며 rename/respawn으로
표현하지 않는다. UI card-title projection은 독립 capability로, 미지원이면 `false`를
보고하고 지원을 주장하지 않지만 work canary를 단독 차단하지 않는다.

native dispatch가 시작된 뒤에는 isolated CLI Runner로 중간 fallback하지 않는다. 실패 시
live handle을 interrupt/cancel하고 late result와 replacement spawn을 거부한다. token 측정이
없으면 `tokens:null`, `token_coverage:unavailable`을 유지한다. pairing은 역할별 hard write
confinement가 입증되기 전까지 existing isolated Runner 경로를 유지한다.

## 취지

brainstorm 시간이 길어질 때 매 round의 fresh process/session 생성과 persona 재주입 비용을
줄이되, 논리 round 수와 검증 강도를 임의로 축소하지 않는다. 비용 최적화는 identity 유지와
exact broker relay에서 얻고, critic 독립성·dry stop·owner gate는 보존한다.

## 트레이드오프

- native host lifecycle failure와 late result를 명시적으로 관리해야 한다.
- persistent context는 이전 turn의 오류도 보존하므로 schema validation과 barrier 순서가
  더 강한 hard floor가 된다.
- UI card title은 host capability에 따라 canonical label과 다를 수 있다. runtime
  ledger/envelope가 정본이고 UI 미지원 사실을 숨기지 않는다.
- isolated CLI Runner는 호환성을 유지하지만 persistent 비용 절감은 제공하지 않는다.

## 기존 기록 lifecycle 후보

- `DEC-2026-07-08-164805...소집형`의 원시개념, run 단위, broker relay, producer 금지,
  transcript/dry-stop 설계는 유지한다. 단 **brainstorm native path의 fresh-per-turn 조항만
  이 결정으로 부분 대체**하는 것이 적절하다. 전체 record retire는 나머지 유효 결정까지
  잃으므로 후보가 아니다.
- `REJ-2026-07-08-164619...상주-에이전트`는 당시 재고 조건인 continuation 지원이
  충족된 범위에 한해 반려 사유가 해소됐다. 이를 “전면 반려”에서 “unverified host 또는
  pairing에는 계속 반려, verified native brainstorm에는 채택”으로 재분류하는 후보로 둔다.
  record type 이동/retire는 별도 owner capture gate에서 확정한다.

## 재평가 조건

- same-handle continuation이 fresh isolated Runner보다 token/time을 유의미하게 줄이지 못함.
- host handle resume가 cwd/sandbox/tool boundary를 유지하지 못함.
- barrier ordering 또는 structured result repair가 반복적으로 fail-closed함.
- brainstorm 외 ritual에 persistent lifecycle을 확장할 만큼 hard confinement evidence가 생김.
