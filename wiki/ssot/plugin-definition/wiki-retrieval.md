---
title: 위키 인덱스와 조회
created_at: 2026-05-29
summary: 인덱스·조회·proactive context 정본: 폴더 단위 독립 인덱스, 3-stage recall, snapshot 조회, changed-path-stale, 승인형 capture와 초기화 시 auto-loaded agent policy 설치 계약.
tags: [wiki, retrieval, ssot]
verified_at: 2026-08-13
affects_paths: [plugins/wiki-markdown/**]
---

## 현재 상태

### 인덱스 = 파생 (직접 작성 금지)

- 각 폴더의 `<폴더명>.md`가 인덱스 (예: `ssot/ssot.md`, `context/decision/decision.md`)
- 인덱스는 그 폴더 직속 문서의 frontmatter `summary`를 모아 **자동 생성**
- 형식: `- [[<basename>]] — {summary}`, 정렬은 파일명 오름차순
- `retired/` 제외

### 폴더 단위 독립 파생

```
재귀 = 폴더 발견   (vault 재귀 탐색해 모든 인덱스 보유 폴더 찾기)
비재귀 = 노트 수집  (각 인덱스는 자기 폴더의 직속 문서만 모음)
```

- 하위 폴더 문서는 **하위 폴더의 독립 인덱스에만** 포함
- 상위 인덱스는 하위 인덱스 *링크*는 노출 가능하지만 하위 문서 summary를 **중복 수집하지 않음**

→ [[DEC-2026-05-29-105321-folder-independent-index-derivation]]

### 3-Stage Recall

| Stage | 무엇을 | 토큰 가드 |
|-------|--------|-----------|
| 1 | frontmatter 스캔 (summary / tags / search_terms / verified_at) | ~2KB |
| 2 | 고정 섹션 추출 (H2 정규식, 본문 섹션 헤더는 계약) | 섹션당 ~500B |
| 3 | 전문 Read | — |

추가:
- `--pack` — Stage 1 매칭을 authority/freshness/use_as/warnings 라벨과 함께 결정적으로 투영하는 단일 호출 context pack(~4KB 예산). proactive recall의 기본 호출 형태.
- `--read a,b,c` batch — 입력 순서 보존
- `--backlinks-of <basename>` — YAML relations에 대상 basename을 가진 record grep (본문 wikilink 무시)
- Snapshot은 `recall` 대상이 아니다. 대화 맥락 체크포인트 조회는 `snapshot list/search/load`가 담당한다.

### Proactive Recall과 승인형 Capture 계약 (0.24.0 current)

recall/capture는 사용자의 명시 요청만 기다리지 않는다. agent·작업 플러그인·review 플러그인·대화
UI 등 모든 caller가 지키는 cross-plugin 계약이며, caller의 실행 분류나 delivery 비용은 recall·제안
여부를 바꾸지 않는다.

1. **Scoped recall 1회**: 과거 intent/decision/lesson 또는 현재 SSOT가 판단을 바꿀 수 있는
   substantive 진입점에서 결정 전에 `recall --pack`을 1회 수행하고, scope·근거·anchor가 바뀌기
   전까지 재사용한다.
2. **Ephemeral candidate**: durable 후보는 세션 컨텍스트 안에서만 모으고, 후보 보관만을 위해
   snapshot·ledger·wiki node를 만들지 않는다.
3. **Semantic milestone 감사**: 본 작업과 primary 답변을 먼저 완료한다. 의미 있는 결정 시점 또는
   closeout에 이미 가진 context로 claim+anchor 기준 internal audit을 수행한다. genuine durable 후보가
   있을 때만 같은 final 하단에 자연스러운 optional grouped capture 질문을 붙이고, 없으면 user-facing
   audit/status/`none` 문구 없이 종료한다.
4. **승인 전 write 0**: observation과 living 갱신을 포함한 모든 write는 workspace가 더 좁은
   auto-write class를 명시 opt-in하지 않는 한 사용자 승인이 먼저다. 특정 항목을 "기록해"라는
   요청 자체가 그 항목의 승인이다. 거절·보류 후보는 새 근거 없이 재제안하지 않는다.
5. **Knowledge value 독립성**: 판정 기준은 미래 재사용성·재방문/되돌리기 비용·현재 상태 영향이며
   작업 크기·실행/review 비용·호출 플러그인은 대리변수가 아니다.

**집행(0.24.0)**: raw `wiki_cli.py init`은 vault-only API로 유지한다. 사용자가 호출하는 agent-facing
`$wiki init`은 raw init 뒤 `agent-policy` workflow를 실행해 auto-loaded `CLAUDE.md`와 `AGENTS.md`의
관리 블록에 위 계약을 멱등 설치한다. 본문 밖 기존 내용은 보존한다. runtime Stop/UserPromptSubmit/
PostToolUse hook, activity/commit heuristic, transcript/session ledger, user-visible continuation은 두지
않는다. 이는 hard guarantee가 아니라 긴 작업 시작 시 한 번 로드되는 best-effort policy다. 근거
[[DEC-2026-08-13-152825-capture-정책은-초기화-시-auto-loaded-agent-entry에-설치한다]].

mechanism 정본은 `rules/knowledge-protocol.md` §12·`skills/wiki/SKILL.md`이며, 어느 workspace가
auto-write class를 여는지는 그 프로젝트의 자동로드 policy statement(CLAUDE.md/AGENTS.md) 영역이다.
`skills/agent-policy/SKILL.md`와 그 scaffold script가 설치 메커니즘을 소유한다.

### Search 보조

- `summary` + `tags` + 본문 ripgrep이 기본 검색 표면
- `search_terms` (선택, recognized optional) — capture 기본 생성 X, refresh 누락 검사 X, **recall Stage 1 매칭 O**
- 운영 중 검색 누락이 반복될 때 운영자가 수동 추가
- Snapshot도 `search_terms`를 가질 수 있지만 graph `recall`에는 노출하지 않고 `snapshot list/search`의 검색 표면에만 포함한다.

→ [[DEC-2026-05-29-105324-search-terms-recognized-optional]]

### Refresh 무결성 점검 (13 검사)

`stale` / `supersede` / `broken-rel` / `task-ref` / `orphan` / `index` / `retired-in-index` / `active-ref-retired` / `tags` / `changed-path-stale` / `duplicate-basename` / `empty-lesson` / `schema`.

각 검사는 **integrity**(그래프/데이터 정합성 — 반드시 막음) 또는 **hygiene**(파생 가능·문체 —
권고만) tier를 갖는다. `--level integrity --strict`는 integrity tier 이슈가 있을 때만 exit 6
(merge/verify 하드 게이트), `--level hygiene`는 orphan/stale/tags 등을 non-blocking 권고로만
보여준다. 기본 `--level all`은 두 tier를 함께 돈다.

#### Changed-path-stale 검사

`affects_paths`(glob) + git diff(또는 `--changed-path`) 매칭으로 `verified_at` 미갱신 living/trial_error/observation 자동 식별. 코드 변경 발 drift 능동 감지.

→ [[DEC-2026-05-29-105323-affects-paths-and-changed-path-stale]]

#### `--fix` 화이트리스트

- 허용 인자: `index`, `retired-in-index` (또는 콤마 조합)
- **bare `--fix` exit 2**, 화이트리스트 외 인자 exit 2
- 의미 판단 필요한 자동수정은 명시 capture/Edit으로

→ [[DEC-2026-05-29-105325-refresh-fix-whitelist]]

## 취지

이 조회 모델이 추구하는 일급 원칙:

- [[INT-2026-05-29-104707-token-efficient-context-loading]] — 3-stage가 토큰 효율의 핵심
- [[INT-2026-05-29-104710-ai-driven-documentation]] — 인덱스·검증을 AI가 자동 유지

## 구성요소

이 영역에 응집된 결정 anchor:

- [[DEC-2026-05-29-105321-folder-independent-index-derivation]] — 폴더 단위 독립 파생
- [[DEC-2026-05-29-105323-affects-paths-and-changed-path-stale]] — 코드 변경 drift 감지
- [[DEC-2026-05-29-105324-search-terms-recognized-optional]] — 검색 escape hatch
- [[DEC-2026-05-29-105325-refresh-fix-whitelist]] — 안전한 자동수정만
- [[DEC-2026-08-13-152825-capture-정책은-초기화-시-auto-loaded-agent-entry에-설치한다]] — runtime hook 대신 초기화 시 auto-loaded capture policy 설치

반려 대안: [[REJ-2026-05-29-105502-upper-index-recursive-collection]] (상위 인덱스 재귀 수집).
