---
title: Studio를 host-native crew orchestrator로 단순화
created_at: 2026-07-29
summary: Studio 0.11.1의 자체 runtime과 중복 실행·리뷰·컨텍스트 계층을 제거하고 호스트 서브에이전트 orchestration만 남긴다.
tags: [studio, refactor, orchestration, simplification]
relations:
  decisions: [DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다]
---

## 개요

기존 Studio의 역할·casting·mission·crew lifecycle 개념은 유지하되 Codex/Claude Code host adapter가 native subagent API를 호출하도록 제품 경계를 재구성한다.

## 근거

Studio 0.11.1 admission 실패의 직접 원인은 sandbox에서 금지된 loopback listener였으며, 감사에서 custom runtime, execution control, review cycle, Context Kernel, workflow routing과 economics ledger의 책임 중복이 확인됐다.

## 범위와 완료 기준

범위: plugins/studio의 persistent runtime, custom Workflow runner/broker 실행체, execution-control contract, 자체 review/context/workflow/lease/economics 계층 제거; Codex와 Claude host adapter 계약, 역할·casting·mission·crew state, relay/result/review/rework lifecycle, 간결한 README와 테스트 유지. 완료 기준: 삭제된 runtime 경로 참조 없음, 두 호스트 adapter 계약 검증, 핵심 crew lifecycle 테스트 통과, plugin manifest 일치, wiki 무결성 및 git diff check 통과.
