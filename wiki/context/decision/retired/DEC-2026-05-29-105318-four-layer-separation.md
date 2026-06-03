---
title: mechanism/policy/agent entry/knowledge 4계층 분리 (v1)
created_at: 2026-05-29
summary: v1 시점 결정: 4계층 분리 = plugin 메커니즘 / agent-operating-model.md 정책 / CLAUDE.md·AGENTS.md agent entry / wiki/* knowledge. v0 3계층 분리를 supersede.
tags: [wiki, layering, v1]
supersedes: [DEC-2026-05-29-105235-three-layer-mechanism-policy-knowledge]
relations:
  intents: [INT-2026-05-29-104711-plugin-agent-neutrality, INT-2026-05-29-104708-atomic-knowledge-records]
retired_at: 2026-06-03
retired_type: superseded
superseded_by: DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다
---

## 결정

위키 시스템을 mechanism, policy, agent entry, knowledge 네 계층으로 분리한다. Mechanism은 플러그인과 그 스키마/CLI 규약, policy는 `wiki/ssot/agent-operating-model.md`, agent entry는 `CLAUDE.md`/`AGENTS.md` 같은 짧은 포인터, knowledge는 실제 `wiki/*` 기록이다.

이 결정은 v0의 "plugin rules / CLAUDE.md 정책 / wiki 지식" 3계층 모델을 대체한다. `CLAUDE.md`에 긴 운영 정책을 직접 두지 않고, 정책 정본은 wiki 안의 ssot로 둔다.

## 취지

변경 빈도가 다른 자산을 같은 파일에 묶으면 플러그인 메커니즘이 운영 정책 변화에 함께 흔들린다. 계층을 나누면 플러그인은 agent-neutral하게 이동하고, 프로젝트별 운영 정책은 별도로 진화할 수 있다.

운영 모델 자체도 위키 안의 living ssot로 두면 이 위키의 검증·갱신·추적 규칙을 dogfooding할 수 있다.

## 배경

과거 대화에서는 Claude/Codex/GitHub 역할 분리를 상세히 논의했다. 이후 이 내용이 위키 플러그인 메커니즘에 들어가면 특정 agent 이름과 GitHub 운영 방식이 스키마에 박히는 문제가 드러났다.

따라서 작업/GitHub 운영은 별도 policy 계층으로 보류·분리하고, plugin-definition은 타입·관계·조회·검증 메커니즘에 집중한다.

## 고려한 대안

- v0 3계층 유지: `CLAUDE.md`가 정책 정본이 되어 변경 빈도와 ownership이 섞여 반려했다.
- plugin spec에 Claude/Codex/GitHub 규칙 포함: agent-neutral 원칙을 깨서 반려했다.
- 운영 정책을 문서화하지 않고 각 agent 설정에 분산: drift와 중복이 커져 반려했다.

## 트레이드오프

계층이 늘어나 처음 읽는 사람에게 구조가 복잡해 보일 수 있다. 대신 각 문서의 책임이 선명해지고, plugin 메커니즘과 프로젝트 운영 정책을 독립적으로 갱신할 수 있다.

`agent-operating-model.md`는 물리적으로 `wiki/*` 안에 있으므로 knowledge와 policy가 위치상 겹친다. 문서에서는 "물리 위치는 같지만 역할이 다르다"는 점을 명시한다.

## 재평가 조건

단일 agent/단일 프로젝트만 영구적으로 사용해 운영 정책 분리가 오히려 부담이라는 운영 데이터가 쌓이면 단순화를 검토할 수 있다. 여러 agent나 GitHub 외 작업 시스템을 병행할수록 이 분리는 유지해야 한다.
