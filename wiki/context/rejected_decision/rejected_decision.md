---
title: Rejected Decisions — 반려된 대안
created_at: 2026-05-29
summary: 이 대안이 섬길 진 취지를 보유(record).
tags: [meta]
audience: [human, agent]
---

# Rejected Decisions — 반려된 대안

이 대안이 섬길 진 취지를 보유(record).

## 노트

- [[REJ-2026-05-29-105454-sequential-numeric-id]] — DEC-00005 같은 5자리 순차 번호 ID. 단일 채번자·전역 max 스캔 + 병렬 브랜치 충돌 + 재채번 불가 = 병렬과 양립 불가. timestamp+slug로 반려.
- [[REJ-2026-05-29-105456-wikilink-as-relation-source]] — 관계 정본을 본문 [[wikilink]]로 두자는 안. 코드블록 오탐, 파싱 모호, 양방향 정합성 검사 곤란, obsidian-cli 절단 전제 붕괴로 반려. YAML plain ID가 정본.
- [[REJ-2026-05-29-105457-obsidian-cli-primary-search]] — AI 검색의 1차 경로로 obsidian-cli/Dataview/Bases를 쓰자는 안. 캐시 신선도 지연, 헤드리스 미동작, 데이터모델이 강점을 이미 대체. filesystem+ripgrep 단일로 반려.
- [[REJ-2026-05-29-105458-living-writes-relations]] — ssot/runbook이 자기 frontmatter에 relations를 쓰자는 안. 스키마 검증 복잡화, 허브 헤더 비대화. 늦게 발견된 영향은 새 record가 가리키게 해서 반려.
- [[REJ-2026-05-29-105459-plugin-spec-with-agent-names]] — CLI 인자/스키마/알고리즘 출력에 Claude/Codex 같은 특정 도구 이름 박는 안. 미래 도구 호환성 깨짐. agent별 규약은 operating model로 격리해 반려.
- [[REJ-2026-05-29-105500-obs-classified-retired-type]] — Observation 분류 완료 상태를 위한 별도 retired_type(classified) + classified_as 필드 도입 안. lifecycle 축이 무효/대체에서 분류완료로 부풀어남. 2값 모델 유지로 반려.
- [[REJ-2026-05-29-105501-promotion-auto-judgment]] — Plugin이 어떤 발견을 정식 record로 승격할지 자동 판정하는 안. 의미·운영 판단이라 자동화 시 거짓 양/음성 누적. plugin은 구조 검증만, 판정은 운영자로 반려.
- [[REJ-2026-05-29-105502-upper-index-recursive-collection]] — ssot/ssot.md가 ssot/auth/auth-session.md 같은 하위 문서 summary까지 재귀 수집하는 안. nested 도입 의도(분할)와 충돌, 중복 노출, 부모 비대화. 폴더 단위 독립으로 반려.
- [[REJ-2026-05-29-181259-task-as-immutable-record]] — task를 다른 record처럼 불변으로 두고 진행은 연결된 이슈에서만 본다 — 독립 사용 시 문서 내 상태 가시성이 없고 상태 변경마다 supersede가 비현실적이라 반려.
- [[REJ-2026-05-29-181259-task-as-living-relax-invariant]] — task를 ssot처럼 living으로 두되 관계를 갖도록 기존 불변식을 완화하는 안 — 핵심 불변식을 훼손하므로 제3 범주 신설이 더 깨끗하여 반려.
- [[REJ-2026-05-29-181259-wiki-holds-task-detailed-phase]] — 위키 task가 todo/doing/done 상세 단계를 추적하는 안 — 연결 시 GitHub 상태와 이중 정본 동기화 문제를 낳아, 이진(완료/미완)으로 축소하고 상세는 플러그인에 위임하기로 반려.
- [[REJ-2026-06-02-120300-parallel-sequential-라벨로-하위-작업-실행-순서-표현]] — 하위 작업의 병렬/직렬 가능성을 parallel/sequential 라벨로 표시하는 방식. 혼합 DAG를 표현하기 어렵고 GitHub Issue dependencies와 중복되므로 반려.
- [[REJ-2026-06-12-185220-gate-mvp를-llm-judge로-먼저-구축]] — 품질 gate MVP를 의미판정 LLM-judge로 우선 구축하는 안. in-stack judge 천장·판정 불안정·prompt 의존으로 반려, 정적 룰 v0를 먼저.
- [[REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]] — snapshot을 active/archived/promoted 3상태로 보존하고 기본 save를 append-only로 누적하며 --continues 체인을 두는 모델. 단일 active 휘발 모델에 반려.
- [[REJ-2026-07-02-212018-local-closeout-mode-유지-worktree-격리-all-pr-통합-대신]] — 컨테이너 머지업을 로컬 git merge로 유지하되 temp worktree로 격리해 메인 트리 checkout만 회피하는 대안. 로컬 머지 machinery+불변식 guard 유지 부담으로 반려하고 all-PR 통합을 채택.
- [[REJ-2026-07-03-182352-solo-경량-브랜치-토폴로지-신모드]] — 경로분리 리프를 컨테이너 브랜치·FF 머지업·gear→PR 승격 세리머니 없이 피처브랜치→단일 통합 PR(또는 리프별 직접 PR)로 두는 solo 전용 경량 토폴로지. copymachine Wave1 피드백(B)이 제안. 반려.
- [[REJ-2026-07-07-204429-orchestrate-실행-단계에서-여러-이슈를-한-워커에-묶어-처리]] — 토큰 오버헤드를 줄이려고 이미 분할된 형제 이슈 여러 개를 실행 단계에서 한 worker 세션에 묶어 배정하는 방식. 잘못 나뉜 트리를 실행에서 우회하는 것이고 1이슈=1점유 불변식을 훼손하므로 반려 — 해법은 정의 단계의 재합침(phase화)이다.
- [[REJ-2026-07-07-204429-이슈-분할-판정을-3-of-5-산술-기준으로-대체]] — 분할/비분할을 각 5개 조건 중 3개 이상 충족으로 판정하는 체크리스트 산술. 5개 조건이 사실상 한 잠재변수(독립 점유 가능성)의 변주라 상관이 높고 임계 산술은 가짜 정밀도를 만들므로 반려 — 기존 절단 사유 4개 + don't-split 프로브로 흡수한다.
- [[REJ-2026-07-08-164619-crew-상주-에이전트-sendmessage-지속-대화-방식]] — 팀원을 세션 내 상주 에이전트로 유지하며 SendMessage로 대화를 잇는 방식 — 기각, 소집형 채택.
- [[REJ-2026-07-08-164619-studio를-이슈트리-오케스트레이션-확장으로-만드는-안]] — orchestrate 위에 미션 레이어를 얹어 이슈트리 순차 처리로 팀을 구동하는 안 — 기각.
