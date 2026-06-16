---
title: rationale는 메인 직접 커밋·코드 PR은 ID 참조; define이 rationale 커밋과 dirty-vault 경고 담당
created_at: 2026-06-17
summary: 결정/반려 등 근거 레코드는 메인 트리에 직접 커밋(코드 PR과 분리, PR은 DEC ID 참조). 엉킴 방지를 위해 define이 자기 rationale을 커밋하고 define/start가 dirty wiki vault를 경고한다.
tags: [wiki, task-github, workflow, worktree]
supersedes: [OBS-2026-06-17-011222-결정-우선-플로우에서-wiki-결정-레코드가-워크트리-코드-pr과-분리되고-공유-인덱스가-미커밋-레코드와-엉킴]
relations:
  ssot: [wiki-four-layer-separation]
  tasks: [Jeis-Jw/ai-plugins#1]
---

## 결정

- **rationale 레코드(decision/rejected 등)는 메인 트리에 직접 커밋**한다. 코드 변경은 PR 브랜치로 가고, PR 본문·커밋 메시지·SSOT가 `DEC` ID로 참조한다. 결정과 코드가 다른 커밋·위치에 있는 것을 **정상으로 수용**한다(4계층 분리: [[wiki-four-layer-separation]]).
- 기계적 엉킴(공유 context 인덱스 + 잔여 미커밋 레코드) 방지:
  - `define`이 생성한 task 노드 + 근거 `DEC`/`REJ`를 **그 자리에서 메인에 커밋**한다(원자적 rationale 커밋).
  - `define`/`start`는 시작 시 **dirty wiki vault**(미커밋 context 레코드)를 감지하면 경고한다.
- **최소 적용분**: 자동 커밋이 부담되면 dirty-vault 경고만으로도 채택 가능(엉킴의 주원인인 잔여 레코드를 막는다).

## 취지

결정은 repo 지식으로 코드 PR보다 오래 살고, 코드 리뷰 브랜치에 인질로 잡히거나 브랜치 폐기 시 유실되면 안 된다. rationale을 캡처 즉시 메인에 커밋하면 각 작업의 근거가 원자적·독립적으로 남고, 워크트리 생성 전 메인이 깨끗해 작업별 커밋이 자명해진다.

## 배경

[[OBS-2026-06-17-011222-결정-우선-플로우에서-wiki-결정-레코드가-워크트리-코드-pr과-분리되고-공유-인덱스가-미커밋-레코드와-엉킴]]에서 관찰(이 결정으로 superseded). snapshot 리팩터 [Jeis-Jw/ai-plugins#1](https://github.com/Jeis-Jw/ai-plugins/issues/1) 때 DEC/REJ를 메인에 캡처 → `start`가 워크트리 생성 → 코드(PR #2)와 rationale(메인)이 분리됐고, 메인의 잔여 미커밋 2026-06-12 배치가 공유 인덱스에서 엉켜 작업별 분리 커밋을 막았다. 통증의 주원인은 구조적 분리(A)가 아니라 **잔여 엉킴(B)**이었다.

## 고려한 대안

- **결정을 워크트리/PR에 포함**(반려): PR 자기완결은 얻으나 ① 결정이 머지 전까지 브랜치에만 존재 → 폐기 시 유실, ② 코드 리뷰에 게이트(결정은 코드가 아님), ③ 워크트리 vault와 메인 vault 이중화 → 동기화 고통, ④ 인과 역전(`DEC`가 작업 생성을 정당화해야 하는데 작업 후 캡처).
- **수동 위생만**(부분 채택): 매 시작 전 수동 정리. `define` 자동화/경고가 더 견고하므로 경고를 기본 메커니즘으로 둔다.

## 트레이드오프

- 얻음: rationale 원자적 보존, dangling 링크 제거, 작업별 깔끔한 커밋, 결정의 수명·독립성.
- 비용: `define`에 git 커밋 책임 추가(스킬 복잡도↑). 자동 커밋은 미완 캡처를 커밋할 위험 → dirty-vault 경고가 완충.
- 포기: PR 자기완결성(코드+근거 한 단위) → `DEC` ID 참조로 대체.

## 재평가 조건

- `define` 자동 커밋이 미완 캡처를 커밋하는 사고가 잦으면 → 경고-only로 후퇴.
- 팀/다중 에이전트 프로파일로 가서 메인 직접 커밋이 충돌을 일으키면 → rationale도 브랜치 경유로 재고.

