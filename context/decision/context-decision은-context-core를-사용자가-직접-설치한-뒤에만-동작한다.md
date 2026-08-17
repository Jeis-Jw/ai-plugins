---
schema: "context-decision/v1"
id: "ctx_10e8ed46e7014b7b954357881128b7eb"
title: "context-decision은 context-core를 사용자가 직접 설치한 뒤에만 동작한다"
summary: "Claude Code와 Codex 모두 native dependency와 자동 설치를 사용하지 않고, provider marketplace jeis-ai-plugins의 context-core가 준비되지 않으면 무변경으로 중단한다."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-08-13-233319-context-decision은-context-core를-사용자가-직접-설치한-뒤에만-동작한다.md"]
tags: ["context-decision","context-core"]
scope: "ai-plugins/context"
decision_key: "init-bootstrap-semantics"
revisit_when: ["Codex와 Claude Code가 같은 manifest dependency·설치 scope·동의 UX·rollback 계약을 공식 지원하고, 자동 설치가 사용자 승인 없이 수행되지 않는 것이 검증되면 native dependency를 편의 기능으로 재검토한다. correctness는 계속 runtime capability와 protocol handshake로 검증한다."]
---

## 결정

Claude Code와 Codex 모두 native dependency와 자동 설치를 사용하지 않고, provider marketplace jeis-ai-plugins의 context-core가 준비되지 않으면 무변경으로 중단한다.

## 취지

사용자가 선택하지 않은 scope나 환경에 plugin이 설치되는 일을 막고, Claude Code와 Codex의 사용자 경험과 안전 경계를 같게 유지한다. 설치라는 사용자 환경 변경과 repository 초기화라는 프로젝트 변경을 분리하면서도 storage coordinator를 하나로 유지한다.

## 반려대안

- Claude Code에서만 native dependency 사용: 두 host의 설치·오류 계약이 달라져 반려한다. 2. context-decision:init이 context-core를 자동 설치·활성화: 사용자의 환경과 설치 scope를 임의 변경하므로 반려한다. 3. context-core 전체 또는 storage runtime을 context-decision에 내장: coordinator와 migration 구현이 addon마다 복제될 수 있어 반려한다. 4. core 부재 시 decision을 제한적으로 단독 실행: 동일 storage protocol을 우회하는 별도 경로가 생겨 반려한다.

## 트레이드오프

- 최초 사용자는 provider marketplace를 직접 추가하고 context-core와 context-decision을 올바른 scope에 설치·활성화한 뒤 reload, `context-core:init`, `context-decision:init`을 순서대로 수행해야 한다.

## 재평가 조건

- Codex와 Claude Code가 같은 manifest dependency·설치 scope·동의 UX·rollback 계약을 공식 지원하고, 자동 설치가 사용자 승인 없이 수행되지 않는 것이 검증되면 native dependency를 편의 기능으로 재검토한다. correctness는 계속 runtime capability와 protocol handshake로 검증한다.
