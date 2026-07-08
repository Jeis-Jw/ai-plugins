---
title: studio 연극 방지 품질 체계 — critic 검증 전용 + delta 증거 + baseline
created_at: 2026-07-08
summary: 독립 판정자 critic(검증 전용·로스터 밖), anchor 없는 delta는 dry, 게이트 체계, baseline 비교 판정을 품질 체계로 채택 — 에이전트 상호 칭찬 수렴(비싼 연극) 차단이 목적.
tags: [studio, multi-agent, quality, plugin-design]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
---

## 결정

① critic: 로스터 밖 독립 판정자(페르소나 아님 — run 파라미터 judge로 주입). 계약은 검증 전용 — delta 레코드를 생성·보강하지 않고 참가자/합성 스텝이 제출한 것을 검증만 한다(관대한 재해석으로 연극 통과 방지). 동일 모델 티어로 시작, rubric이 먼저 — false positive가 반복 관측될 때만 상위 모델/2차 critic.
② delta 판정 규칙: changed_what이 durable artifact / acceptance criteria / risk / rejected alternative / repro·test 중 하나에 실제 anchor를 못 가지면 dry=true. dry 2회 = 폐회. 동의 요약은 산출물이 아니다. 상이한 prior 강제가 논쟁의 원료.
③ pairing 증거 = 반박 횟수가 아니라 재현 가능한 실패 리포트 ↔ 방어된 테스트의 쌍. acceptance criteria는 구현 전 고정, 변경은 재소집 사유. kill된 run의 delta는 aborted evidence로 표시해 합성 오염 방지.
④ 게이트(owner 전권): 미션 계약 확정·변경 / 신규 에픽·방향 전환 / 머지 등 비가역 / 결정·기각 wiki 승격 / 외부 공개 / 예산 상향. 질문 큐로 게이트 대기 중에도 타 track 계속.
⑤ MVP 판정 프로토콜: 같은 소형 미션(소형 CLI — 실패 재현·테스트 방어가 싸게 남는 크기, task-github 미접속)을 솔로 1회 vs 팀 1회 비교, 팀의 추가 delta가 0이면 연극 판정.

## 취지

살아있음의 최소 조건 중 '증거 기반 delta'와 '사용자 게이트'의 집행 메커니즘. 살아있는 척하는 비싼 연극과 실제 팀을 판별 가능하게 만든다.

## 배경

r1 리뷰 핵심 지적 — 같은 하니스가 자기 판정하면 칭찬 수렴을 못 막는다, 판정 기준은 말투가 아니라 delta여야 한다 — 를 r2에서 계약화. critic의 검증 전용 제약과 anchor 규칙은 r2 리뷰에서 추가 수렴.

## 고려한 대안

참석자 자기 판정(기각 — 칭찬 수렴 못 막음) / critic을 로스터 페르소나로 승격(기각 — 팀 정치의 일원이 되어 독립성 상실) / 상위 모델 critic 즉시 도입(유예 — rubric 우선) / pairing에 session-review 재사용(기각 — 세레머니 과잉, 신규 경량 브로커로; session-review는 사람 게이트·audit trail 필요한 외부 리뷰 전용).

## 트레이드오프

critic 호출이 라운드마다 추가되는 토큰 비용 — 연극으로 낭비되는 미팅 전체 비용보다 싸다는 판단. anchor 규칙이 초기 아이디어 발산을 과하게 조일 수 있음 — diverge 단계는 병렬 독립 제안이라 anchor 검증 밖.

## 재평가 조건

①MVP baseline 실험에서 critic이 실질 delta를 dry로 오판(false positive)하는 사례가 반복되면 rubric 수정 → 그래도 반복이면 티어 상향. ②diverge 산출까지 dry 판정이 필요해지면 발산 전용 완화 rubric 검토.
