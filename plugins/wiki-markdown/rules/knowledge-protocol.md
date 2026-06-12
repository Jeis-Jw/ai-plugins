# 지식관리 프로토콜 (메커니즘 계층)

이 문서는 wiki 플러그인이 **함께 이동시키는 규약**이다(§15: mechanism / policy statement / policy rationale / knowledge 4계층 중 **mechanism**). 작업환경 운영 정책(언제·누가·무엇을 capture할지, 동시 작업을 어떻게 격리할지)은 `CLAUDE.md` / `AGENTS.md` / `.claude/` 같은 자동로드 agent-entry 표면에 둔다. 실제 축적 내용은 vault(`wiki/`)가 담는다. 본 문서는 wiki 메커니즘의 정본 — 본 플러그인을 다른 프로젝트로 옮기면 본 문서도 함께 따라간다.

본 메커니즘의 설계 배경은 이 플러그인 개발 repo의 `wiki/ssot/plugin-definition/`에 dogfood되어 있다. 본 문서는 배포되는 메커니즘 규약을 압축한다.

## 1. 타입 분류

```
wiki/
├── ssot/                       ← 현재 유효한 설계 정본 (living, nested 허용)
├── runbook/                    ← 운영 절차 (living, nested 허용)
├── task/                       ← 작업지시서형 컨텍스트 브릿지 (제3 범주: 활성 / done/ / retired/)
└── context/                    ← 의사결정 맥락 엔진 (record)
    ├── intent/                 ← 취지 (그래프의 뿌리)
    ├── decision/               ← 결정
    ├── rejected_decision/      ← 반려된 대안
    ├── trial_error/            ← 시행착오·함정·교훈
    └── observation/            ← 발견·관찰 (분류 전 임시)
```

## 2. Living vs Record vs Task (구분축)

