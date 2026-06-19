---
title: ceremony를 파급력(gear)에 비례시킨다
created_at: 2026-06-19
summary: PR 분할·리뷰 강도를 설계결정 수가 아니라 기어·롤백 단위에 맞춘다. mechanism=task-protocol §3.1, principle=agent-policy 스캐폴드(CLAUDE/AGENTS 재렌더).
tags: [process, ceremony, gear, task-github]
---

## 결정

출하 ceremony(PR 분할·리뷰 강도)를 파급력(gear)에 비례시킨다. '사고는 분해, 출하는 묶음'. gear→PR/리뷰 mechanism 표는 task-github task-protocol §3.1에, 항상 읽히는 원칙 1줄은 agent-policy 스캐폴드(→CLAUDE/AGENTS 재렌더)에 둔다. micro=동승·경량, normal=같은테마 묶음·1리뷰, major/비가역=격리·적대적 리뷰. 묶음 상한=단일 롤백 단위.

## 취지

매 세션 읽는 운용정책에 박아 과분해 재발을 막는다. 정책은 에이전트 행동의 레버리지 지점.

## 배경

긴 세션에서 3 플러그인을 6 PR로 출하하며 B/C1/C2를 각각 풀 사이클(brainstorm→spec→self-flow 다라운드→PR→gate)로 돌림. #15는 단독 잡일 PR. 사용자가 과분해 지적. 독립 타당성 리뷰가 VALID-WITH-CHANGES: home 분리·묶음 상한·when-to-split·이 변경 자체는 major로 판정.

## 고려한 대안

(a) 전체 gear→ceremony 표를 scaffold에만: 기각 — task-protocol의 gear 단일정의를 fork하고 4계층 분리(mechanism은 plugins/) 위반. (b) task-protocol에만: 기각 — 자동로드 표면에 원칙이 안 보임. (채택) 분리: 표=task-protocol(mechanism), 원칙 1줄=scaffold(policy statement).

## 트레이드오프

얻음: 과분해 재발방지, 4계층 정합, 기존 gear 모델 재사용. 잃음: 두 곳 유지(상호참조로 완화). 위험: '항상 묶음' 과교정 → when-to-split·highest-gear-governs·never-bundle-to-dodge 가드레일로 방지.

## 재평가 조건

에이전트가 과묶음하거나 형제 PR로 리뷰를 회피하기 시작하면 격리 쪽으로 조인다. task-protocol의 gear 모델 자체가 바뀌면 §3.1도 갱신. 묶음 상한(롤백 단위)이 실제로 과대 PR을 못 막으면 재설계.
