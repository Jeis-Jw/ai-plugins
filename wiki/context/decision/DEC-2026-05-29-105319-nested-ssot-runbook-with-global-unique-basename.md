---
title: nested ssot/runbook + basename 전역 유일성 (v1)
created_at: 2026-05-29
summary: v1 시점 결정: ssot/runbook은 하위 폴더 허용. basename은 vault 전역 유일. resolver 단순성 + nested 분할 가능성 양립. v0 평면 디렉토리 supersede.
tags: [wiki, directory, v1]
supersedes: [DEC-2026-05-29-105236-flat-ssot-runbook-directory]
relations:
  intents: [INT-2026-05-29-104713-single-canonical-current-state, INT-2026-05-29-104708-atomic-knowledge-records]
---

## 결정

`ssot`와 `runbook`은 하위 폴더를 허용한다. 다만 문서 참조 resolver가 basename을 정본 ID로 쓰므로, nested 구조에서도 모든 `.md` basename은 vault 전역에서 유일해야 한다.

각 하위 폴더는 자기 인덱스를 가질 수 있고, 상위 인덱스는 하위 문서 summary를 중복 수집하지 않는다.

## 취지

도메인이 커지면 평면 `ssot/` 하나에 모든 현재 정본을 넣는 방식은 파일 목록과 인덱스를 비대하게 만든다. 폴더 분할은 필요하지만, 경로 기반 ID를 도입하면 링크 안정성과 이동 내성이 약해진다.

전역 basename 유일성을 유지하면 nested와 단순 resolver를 동시에 얻을 수 있다.

## 배경

v0 설계는 `ssot`와 `runbook`을 평면 폴더로 보았다. 이후 인증, 결제, 배포처럼 영역이 늘어날 경우 한 폴더의 인덱스가 다시 monolithic 문서처럼 커질 수 있다는 문제가 확인됐다.

다만 `session.md`처럼 서로 다른 폴더에 같은 basename이 생기면 `[[session]]`과 YAML basename 참조가 모호해진다.

## 고려한 대안

- 평면 폴더 유지: 단순하지만 장기 확장성이 약해 반려했다.
- 경로 전체를 ID로 사용: 전역 유일성 문제는 줄지만 이동 비용과 참조 복잡도가 커져 반려했다.
- 폴더별 basename 유일성만 강제: resolver가 모호해져 반려했다.

## 트레이드오프

파일 생성 시 전역 basename 중복 검사가 필요하다. 같은 주제를 다른 영역에서 다룰 때는 slug를 더 구체적으로 지어야 한다.

Nested 구조가 가능해지면서 인덱스 파생 알고리즘도 "폴더 발견은 재귀, 문서 수집은 직속만"으로 명확히 나눠야 한다.

## 재평가 조건

vault 규모가 커져 basename 전역 유일성이 지나치게 제약적이거나, 경로 기반 resolver를 도입해도 링크 안정성을 유지할 수 있는 도구가 생기면 재평가한다.
