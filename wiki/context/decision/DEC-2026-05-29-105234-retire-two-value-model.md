---
title: Retire 모델 = deprecated/superseded 2값
created_at: 2026-05-29
summary: 모든 record(OBS 포함)는 deprecated(틀림/무효) 또는 superseded(새 record로 대체) 2값으로 retire. classified 같은 별도 분류 축 미도입.
tags: [wiki, lifecycle, architecture]
relations:
  intents: [INT-2026-05-29-104708-atomic-knowledge-records]
---

## 결정

모든 context record의 retire 사유는 `deprecated` 또는 `superseded` 두 값만 사용한다. `deprecated`는 틀렸거나 무효가 된 경우, `superseded`는 새 active record가 기존 record를 대체한 경우다.

Observation도 같은 2값 모델을 따른다. 분류 완료를 뜻하는 `classified`나 `classified_as` 필드는 도입하지 않는다.

## 취지

retire 모델은 문서가 active 탐색에서 빠지는 이유만 설명하면 된다. lifecycle 축이 많아지면 상태값 해석이 어려워지고, refresh/schema 검증도 복잡해진다.

새 문서로 의미가 이어지는 경우는 `superseded_by`로 충분히 표현할 수 있다. 거짓 알람이나 상황 변화로 더 이상 볼 필요가 없는 경우는 `deprecated`가 맞다.

## 배경

Observation이 추가되면서 "분류 완료"를 별도 retired_type으로 둘지 논의했다. 한 OBS가 TRI/DEC/SSOT 갱신으로 이어질 수 있어 `classified`가 매력적으로 보였지만, 결국 active에서 빠지는 실제 이유는 대체 또는 무효화로 해석 가능했다.

기존 두 값으로 모든 record에 같은 lifecycle을 적용하는 편이 더 단순하고 예측 가능하다.

## 고려한 대안

- `classified`: observation 전용 분류 완료 상태. 의미는 분명하지만 lifecycle 축을 늘려 반려했다.
- `archived`, `resolved` 등 추가 상태: 작업관리 상태와 섞일 위험이 있어 반려했다.
- retired 폴더만 사용하고 YAML 사유 제거: 왜 빠졌는지 알 수 없어 반려했다.

## 트레이드오프

`deprecated`가 "틀림"과 "상황 변화로 무효"를 함께 담기 때문에 세부 의미는 본문이나 후속 record를 읽어야 한다. 대신 스키마와 운영 규칙은 단순해진다.

Observation이 SSOT 갱신만 트리거한 경우에도 primary successor가 되는 OBS/TRI/DEC record를 두어 `superseded`로 연결하는 운영 습관이 필요하다.

## 재평가 조건

운영 중 `deprecated`와 `superseded`로 설명하기 어려운 retire 사례가 반복되고, 그 차이가 검색·검증·자동화에 실제 영향을 주면 상태값 추가를 재검토한다.
