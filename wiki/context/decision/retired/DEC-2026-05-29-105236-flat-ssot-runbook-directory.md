---
title: 평면 ssot/runbook 디렉토리 (v0)
created_at: 2026-05-29
summary: v0 시점 결정: ssot/runbook은 평면 단일 폴더. 주제 slug는 폴더 내 유일. nested 폴더 미허용.
tags: [wiki, directory, v0]
relations:
  intents: [INT-2026-05-29-104713-single-canonical-current-state, INT-2026-05-29-104708-atomic-knowledge-records]
retired_at: 2026-05-29
retired_type: superseded
superseded_by: DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename
---

## 결정

v0에서는 `ssot`와 `runbook`을 평면 단일 폴더로 유지했다. 각 living 문서의 basename은 해당 폴더 안에서만 충돌하지 않으면 된다는 전제였다.

## 취지

초기 구조를 단순하게 유지하려는 결정이었다. 경로가 얕으면 resolver와 인덱스 파생이 쉽고, 사용자가 문서 위치를 고민하지 않아도 된다.

## 배경

초기 위키 규모에서는 ssot/runbook 문서가 많지 않았고, 도메인별 하위 폴더를 미리 설계하는 것은 YAGNI로 보였다.

그러나 위키 플러그인 자체의 ssot가 커지면서 domain별 분할 필요가 생겼고, 평면 구조는 빠르게 비대해질 수 있음이 드러났다.

## 고려한 대안

- 평면 구조 유지: 단순하지만 장기적으로 인덱스와 폴더가 비대해져 v1에서 대체했다.
- 경로 기반 ID 도입: nested를 지원하지만 링크 안정성을 해쳐 반려했다.

## 트레이드오프

평면 구조는 초기 학습 비용이 낮다. 대신 문서 수가 늘어나면 탐색 비용과 이름 충돌 회피 비용이 커진다.

## 재평가 조건

이 결정은 [[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]]로 superseded되었다. 현재는 nested를 허용하되 basename 전역 유일성을 강제한다.
