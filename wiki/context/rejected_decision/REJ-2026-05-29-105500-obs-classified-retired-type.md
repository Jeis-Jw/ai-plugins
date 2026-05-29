---
title: OBS 전용 classified retired_type + classified_as 필드
created_at: 2026-05-29
summary: Observation 분류 완료 상태를 위한 별도 retired_type(classified) + classified_as 필드 도입 안. lifecycle 축이 무효/대체에서 분류완료로 부풀어남. 2값 모델 유지로 반려.
tags: [wiki, observation, lifecycle, rejected]
---

## 대안

Observation이 후속 분석을 통해 TRI/DEC/SSOT 갱신 등으로 분류 완료되었을 때 `retired_type: classified`와 `classified_as` 필드를 사용하는 방식이다. 한 OBS가 여러 후속 문서로 이어질 수 있다는 점을 명시하려는 모델이다.

## 반려 사유

분류 완료는 의미상 매력적이지만, retire lifecycle의 축을 "무효/대체"에서 "분류 완료"까지 넓힌다. 대부분의 경우 후속 record가 생기면 `superseded`, 거짓 알람이나 상황 변화로 의미가 없어지면 `deprecated`로 충분하다.

상태값을 늘리면 schema, refresh, retire 명령, 문서 해석이 모두 복잡해진다. v1에서는 모든 record 공통 2값 모델을 유지한다.

## 이 대안의 취지

Observation은 분류 전 임시 record라는 성격이 강하므로, "분류되었다"는 상태를 별도 값으로 표현하고 싶었다. 특히 TRI와 SSOT 갱신 양쪽으로 이어지는 경우를 명시하기 좋다.

## 재고 조건

운영 중 observation retire 사유가 `deprecated`/`superseded`로 반복적으로 오해되고, 분류 완료 상태가 검색이나 검증에서 실제로 필요해지면 observation 전용 상태 확장을 재검토한다.
