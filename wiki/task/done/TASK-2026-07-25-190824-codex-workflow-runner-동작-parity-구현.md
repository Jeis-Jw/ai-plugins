---
title: Codex Workflow Runner 동작 parity 구현
created_at: 2026-07-25
summary: Claude의 기존 Studio broker 의미를 Codex에서도 코드로 강제하는 자동 Runner를 구현하고 검증한다.
tags: [studio, codex, workflow, runner]
relations:
  tasks: [Jeis-Jw/ai-plugins#78]
  decisions: [DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다]
---

## 개요

UI와 토큰 telemetry 변경은 제외하고 Codex 실행 절차 parity에 집중한다.

## 근거

현재 Codex는 callable Workflow가 없어 producer의 일반 subagent fallback으로 실행된다. 설계 crew와 critic은 기존 broker JS를 정본으로 유지하고, live capability probe 통과 후 automatic codex-exec adapter를 구현하는 순서를 승인했다.

## 범위와 완료 기준

범위: disposable live capability probe, 기존 brainstorm/pairing broker를 재사용하는 Codex runner, capability fail-closed routing, sandbox/worktree/cancellation/schema 회귀 테스트, producer 및 README 계약 갱신. 완료 기준: probe 통과, broker parity와 전체 Studio 테스트 통과, 독립 reviewer 승인. 제외: UI, token telemetry, main 통합, push/PR은 별도 owner gate.

**종결**: [[DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다]]가 Studio를 host subagent orchestration만 남기는 방향으로 재설계하면서, 이 작업이 parity를 만들려던 대상인 자체 Workflow runner/broker(brainstorm/pairing broker JS, 그 위의 Codex-exec adapter)를 전량 제거했다(구현: `TASK-2026-07-29-233856-studio를-host-native-crew-orchestrator로-단순화`). 대상 서브시스템 자체가 없어져 완료 기준(probe 통과·broker parity)을 더 이상 평가할 수 없다. 구현은 착수되지 않았고, 방향전환에 따른 moot로 완료 처리한다.
