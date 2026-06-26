---
title: session-review complete 단일 커밋 정리
created_at: 2026-06-26
summary: session-review complete가 squash merge와 snapshot discard를 한 커밋으로 처리하도록 개선해 main history noise를 줄인다.
tags: [session-review, workflow, complete, cleanup]
relations:
  tasks: [Jeis-Jw/ai-plugins#30]
---

## 개요

session-review:complete는 현재 approved review branch를 squash merge한 뒤 snapshot-discard를 별도 커밋으로 남긴다. snapshot 삭제만 있는 커밋은 장기 history에서 noise가 크므로, complete 단계에서 squash merge 결과와 snapshot discard를 하나의 complete 커밋에 포함하는 흐름으로 바꾼다.

## 근거

이번 task-github v0.8.0 self-review complete에서 review: complete 커밋 뒤 review: discard handshake 커밋이 별도로 생겼다. discard 커밋의 실질 변경은 snapshot 삭제뿐이므로, 완료된 리뷰의 요약은 complete 커밋 메시지에 남기고 snapshot 파일은 최종 tree에 남기지 않는 편이 더 간결하다.

## 범위와 완료 기준

범위: plugins/session-review/**의 complete skill/CLI 동작과 관련 테스트/문서. 완료 기준: approved complete 흐름이 squash merge와 snapshot discard를 단일 커밋으로 만들거나 동등한 single-commit 옵션을 제공한다; complete 커밋 메시지에는 snapshot slug, 승인 round, resolved blocking 요약이 남는다; snapshot은 최종 tree에서 제거된다; 기존 review/request/address 흐름은 깨지지 않는다.
