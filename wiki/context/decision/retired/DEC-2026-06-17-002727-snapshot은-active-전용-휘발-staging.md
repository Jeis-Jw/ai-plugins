---
title: snapshot은 active 전용 휘발 staging
created_at: 2026-06-17
summary: snapshot staging을 active 단일 폴더로, slug당 제자리 갱신, 종료는 삭제. 이력은 git과 record가 보유. archived/promoted/append-only/continues 제거.
tags: [wiki, snapshot, lifecycle]
relations:
  intents: [INT-2026-05-29-104713-single-canonical-current-state]
  rejected_decisions: [REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]
  ssot: [wiki-data-model, wiki-lifecycle, wiki-retrieval]
retired_at: 2026-06-18
retired_type: superseded
superseded_by: DEC-2026-06-18-120000-snapshot은-상태-폴더-없는-휘발-staging
---

## 결정

snapshot staging layer를 **active 단일 폴더 휘발 모델**로 한다.

- 상태 폴더는 `snapshot/active` 하나뿐. `archived/`·`promoted/` 제거.
- 기본 `snapshot save`는 **slug당 제자리 갱신** — 같은 slug로 다시 저장하면 기존 active 파일을 덮어쓴다. 새 slug면 새 파일.
- 종료(정리)는 **삭제**. 별도 보존 폴더로 옮기지 않는다.
- `--continues` 체인, `--update` 분기, `promoted` 상태 슬롯, append-only 기본값을 모두 제거한다.
- 정식 지식화는 기존대로 별도 `capture`/Edit으로 record/SSOT에 승격한다.

## 취지

snapshot의 본질은 **세션 컨텍스트 메모장** — 정식 graph 승격 전 대화 맥락을 잠깐 들고 다음 세션에서 이어받는 staging이다. 메모장은 토론당 "현재 상태 하나"면 충분하며, 그 이상의 누적·이력·감사 추적은 staging의 책임이 아니다. Living 정본 원칙([[INT-2026-05-29-104713-single-canonical-current-state]])을 snapshot에도 그대로 적용한다 — 하나의 현재 상태만, 이력은 record가 보유.

## 배경

0.7.0(commit `730db3a`)에 snapshot이 active/archived/promoted 3상태 + append-only 기본 + `--continues` 체인으로 출시됐다. 그러나 이 설계의 근거는 어느 DEC/INT/REJ에도 캡처된 적이 없고, "active만 관리하는 휘발 메모장"이라는 원래 의도와 코드가 어긋난 상태였다(SSOT는 이미 코드를 정본화). 2026-06-17 dogfooding 토론에서 의도 대비 드리프트를 확인하고 의도 쪽으로 되돌리기로 했다.

핵심 관찰: vault는 git 추적 대상이므로 삭제한 스냅샷도 git 히스토리에 남는다 → `archived/`가 제공하려던 복구 보험을 git이 이미 공짜로 제공한다. 따라서 보존 폴더는 잉여다.

## 고려한 대안

- **3상태 누적 보존(반려)**: [[REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]]. 현 0.7.0 구현. 메모장 목적과 어긋나고 git과 중복.
- **archived만 유지, promoted/append/continues 제거(절충, 미채택)**: 삭제가 불안할 때의 soft-delete 보험. 그러나 git이 같은 역할을 하므로 "active만" 의도엔 절반만 부합 — 단순성을 위해 미채택.

## 트레이드오프

- 얻음: 단일 상태 모델로 단순. `active/` 누적·dead 슬롯 제거. 의도-구현 일치. git이 이력/복구 단일 책임.
- 잃음: vault가 git 밖이면 삭제가 비가역. snapshot 자체의 체크포인트 이력을 1급으로 비교·조회하는 기능 상실(=의도된 비범위).
- slug 충돌=덮어쓰기 시맨틱이 새로 필요. 다른 토론은 다른 slug로 분리해야 한다(운영 규약).

## 재평가 조건

- snapshot을 git 없는 vault에서 운용하게 되어 삭제가 진짜 비가역이 되는 경우.
- 한 토론의 체크포인트 진화 이력을 staging 안에서 1급으로 조회·비교해야 하는 요구가 생기는 경우.
- staging→record 자동 promote 계약을 구현하기로 하는 경우(그때 `promoted/` 슬롯 재도입 검토).

