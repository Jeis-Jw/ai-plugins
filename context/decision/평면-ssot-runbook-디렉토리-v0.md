---
schema: "context-decision/v1"
id: "ctx_ec181350e35e4cc38790e2a0d9011234"
title: "평면 ssot/runbook 디렉토리 (v0)"
summary: "v0 시점 결정: ssot/runbook은 평면 단일 폴더. 주제 slug는 폴더 내 유일. nested 폴더 미허용."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-05-29-105236-flat-ssot-runbook-directory.md"]
tags: ["wiki","directory"]
scope: "ai-plugins/wiki-markdown"
decision_key: "living-document-layout"
revisit_when: ["이 결정은 [[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]]로 superseded되었다. 현재는 nested를 허용하되 basename 전역 유일성을 강제한다."]
---

## 결정

v0 시점 결정: ssot/runbook은 평면 단일 폴더. 주제 slug는 폴더 내 유일. nested 폴더 미허용.

## 취지

초기 구조를 단순하게 유지하려는 결정이었다. 경로가 얕으면 resolver와 인덱스 파생이 쉽고, 사용자가 문서 위치를 고민하지 않아도 된다.

## 반려대안

- 평면 구조 유지: 단순하지만 장기적으로 인덱스와 폴더가 비대해져 v1에서 대체했다.
- 경로 기반 ID 도입: nested를 지원하지만 링크 안정성을 해쳐 반려했다.

## 트레이드오프

- 평면 구조는 초기 학습 비용이 낮다. 대신 문서 수가 늘어나면 탐색 비용과 이름 충돌 회피 비용이 커진다.

## 재평가 조건

- 이 결정은 [[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]]로 superseded되었다. 현재는 nested를 허용하되 basename 전역 유일성을 강제한다.
