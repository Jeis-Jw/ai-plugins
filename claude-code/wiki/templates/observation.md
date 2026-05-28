---
# 선택 필드:
#   verified_at    — 이 관찰이 여전히 유효함을 확인한 마지막 날 (YYYY-MM-DD)
#   affects_paths  — 관련 코드 경로 (glob). refresh changed-path-stale 기반.
# relations 키 의미 (allowed: ssot / runbook / decisions / tasks):
#   ※ observation은 intents·rejected_decisions를 직접 가리키지 않는다.
#     추상 원칙은 후속 decision이 잇는다.
title: <발견·관찰의 한 줄 이름>
created_at: YYYY-MM-DD
summary: <무엇을 발견했고 왜 추적할 가치가 있는지 한 줄>
tags: [<통제 어휘에서>]
verified_at: YYYY-MM-DD
affects_paths: [src/<area>/**]
audience: [human, agent]
relations:
  ssot: [<slug>]
  runbook: [<slug>]
  decisions: [DEC-...]
  tasks: [owner/repo#N]
---

## 관찰

무엇을 발견했는가. 사실 단위로 간결하게 — "왜 중요한가"는 `## 영향`에 따로 적는다.

## 근거

어떤 파일·테스트·로그·현상에 기반하는가. 재현 가능성을 적어야 후속 분류가 가능하다. (코드 경로·로그 라인·재현 명령 등)

## 영향

왜 나중에 중요할 수 있는가. blast radius·관련 시스템·잠재 비용. 결정처럼 단정하지 말고 *가능성*으로.

## 현재 처리

이번 작업에서 처리했는가, 보류했는가, 우회했는가. "TODO" 한 줄이 아니라, *어떤 결정으로 보류*하고 어디까지 영향이 잠긴 상태인지.

## 후속 분류 조건

**어떤 조건이 발생하면 이 observation을 어떤 record로 승격할지** 사전에 박아둔다. 예:
- "동일 패턴이 또 발생하면 → `trial_error`로 승격(교훈 명시)"
- "관련 코드를 다시 만질 때 → 후속 `decision`을 만들고 이 OBS를 supersede"
- "30일 내 추가 신호 없으면 → `deprecated`로 retire (거짓 알람)"

승격 시 새 record를 capture하면서 `--supersedes <이 OBS basename>`을 주면, CLI가 양방향 lifecycle을 자동으로 처리한다.

---

**lifecycle 정책** (v1 §9 운영 가이드):
- 후속 TRI/DEC/다른 OBS로 이어지면 그 record를 primary successor로 두고 `superseded`로 retire.
- SSOT/runbook 갱신만 트리거된 경우에도 그 갱신의 근거가 되는 TRI/DEC/OBS를 하나 만들어 primary successor로 둔다 (SSOT 갱신 자체는 후속 record의 `relations.ssot`에 표현).
- 거짓 알람·상황 변화로 무효가 된 경우만 `deprecated`.
