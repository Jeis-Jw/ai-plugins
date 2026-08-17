---
schema: "context-decision/v1"
id: "ctx_dc73c1a128cc4ea4a719aba6736c82d5"
title: "snapshot은 active 전용 휘발 staging"
summary: "snapshot staging을 active 단일 폴더로, slug당 제자리 갱신, 종료는 삭제. 이력은 git과 record가 보유. archived/promoted/append-only/continues 제거."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-06-17-002727-snapshot은-active-전용-휘발-staging.md"]
tags: ["wiki","snapshot"]
scope: "ai-plugins/wiki-markdown"
decision_key: "wiki-snapshot-storage"
revisit_when: ["snapshot을 git 없는 vault에서 운용하게 되어 삭제가 진짜 비가역이 되는 경우.","한 토론의 체크포인트 진화 이력을 staging 안에서 1급으로 조회·비교해야 하는 요구가 생기는 경우."]
---

## 결정

snapshot staging을 active 단일 폴더로, slug당 제자리 갱신, 종료는 삭제. 이력은 git과 record가 보유. archived/promoted/append-only/continues 제거.

## 취지

snapshot의 본질은 **세션 컨텍스트 메모장** — 정식 graph 승격 전 대화 맥락을 잠깐 들고 다음 세션에서 이어받는 staging이다. 메모장은 토론당 "현재 상태 하나"면 충분하며, 그 이상의 누적·이력·감사 추적은 staging의 책임이 아니다. Living 정본 원칙([[INT-2026-05-29-104713-single-canonical-current-state]])을 snapshot에도 그대로 적용한다 — 하나의 현재 상태만, 이력은 record가 보유.

## 반려대안

- **3상태 누적 보존(반려)**: [[REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]]. 현 0.7.0 구현. 메모장 목적과 어긋나고 git과 중복.
- **archived만 유지, promoted/append/continues 제거(절충, 미채택)**: 삭제가 불안할 때의 soft-delete 보험. 그러나 git이 같은 역할을 하므로 "active만" 의도엔 절반만 부합 — 단순성을 위해 미채택.
- snapshot을 active/archived/promoted 3상태로 보존하고 기본 save를 append-only로 누적하며 --continues 체인을 두는 모델. 단일 active 휘발 모델에 반려.

## 트레이드오프

- 얻음: 단일 상태 모델로 단순. `active/` 누적·dead 슬롯 제거. 의도-구현 일치. git이 이력/복구 단일 책임.
- 잃음: vault가 git 밖이면 삭제가 비가역. snapshot 자체의 체크포인트 이력을 1급으로 비교·조회하는 기능 상실(=의도된 비범위).

## 재평가 조건

- snapshot을 git 없는 vault에서 운용하게 되어 삭제가 진짜 비가역이 되는 경우.
- 한 토론의 체크포인트 진화 이력을 staging 안에서 1급으로 조회·비교해야 하는 요구가 생기는 경우.
