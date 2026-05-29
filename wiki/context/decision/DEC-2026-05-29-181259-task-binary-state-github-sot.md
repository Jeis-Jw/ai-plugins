---
title: task 상태는 이진(경로 기반)이고 연결 시 GitHub이 정본
created_at: 2026-05-29
summary: task는 활성과 완료 이진만 추적하고 done은 경로 이동으로 표현 — 독립은 위키 정본, 연결은 GitHub 정본이며 task-github가 done 투영과 reconcile을 담당하고 위키는 gh를 모른다. CLI는 complete와 reopen.
tags: [wiki, task, lifecycle]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
  rejected_decisions: [REJ-2026-05-29-181259-wiki-holds-task-detailed-phase]
  ssot: [wiki-lifecycle]
---

## 결정

`task`의 상태는 **이진**이다 — 활성(`wiki/task/`) vs 완료(`wiki/task/done/`). 완료는 `done/`로의 **경로 이동**으로 표현한다(위키의 "경로=상태" 원칙, `retired/`의 형제).

정본은 사용 맥락으로 결정된다:
- **독립**(작업 플러그인 미연결): 위키가 완료/미완의 정본.
- **연결**: **GitHub 이슈가 정본**. task-github가 이슈 close 시 `done/`로 투영하고, 밖에서 닫힌 경우 reconcile한다.

위키 CLI는 GitHub을 모른다 — 폴더 이동 명령 `complete`/`reopen`만 제공한다.

## 취지

위키와 작업 플러그인이 같은 상태를 이중으로 들면 동기화 지옥이 된다. 위키가 추적하는 상태를 **이진으로 최소화**해 겹침을 없애고, 상세 단계는 도구에 위임한다([[INT-2026-05-29-181219-task-decision-execution-traceability]]). 위키의 도구 중립도 지킨다.

## 배경

위키가 상세 단계(todo/doing/done)를 들면([[REJ-2026-05-29-181259-wiki-holds-task-detailed-phase]]) GitHub과 dual-SoT가 된다. 이진으로 줄이면 동기화할 전이가 **"활성→완료" 하나(단조)** 뿐이라, 정상 흐름(merge/close 시 task-github가 이동)에서 드리프트가 없고, 밖에서 닫힌 예외만 reconcile하면 된다.

## 고려한 대안

- [[REJ-2026-05-29-181259-wiki-holds-task-detailed-phase]] — 위키가 상세 단계 보유. 반려.

## 트레이드오프

위키만 보면 작업의 거친 **완료 여부**만 알고 상세 진행은 이슈로 가야 한다. 대신 동기화 문제가 사라지고 위키는 도구 중립을 지킨다.

## 재평가 조건

위키 단독 운영이 주가 되어 상세 진행 가시성이 강하게 필요해지면 상태 모델 확장을 재검토한다.
