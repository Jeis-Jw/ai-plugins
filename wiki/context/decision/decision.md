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
- [[DEC-2026-07-02-190102-define은-topology-판단을-제안-게이트에-필수-포함]] — define이 issue tree를 제안할 때 what(작업 목록)뿐 아니라 how(branch/integration topology)를 필수 판단한다. 확인안에 Topology Decision 섹션 의무화, flat under-structuring 정적 휴리스틱 경고, 조건 충족 시 flat/stacked 2안 비교. vertical slice는 product goal이 하나라는 뜻이지 tree가 flat이어야 한다는 뜻이 아니다 — ownership/path/integration branch가 갈리면 stacked 우선 검토.
- [[DEC-2026-07-02-205231-orchestrated-worker에-expected-pr-base-계약-강제]] — stacked issue tree에서 leaf PR이 parent issue branch 대신 main을 base로 열리던 버그를, orchestrator→worker handoff에 expected PR base(BASE_BRANCH)를 명시 전달하고 orchestrated mode에서 base 누락 시 PR/worktree 생성 전 hard STOP하는 계약으로 차단한다. orchestrate v2(DEC-2026-06-26-190009) 브랜치트리 설계의 fallback 공백을 메운다.
- [[DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거]] — orchestrate 컨테이너/epic 머지업을 PR화(gh pr create+merge)하고 run_local_closeout(local mode)+Integration Ledger를 제거해, 오케스트레이션 중 메인 워크트리 HEAD가 trunk를 벗어나지 않음을 구조적으로 보장한다. v2(DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml)의 always-PR 원칙을 컨테이너 머지업까지 실현.
- [[DEC-2026-07-02-224910-orchestrate-세리머니를-merge-edge-gear로-이동-분해를-payoff-원리로-재정의]] — orchestrate 오버헤드(리프당 ~20분 고정비×리프 수)를 잡기 위해 세리머니(plan/verify/PR/review)를 리프 속성이 아닌 부모 머지 edge의 gear 속성으로 옮기고(micro/normal=로컬 FF 머지 무PR, major=PR+review, 컨테이너 gear=자식 누적 승격), 분해를 payoff>고정비 원리(절단 사유 4개, 하드캡 없음)로 재정의. DEC-212109 all-PR을 gear-gated로 부분 개정하되 메인 트리 HEAD 불변은 유지.
- [[DEC-2026-07-03-012207-define에-co-design-뒤-challenge-review-게이트-config-driven-지시-설정-하네스-off-default]] — task-github:define에 co-design 다음 challenge review 게이트 추가. fresh-context 적대 서브에이전트가 분해 제안을 4 절단규칙+위키 결정그래프에 refute로 감사(분해/의도 에러를 최상류에서 포착). 저-의존 config-driven(orchestrate review-tool 패턴 미러): define.review-tool/review-command, off-default, `--review`로 on, TOOL 우선순위 지시>설정>하네스, terminal=하네스(내장 challenge, STOP 아님 — 사람이 co-design에 present). 대상=분해 제안 문서라 내장이 1급, 외부 슬롯은 옵션.
- [[DEC-2026-07-03-182551-task-github-v0-16-0-실행레이어-마찰을-경로-이식성-b-lite-가드로-해소]] — copymachine Wave1 피드백 6건 반영. 실행 레이어 스케일 마찰을 경로 이식성·핸드오프·공유지식·closeout 가드로 메우고 경량 토폴로지 신모드는 반려.
- [[DEC-2026-07-07-204311-분해-판정에-don-t-split-프로브와-재합침-우선-원리-도입]] — 0.18.1 dogfood(#119 Lightning Santa)에서 절단 원리 4사유가 존재했는데도 same-theme 형제 과분해가 발생 — 사유①의 '독립 조각' 판정이 표면 디렉토리 분리만 보고 공유 기반이 곧 write-set임을 놓쳤다. 절단 사유 프레임워크는 유지하되, don't-split 프로브 3개(검증 명령 동일/같은 공유 컴포넌트 수정/앞 조각 context 계속 필요)를 사유① 정직성 검사로 추가하고, write-set 겹침을 blocked_by 직렬화 신호가 아니라 재합침(phase화) 우선 신호로 재정의하며, siblings_maybe_phases 역방향 dry-run 경고와 phase 운영 규약(phase별 커밋·체크포인트·순차 세션 재진입)을 도입한다.
- [[DEC-2026-07-08-164718-studio-연극-방지-품질-체계-critic-검증-전용-delta-증거-baseline]] — 독립 판정자 critic(검증 전용·로스터 밖), anchor 없는 delta는 dry, 게이트 체계, baseline 비교 판정을 품질 체계로 채택 — 에이전트 상호 칭찬 수렴(비싼 연극) 차단이 목적.
- [[DEC-2026-07-08-164805-studio-코어-설계-채택-원시개념-run-실행-모델-소집형]] — 원시개념 5+producer, 실행 단위 run(일감×ritual×crew), 소집형 fresh-per-turn + transcript-first 캐시 배치, 리추얼별 브로커 + 공통 I/O 계약, track 동시 운영을 studio 코어 구조로 채택.
- [[DEC-2026-07-10-133541-studio-최적화-우선순위-artifact-context-품질-hard-floor와-가중-효용]] — 결과물과 컨텍스트 품질을 각각 hard floor로 보장하고, 통과한 후보만 품질에 최고 비중을 둔 token·elapsed·avoidable owner intervention 가중 효용으로 비교한다.
- [[DEC-2026-07-10-133629-studio-실행-경계-mission-quality-context-gate-소유와-선택적-single-executor]] — Studio가 mission·quality·context·owner gate를 소유하고 track별 외부 workflow는 단일 선택 executor로 위임한다. task-github와 wiki-markdown은 각각 reference adapter와 optional promotion provider이며 hard dependency가 아니다.
- [[DEC-2026-07-10-161845-작업-정의와-github-기록을-분리하고-전체-트리만-투영]] — define은 provider-neutral DefinitionArtifact를 만들고 GitHub 기록을 선택하면 root 전체 tree를 누락 없이 materialize한다.
