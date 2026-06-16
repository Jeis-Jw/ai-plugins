---
title: 다중값 관계 플래그 누적은 action=append + 공유 정규화로 통일
created_at: 2026-06-17
summary: argparse 기본 store는 반복 다중값 플래그를 조용히 last-wins 드롭한다. 교훈: 모든 list형 관계 인자를 action=append + 콤마 split·flatten·strip·순서보존 dedup 공유 헬퍼로 통일하고, 반복·콤마·혼합·중복 4형 회귀 테스트로 고정.
tags: [plugin, quality, cli]
affects_paths: [plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py]
supersedes: [OBS-2026-06-12-190117-wiki-cli-다중값-플래그-반복-시-조용히-마지막만-남김]
relations:
  decisions: [DEC-2026-06-03-155419-define-batch-helper-and-wiki-relate]
  tasks: [Jeis-Jw/ai-plugins#3]
---

## 교훈

다중값(반복 가능) 관계 플래그는 argparse 기본 `store`를 쓰지 말고 **`action="append"` + 공유 정규화 헬퍼**(콤마 split → flatten → strip → 빈값 제거 → 순서보존 dedup)로 통일한다. 반복·콤마·혼합·중복 4형을 모두 받아 같은 set을 내고 **조용한 드롭을 0으로** 만든다. 모든 list형 관계 인자(`--intents`/`--decisions`/`--ssot`/`--rejected`/`--tasks`/`--add-*` 등)에 일괄 적용한다.

## 상황

`wiki_cli`에서 `--intents a --intents b`처럼 다중값 플래그를 반복 지정하면 argparse `store`의 last-wins로 앞 값이 에러 없이(exit 0) 드롭됐다([[OBS-2026-06-12-190117-wiki-cli-다중값-플래그-반복-시-조용히-마지막만-남김]]). 콤마형 `a,b`만 정상이었다. 관계 링크의 조용한 누락은 결정 그래프 무결성을 손상하고 "예외 없는 결정성" 원칙과 충돌한다.

## 피해야 할 것

- 다중값 플래그에 argparse 기본 `store` 사용(반복 시 silent last-wins).
- 정규화 로직을 플래그별로 중복 구현 — 콤마형만 우연히 동작하는 비대칭.
- 정상 경로(콤마형)만 테스트하고 반복형을 격리 검증하지 않기 — 부분 회귀가 샌다.

## 대안 또는 우회

`parse_csv` 단일 공유 헬퍼로 수렴: `action="append"`로 raw 리스트 수집 → 각 값 콤마 split → flatten → strip → 빈값 제거 → 순서보존 dedup. 스칼라 인자(`--title`/`--summary`/`--slug` 등)는 비대상으로 명확히 구분. 반복·콤마·혼합·중복-멱등 4형 회귀 테스트로 고정하고, last-wins 재주입 시 FAIL하는지로 load-bearing 검증.

## 현재도 유효한가

유효. 수정은 `cf3cd1d`에 반영됐고, 4형 회귀 테스트가 #3(PR #7)에서 추가돼 회귀를 고정한다. 새 다중값 관계 플래그를 추가할 때 동일 패턴(append + 공유 정규화 + 4형 테스트)을 적용한다.

