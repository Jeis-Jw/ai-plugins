---
title: context 플러그인 대화형 recall·비교·승인 capture 재정렬
created_at: 2026-08-17
summary: context-core와 context-decision에서 claim fingerprint를 제거하고, 명시적 init이 설치하는 관리형 운영지침을 통해 기존 컨텍스트 recall·본문 의미 비교·충돌/취지 변경 알림·승인형 capture 제안을 일관되게 수행하도록 재정렬한다.
tags: [context-core, context-decision, durable-context, semantic-comparison, agent-policy]
relations:
  decisions: [DEC-2026-08-13-180535-capture-audit는-milestone-단위-단일-판독과-승인형-write를-지킨다, DEC-2026-08-13-183612-컨텍스트-플러그인은-milestone-capture-audit와-semantic-owner-draft로-결합한다, DEC-2026-08-17-114327-fingerprint-제거-release는-context-common-v2로-분리하고-init은-managed-policy까지-완료한다]
---

## 개요

사용자와 LLM의 대화에서 재사용 가치가 있는 맥락과 결정 수렴을 능동적으로 감지하되, 영속 쓰기는 명시 승인 뒤에만 수행한다. claim fingerprint 기반 동일성 추정은 제거하고 실제 본문·rationale·scope·현재 상태를 비교한다.

## 근거

문장 정규화 해시는 같은 의미의 다른 문장을 잡지 못하고 다른 의미의 유사 문장을 오인할 수 있다. 현재 플러그인은 저장 원자성과 exact slot 충돌 검사는 제공하지만, 결정 전 recall과 의미 비교가 하나의 대화 흐름으로 충분히 연결되지 않았다. 기존 milestone audit와 semantic owner 책임 분리를 유지하면서 단순한 운영 메커니즘으로 보완한다.

## 범위와 완료 기준

완료 기준: (1) 두 플러그인의 schema/runtime/template/docs/tests에서 claim_fingerprint와 source_claim_fingerprint 계약을 제거한다. (2) context-decision이 관련 Current 결정의 본문과 rationale를 읽어 same/supporting/rationale_changed/conflict/new를 판정하고 결정 전 알림 및 capture 제안에 사용한다. (3) context-core init과 context-decision init이 활성 host의 AGENTS.md 또는 CLAUDE.md에 단일 관리형 운영지침을 안전하고 idempotent하게 설치·갱신한다. (4) 운영지침은 자동 recall·비교·알림·milestone 제안을 요구하되 사용자 컨텍스트 write는 승인형으로 유지한다. (5) 교차 플러그인 테스트와 배포 표면 parity 검증이 통과한다.
