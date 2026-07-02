---
title: define topology 제안 품질 개선
created_at: 2026-07-02
summary: define이 issue tree 제안 시 flat로 관성 제안하는 문제 해소 — topology 판단 게이트 필수화, flat under-structuring 경고 휴리스틱, stacked/container 대안 자동 제시 (lightning-pay handoff 기반)
tags: [task-github, define, topology, quality]
relations:
  decisions: [DEC-2026-06-12-185228-결정-분해-품질-gate를-플러그인에-추가-정적-룰-v0-먼저, DEC-2026-06-03-155419-define-batch-helper-and-wiki-relate, DEC-2026-07-02-190102-define은-topology-판단을-제안-게이트에-필수-포함]
  tasks: [Jeis-Jw/ai-plugins#31]
---

## 개요

lightning-pay에서 "현재 구현 기준 추가 개발 issue tree 생성" 요청 시 agent가 execution boundary(Auth/Wallet/QR/Ops)가 갈리는 작업을 flat 1-depth로 관성 제안했다. define 문서에 topology=stacked·parent·epic 개념은 이미 있으나 **제안 단계의 topology 판단 게이트가 약한 것**이 문제다. define이 "무엇을 할지"뿐 아니라 "어떤 branch/integration topology로 실행할지"를 제안하게 한다.

## 근거

- [[DEC-2026-06-12-185228-결정-분해-품질-gate를-플러그인에-추가-정적-룰-v0-먼저]] — 품질 gate는 정적 룰 먼저; 이번 flat under-structuring 휴리스틱은 그 연장선
- [[DEC-2026-06-03-155419-define-batch-helper-and-wiki-relate]] — 트리 생성 정본은 batch helper; dry-run 경고 추가 위치가 create_issue_tree.py인 이유
- lightning-pay dogfood handoff — flat 관성 제안의 실사례

## 범위와 완료 기준

영향 경로: `plugins/task-github/skills/define/**`, `plugins/task-github/tests/**` (+필요 시 `rules/quality-gates.md`)

1. SKILL.md 확인안에 Topology Decision 섹션 필수화 + flat 선택 사유 요구
2. flat under-structuring 경고 휴리스틱 문서화 (조건 2개 이상 충족 시 경고)
3. 조건 충족 시 flat/stacked 2안 비교 제시 규칙
4. "vertical slice ≠ flat" 오해 방지 규칙 명시
5. container/epic 승격/비승격 기준 예시 구체화
6. create_issue_tree.py: topology=flat + path cluster 다수 감지 시 flat_maybe_understructured 경고 (suggested_epics 포함)
7. 확인 질문 개선 + root body Topology Rationale 기록 규칙

검증: `python3 -m pytest plugins/task-github/tests/ -q` green + dry-run 경고 케이스 테스트
