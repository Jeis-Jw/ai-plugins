---
title: living(ssot/runbook)이 relations 작성
created_at: 2026-05-29
summary: ssot/runbook이 자기 frontmatter에 relations를 쓰자는 안. 스키마 검증 복잡화, 허브 헤더 비대화. 늦게 발견된 영향은 새 record가 가리키게 해서 반려.
tags: [wiki, relations, rejected]
---

## 대안

`ssot`나 `runbook` 같은 living 문서도 frontmatter에 `relations`를 작성해, 자신과 관련된 decisions/trial_errors/tasks를 직접 보유하는 방식이다.

## 반려 사유

Living 문서는 현재 상태 정본이어야 한다. 관련 record 목록까지 들고 있으면 헤더가 계속 커지고, 새 decision이 생길 때마다 hub 문서를 함께 수정해야 한다.

관계는 record가 작성하고 허브는 백링크로 파생하는 편이 drift가 적다. 늦게 발견된 영향은 새 observation/trial_error/decision이 해당 living 문서를 가리키면 된다.

## 이 대안의 취지

SSOT 문서를 열었을 때 관련 결정과 시행착오를 바로 볼 수 있게 하려는 목적이다. 사람이 읽는 관점에서는 hub 문서에 모든 주변 맥락이 모여 있으면 편하다.

## 재고 조건

특정 living 문서의 주변 record 탐색 비용이 실제 병목이 되고, 백링크 파생만으로 UX가 부족하다는 운영 데이터가 쌓이면 인덱스나 별도 map 문서를 추가한다. living frontmatter relations는 기본적으로 금지한다.
