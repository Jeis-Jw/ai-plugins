---
title: affects_paths + changed-path-stale 검사
created_at: 2026-05-29
summary: v1 신규: ssot/runbook/trial_error/observation의 affects_paths(glob) + git diff 매칭으로 verified_at 미갱신 문서 자동 식별. 코드 변경발 drift 능동 감지.
tags: [wiki, refresh, v1]
relations:
  intents: [INT-2026-05-29-104710-ai-driven-documentation]
---

## 결정

`ssot`, `runbook`, `trial_error`, `observation`은 선택적으로 `affects_paths`를 가질 수 있다. 값은 `src/auth/**` 같은 glob이며, 관련 코드 경로와 문서의 유효성 연결을 표현한다.

`refresh --check changed-path-stale`은 git diff 또는 명시 `--changed-path` 입력이 `affects_paths`와 매칭되는데 `verified_at`이 갱신되지 않은 문서를 플래그한다.

## 취지

시간 기반 stale 검사만으로는 코드 변경으로 인한 문서 drift를 잡기 어렵다. 관련 코드가 바뀌면 해당 설계·런북·교훈·관찰을 다시 확인해야 한다.

이 검사는 문서 검토를 능동적으로 유도하면서도 의미 판단은 자동화하지 않는다. 플래그만 만들고, 갱신 여부는 사람/에이전트가 판단한다.

## 배경

위키는 장기 프로젝트에서 "현재도 맞는가"가 중요하다. 특히 living 문서와 시행착오 기록은 코드 구조가 바뀌면 빠르게 낡을 수 있다.

Observation은 시간만 지났다고 stale한 것은 아니지만, 관찰이 관련된 코드가 바뀌면 재검토할 가치가 있다.

## 고려한 대안

- 시간 기반 `verified_at`만 사용: 코드 변경 직후 drift를 놓칠 수 있어 보완이 필요했다.
- 모든 코드 변경마다 전체 위키 재검토: 비용이 커서 반려했다.
- 자동으로 `verified_at` 갱신: 실제 검토 없이 신선하다고 표시하게 되어 반려했다.

## 트레이드오프

`affects_paths`는 리팩토링 시 함께 갱신해야 하는 관리 비용이 있다. glob이 너무 넓으면 노이즈가 늘고, 너무 좁으면 drift를 놓친다.

검사는 false positive를 낼 수 있지만, false negative로 낡은 정본을 계속 믿는 위험보다 작다고 판단했다.

## 재평가 조건

운영 중 changed-path-stale 플래그가 지나치게 많이 발생해 무시되는 수준이 되면 glob 작성 가이드나 검사 범위를 조정한다.
