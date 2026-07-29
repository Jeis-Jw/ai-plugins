---
title: Studio를 host-native crew orchestrator로 단순화
created_at: 2026-07-29
summary: Studio 0.11.1의 자체 runtime과 중복 실행·리뷰·컨텍스트 계층을 제거하고 호스트 서브에이전트 orchestration만 남긴다.
tags: [studio, refactor, orchestration, simplification]
relations:
  decisions: [DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다]
---

## 개요

기존 Studio의 역할·casting·mission 개념은 유지하되 Producer skill이 Codex/Claude Code의
native subagent API를 직접 호출하도록 제품 경계를 재구성한다.

## 근거

Studio 0.11.1 admission 실패의 직접 원인은 sandbox에서 금지된 loopback listener였으며, 감사에서 custom runtime, execution control, review cycle, Context Kernel, workflow routing과 economics ledger의 책임 중복이 확인됐다.

## 범위와 완료 기준

범위: `plugins/studio`의 persistent runtime, custom Workflow runner/broker, execution-control
contract, 자체 state/review/context/workflow/lease/economics 계층 제거; Codex와 Claude host
도구 대응, host-independent 역할 prompt, 최소 casting, mission 양식, 간결한 Producer skill과
README만 유지.

완료 기준: Studio runtime·state·입장 검사 경로가 없고, 두 host의 native subagent 호출
계약이 문서화되며, 역할 prompt에 host-specific tool metadata가 없고, plugin/marketplace
manifest와 저장소 배포 테스트 및 `git diff --check`가 통과한다.
