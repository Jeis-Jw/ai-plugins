---
title: plugin agent-neutral (CLI/스키마)
created_at: 2026-05-29
summary: v1 명시화: CLI 인자/출력 메시지/frontmatter 필드명/알고리즘 명세에 Claude/Codex 등 agent 이름 없음. agent별 규약은 operating model로 격리.
tags: [wiki, plugin, v1]
relations:
  intents: [INT-2026-05-29-104711-plugin-agent-neutrality]
  rejected_decisions: [REJ-2026-05-29-105459-plugin-spec-with-agent-names]
---

## 결정

위키 플러그인 메커니즘은 agent-neutral하게 유지한다. CLI 인자, 출력 메시지, frontmatter 필드명, 알고리즘 명세에는 Claude/Codex 같은 특정 도구 이름을 박지 않는다.

에이전트별 역할, capture 권한, issue/PR 흐름, 리뷰 정책은 `wiki/ssot/agent-operating-model.md`의 policy 계층으로 격리한다.

## 취지

플러그인은 프로젝트와 agent를 넘어 이동 가능한 mechanism이어야 한다. 특정 agent 이름이 스키마에 들어가면 도구가 바뀔 때 지식 모델까지 흔들린다.

Agent 이름은 운영 정책 설명이나 사례에는 등장할 수 있지만, 데이터 모델과 CLI 계약의 일부가 되면 안 된다.

## 배경

과거 논의에서는 Claude를 장기 기억/리뷰 담당, Codex를 stateless 실행 담당으로 나누는 운영 모델이 있었다. 하지만 이는 GitHub 작업관리와 함께 보류된 운영 정책이지, 위키 플러그인 자체의 필수 메커니즘이 아니다.

따라서 plugin spec은 "누가"가 아니라 "어떤 타입, 어떤 관계, 어떤 검증"을 정의한다.

## 고려한 대안

- plugin spec에 Claude/Codex 역할을 직접 포함: 미래 도구 교체와 다중 agent 운영을 방해해 반려했다.
- agent별 CLI 명령을 제공: 같은 기능을 이름만 바꿔 중복하게 되어 반려했다.
- 운영 정책을 아예 문서화하지 않음: 역할 drift가 생기므로 별도 ssot로 분리했다.

## 트레이드오프

Plugin spec만 읽으면 특정 프로젝트에서 어떤 agent가 어떤 작업을 해야 하는지 알 수 없다. 그 정보는 `agent-operating-model.md`를 추가로 읽어야 한다.

대신 plugin mechanism은 더 작고 안정적이며, 작업/GitHub 운영 정책이 보류되거나 바뀌어도 스키마는 유지된다.

## 재평가 조건

특정 agent 전용 기능이 플러그인 메커니즘 자체에 필수이고 다른 agent로 추상화할 수 없다는 사례가 생기면 별도 adapter 계층을 검토한다. core schema에는 넣지 않는다.
