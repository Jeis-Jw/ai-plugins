---
title: promotion threshold = plugin spec, 판정 = operating model
created_at: 2026-05-29
summary: v1 신규: plugin은 capture된 문서가 타입별 구조/스키마를 만족하는지만 검증. 의미적 승격 가치 판정(누가 무엇을 언제)은 agent-operating-model.md 영역.
tags: [wiki, plugin, v1]
relations:
  intents: [INT-2026-05-29-104711-plugin-agent-neutrality, INT-2026-05-29-104710-ai-driven-documentation]
  rejected_decisions: [REJ-2026-05-29-105501-promotion-auto-judgment]
---

## 결정

Plugin spec에는 promotion threshold의 추상 기준만 둔다. 정식 record로 승격되는 정보는 장기 재사용 가능성, 구조적 영향, 반복 가능성, 되돌리기 비용, 후속 작업자가 알아야 할 필요성 중 하나 이상을 가져야 한다.

Plugin은 승격 판단 자체를 자동화하지 않는다. `capture`된 문서가 타입별 구조 조건과 스키마를 만족하는지만 검증하며, 언제 무엇을 capture할지는 운영 모델의 영역이다.

## 취지

위키는 아무 대화나 저장하는 메모장이 아니라 장기 운영 기억이다. promotion 기준이 없으면 trivial fix, 일회성 토론, 임시 추측이 record로 쌓여 검색 오염을 만든다.

반대로 plugin이 의미적 승격 여부를 자동 판정하면 false positive/negative가 누적된다. 의미 판단은 사람이나 운영 policy가 담당하고, plugin은 구조 검증에 집중한다.

## 배경

Claude/Codex 운영 논의에서 DEC/TRI/OBS/INT 승격 트리거가 제안되었다. 그러나 "같은 함정을 두 번째 만남" 같은 트리거는 특정 운영 방식에 의존하므로 core plugin spec에 넣기엔 과하다.

최종 분리는 plugin = 추상 기준/구조 조건, operating model = 운영 트리거다.

## 고려한 대안

- promotion trigger를 plugin spec에 모두 포함: agent-specific 운영 규칙이 core mechanism에 침투해 반려했다.
- promotion 자동 판정: 의미 판단 자동화 비용과 오류 위험 때문에 반려했다.
- 기준 미도입: 지식 저장소가 잡음으로 오염될 위험이 있어 반려했다.

## 트레이드오프

Plugin만으로는 어떤 발견을 기록해야 하는지 완전히 결정할 수 없다. 운영자는 `agent-operating-model.md`나 프로젝트 정책을 함께 봐야 한다.

대신 plugin은 agent-neutral하고 재사용 가능하며, 운영 정책 변경에도 schema migration이 필요 없다.

## 재평가 조건

반복 운영 결과 특정 promotion trigger가 agent-neutral하고 모든 프로젝트에 필요한 구조 조건으로 확인되면 plugin spec으로 승격할 수 있다.
