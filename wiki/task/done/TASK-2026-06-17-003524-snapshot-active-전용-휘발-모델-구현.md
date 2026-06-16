---
title: snapshot active 전용 휘발 모델 구현
created_at: 2026-06-17
summary: DEC-2026-06-17-002727 구현 — snapshot을 active 단일 폴더 휘발 모델로 리팩터(3상태/append/continues 제거).
tags: [wiki, snapshot, lifecycle]
relations:
  intents: [INT-2026-05-29-104713-single-canonical-current-state]
  decisions: [DEC-2026-06-17-002727-snapshot은-active-전용-휘발-staging]
  tasks: [Jeis-Jw/ai-plugins#1]
---

## 개요

snapshot staging layer를 active 단일 폴더 휘발 모델로 리팩터한다. GitHub 이슈 [Jeis-Jw/ai-plugins#1](https://github.com/Jeis-Jw/ai-plugins/issues/1)이 실제 작업을 소유한다.

## 근거

[[DEC-2026-06-17-002727-snapshot은-active-전용-휘발-staging]]의 구현 단위. snapshot은 세션 컨텍스트 메모장이므로 토론당 현재 상태 하나만 들고, 이력·보존은 git과 record가 담당한다([[INT-2026-05-29-104713-single-canonical-current-state]]). 0.7.0의 3상태 누적 모델([[REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]])을 의도대로 되돌린다.

## 범위와 완료 기준

- `wiki_cli.py`: `SNAPSHOT_STATES=("active",)`, active 전용 `ensure_snapshot_tree`, `save` 기본 slug 제자리 갱신(basename `SNAP-<slug>`), `--update`/`--continues` 제거, `archive`→`discard`(삭제), `list`/`search`/`iter_snapshot_paths`의 archived/promoted 분기 제거.
- SSOT 3개(`wiki-data-model`/`wiki-lifecycle`/`wiki-retrieval`) snapshot 섹션 갱신.
- 문서(`SKILL.md`/`references/wiki-protocol.md`) + 테스트(`test_wiki_cli.py`) 동기화.
- plugin 0.7.1 → 0.8.0(breaking), `refresh --strict` 통과.
- 완료 = 이슈 #1 close + PR merge.

