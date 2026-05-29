---
title: ssot 평면 폴더는 도메인 성장 시 비대화
created_at: 2026-05-29
summary: v0에서 ssot/는 평면 단일 폴더. 도메인이 커지면 한 폴더에 수십 개 파일이 쌓이고 인덱스도 비대화. v1은 nested 허용 + basename 전역 유일성 + 폴더 단위 독립 인덱스로 대응.
tags: [wiki, directory, lesson]
verified_at: 2026-05-29
relations:
  decisions: [DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]
---

## 교훈

ssot 폴더의 비대화는 일정 임계점 이후 인덱스 토큰 비용과 검색 효율을 모두 깎는다. 처음부터 nested를 권하지는 않지만(YAGNI), 비대화 신호가 보이면 *분할*이 옳고 *상위 인덱스가 하위 문서를 재귀 수집*하는 것은 옳지 않다.

## 상황

v0 §6 디렉토리 구조는 ssot/runbook을 평면 단일 폴더로만 정의. 도메인이 여러 영역(auth, payment, billing, search, ...)으로 갈라지면 한 폴더에 수십 개 파일 + 인덱스도 비대화.

## 피해야 할 것

- ssot 폴더를 비대해질 때까지 방치.
- 비대화 해소를 위해 상위 인덱스가 하위 폴더 문서까지 재귀 수집하게 만드는 것 (중복 노출 + 부모 인덱스 비대화의 악순환).

## 대안 또는 우회

- nested ssot/runbook 허용 + basename **vault 전역 유일성** ([[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]]).
- 인덱스는 **폴더 단위 독립** — 재귀=폴더 발견, 비재귀=노트 수집 ([[DEC-2026-05-29-105321-folder-independent-index-derivation]]).
- 영역 분할 시점은 운영자 판단(이 plugin은 강제하지 않음).

## 현재도 유효한가

유효. ssot/auth 또는 ssot/payment 같은 분할이 필요해질 때마다 이 교훈이 적용된다.