| | **living** (ssot, runbook) | **record** (context/*) | **task** (제3 범주) |
|---|---|---|---|
| 성격 | 현재 상태 | 시점 기록 | 작업지시서형 컨텍스트 브릿지 |
| 정체성 | **주제** | **시점** | **업무** |
| 갱신 | **제자리 수정** | **불변 + supersede** | **제자리 수정**(living처럼) |
| 파일명 | `<slug>.md` | `<TYPE>-<YYYY-MM-DD-HHMMSS>-<slug>.md` | `TASK-<YYYY-MM-DD-HHMMSS>-<slug>.md` |
| 폐기 | retire 아닌 **갱신**; 주제 소멸 시 삭제 | `retired/`로 물리 이동 + `retired_type` | 완료 시 `done/` 이동(`complete`); 무효 시 `retired/`(`deprecated`) |
| 관계 작성 | **절대 안 함** (불변식) | 함 (§5) | 함 — `intents/decisions/ssot/tasks`. **순수 잎**(가리켜지지 않음) |
| stale 판정 | 시간 stale + changed-path-stale | supersede가 주된 판정. 시간/경로 stale은 타입별 (§7 표) | 이진 상태(활성/done), stale 판정 없음 |

**task 상태 = 경로**: 활성 `task/`, 완료 `task/done/`, 무효 `task/retired/`. `status` 필드 없음(경로가 정본). `complete`/`reopen`으로 활성↔done 이동. supersede 안 함. task는 외부 작업 시스템 없이도 완결되는 작업지시서형 handoff 노드다. 외부 작업 시스템과 함께 쓰이면 `relations.tasks`로 Issue/PR 등 실행 기록을 링크하지만, 위키 CLI는 외부 시스템을 호출하거나 상태를 해석하지 않는다. 연동 시 외부 작업 플러그인이 상태 정본을 갖고 `done/` 전이를 투영한다.

## 3. 문서 ID & 파일명 (§5)

- **문서 ID = 파일 basename** (확장자 제외). YAML `id` 필드 없음.
- **record**: `<TYPE>-<YYYY-MM-DD-HHMMSS>-<slug>.md`. TYPE: `INT` / `DEC` / `REJ` / `TRI` / `OBS`.
- **task**: `TASK-<YYYY-MM-DD-HHMMSS>-<slug>.md` (record와 동일 채번, 경로 `task/`).
- **living**: `<slug>.md` — 접두사·타임스탬프 없음. **vault 전역 basename 유일** (nested ssot/runbook 도입에 따른 강제).
- **인덱스**: `<폴더명>.md` (예: `ssot/ssot.md`, `ssot/auth/auth.md`, `context/decision/decision.md`). 루트는 `wiki/README.md`.
- slug는 생성 시 정하고 변경하지 않는다. 제목이 바뀌어도 파일명 불변.

## 4. Frontmatter 스키마 (§7)

### 공통 (모든 타입)

```yaml
---
title: ...
created_at: 2026-05-28       # ISO 날짜
summary: ...                 # 필수. 인덱스가 여기서 파생
tags: [...]                  # 필수. 통제 어휘 (tag-vocabulary.md)
audience: [human, agent]     # 선택. 기본 양쪽
search_terms: [...]          # 선택 (recognized optional). recall Stage 1 매칭 표면
---
```

### 타입별 한정 필드

| 필드 | 적용 타입 | 의미 |
|------|-----------|------|
| `verified_at` | **ssot/runbook 권장, trial_error/observation 선택, intent/decision/rejected_decision 없음** | 현재도 유효함을 마지막 확인한 날 |
| `affects_paths` | **ssot/runbook/trial_error/observation 선택** | 관련 코드 경로 (glob 허용: `src/auth/**`). `changed-path-stale` 기반 |
| `search_terms` | **모든 타입 선택** | 검색 보조 키워드 |

### 타입별 정리표

| 타입 | relations (자기 작성) | 생명주기 (top-level) |
|------|----------------------|--------------|
| intent | 없음 | retired 전용: `retired_at`, `retired_type`, `superseded_by` |
| decision | `intents`(이긴 취지), `rejected_decisions`, `ssot`, `tasks` | `supersedes` / retired 전용 |
| rejected_decision | `intents`(섬길 진 취지) | `supersedes` / retired 전용 |
| trial_error | `decisions`, `tasks` | `supersedes` / retired 전용 |
| **observation** | `ssot`, `runbook`, `decisions`, `tasks` | `supersedes` / retired 전용 |
| **task** | `intents`, `decisions`, `ssot`, `tasks` | 없음 (supersede 안 함; `complete`/`reopen`으로 경로 이동) |
| ssot, runbook | 없음 (`relations` 키 자체 불허) | — (retire 안 함) |

**중요**: `supersedes`, `superseded_by`, `retired_at`, `retired_type`은 **top-level 필드** — `relations` 안에 넣지 않는다.

**status 필드 없음** — active/retired는 경로(`retired/`)가 정본.
**id 필드 없음** — basename이 정본.
**v1: `classified_as` 필드 미도입** — OBS도 다른 record와 동일한 `deprecated`/`superseded` 2값 lifecycle.

## 5. 관계 모델 (§11)

### 정본과 형식

- **관계 정본 = frontmatter YAML의 plain basename**. 본문 wikilink는 사람 탐색용 장식(정본 아님).
- **관계 값 = 항상 대상의 전체 basename** (record는 `DEC-...-x`, living은 `x`). 짧은 slug 단독 사용 금지.
- **예외: `relations.tasks`** = 외부 작업 시스템 참조 (`owner/repo#N`, `github:owner/repo#N`). 위키 파일 존재 검사 대상 아님, 형식 검증만. 이 값은 링크이지 runtime 의존성이 아니며, 해석·동기화는 해당 작업 플러그인의 책임이다.
- **resolver = basename 정확 일치** (recall/refresh). **친숙 참조 해소 = 쓰기 시점(capture)에서만** — 슬러그 단편을 정규 basename으로 해소해 저장.

### 저장 규칙

- **record가 관계를 작성**한다. 허브(intent, ssot, runbook)는 작성하지 않고 **가리켜지기만** 한다(역방향은 백링크로 파생).
- 양방향 탐색은 보장(파생), 양방향 저장은 안 함. **예외: supersede 쌍**은 양쪽 저장하되 `relations`가 아니라 top-level 생명주기 필드(`supersedes`, `superseded_by`)에 저장.

### 트레이드오프 (취지 승/패)

- `decision.intents` = **이긴** 취지, `rejected_decision.intents` = **진** 취지.
- 한 intent의 백링크가 그 취지의 승/패 기록을 이룬다 — `recall --backlinks-of <INT-...>`로 통째로 조회.

### observation 관계

- observation은 `ssot` / `runbook` / `decisions` / `tasks`를 가리킬 수 있다. **intent · rejected_decision은 직접 가리키지 않는다** — 추상 원칙과 거리가 먼 임시 발견이므로, 후속 decision/trial_error가 intent와 잇는다.

### ssot의 "왜"는 어떻게 얻나

- intent가 ssot에 닿는 건 **항상 decision을 거친다** → ssot의 취지는 `ssot ← (백링크) decisions → intents`로 **파생**. 별도 저장 안 함.
- decision 없이 만든 설명적 ssot의 취지는 본문 `## 취지` prose로.

## 6. 본문 고정 섹션 (§8)

| 타입 | 고정 H2 섹션 (순서 고정) |
|---|---|
| **intent** | `## 취지`, `## 배경` |
| **decision** | `## 결정`, `## 취지`, `## 배경`, `## 고려한 대안`, `## 트레이드오프`, `## 재평가 조건` |
| **rejected_decision** | `## 대안`, `## 반려 사유`, `## 이 대안의 취지`, `## 재고 조건` |
| **trial_error** | `## 교훈`, `## 상황`, `## 피해야 할 것`, `## 대안 또는 우회`, `## 현재도 유효한가` |
| **observation** | `## 관찰`, `## 근거`, `## 영향`, `## 현재 처리`, `## 후속 분류 조건` |
| **ssot** | `## 현재 상태`, `## 취지`, `## 구성요소` |
| **runbook** | `## 목적`, `## 절차`, `## 주의점` |
| **task** | `## 개요`, `## 근거`, `## 범위와 완료 기준` |

**섹션 헤더를 임의로 바꾸지 않는다** — `recall --stage 2 --section <name>`이 이 고정성에 의존한다.

## 7. Active / Retired & 생명주기 (§9)

### context/* (record) — 불변 + supersede

- **active**: 타입 폴더 루트. **retired**: `retired/` 하위로 **물리 이동** (AI 기본 탐색·인덱스에서 제외).
- `retired_type`: `deprecated`(틀림/무효) 또는 `superseded`(당시 유효, 새 record로 대체).
- **supersede 처리**: `retire <old> --type superseded --superseded-by <new>` 또는 capture 시 `--supersedes <old>`. CLI가 양방향(old.superseded_by / new.supersedes)을 자동으로 채운다. **successor는 active context/\* record여야 한다** (ssot/runbook이나 retired record이면 거부).

### observation lifecycle 운영 가이드

- 후속 TRI/DEC/다른 OBS로 이어지면 그 record를 primary successor로 두고 `superseded_by`에 지정.
- **SSOT/runbook 갱신만 트리거된 경우에도** 그 갱신 근거가 되는 TRI/DEC/OBS를 하나 만들어 primary successor로 둔다. SSOT 갱신 자체는 그 후속 record의 `relations.ssot`/`relations.runbook`로 표현.
- 거짓 알람 또는 상황 변화로 무효가 된 경우만 `deprecated`.

### ssot / runbook (living) — retire가 아니라 **갱신**

- 현실이 바뀌면 **문서를 제자리 수정**.
- "왜 바뀌었나"는 그 변경을 일으킨 context/decision이 보유.
- 주제 자체가 **소멸**할 때만 삭제 (옛 내용은 git이 보존).
- **living은 어떤 경우에도 `relations` 키를 두지 않는다** (불변식). 늦게 발견된 영향은 새 record(observation, trial_error, 후속 decision)가 ssot를 가리킨다.

## 8. 인덱스 (§10·§14.2) — 폴더 단위 독립

- 각 폴더 인덱스(`<폴더명>.md`)는 그 폴더 내 **직속 활성 문서**의 frontmatter `summary`를 모아 **자동 파생**. 형식: `## 노트` 섹션 안에 `- [[<basename>]] — {summary}` (파일명 오름차순, `retired/` 제외).
- **상위 인덱스는 하위 폴더 문서를 중복 수집하지 않는다.** `ssot/ssot.md`는 `ssot/auth/auth-session.md`를 자기 인덱스에 넣지 않는다 — 그건 `ssot/auth/auth.md`의 책임. 재귀 = 폴더 발견, 비재귀 = 노트 수집.
- **인덱스는 직접 편집하지 않는다**. `init`·`capture`·`retire`가 자동 관리. `refresh --check index`로 동기화 점검, `refresh --fix index`로 화이트리스트 자동수정.
- 루트 `wiki/README.md`는 오리엔테이션 + 폴더 인덱스 링크 + 에이전트 탐색 힌트.

## 9. Obsidian 의존성 정책 (§12)

- **AI 검색 정본 경로 = filesystem 단일** (ripgrep + 본 CLI의 YAML 파싱).
- **obsidian-cli / Dataview / Bases / 백링크 그래프는 본 플러그인 사용 안 함**. 사람용 편의로만 호환(wikilink 문법 유지).
- 정본 데이터 모델은 도구가 아니라 파일시스템에 둔다 → 헤드리스(CI, git hook, 워크트리, 자율 에이전트)에서 깨지지 않음.

## 10. 조회 전략 (§13.4·§10)

본문 전체를 기본으로 읽지 않는다. **압축도 계층**: 인덱스(요약 모음) → Stage 1(frontmatter 요약 — `summary` + `tags` + `search_terms`) → Stage 2(섹션 추출) → Stage 3(전문) + 백링크.

- Stage 1: ≤2KB 토큰 가드, 초과 시 절단 + 필터 안내. `search_terms`에만 키워드가 있어도 매칭.
- Stage 2: 섹션당 ≤500B, 초과 시 절단 + "전문은 --read"
- 배치 read: `recall --read a,b,c` — 순서 보존, 명시 ref 묶음 읽기
- 백링크: `recall --backlinks-of <basename>` — 허브의 역방향 탐색

## 11. 스킬 책임 분담

| 스킬 (`wiki:` 서브커맨드) | 보장하는 불변식 |
|---|---|
| `init` | 폴더 구조·인덱스 뼈대 멱등 생성. 기존 노트 자동 등록. observation·task(+`done/`·`retired/`) 폴더 포함. |
| `capture` | 타입·관계·허브 불변식, ID 결정성, 인덱스 파생 갱신, supersede 자동 처리. **타입별 필드 가드** (verified_at/affects_paths 적용 타입 강제). `task` 타입 포함(supersede 불가). |
| `retire` | record(및 무효 task) 물리 이동, top-level 생명주기 필드 부여, supersede 양방향 갱신, **successor가 active context/\* record인지 검증**, 인덱스 재파생. task는 `deprecated`만 허용. |
| `complete` / `reopen` | **task 전용** — 활성(`task/`)↔done(`task/done/`) 경로 이동. 목적지 덮어쓰기 거부. 인덱스 재파생. |
| `relate` | 기존 문서 관계 보강. task는 semantic relation과 외부 task ref를 추가할 수 있고, immutable record는 `relations.tasks`만 추가 가능. 의미 관계를 바꾸려면 새 record를 `capture`한다. |
| `snapshot` | 정식 graph로 승격하기 전 대화 맥락 체크포인트 관리. `save/list/search/load/archive`를 제공하며 `snapshot/active`, `snapshot/archived`, `snapshot/promoted` 아래에 저장한다. `recall`/관계 해소/`refresh --strict`/basename 중복 검사 대상이 아니다. 기본 저장은 append-only이고, 기존 파일 갱신은 `snapshot save --update <ref>` 명시 시에만 한다. |
| `recall` | 토큰 효율(3-stage + 가드 + search_terms 매칭), retired 기본 제외(done task는 백링크에 기본 포함), basename 정확 매칭, `--read a,b,c` 배치 read |
| `refresh` | 무결성 점검 13종 (`stale` · `supersede` · `broken-rel` · `task-ref` · `orphan` · `index` · `retired-in-index` · `active-ref-retired` · `tags` · `changed-path-stale` · `duplicate-basename` · `empty-lesson` · `schema`). `task-ref`는 human-edited quoted ref를 정규화해 검사. **자동 수정은 화이트리스트만** (`--fix index,retired-in-index`). bare `--fix` 또는 그 외 인자는 거부 — 의미 판단이 필요한 수정은 사람·에이전트가 capture·Edit으로 명시 처리 |

## 12. 수집 트리거 (권장)

- 결정 직후 → `capture decision`. 결정에 묶인 함정 → `capture trial_error --decisions <DEC-...>`
- 대안 검토 후 거부 → `capture rejected_decision --intents <INT-...>` (진 취지)
- 새 설계 결정으로 시스템 상태가 바뀜 → 영향받은 `ssot` 갱신 (capture 아니라 Edit)
- 분류·결정 어디로 갈지 아직 불명확한 발견 → `capture observation` (후속 TRI/DEC로 승격 + 원본 supersede)
- 대화 맥락을 나중에 재개하고 싶지만 아직 지식 record로 정리하지 않을 때 → `snapshot save` (후속 세션은 `snapshot list/search/load`)
- 운영 절차 정립 → `capture runbook`
- 주기적(예: 주 1회 또는 큰 PR 직후) → `refresh --strict` 점검. CI에서 `refresh --check changed-path-stale`로 코드 drift 감지.

## 13. 4계층 분리 (§15)

| 계층 | 위치 | 담는 것 |
|------|------|---------|
| **mechanism** | 플러그인 (`rules/`, `skills/wiki/`, `wiki_cli.py`) | 타입집합·ID포맷·frontmatter 스키마·관계 작성·생명주기·조회 단계 |
| **policy statement** | 프로젝트 루트 `CLAUDE.md` / `AGENTS.md`, 필요 시 `.claude/` | agent 역할, 동시성 규약, leaf issue 규약, promotion triggers, agent별 capture 권한 |
| **policy rationale** | 프로젝트가 정한 운영 이력 위치. 이 플러그인 개발 repo는 `wiki/context/decision/`에 dogfood 기록 | 정책을 왜 채택했는가. 소비 프로젝트 wiki에 자동 생성하지 않음 |
| **knowledge** | `wiki/*` | 제품·서비스·시스템 지식과 작업이 낳은 context/task 기록 |

플러그인은 기본적으로 **mechanism**만 제공한다 — agent-neutral. 다만 소비 프로젝트가 자동로드 정책을 쉽게 설치하도록 `skills/agent-policy/` 스캐폴드를 함께 제공한다. 이 스캐폴드는 `CLAUDE.md`/`AGENTS.md`의 관리 블록만 병합하며, 소비 프로젝트의 `wiki/ssot/agent-operating-model.md`를 만들거나 덮어쓰지 않는다. `wiki init`도 vault 구조만 만든다.

---

본 문서는 메커니즘의 정본. 변경 시 본 플러그인 버전(plugin.json의 version)을 올리고 변경 사유를 wiki/context/decision/에 기록한다(자기 적용).
