---
title: Studio v0.2 품질 우선 Context Kernel과 외부 Workflow 실행 계약
created_at: 2026-07-10
summary: Studio의 runtime 안정화 위에 품질 hard floor, Context Kernel, 선택적 외부 workflow executor 계약을 한 delivery unit으로 구현·검증한다.
tags: [studio, quality, context, workflow-adapter, v0.2]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
  decisions: [DEC-2026-07-10-133541-studio-최적화-우선순위-artifact-context-품질-hard-floor와-가중-효용, DEC-2026-07-10-133629-studio-실행-경계-mission-quality-context-gate-소유와-선택적-single-executor]
  tasks: [Jeis-Jw/ai-plugins#53]
---

## 개요

기존 QA 완료 runtime 변경을 안전하게 이관하고, Studio가 wiki나 task-github 없이도 동작하는 최소 Context Kernel과 품질 판정 계약을 구현한다. 그 위에 track별 single executor 추상화와 task-github reference adapter, wiki-markdown optional promotion provider를 연결한다. 동일한 broker·producer·상태 schema·배포 검증 표면을 공유하므로 root 1개와 executable leaf 1개, flat topology, major PR 한 단위로 배송한다.

## 근거

상위 취지 [[INT-2026-07-08-164552-studio-살아있는-에이전트-팀]]의 증거 기반 품질 수단을 구체화한다. [[DEC-2026-07-10-133541-studio-최적화-우선순위-artifact-context-품질-hard-floor와-가중-효용]]에 따라 artifact/context 품질을 비용보다 앞선 hard floor로 집행하고, [[DEC-2026-07-10-133629-studio-실행-경계-mission-quality-context-gate-소유와-선택적-single-executor]]에 따라 mission·quality·context·gate는 Studio가 소유한다. 기존 [[REJ-2026-07-08-164619-studio를-이슈트리-오케스트레이션-확장으로-만드는-안]]을 되살리지 않으며, task-github는 코드 중심 track의 선택적 실행 백엔드라는 재고 조건 안에서만 사용한다.

## 범위와 완료 기준

Phase 1 — Runtime hardening과 carrier 이관: QA 완료된 studio/→.studio/ 변경을 보존해 이관하고 run_id path confinement, mission/KPI/delta strict schema, pairing false-ready 차단, atomic board transaction, budget reserve→dispatch→settle/release, 실제 JS broker semantic test를 완성한다.

Phase 2 — QualityPlan·Context Kernel·board schema 2: ContextItem/ContextPack/ContextDelta와 .studio/context/{items,bundles,deltas,outbox} 로컬 projection, artifact/context required criterion 및 quality floor, 통과 후 weighted utility, schema 1 lazy migration, track.executor 단일 lease, context compact/prune/promotion candidate를 구현한다.

Phase 3 — Workflow adapter와 전체 검증: WorkPacket/ResultEnvelope, studio-native/external-workflow 공통 계약, task-github reference adapter, capability snapshot+실행 직전 preflight, unavailable/unknown degraded mode, wiki-markdown optional promotion provider, 문서·manifest·distribution parity를 구현한다.

완료 기준: quality floor 실패는 비용·시간 점수와 무관하게 완료될 수 없다. 한 track의 executor 중복 실행을 거부한다. task-github 미설치 시 native 실행이 정상 동작하고 wiki-markdown 미설치 시 promotion candidate가 로컬 outbox에 보존된다. 외부 workflow 내부 상태는 복제하지 않고 reference만 저장한다. readyForIntegration은 실제 verification·quality evidence를 요구한다. 기존 .studio/ 상태를 삭제하거나 자동 덮어쓰지 않는다. 기존 schema 1은 lazy migration으로 읽을 수 있다.

검증: studio Python 전체 테스트, 실제 Node broker semantic test, wiki-markdown distribution unittest, git diff --check를 모두 통과한다.

영향 경로: plugins/studio/**, plugins/wiki-markdown/tests/test_plugin_distribution.py, .claude-plugin/marketplace.json 및 Studio 배포/version 정합 파일, 기존 QA carrier의 .studio/**.

Non-goals: Studio를 GitHub Issue tree 처리기로 전환하지 않는다. task-github/wiki-markdown을 필수 dependency로 만들지 않는다. 외부 workflow의 issue·branch·PR 상태 전체를 board에 복제하지 않는다. raw transcript 전체를 장기 context에 누적하지 않는다. worker가 decision·rejected alternative를 owner 승인 없이 wiki로 승격하지 않는다.
