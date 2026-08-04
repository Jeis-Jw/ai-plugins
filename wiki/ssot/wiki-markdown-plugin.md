---
title: wiki-markdown 플러그인
created_at: 2026-08-04
summary: AI-native 위키 메커니즘 정본 — 버전·진화·소유범위·구성의 단일 진입점. 그래프 타입 체계, 경로 기반 lifecycle(retire/discard), 3-stage recall+pack, refresh tiering, cross-plugin proactive capture 계약을 소유하며 세부 계약은 plugin-definition 6종 sub-ssot가 정본이다.
tags: [wiki-markdown, wiki, plugin, ssot]
verified_at: 2026-08-04
affects_paths: [plugins/wiki-markdown/**]
---

## 현재 상태

wiki-markdown 0.21.0은 이 워크스페이스의 AI-native 위키 메커니즘 정본이다.

버전 이력(주요 마일스톤, 커밋 확인):

- 0.6.0(cd5ddd7) — intent/decision/rejected_decision/trial_error/ssot/runbook 그래프 기본형 정립.
- 0.10.0(33b5708) — 운용 효율 개선 5건: orphan 검사·snapshot·capture·lite·policy.
- 0.12.0(fb516d7) — ceremony를 파급력(gear)에 비례시키는 모델 도입.
- 0.13.0~0.19.x(60615ae~9dec940, Unit A/B/C 웨이브, PR #21–27) — agent-facing 표면 재설계: capture 1-call payload, discard 완전삭제(0.14.0), recall --pack 결정적 투영(0.15.0), snapshot load 권위 라벨(0.16.0), schema/capture --dry-run 머신 판별성(0.17.0), @file/@-(STDIN) body 입력(0.18.0), complete/reopen closeout payload(0.19.0).
- 0.20.0(2ad3cd6) — task-worker/task-github 분리 완료에 맞춰 tracker policy 문구 정비 + "런타임 버그는 코드부터, wiki는 설계 모호성에" 프롬프트 추가.
- 0.21.0(f41a6d6, 오늘) — 실행 규모와 분리한 proactive durable-context 계약 복원: recall 1회 → semantic milestone 감사 → 승인형 capture. 상세는 [[wiki-retrieval]] 참조.

소유 범위:

- 그래프 타입 체계 — living(ssot/runbook) + record(intent/decision/rejected_decision/trial_error/observation) + task(제3 범주, work-definition bridge) + snapshot(graph 밖 staging)
- 경로 기반 active/retired 상태, 2값 retire 모델(deprecated/superseded), discard(완전삭제 mistake-undo)
- 폴더 단위 독립 파생 인덱스, 3-stage recall + `--pack` 결정적 투영
- refresh 무결성 검사 13종 + opt-in 품질 flag 2종(`decision-quality`/`task-quality`), `--level integrity|hygiene` tiering
- cross-plugin proactive recall/승인형 capture 계약(0.21.0)
- `agent-policy` skill을 통한 CLAUDE.md/AGENTS.md agent-operating-policy 관리 블록 스캐폴딩

소유하지 않는 범위:

- 작업환경 운영 정책의 실제 statement 내용(언제·누가·무엇을 capture할지) — CLAUDE.md/AGENTS.md 자동로드 표면이 정본이며 wiki-markdown은 스캐폴딩만 제공
- GitHub Issue/PR, task 실행·검증 상태 — task-github/task-worker
- review episode 상태 — session-review

## 취지

[[INT-2026-05-29-104710-ai-driven-documentation]](AI 주도 문서화)와 [[INT-2026-05-29-104707-token-efficient-context-loading]](토큰 효율적 계층 조회)을 잇는다. 다른 4개 plugin SSOT(studio/task-github/task-worker/session-review)와 동일한 단일 진입점 패턴을 적용해 AI 주작성자가 스스로 버전·drift를 확인할 기준점을 갖는다. 세부 계약의 근거는 이 문서가 아니라 각 sub-ssot와 해당 DEC가 보유한다([[DEC-2026-08-04-221921-wiki-markdown도-단일-plugin-ssot를-갖는다]]).

## 구성요소

- CLI: `skills/wiki/scripts/wiki_cli.py`(stdlib-only), 11개 top-level subcommand — `init`/`capture`/`retire`/`discard`/`complete`/`reopen`/`relate`/`snapshot`/`recall`/`refresh`/`schema`
- skills: `skills/wiki/SKILL.md`(런타임 cheat-sheet) + `skills/agent-policy/SKILL.md`(CLAUDE.md/AGENTS.md 스캐폴딩, `scripts/scaffold_agent_policy.py`)
- 계약 문서: `rules/knowledge-protocol.md`(메커니즘 정본, cross-plugin durable-context 계약 포함), `skills/wiki/references/wiki-protocol.md`(전체 필드/13검사/exit code 계약)
- 템플릿: `templates/`에 8종 — `intent`/`decision`/`rejected_decision`/`trial_error`/`observation`/`ssot`/`runbook`/`task`

세부 계약(sub-ssot): 버전·현황·구성의 단일 진입점은 이 문서이지만 각 메커니즘 영역의 세부 계약 정본은 [[plugin-definition]](영역 라우팅 겸 폴더 인덱스, sub-ssot 5종: [[wiki-data-model]]/[[wiki-lifecycle]]/[[wiki-retrieval]]/[[wiki-external-tools-policy]]/[[wiki-four-layer-separation]])가 계속 소유한다.
