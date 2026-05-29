---
title: refresh --fix 화이트리스트
created_at: 2026-05-29
summary: v1 명확화: --fix는 index/retired-in-index 인자만 허용. bare --fix와 그 외 인자 모두 exit 2. 의미 판단 필요한 자동수정은 명시 capture/Edit으로.
tags: [wiki, refresh, v1]
relations:
  intents: [INT-2026-05-29-104710-ai-driven-documentation, INT-2026-05-29-104708-atomic-knowledge-records]
---

## 결정

`refresh --fix`는 명시된 화이트리스트 항목만 자동 수정한다. v1에서 허용하는 자동 수정은 `index`와 `retired-in-index`이며, bare `--fix` 또는 목록 밖 항목은 exit 2로 거부한다.

자동 수정이 실제로 파일을 바꾸면 stdout/JSON에 변경 내역을 보고해야 한다. 조용한 mutation은 허용하지 않는다.

## 취지

인덱스 재생성과 retired 문서의 인덱스 제거는 결정 의미를 바꾸지 않는 기계적 작업이다. 반면 broken relation, stale, schema 의미 판단은 어떤 문서를 만들거나 수정해야 할지 사람이 판단해야 한다.

자동화는 안전한 반복 작업에 한정하고, 의미 판단이 필요한 수정은 `capture`, `retire`, 명시적 편집으로 남긴다.

## 배경

초기 설계는 refresh가 여러 무결성 문제를 감지하도록 확장되었다. 감지와 수정의 경계를 명확히 하지 않으면 플러그인이 사용자의 의도 없이 지식 그래프를 바꿀 위험이 있다.

## 고려한 대안

- 모든 refresh issue 자동 수정: 의미 판단이 섞여 반려했다.
- `--fix`만 주면 가능한 수정 전체 수행: 사용자가 무엇을 바꾸는지 예측하기 어려워 반려했다.
- 자동 수정 기능 제거: 인덱스 같은 안전한 반복 작업까지 수동화되어 반려했다.

## 트레이드오프

일부 문제는 사용자가 직접 고쳐야 하므로 자동화 범위가 좁아 보일 수 있다. 대신 위키의 의미론적 정본을 플러그인이 임의로 바꾸지 않는다는 신뢰를 얻는다.

## 재평가 조건

특정 무결성 issue가 의미 판단 없이 항상 같은 방식으로 고쳐진다는 운영 데이터가 쌓이면 화이트리스트 추가를 검토한다.
