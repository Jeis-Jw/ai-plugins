---
title: 명시적 init 호출은 필요한 repository bootstrap을 한 번에 완료한다
created_at: 2026-08-14
summary: Plugin 설치는 수동으로 유지하되 init 호출 자체가 안전한 repository 초기화를 적용하며 decision init은 필요한 core init까지 연계한다.
tags: [context-core, context-decision, init, bootstrap, ux]
supersedes: [DEC-2026-08-13-233319-context-decision은-context-core를-사용자가-직접-설치한-뒤에만-동작한다]
relations:
  ssot: [context-core-plugin, context-decision-plugin, context-v1-implementation]
retired_at: 2026-08-17
retired_type: superseded
superseded_by: DEC-2026-08-17-114327-fingerprint-제거-release는-context-common-v2로-분리하고-init은-managed-policy까지-완료한다
---

## 결정

`context-core:init`의 명시적 호출은 해당 저장소를 사용 가능하게 만드는 고정·안전·멱등 초기화를 실제 적용하도록 승인한 것으로 본다. absent 상태에서는 canonical core seed를 즉시 적용하고, ready 상태에서는 noop이며, valid user data를 삭제하거나 덮어쓰지 않는다. 고정 init effect에 대해서는 preview 뒤 exact digest를 다시 승인받지 않는다.

`context-decision:init`은 exact `context-core@jeis-ai-plugins`가 설치·활성화되어 있고 `context-common/v1`과 호환되면 repository state를 검사한다. core가 absent이면 같은 호출 안에서 core init을 먼저 완료하고 이어서 decision area를 등록한다. core와 decision area가 이미 ready이면 noop이다.

core plugin 부재, source mismatch, disabled, incompatible 상태에서는 기존처럼 repository와 host configuration write를 0으로 유지하고 사용자가 정확한 plugin을 설치·활성화·업데이트하도록 안내한다. partial 또는 invalid repository는 자동 복구하지 않고 fail-closed한다. 일반 DEC·OBS·SNAP capture와 user content mutation의 exact digest approval은 유지한다. plugin 설치·활성화·업데이트와 선택적 agent policy 설치는 init bootstrap이 임의 실행하지 않는다.

## 취지

일반적인 init 명령의 의미처럼 사용자가 명시적으로 초기화를 요청하면 현재 상태에 필요한 안전한 설정을 한 번에 완료한다. repository 초기화와 plugin 설치 권한을 분리해 환경 scope 선택권은 보존하면서, 고정 seed 적용에 대한 중복 승인과 `core:init` 다음 `decision:init`을 수동으로 연속 호출하는 비용을 제거한다.

## 배경

기존 계약은 plugin 자동 설치를 막기 위해 repository 초기화도 별도 수동 단계와 digest 재승인으로 묶었다. 실제 사용에서 `context-core:init`을 호출한 뒤에도 동일한 세 seed 파일 적용을 다시 승인해야 했고, core와 decision을 모두 설치한 사용자가 `context-decision:init`을 실행해도 `context-core:init`을 별도로 실행해야 했다. 이는 설치 scope를 보호하는 경계와 이미 명시적으로 요청한 idempotent repository bootstrap을 불필요하게 같은 gate로 취급했다.

## 고려한 대안

1. 기존 preview와 exact digest 재승인을 유지한다: 고정되고 멱등인 init seed에 사용자 의사를 두 번 묻기 때문에 반려한다.
2. `context-decision:init`이 core init 안내만 하고 중단한다: 두 plugin을 이미 설치한 사용자가 두 init 명령을 순서대로 호출해야 하므로 반려한다.
3. decision init이 core plugin 설치·활성화까지 자동 수행한다: host 환경과 설치 scope를 임의 변경하므로 반려한다.
4. partial·invalid core state도 자동 repair한다: 기존 사용자 데이터의 의미와 복구 의도를 추측할 수 있으므로 반려한다.

## 트레이드오프

init이 preview-only 표면이 아니라 제한된 physical mutation 표면이 되므로 허용 effect와 idempotence를 executable test로 고정해야 한다. decision init은 core bootstrap과 area registration의 단계별 결과를 명확히 보고해야 하며 중간 실패에서도 일관된 상태를 유지해야 한다. 대신 최초 사용 경로는 한 명령으로 줄고 명령 이름과 실제 동작이 일치한다.

## 재평가 조건

init이 고정 seed를 넘어 기존 user content를 변경하거나, agent policy·host 설정·plugin 설치처럼 별도 선택이 필요한 effect를 암묵적으로 포함하게 되면 해당 effect만 명시 flag 또는 별도 preview 승인으로 분리한다. 자동 repair의 안전성을 증명할 수 있는 versioned migration과 rollback 계약이 생기면 partial state 처리를 재검토한다.
