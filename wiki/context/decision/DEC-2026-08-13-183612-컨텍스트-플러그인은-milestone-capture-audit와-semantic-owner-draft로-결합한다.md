---
title: 컨텍스트 플러그인은 milestone capture audit와 semantic owner draft로 결합한다
created_at: 2026-08-13
summary: context-core가 milestone 단위 단일 audit와 승인 UX 및 physical write coordinator를 맡고, semantic owner는 bounded candidate에서 완성된 artifact draft와 mutation plan을 만들어 중복 없이 결합한다.
tags: [context-core, context-decision, capture, routing, approval, plugin-architecture]
search_terms: [one auditor many semantic owners, complete draft, approved digest, storage coordinator]
supersedes: [DEC-2026-08-13-164257-컨텍스트-플러그인은-단일-capture-audit와-semantic-owner로-결합한다]
---

## 결정

context-core를 컨텍스트 생태계의 공통 기반으로 둔다. context-core는 SNAP·OBS, semantic milestone 또는 closeout당 최대 한 번의 capture audit, 설치된 semantic owner의 claim 결과를 받는 deterministic routing, 실제 artifact draft를 포함한 grouped approval, semantic index recall과 유일한 physical write coordinator를 소유한다. context-decision은 bounded candidate만 받아 DEC를 결정·취지·반려대안의 원자적 draft로 만들고 scope·supersede·conflict·revisit와 decision recall을 소유한다. owner는 filesystem을 직접 쓰지 않고 complete draft와 mutation plan을 반환한다. 사용자가 승인한 final preview+plan bundle의 approval digest만 core coordinator가 root lock 아래 적용한다. 사용자 지정 type은 owner 선택을 강제하지만 semantic validation을 우회하지 않으며, 같은 claim을 OBS와 전문 type에 중복 기록하지 않는다.

## 취지

대화 판독을 addon마다 반복하지 않으면서 승인 대상과 실제 저장 내용이 달라지는 문제를 막으려면 발견, 의미 검증, 승인, physical write를 분리해야 한다. auditor는 capability가 요구한 핵심 입력을 candidate에 한 번 담고, owner는 원문 재판독 없이 실제 문서를 완성하며, core coordinator는 승인 digest와 공통 무결성만 검증한다. milestone 단위 audit는 세션 길이와 무관하게 의미 있는 상태 변화만 포착해 토큰과 제안 피로를 줄인다.

## 배경

기존 결정은 세션당 한 번의 audit와 semantic owner 결합을 정했지만, 세션 경계는 실제 의미 변화와 일치하지 않고 승인 시점에 artifact 핵심 내용이 완성되지 않는 여지가 있었다. 또한 addon이 root index나 다른 owner artifact를 직접 쓰면 lock과 lifecycle 원자성 계약이 갈라진다.

## 고려한 대안

1. 기존의 세션당 한 번 audit는 짧은 세션에서 불필요하고 긴 세션에서는 중요한 milestone을 놓쳐 반려한다. 2. 제목과 authority만 승인받은 뒤 owner가 본문을 만드는 방식은 승인되지 않은 취지·반려대안이 기록될 수 있어 반려한다. 3. 각 owner가 자기 파일을 직접 쓰는 방식은 root registration과 OBS에서 DEC로의 cross-owner 전환을 원자적으로 처리하기 어려워 반려한다. 4. core가 addon schema 의미까지 해석하는 방식은 확장할수록 core가 비대해져 반려한다.

## 트레이드오프

owner capability에 draft field와 owner-result envelope이 추가되고 core에 mutation coordinator가 필요하다. complete preview는 제목 목록보다 승인 비용이 크므로 artifact를 짧게 유지하고 32 KiB를 넘으면 후보를 나눠야 한다. core가 physical write의 단일 의존점이 되지만 semantic schema와 판단은 owner에 남는다.

## 재평가 조건

두 번째 실제 addon이 구현될 때 candidate owner_inputs와 mutation plan이 addon 고유 schema를 누출하지 않고 충분한지 검증한다. grouped complete preview가 반복적으로 너무 크거나 사용자 승인 비용을 줄이지 못하면 preview 표현과 batch 크기를 재설계한다. core coordinator가 domain 의미를 해석하기 시작하거나 host별 owner 호출 계약이 성립하지 않으면 경계를 재검토한다.
