---
title: Decisions — 결정
created_at: 2026-05-29
summary: 결정·취지·트레이드오프·재평가 조건(record).
tags: [meta]
audience: [human, agent]
---

# Decisions — 결정

결정·취지·트레이드오프·재평가 조건(record).

## 노트

- [[DEC-2026-05-29-105230-record-living-id-system]] — Record는 TYPE-YYYY-MM-DD-HHMMSS-slug, living은 slug만 사용. basename이 정본 ID, YAML id 필드 없음.
- [[DEC-2026-05-29-105231-wiki-type-taxonomy]] — ssot/runbook(living) + context의 intent/decision/rejected_decision/trial_error/observation(record)으로 분리. fact·pattern·overview·planning은 흡수/이관.
- [[DEC-2026-05-29-105232-relations-asymmetric-write]] — 관계 정본은 frontmatter YAML의 plain basename. record(decision/rejected/trial/observation)만 작성하고 허브(intent/ssot/runbook)는 백링크로 파생.
- [[DEC-2026-05-29-105233-obsidian-zero-runtime-dependency]] — AI 검색 정본은 filesystem 단일(ripgrep+YAML). obsidian-cli/Dataview/Bases는 AI 파이프라인 제외. wikilink는 사람용 장식.
- [[DEC-2026-05-29-105234-retire-two-value-model]] — 모든 record(OBS 포함)는 deprecated(틀림/무효) 또는 superseded(새 record로 대체) 2값으로 retire. classified 같은 별도 분류 축 미도입.
- [[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]] — v1 시점 결정: ssot/runbook은 하위 폴더 허용. basename은 vault 전역 유일. resolver 단순성 + nested 분할 가능성 양립. v0 평면 디렉토리 supersede.
- [[DEC-2026-05-29-105321-folder-independent-index-derivation]] — v1 시점 결정: 재귀=폴더 발견, 비재귀=노트 수집. 각 폴더 인덱스는 직속 문서만 모음. 상위는 하위 문서 summary 중복 수집 안 함. v0 단순 폴더 인덱스 supersede.
- [[DEC-2026-05-29-105322-observation-record-type]] — v1 신규: 실행 중 발견했지만 아직 결정/교훈/정본 갱신으로 분류하기 이른 사실을 안전하게 보존하는 임시 record. 다른 record와 같은 2값 supersede 모델.
- [[DEC-2026-05-29-105323-affects-paths-and-changed-path-stale]] — v1 신규: ssot/runbook/trial_error/observation의 affects_paths(glob) + git diff 매칭으로 verified_at 미갱신 문서 자동 식별. 코드 변경발 drift 능동 감지.
- [[DEC-2026-05-29-105324-search-terms-recognized-optional]] — v1 신규: 전 타입 선택 필드. capture 기본 생성 X, refresh 누락 검사 X, recall Stage 1 매칭 O. summary+tags+본문 외 검색 escape hatch.
- [[DEC-2026-05-29-105325-refresh-fix-whitelist]] — v1 명확화: --fix는 index/retired-in-index 인자만 허용. bare --fix와 그 외 인자 모두 exit 2. 의미 판단 필요한 자동수정은 명시 capture/Edit으로.
- [[DEC-2026-05-29-105326-plugin-agent-neutral-cli-schema]] — v1 명시화: CLI 인자/출력 메시지/frontmatter 필드명/알고리즘 명세에 Claude/Codex 등 agent 이름 없음. agent별 규약은 operating model로 격리.
- [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]] — v1 신규: plugin은 capture된 문서가 타입별 구조/스키마를 만족하는지만 검증. 의미적 승격 가치 판정(누가 무엇을 언제)은 agent-operating-model.md 영역.
- [[DEC-2026-05-29-181259-task-binary-state-github-sot]] — task는 활성과 완료 이진만 추적하고 done은 경로 이동으로 표현 — 독립은 위키 정본, 연결은 GitHub 정본이며 task-github가 done 투영과 reconcile을 담당하고 위키는 gh를 모른다. CLI는 complete와 reopen.
- [[DEC-2026-05-29-181259-task-third-category]] — 결정과 취지를 이슈에 잇는 작업 브릿지 노드 task를 신설 — 제자리 갱신과 관계 보유를 조합한 순수 잎, relations는 intents/decisions/tasks/ssot, ID는 TASK 프리픽스, 경로는 wiki/task.
- [[DEC-2026-06-02-120100-task-github-작업-종료-전-knowledge-capture-audit-의무화]] — 비 trivial task-github 작업은 종료 전에 위키 기록 후보를 감사하고 recorded/proposed/none 중 하나를 최종 보고나 Issue 코멘트에 남긴다.
- [[DEC-2026-06-02-120400-하위-작업-실행-순서는-github-issue-dependencies를-정본으로-사용]] — sub-issue는 작업 분해 구조만 표현하고, 하위 작업의 선후관계와 blocked 상태는 GitHub Issue dependencies의 blocked_by/blocking 관계를 정본으로 사용한다.
- [[DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다]] — wiki-markdown 배포 설계에서 작업환경 운영정책 statement의 정본 위치를 소비 프로젝트 wiki/ssot/agent-operating-model.md가 아니라 CLAUDE.md/AGENTS.md 같은 자동로드 agent-entry 표면으로 재배치한다. 이 repo의 위키에는 플러그인 설계 결정만 dogfood로 남기고, 플러그인 패키지는 agent-policy 스캐폴드로 CLAUDE.md/AGENTS.md 관리 블록을 만든다.
- [[DEC-2026-06-03-155419-define-batch-helper-and-wiki-relate]] — task-github define은 테스트된 issue-tree 헬퍼로 루트·서브이슈·dependency를 만들고, wiki-markdown은 기존 노드 관계 보강을 위해 relate와 견고한 ref/task-ref 정규화를 제공한다.
- [[DEC-2026-06-12-185228-결정-분해-품질-gate를-플러그인에-추가-정적-룰-v0-먼저]] — task-github/wiki-markdown에 decision/define 품질 gate(G1–G4)를 추가하되 MVP는 LLM-judge가 아닌 정적 룰부터. 나쁜 define이 비동기 실행으로 증폭되는 것을 실행 전에 차단.
- [[DEC-2026-06-17-012702-rationale는-메인-직접-커밋-코드-pr은-id-참조-define이-rationale-커밋과-dirty-vault-경고-담당]] — 결정/반려 등 근거 레코드는 메인 트리에 직접 커밋(코드 PR과 분리, PR은 DEC ID 참조). 엉킴 방지를 위해 define이 자기 rationale을 커밋하고 define/start가 dirty wiki vault를 경고한다.
- [[DEC-2026-06-18-120000-snapshot은-상태-폴더-없는-휘발-staging]] — snapshot은 상태 폴더 없이 wiki/snapshot/ 루트의 SNAP-<slug>.md 파일로 관리한다. 토론당 현재 상태 하나만, 이력은 git과 record가 보유한다.
- [[DEC-2026-06-18-224414-session-review를-wiki-기능-위-리뷰-루프로-설계]] — 산출물=wiki ssot, 소통=wiki snapshot, git 리뷰브랜치+squash merge로 두 독립 세션의 리뷰 루프를 구성. 별도 파일포맷·디렉터리(bespoke)는 기각.
- [[DEC-2026-06-19-115758-위키-task-github-계획-플로우-작업정의-먼저-수행-이슈-나중]] — 작업 계획 시 wiki 작업정의 task를 먼저, 연계 GitHub 이슈를 나중에 생성·링크. 조율은 task-github가 전담하고 wiki는 순수 유지. define를 doc-first로 반전.
- [[DEC-2026-06-19-144637-session-review-스냅샷-백엔드-하이브리드화]] — session-review가 wiki-markdown 있으면 위임, 없으면 동일 포맷 내장 writer로 fallback. 타 워크스페이스 이식성 확보.
- [[DEC-2026-06-19-190302-ceremony를-파급력-gear-에-비례시킨다]] — PR 분할·리뷰 강도를 설계결정 수가 아니라 기어·롤백 단위에 맞춘다. mechanism=task-protocol §3.1, principle=agent-policy 스캐폴드(CLAUDE/AGENTS 재렌더).
- [[DEC-2026-06-25-182926-wiki-markdown-개선-agent-facing-표면-재설계-우선-unit-a-b-c-closeout]] — wiki 운용 마찰 본체는 신규기능이 아니라 SKILL/CLI 표면이 실체와 drift한 것 — 표면 재설계를 P0로, discard/projection/stale/closeout을 소수 추가
- [[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]] — 이슈트리 자동수행 orchestrate를 공통 플로우(worktree·PR 필수) 위 브랜치트리 머지업 + 전문 에이전트 분해로 설계. 정본 작업정의=TASK-2026-06-26-190656 (설계 r5).
