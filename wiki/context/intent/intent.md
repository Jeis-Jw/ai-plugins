---
title: Intents — 취지
created_at: 2026-05-29
summary: 상황이 바뀌어도 유지돼야 하는 원칙(record). 결정·반려가 이 취지를 가리킨다.
tags: [meta]
audience: [human, agent]
---

# Intents — 취지

상황이 바뀌어도 유지돼야 하는 원칙(record). 결정·반려가 이 취지를 가리킨다.

## 노트

- [[INT-2026-05-29-104707-token-efficient-context-loading]] — AI는 인덱스→summary→섹션→전문 단계로 본문 전체를 기본 읽지 않는다. 토큰 효율이 위키 시스템의 최우선 설계 제약.
- [[INT-2026-05-29-104708-atomic-knowledge-records]] — 취지·결정·반려·시행착오·관찰은 각각 독립 파일. 한 정보가 번복돼도 다른 맥락을 오염시키지 않고 독립 생명주기를 갖는다.
- [[INT-2026-05-29-104709-filesystem-primary-truth]] — 정본 데이터 모델은 파일시스템(YAML + ripgrep)에 둔다. Obsidian 같은 외부 도구가 정본이 되면 헤드리스·자동화·이식에서 깨진다.
- [[INT-2026-05-29-104710-ai-driven-documentation]] — 사람은 결론·방향만 말하고, 문서 생성·이동·인덱스 갱신·관계 갱신·형식 검증은 에이전트가 한다. 사람의 인지 부담은 결정에만 집중.
- [[INT-2026-05-29-104711-plugin-agent-neutrality]] — Plugin 메커니즘은 특정 AI 도구(Claude/Codex 등) 이름을 박지 않는다. 미래 도구 교체에도 메커니즘이 흔들리지 않게.
- [[INT-2026-05-29-104712-parallel-safe-headless-operation]] — ID·관계·인덱스 메커니즘은 CI/git hook/워크트리/자율 에이전트 등 헤드리스 환경에서 충돌 없이 작동해야 한다.
- [[INT-2026-05-29-104713-single-canonical-current-state]] — Living(ssot/runbook) 정본은 현재 상태 하나여야 한다. 이력은 git과 context 결정들이 별도로 보유한다 — 정본에 시점 분기를 두지 않는다.
- [[INT-2026-05-29-181219-task-decision-execution-traceability]] — 위키의 결정 그래프와 실제 작업(이슈) 실행을 양방향 추적 가능하게 잇는다 — 결정에서 작업으로, 작업에서 근거로.
