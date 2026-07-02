---
title: define은 topology 판단을 제안 게이트에 필수 포함
created_at: 2026-07-02
summary: define이 issue tree를 제안할 때 what(작업 목록)뿐 아니라 how(branch/integration topology)를 필수 판단한다. 확인안에 Topology Decision 섹션 의무화, flat under-structuring 정적 휴리스틱 경고, 조건 충족 시 flat/stacked 2안 비교. vertical slice는 product goal이 하나라는 뜻이지 tree가 flat이어야 한다는 뜻이 아니다 — ownership/path/integration branch가 갈리면 stacked 우선 검토.
tags: [task-github, define, topology, quality]
---

## 결정

`task-github:define`은 issue tree 제안 시 topology 판단을 필수 게이트로 포함한다.

1. 사령관 확인안에 **Topology Decision 섹션 필수** — 선택(flat|stacked), 이유, 병렬 트랙 수, 경로/소유권 분리, cross-track dependency, parent branch 필요 여부. flat 선택 시 사유(단일 surface? 순차? integration branch 무의미?)를 명시한다.
2. **flat under-structuring 정적 휴리스틱** — leaf ≥6, affects_paths 도메인 ≥3, domain prefix 반복, cross-domain blocked_by ≥2, vertical slice 언급+다중 surface 중 2개 이상이면 flat 제안 전 경고하고 stacked 대안을 함께 제시한다. dry-run에도 `flat_maybe_understructured` 경고(+cluster 후보)를 넣는다.
3. **vertical slice ≠ flat** — product goal이 하나라는 뜻이지 tree가 flat이어야 한다는 뜻이 아니다. ownership/affected paths/integration branch가 갈리면 stacked를 우선 검토한다.
4. 채택된 topology 근거는 root issue body의 **Topology Rationale**로 남겨 orchestrate/run/merge 시 복원 가능하게 한다.

## 취지

이슈트리 shape는 정리가 아니라 브랜치 분기 전략이다. agent가 backlog 정리 관성으로 flat을 내면 branch/integration boundary가 루트 하나로 몰리고 병렬 트랙 owner가 불명확해진다. 최종 결정은 사령관이 하지만, plugin은 더 좋은 후보 구조를 제안할 책임이 있다.

## 배경

lightning-pay dogfood에서 Auth/Wallet·Store/QR/Ops로 execution boundary가 갈리는 작업을 agent가 flat 1-depth로 제안했다. stacked·parent·epic 기능은 이미 있었으므로 문제는 기능 부재가 아니라 제안 단계 판단 게이트 부재였다.

## 고려한 대안

- **LLM-judge로 topology 판정**: 반려 — [[DEC-2026-06-12-185228-결정-분해-품질-gate를-플러그인에-추가-정적-룰-v0-먼저]]와 동일하게 정적 룰 v0 먼저.
- **stacked를 기본값으로 강제**: 반려 — 단일 surface/순차/문서 작업엔 flat이 옳다. 게이트는 판단을 요구하는 것이지 답을 고정하는 게 아니다.

## 트레이드오프

- 확인안이 길어지고 define 왕복이 다소 무거워진다 ↔ 잘못된 flat 트리가 비동기 실행(orchestrate)으로 증폭되는 비용이 훨씬 크다.
- 휴리스틱은 오탐 가능 ↔ 경고일 뿐 차단이 아니며, 사령관이 명시했으면 질문 없이 그 기준을 따른다.

## 재평가 조건

- 정적 휴리스틱 오탐/미탐이 dogfood에서 반복되면 조건 가중치 조정 또는 judge 승격 검토
- orchestrate가 topology rationale을 실제로 소비하는 방식이 바뀌면 기록 위치 재검토
