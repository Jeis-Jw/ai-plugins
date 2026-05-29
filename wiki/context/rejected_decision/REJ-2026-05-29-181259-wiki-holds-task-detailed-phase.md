---
title: 위키가 작업 상세 단계를 보유
created_at: 2026-05-29
summary: 위키 task가 todo/doing/done 상세 단계를 추적하는 안 — 연결 시 GitHub 상태와 이중 정본 동기화 문제를 낳아, 이진(완료/미완)으로 축소하고 상세는 플러그인에 위임하기로 반려.
tags: [wiki, task, rejected]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
---

## 대안

위키 `task`가 `todo`/`doing`/`done` 같은 **상세 작업 단계**를 폴더(경로)로 직접 추적한다.

## 반려 사유

작업 플러그인(GitHub)과 연결되면 같은 "진행 단계"를 위키와 이슈가 **각자 정본으로** 들게 되어 이중 정본(dual-SoT) 동기화 문제가 생긴다. 상세 단계는 도구(이슈)에 맡기고, 위키는 **완료/미완 이진**만 들어 겹침을 없앤다.

## 이 대안의 취지

위키만 봐도 작업이 어디까지 왔는지 알 수 있게 하려 했다. (→ [[INT-2026-05-29-181219-task-decision-execution-traceability]])

## 재고 조건

작업 플러그인 연계를 전제하지 않는 **순수 위키 단독 운영**이 주 사용처가 되면, 위키가 상세 단계를 들 가치가 다시 생긴다.
