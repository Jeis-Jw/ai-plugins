---
title: 컨텍스트 플러그인 정의 (영역 인덱스)
created_at: 2026-08-13
summary: context-core와 context-decision의 구현 정본 영역으로 공통 저장·semantic index, artifact별 lifecycle, 단일 capture audit와 recall, v1 구현·검증 계약을 연결한다.
tags: [context-core, context-decision, plugin, architecture, ssot]
verified_at: 2026-08-13
audience: [human, agent]
affects_paths: [plugins/context-core/**, plugins/context-decision/**]
---

# 컨텍스트 플러그인 정의

이 영역은 기존 `wiki-markdown`을 그대로 분리하는 설계가 아니라, 대화와 작업에서 생긴 공유 맥락을 가볍게 보존하는 새 플러그인군의 구현 계약이다. 기존 플러그인은 동작·실패 사례를 확인하는 참고 구현이며 새 계약의 하위 호환 대상은 아니다.

현재 상태는 **설계 확정, 구현 전**이다. 문서의 `MUST`는 v1 acceptance를 구성하고 `SHOULD`는 특별한 반대 근거가 없으면 구현한다. `MAY`는 v1 이후 선택 사항이다.

## 제품 구조

| 구성요소 | 사용자 가치 | 소유 범위 |
|---|---|---|
| [[context-core-plugin]] | session handoff와 비권위 발견 보존, 통합 검색 | SNAP, OBS, root catalog, 공통 recall, capture audit·approval UX, 유일한 physical write coordinator |
| [[context-decision-plugin]] | 프로젝트·조직의 결정 연속성 | DEC의 결정·취지·반려대안, scope, conflict, supersede, revisit, decision draft/plan과 recall |
| 향후 semantic owner | 검증된 별도 문제 | 자기 artifact schema·권위·lifecycle·전용 recall만 소유 |

공개 제품의 전면 메시지는 `context-decision`의 결정 연속성이다. `context-core`는 독립 가치가 있는 가벼운 기반이지만 범용 context universe나 addon framework를 v1 마케팅 전면에 내세우지 않는다.

## 공통 불변식

1. Markdown 문서가 정본이고 index는 언제든 재생성 가능한 projection이다.
2. 폴더와 문서 `schema`가 artifact 의미를 정한다. 파일명은 정체성이나 lifecycle을 결정하지 않는다.
3. 파일명에는 `SNAP-`, `OBS-`, `DEC-`, timestamp를 강제하지 않는다.
4. 관계와 lifecycle edge는 immutable internal ID를 사용한다.
5. 한 semantic claim에는 primary owner가 하나다. 서로 다른 의미의 OBS·DEC·TASK는 관계로 공존할 수 있다.
6. audit는 후보만 만들며 명시적 요청 또는 grouped proposal 승인 전에는 durable write를 하지 않는다.
7. addon은 원문 대화를 다시 읽지 않고 auditor가 capability에 맞춰 만든 bounded candidate만 받는다.
8. semantic owner는 complete artifact draft·effect·proposed plan을 만들고, context-core가 final preview+plan bundle로 봉인한다. coordinator만 final approval digest를 검증해 physical write한다.
9. core는 addon의 schema·lifecycle·domain recall 의미를 알지 않는다. 공통 envelope와 owner가 선언한 plan precondition만 검증한다.
10. 기본 검색은 semantic index에서 후보를 좁힌 뒤 선택한 문서 또는 section만 읽는다.
11. Obsidian은 호환되는 view일 뿐 runtime dependency가 아니다.

## 런타임 지도

```text
대화·작업
   │ semantic milestone 또는 closeout당 최대 1회
   ▼
context-core capture audit
   │ capability-aware bounded ephemeral candidates
   ├─ explicit type
   ├─ installed semantic owner claim
   ├─ reusable evidence → OBS fallback
   └─ handoff request → SNAP
   │
   ▼ owners: claim + complete artifact draft/mutation plan
context-core route
   │ one grouped preview: content + lifecycle + digest
   ▼
사용자 승인
   │ approved final bundle digest
   ▼
context-core storage coordinator
   └─ SNAP / OBS / DEC document + semantic index transaction
```

## 세부 계약

| 문서 | 정본 범위 |
|---|---|
| [[context-storage-retrieval]] | 디렉터리, 자유 파일명, immutable ID, `*.index.md`, index-first recall, 원자성·drift |
| [[context-artifact-lifecycle]] | SNAP·OBS·DEC의 mutation과 상태 전이, freshness, cross-artifact 전이 |
| [[context-capture-routing]] | audit 시점, candidate·owner 계약, routing·approval·dedupe·token budget |
| [[context-v1-implementation]] | source layout, CLI surface, 단계별 구현 순서, acceptance matrix와 release gate |

## 결정 anchor

- [[DEC-2026-08-13-183612-컨텍스트-플러그인은-milestone-capture-audit와-semantic-owner-draft로-결합한다]] — 기존 세션 단위 결정을 supersede한 현재 architecture 결정
- [[DEC-2026-08-13-180256-컨텍스트-저장소는-semantic-index와-파일명-독립-id를-사용한다]]
- [[DEC-2026-08-13-180257-snap-obs-dec는-각-의미에-맞는-독립-lifecycle을-갖는다]]
- [[DEC-2026-08-13-180535-capture-audit는-milestone-단위-단일-판독과-승인형-write를-지킨다]]

## 비목표

- vector database, embedding, graph database
- 범용 ontology와 임의 plugin registry framework
- transcript/session activity ledger
- 승인 없는 자동 capture 또는 자동 promotion
- 기존 `wiki-markdown` vault의 자동 migration
- PCMS의 조직 권한·승인 queue·cross-project control plane

## 계약 진화

공통 envelope와 index 문법은 `context-common/v1`, candidate는 `context-capture-candidate/v1`로 versioning한다. v1 필드 추가는 reader가 모르는 필드를 무시할 수 있을 때만 호환이다. 필드 의미 변경, ID/ref 형식 변경, generated block 문법 변경은 새 major schema가 필요하다.

두 번째 실제 addon이 구현되기 전에는 generic SDK를 추출하지 않는다. 그 시점에 현재 decision owner와 새 owner의 공통 부분만 공통 계약으로 승격한다.

## 노트

- [[context-artifact-lifecycle]] — SNAP은 현재 handoff staging으로 제자리 갱신 후 discard하고, OBS와 DEC는 의미 불변 record로서 domain별 retire reason과 supersede edge를 갖는 v1 상태 전이 계약.
- [[context-capture-routing]] — 현재 대화를 milestone당 한 번 감사해 bounded ephemeral candidate를 만들고 설치된 semantic owner로 중복 없이 routing한 뒤 grouped approval 후에만 기록하는 provider-neutral v1 계약.
- [[context-storage-retrieval]] — 자유로운 Markdown 파일명과 immutable ID를 분리하고 context.index.md 및 영역별 semantic index를 문서에서 파생해 index-first·document-authoritative recall을 수행하는 v1 계약.
- [[context-v1-implementation]] — 구현 순서, source 단위, CLI·fixture·통합 테스트, token/I-O 계측, host packaging과 공개 release gate를 정의한 context plugin v1 실행 청사진.
