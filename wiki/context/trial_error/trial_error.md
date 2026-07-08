---
title: Trial & Error — 시행착오
created_at: 2026-05-29
summary: 교훈·피해야 할 것·현재 유효성(record).
tags: [meta]
audience: [human, agent]
---

# Trial & Error — 시행착오

교훈·피해야 할 것·현재 유효성(record).

## 노트

- [[TRI-2026-05-29-105531-monolithic-design-doc-causes-status-ambiguity]] — v0(40KB) + v1(62KB) 두 monolithic 정의 문서가 wiki에 공존했더니 어느 게 현재 정본인지 AI가 추론해야 했다. atomic record 분해 + 단일 ssot 원칙을 위반하면 시스템 자체가 자기 원칙을 어김.
- [[TRI-2026-05-29-105532-flat-ssot-becomes-bloated-when-domain-grows]] — v0에서 ssot/는 평면 단일 폴더. 도메인이 커지면 한 폴더에 수십 개 파일이 쌓이고 인덱스도 비대화. v1은 nested 허용 + basename 전역 유일성 + 폴더 단위 독립 인덱스로 대응.
- [[TRI-2026-06-02-120200-작업-종료-전-지식-기록-감사를-생략하면-결정-그래프가-비게-된다]] — Codex가 task-github 규약 변경 중 durable decision과 rejected alternative를 만들고도 observation 캡처나 1급 기록 제안을 누락했다. 종료 전 Knowledge Capture Audit가 필요하다.
- [[TRI-2026-06-17-032634-다중값-관계-플래그-누적은-action-append-공유-정규화로-통일]] — argparse 기본 store는 반복 다중값 플래그를 조용히 last-wins 드롭한다. 교훈: 모든 list형 관계 인자를 action=append + 콤마 split·flatten·strip·순서보존 dedup 공유 헬퍼로 통일하고, 반복·콤마·혼합·중복 4형 회귀 테스트로 고정.
- [[TRI-2026-07-09-000640-브로커-턴-조인은-에이전트-산출의-문자열-위치가-아니라-브로커-부여-id로-한다]] — studio 브로커가 서로 다른 에이전트의 산출(critic 판정↔제출 delta, dev 방어↔qa 실패)을 배열 위치·제목 문자열로 조인해 오귀속/미매칭 발생. 브로커가 부여한 안정 id로 조인해야 한다. brainstorm·pairing 두 곳에서 동일 계열로 재발.
