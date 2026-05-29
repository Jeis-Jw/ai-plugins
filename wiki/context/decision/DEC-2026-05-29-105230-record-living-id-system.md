---
title: record/living 이중 ID 체계
created_at: 2026-05-29
summary: Record는 TYPE-YYYY-MM-DD-HHMMSS-slug, living은 slug만 사용. basename이 정본 ID, YAML id 필드 없음.
tags: [wiki, id, architecture]
relations:
  intents: [INT-2026-05-29-104712-parallel-safe-headless-operation, INT-2026-05-29-104708-atomic-knowledge-records]
  rejected_decisions: [REJ-2026-05-29-105454-sequential-numeric-id]
---

## 결정

Record 문서는 `<TYPE>-<YYYY-MM-DD-HHMMSS>-<slug>` 형식의 basename을 정본 ID로 사용한다. Living 문서(`ssot`, `runbook`)는 주제 slug 자체를 basename으로 사용하며, 모든 참조는 확장자를 제외한 basename을 가리킨다.

YAML frontmatter에는 `id` 필드를 두지 않는다. 파일명이 이미 정본 ID이므로 같은 값을 헤더에 복제하면 불일치 원인이 된다.

## 취지

ID 체계는 병렬 작업과 장기 링크 안정성을 동시에 만족해야 한다. timestamp 기반 record ID는 여러 에이전트나 브랜치가 동시에 문서를 만들어도 전역 순번을 조율하지 않아도 되고, basename 참조는 파일 이동(`retired/`)에도 깨지지 않는다.

Living 문서는 "현재 상태 하나"가 정본이므로 순번이 아니라 주제 slug를 유지한다. 이렇게 record와 living의 생명주기 차이를 ID 체계에도 반영한다.

## 배경

초기 대화에서는 `DEC-00005-kakao-login` 같은 5자리 순차 ID도 검토했다. 읽기 쉽고 짧다는 장점은 있었지만, 단일 채번자나 전역 max 스캔이 필요해 병렬 브랜치와 맞지 않았다.

또한 `id`와 `slug`를 frontmatter에 나누어 둘지 검토했지만, 링크와 파일명이 basename 기준으로 고정된다면 헤더의 `id`는 중복 데이터가 된다. 최종 결론은 파일시스템을 ID 저장소로 인정하는 것이다.

## 고려한 대안

- 5자리 순차 번호: 사람이 읽기는 좋지만 병렬 생성, 머지, 재채번 문제로 반려했다.
- YAML `id` 필드 유지: 파일명과 중복되어 drift 위험이 있어 반려했다.
- 논리 ID와 slug 분리: 더 정규화된 모델이지만 실제 링크 대상이 basename이라 실익이 작았다.

## 트레이드오프

timestamp ID는 순차 번호보다 길고 사람이 즉시 외우기는 어렵다. 대신 충돌 가능성이 낮고, 생성 시점이 ID에 드러나며, 병렬 에이전트 운영과 잘 맞는다.

Living basename은 짧지만 vault 전역 유일성이 필요하다. 따라서 nested 폴더를 허용하더라도 같은 basename 중복은 `refresh duplicate-basename`으로 막아야 한다.

## 재평가 조건

외부 데이터베이스나 별도 인덱서가 정본 ID를 관리하게 되어 파일명과 논리 ID를 분리해야 하는 요구가 생기면 재평가한다. 그 전까지는 basename 단일 정본 원칙을 유지한다.
