---
title: Monolithic 정의 문서는 정본 모호화를 일으킨다
created_at: 2026-05-29
summary: v0(40KB) + v1(62KB) 두 monolithic 정의 문서가 wiki에 공존했더니 어느 게 현재 정본인지 AI가 추론해야 했다. atomic record 분해 + 단일 ssot 원칙을 위반하면 시스템 자체가 자기 원칙을 어김.
tags: [wiki, architecture, lesson]
verified_at: 2026-05-29
relations:
  decisions: [DEC-2026-05-29-105230-record-living-id-system, DEC-2026-05-29-105231-wiki-type-taxonomy]
---

## 교훈

위키 시스템의 원칙(원자성, 단일 정본)을 위키 자신의 메타 문서에서 어기면 그 위반이 가장 먼저 드러나는 곳이 *위키 자신*이다. 정의 문서도 monolithic 한 파일로 두지 말고, INT/DEC/REJ/TRI 원자 record로 분해해 정본은 ssot 하나로 두자.

## 상황

`wiki/ssot/`에 `plugin_definition_v0.md`(2026-05-22, 40KB, 702줄) + `plugin_definition_v1.md`(2026-05-28, 62KB, 1013줄) 두 monolithic 정의 문서가 공존. AI가 위키 메커니즘을 추론하려면 어느 게 현재 정본인지부터 결정해야 했음.

## 피해야 할 것

- 동일 주제의 정본 문서를 v0/v1/v2처럼 시점 분기로 wiki 안에 공존시키는 것.
- 모든 결정·반려·취지·교훈을 단일 문서에 묶어 한 변경이 전체 문서를 흔드는 것.

## 대안 또는 우회

- 원자 단위(INT/DEC/REJ/TRI/OBS)로 분해 + 단일 ssot 정본.
- 이전 monolithic 문서가 필요하면 wiki 외부의 `backup/` 폴더로 격리 (이 정리 작업의 패턴).

## 현재도 유효한가

유효. 위키 시스템 설계 회귀(또 v2 정의 문서를 ssot에 두려는 충동) 발생 시 즉시 적용. [[DEC-2026-05-29-105230-record-living-id-system]] / [[INT-2026-05-29-104708-atomic-knowledge-records]] / [[INT-2026-05-29-104713-single-canonical-current-state]] 의 운영 사례.

