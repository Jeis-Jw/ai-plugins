---
title: 위키 인덱스와 조회
created_at: 2026-05-29
summary: 인덱스 파생과 조회 표면 정본: 폴더 단위 독립 인덱스, 3-stage recall + batch read, snapshot list/search/load, search_terms recognized optional, affects_paths + changed-path-stale, refresh --fix 화이트리스트. plugin-definition 영역의 sub-ssot.
tags: [wiki, retrieval, ssot]
verified_at: 2026-06-12
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
- `--read a,b,c` batch — 입력 순서 보존
- `--backlinks-of <basename>` — YAML relations에 대상 basename을 가진 record grep (본문 wikilink 무시)
- Snapshot은 `recall` 대상이 아니다. 대화 맥락 체크포인트 조회는 `snapshot list/search/load`가 담당한다.

### Search 보조

- `summary` + `tags` + 본문 ripgrep이 기본 검색 표면
- `search_terms` (선택, recognized optional) — capture 기본 생성 X, refresh 누락 검사 X, **recall Stage 1 매칭 O**
- 운영 중 검색 누락이 반복될 때 운영자가 수동 추가
- Snapshot도 `search_terms`를 가질 수 있지만 graph `recall`에는 노출하지 않고 `snapshot list/search`의 검색 표면에만 포함한다.

→ [[DEC-2026-05-29-105324-search-terms-recognized-optional]]

### Refresh 무결성 점검 (13 검사)

`stale` / `supersede` / `broken-rel` / `task-ref` / `orphan` / `index` / `retired-in-index` / `active-ref-retired` / `tags` / `changed-path-stale` / `duplicate-basename` / `empty-lesson` / `schema`.

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

반려 대안: [[REJ-2026-05-29-105502-upper-index-recursive-collection]] (상위 인덱스 재귀 수집).
