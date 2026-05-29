---
title: observation 타입 신설
created_at: 2026-05-29
summary: v1 신규: 실행 중 발견했지만 아직 결정/교훈/정본 갱신으로 분류하기 이른 사실을 안전하게 보존하는 임시 record. 다른 record와 같은 2값 supersede 모델.
tags: [wiki, taxonomy, v1]
relations:
  intents: [INT-2026-05-29-104708-atomic-knowledge-records, INT-2026-05-29-104707-token-efficient-context-loading]
  rejected_decisions: [REJ-2026-05-29-105500-obs-classified-retired-type]
---

## 결정

`context/observation/` record 타입을 신설한다. ID는 `OBS-<YYYY-MM-DD-HHMMSS>-<slug>` 형식이고, 허용 relations는 `ssot`, `runbook`, `decisions`, `tasks`다.

Observation 본문은 `## 관찰`, `## 근거`, `## 영향`, `## 현재 처리`, `## 후속 분류 조건` 섹션을 가진다. retire 모델은 다른 record와 동일하게 `deprecated` 또는 `superseded`만 사용한다.

## 취지

실행 중에는 중요해 보이지만 아직 결정, 교훈, 정본 갱신으로 분류하기 이른 사실이 자주 발견된다. 이를 바로 decision이나 trial_error로 만들면 과잉 기록이 되고, 기록하지 않으면 후속 작업자가 같은 맥락을 잃는다.

Observation은 분류 전 임시 record로서 발견을 보존하고, 나중에 TRI/DEC/SSOT 갱신 등으로 승격되면 supersede된다.

## 배경

Codex 같은 실행 agent는 구현 중 coupling, flaky test, 문서 불일치, 운영 절차 리스크를 발견할 수 있다. 그러나 이 발견이 항상 "교훈"이나 "결정"은 아니다.

초기 타입 체계에는 이 중간 상태가 없어, 작업 범위 밖 발견을 안전하게 남기는 통로가 부족했다.

## 고려한 대안

- trial_error로 흡수: trial_error는 명시적 `## 교훈`이 필요하므로 아직 패턴화되지 않은 관찰과 맞지 않는다.
- decision 후보로 바로 기록: 결정 권한과 의미가 과해져 반려했다.
- OBS 전용 `classified` retire 상태: lifecycle 축을 늘려 반려했다.

## 트레이드오프

Observation이 쌓이면 미분류 backlog가 될 수 있다. 이를 줄이기 위해 `## 후속 분류 조건`을 capture 시점에 적고, 후속 TRI/DEC/OBS/SSOT 갱신이 생기면 `superseded`로 retire한다.

Observation은 intent/rejected_decision을 직접 가리키지 않는다. 추상 원칙이나 반려 대안과의 연결은 후속 decision/trial_error가 담당한다.

## 재평가 조건

Observation이 장기 backlog로 남아 실제 검색 오염원이 되거나, 별도 aging 규칙이 필요해지면 운영 모델 또는 refresh 검사에서 관리 방식을 추가한다.
