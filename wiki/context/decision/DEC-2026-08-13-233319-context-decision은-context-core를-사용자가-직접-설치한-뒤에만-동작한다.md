---
title: context-decision은 context-core를 사용자가 직접 설치한 뒤에만 동작한다
created_at: 2026-08-13
summary: Claude Code와 Codex 모두 native dependency와 자동 설치를 사용하지 않고, provider marketplace jeis-ai-plugins의 context-core가 준비되지 않으면 무변경으로 중단한다.
tags: [context-decision, context-core, dependency, marketplace, bootstrap]
relations:
  ssot: [context-decision-plugin, context-v1-implementation]
---

## 결정

context-decision은 context-core에 manual hard-depend한다. 요구 distribution identity는 `marketplace: jeis-ai-plugins`, `plugin: context-core`, selector `context-core@jeis-ai-plugins`, source `Jeis-Jw/ai-plugins`로 고정한다. Claude Code와 Codex 양쪽 manifest 모두 native dependency를 선언하지 않으며 context-decision은 core를 자동 설치·활성화·업데이트하거나 core 구현을 내장하지 않는다.

정적 `schema`와 `capabilities`를 제외한 모든 user-facing operation은 host inventory의 exact distribution identity, 활성 상태, `context-common/v1` 호환성과 repository 초기화 상태를 먼저 확인한다. exact core가 없거나 다른 marketplace의 동명 plugin만 있거나 비활성·비호환이면 repository filesystem과 host configuration을 전혀 변경하지 않고 즉시 중단한다. 오류는 provider가 운영하는 정확한 marketplace의 core를 사용자가 직접 설치·활성화·업데이트하고 host를 reload하거나 새 session을 연 뒤 `context-decision:init`을 다시 실행하도록 안내한다. exact core는 준비됐지만 project root가 초기화되지 않았으면 `context-core:init`을 직접 실행한 뒤 `context-decision:init`을 재실행하도록 안내하고 중단한다.

## 취지

사용자가 선택하지 않은 scope나 환경에 plugin이 설치되는 일을 막고, Claude Code와 Codex의 사용자 경험과 안전 경계를 같게 유지한다. 설치라는 사용자 환경 변경과 repository 초기화라는 프로젝트 변경을 분리하면서도 storage coordinator를 하나로 유지한다.

## 배경

Claude Code는 native plugin dependency와 자동 설치를 지원하지만 Codex의 공개 manifest 계약에는 같은 기능이 없다. host별 최적화를 쓰면 설치 동작과 실패 조건이 달라진다. init이 설치까지 수행하는 방식도 user/project/local 또는 managed scope와 reload 경계를 plugin이 임의로 결정하게 만든다.

## 고려한 대안

1. Claude Code에서만 native dependency 사용: 두 host의 설치·오류 계약이 달라져 반려한다. 2. context-decision:init이 context-core를 자동 설치·활성화: 사용자의 환경과 설치 scope를 임의 변경하므로 반려한다. 3. context-core 전체 또는 storage runtime을 context-decision에 내장: coordinator와 migration 구현이 addon마다 복제될 수 있어 반려한다. 4. core 부재 시 decision을 제한적으로 단독 실행: 동일 storage protocol을 우회하는 별도 경로가 생겨 반려한다.

## 트레이드오프

최초 사용자는 provider marketplace를 직접 추가하고 context-core와 context-decision을 올바른 scope에 설치·활성화한 뒤 reload, `context-core:init`, `context-decision:init`을 순서대로 수행해야 한다. host-native 자동 dependency보다 단계가 늘지만 설치 권한·scope·source 선택이 명시적이며 양 host의 동작을 동일하게 테스트할 수 있다.

## 재평가 조건

Codex와 Claude Code가 같은 manifest dependency·설치 scope·동의 UX·rollback 계약을 공식 지원하고, 자동 설치가 사용자 승인 없이 수행되지 않는 것이 검증되면 native dependency를 편의 기능으로 재검토한다. correctness는 계속 runtime capability와 protocol handshake로 검증한다.
