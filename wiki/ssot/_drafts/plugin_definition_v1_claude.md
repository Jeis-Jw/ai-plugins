# AI-Native Wiki 시스템 정의·설계문서 (v1, Claude 안)

> **이 문서의 위상**: 이 문서 하나만으로 위키 플러그인 **메커니즘**을 처음부터 구현할 수 있도록, **모든 설계 결정 + 그 취지(왜) + 반려한 대안 + 구체 알고리즘 + 스킬 계약 + 예시**를 담는다. 대화 맥락 없이도 구현자가 판단할 수 있게 하는 것이 목표다. **wiki plugin 메커니즘의 단독 SSOT** — 운영 정책(`agent-operating-model.md`)은 별도 정본이며, 본 문서는 이를 ID 참조와 §15 4계층 분리로만 연결한다.
>
> 작성 기준일: 2026-05-28 | 상태: **Claude 작성 v1 초안** (Codex 측 별도 작성본과 비교·합의 후 단일 v1으로 수렴 예정)

---

## 목차

1. 목적과 철학
2. 시스템 경계
3. 문서 타입 (Taxonomy)
4. Living vs Record — 핵심 구분 축
5. 문서 ID & 파일명 규칙
6. 디렉토리 구조
7. Frontmatter 스키마 (타입별)
8. 본문 섹션 스키마 (타입별)
9. Active / Retired & 생명주기
10. 인덱스 & 탐색
11. 관계(relations) 모델
12. Obsidian 의존성 정책
13. 스킬 설계
14. 핵심 알고리즘 명세
15. mechanism / policy / agent entry / knowledge — 4계층
16. 문서 예시 (타입별)
17. 반려한 대안 모음 (취지 보존)
18. 미확정 / 후속 과제
19. 수용 기준 / 테스트
20. 한눈 요약

---

## 1. 목적과 철학

1인 풀스택 개발자가 AI 에이전트와 협업할 때 **프로젝트의 역사·설계 취지·결정 이유를 오염 없이 흡수**시키는 지식 컴퓨팅 엔진. 단순 문서 저장소가 아니다.

본 시스템은 **ADR(Architecture Decision Record) 패턴의 확장 변형**이다 — 결정/취지/거절대안/시행착오/관찰을 각각 독립 문서로 분리하고, 관계 그래프와 라이프사이클을 일급 시민으로 둔다.

**해결하려는 문제**:
- 1인 개발자는 모든 결정 이유·시행착오를 머릿속에 유지하기 어렵다.
- AI는 과거 문맥을 모르면 그럴듯하지만 틀린 결정을 반복한다.
- 반대로 AI가 폐기된 과거 문서를 읽으면 현재와 맞지 않는 구현을 한다.
- → AI가 **최소 토큰으로 현재 유효한 맥락**을 읽고, 필요할 때만 깊이 들어가는 구조가 필요.

### 핵심 원칙 (각 취지 포함)

1. **취지(intent)는 상수, 결정(decision)은 상황 함수.**
   취지를 결정과 분리된 일급 시민(독립 문서)으로 둔다.
   *취지*: 상황이 바뀌어도 유지돼야 하는 원칙을 명시하면, AI가 새 상황에서 "이 결정은 이제 안 맞지만 취지는 유효하다"를 판단할 수 있다.

2. **정보의 원자성.** 취지·결정·반려 대안·시행착오·관찰은 각각 독립 파일.
   *취지*: 한 정보가 번복돼도 다른 맥락을 오염시키지 않고, 문서마다 독립 생명주기를 가지며, AI가 특정 맥락만 선택적으로 읽기 쉽다.

3. **계층적 조회로 토큰 효율.** 인덱스(요약) → 헤더(frontmatter) → 본문 순으로 필요한 만큼만.
   *취지*: 토큰 효율이 이 시스템의 최우선 설계 제약. 본문 전체를 기본으로 읽지 않는다.

4. **primary = AI + filesystem + git.** secondary = human Markdown. optional = Obsidian.
   *취지*: 정본 데이터 모델을 도구(Obsidian)가 아니라 파일시스템에 둬야, 헤드리스·자동화·이식에서 깨지지 않는다.

5. **AI-Driven Documentation.** 사람은 결론·방향을 말하고, 문서 생성·이동·인덱스 갱신·관계 갱신·형식 검증은 에이전트가 한다.
   *취지*: 사람의 인지 부담을 결정에만 집중시키고 기계적 유지보수를 자동화한다.

6. **plugin은 agent-neutral.**
   plugin spec은 특정 AI 도구(Claude/Codex 등) 이름을 깊숙이 박지 않는다. agent별 사용 규칙은 별도 운영 모델 문서(§15)로 분리한다.
   *취지*: 미래에 새 도구를 추가하거나 도구를 교체할 때, plugin 메커니즘이 흔들리지 않게 한다.

---

## 2. 시스템 경계

- **위키 = 지식의 정본**, 작업 시스템 = 실행의 정본. 서로의 상태를 복사하지 않고 **ID로만 연결**한다.
  *취지*: 두 시스템을 과결합하면 한쪽 변경이 다른 쪽을 오염시킨다. 얇은 연결(ID 교환)만 둔다.
- 위키→작업: `relations.tasks`에 작업 ID(`owner/repo#N`). 작업→위키: 작업 쪽 Knowledge Links(본 문서 범위 밖).
- **작업 ID가 있다고 구현 완료를 의미하지 않는다** — 탐색 가능한 관련 작업 참조일 뿐.

---

## 3. 문서 타입 (Taxonomy)

```
wiki/
├── sandbox/                 ← (보류) 대화/컨텍스트 체크포인트 — §13.7
├── ssot/                    ← 현재 유효한 설계 정본 (living)
├── runbook/                 ← 운영 절차 (living)
└── context/                 ← 의사결정 맥락 엔진 (record)
    ├── intent/              ← 취지 (그래프의 뿌리)
    ├── decision/            ← 결정
    ├── rejected_decision/   ← 반려된 대안
    ├── trial_error/         ← 시행착오·함정·교훈
    └── observation/         ← 발견·관찰 (분류 전 임시)
```

### 흡수/이관 결정 (각 취지)

| 원래 타입 | 처리 | 취지 |
|-----------|------|------|
| `fact` | → **ssot** | "현재 유효한 사실·정의"는 ssot의 역할과 동일. 별도 타입 불요 |
| `pattern` | → 분산: 설계·코딩 컨벤션 **ssot**, 운영 절차 **runbook**, 실수발 교훈 **trial_error** | pattern(처방적·긍정형)과 trial_error(회고적·부정형)는 다름 |
| `overview` | → **ssot** + 루트 README | 아키텍처 정본은 ssot, 오리엔테이션은 루트 README |
| `planning` | → **작업 시스템**으로 이관 (보류) | 위키는 settled 지식만. 진행 중 기획은 작업 시스템의 영역 |
| `agent-map` | → 루트 README의 한 섹션 | 최상위 구조 고정 → 라우팅 힌트는 루트 README로 충분 |
| **observation** | **신설 타입 (context/observation/)** | trial_error는 교훈 강제, observation은 교훈 없음 허용 — 라이프사이클 분리 |

### 3.7 Promotion Threshold

```
정식 record로 승격되는 정보는 장기 재사용 가능성, 구조적 영향, 반복 가능성, 되돌리기 비용, 후속 작업자가 알아야 할 필요성 중 하나 이상을 가져야 한다.

plugin은 승격 판단 자체를 자동화하지 않는다. plugin은 capture된 문서가 타입별 구조 조건과 스키마를 만족하는지만 검증한다.
```

운영 트리거(어떤 상황에 어느 타입을 capture하나)는 **agent-operating-model의 영역** — agent-neutral 유지를 위해 plugin spec에는 두지 않는다.

---

## 4. Living vs Record — 핵심 구분 축

타입을 두 부류로 가르는 본질. 갱신 방식·생명주기·관계·파일명이 모두 여기서 갈린다.

| | **ssot / runbook** (living) | **context/** intent·decision·rejected·trial·**observation** (record) |
|---|---|---|
| 성격 | 현재 상태 | 시점 기록 |
| 정체성 | **주제** (auth 설계는 10번 고쳐도 그 문서 하나) | **시점** (각 기록은 별개 사건) |
| 갱신 | **제자리 수정** | **불변 + supersede** (모든 record 동일) |
| 파일명 | `<slug>.md` | `<TYPE>-<타임스탬프>-<slug>.md` |
| 폐기 | retire 아닌 **갱신**; 대상 소멸 시 삭제 | `retired/` 이동 + `retired_type` |
| 이력 | git + context의 결정들이 "왜 바뀌었나" 보유 | 기록 자체가 이력 |
| 관계 작성 | **절대 안 함** — 불변식 (전부 파생) | 함 (§11.3) |

*취지*: 이 구분이 context를 별도로 묶은 이유(=의사결정 *맥락 엔진*)와 정확히 맞물린다. "지금 어떻게?"는 ssot 본문, "왜/어떻게 변해왔나?"는 context 추적.

### stale-check 의미론

active record는 묵시적으로 "현재 유효". stale-check는 다음에 한정:

| 타입 | 시간 stale (verified_at 경과) | changed-path-stale (코드 변경 trigger) |
|---|---|---|
| ssot | ✅ | ✅ |
| runbook | ✅ | ✅ |
| trial_error | ✅ (verified_at 있으면) | ✅ |
| observation | ❌ | ✅ |
| intent | ❌ | ❌ |
| decision | ❌ | ❌ |
| rejected_decision | ❌ | ❌ |

*취지*: intent/decision/rejected는 supersede 여부로만 유효성 판정. timestamp 기반 stale은 living + 함정/관찰 영역. observation은 임시 상태라 시간 stale 무의미(분류 강제는 §18 OBS aging 후속에서 검토).

---

## 5. 문서 ID & 파일명 규칙

- **문서 ID = 파일 basename** (확장자 제외). YAML `id` 필드 없음.
  *취지*: 파일명이 이미 canonical ID. `id` 필드는 불일치 위험만 만든다. 참조·링크·검색 모두 basename 기준이면 단순하다.

- **record (context/*)**: `<TYPE>-<YYYY-MM-DD-HHMMSS>-<slug>.md`
  - TYPE: `INT`/`DEC`/`REJ`/`TRI`/`OBS`
  - 예: `DEC-2026-04-17-143052-switch-to-bff.md`, `OBS-2026-05-28-153000-webhook-timeout-risk.md`
  - *취지*: 타임스탬프는 **채번 조율 0**(날짜는 로컬 지식) → 병렬 워크트리에서 안전. 파일명 사전순=시간순.

- **living (ssot/runbook)**: `<subject-slug>.md` — 접두사·타임스탬프 없음.
  - 예: `auth-architecture.md`, `glossary.md`, `deploy.md`
  - *취지*: living은 정체성이 "생성 시점"이 아니라 "주제". 타입은 폴더가, 관계에선 relation 키가 알려주므로 접두사도 중복.

- **인덱스**: `<폴더명>.md` (예: `ssot/ssot.md`, `context/decision/decision.md`). nested 폴더의 경우 폴더별 인덱스(§10). 루트는 `wiki/README.md`.
  - **규칙: `<폴더명>.md` = 인덱스, 그 외 = 내용.**

- slug는 생성 시 정하고 변경하지 않는다(영구 별칭). 제목이 바뀌어도 파일명 불변. 의미가 정체성 수준으로 바뀌면 기존을 retire/삭제하고 새 문서로.

### basename 전역 유일성

**vault 전역에서 모든 wiki 문서의 basename은 유일해야 한다.** 폴더 중첩(§6) 도입에 따라 명시.

- ✅ `ssot/auth/session.md` + `ssot/payment/checkout.md`
- ❌ `ssot/auth/session.md` + `ssot/payment/session.md` ← basename 충돌

*취지*: §11.1 resolver가 basename 정확 일치이므로 전역 유일은 이미 함의되어 있지만, 폴더 중첩이 가능해진 v1에서 명시 필수. refresh의 `duplicate-basename` 검사가 강제.

### 충돌 처리

- record: 충돌은 *같은 TYPE + 같은 초 + 같은 slug* 가 동시에 맞아야만 발생. slug가 다르면 같은 초여도 안 겹침. → 사실상 0. capture가 생성 시 존재검사 후, 충돌하면 짧은 접미사(`-b`)를 붙인다(타임스탬프 위조 금지).
- living: 주제 slug는 vault 전역 유일. 충돌 = 같은 주제 중복 → 기존 문서를 갱신.

---

## 6. 디렉토리 구조 (상세)

```
wiki/
├── README.md                          ← 루트 인덱스 (오리엔테이션 + 인덱스 링크 + 에이전트 탐색 힌트)
├── sandbox/                           ← (보류)
├── ssot/
│   ├── ssot.md                        ← 인덱스 (파생)
│   ├── plugin_definition.md           ← 본 정본
│   ├── agent-operating-model.md       ← 운영 모델 정본
│   ├── auth-architecture.md
│   ├── glossary.md
│   └── auth/                          ← nested 허용
│       ├── auth.md                    ← 영역 인덱스
│       ├── auth-session.md
│       └── auth-token-refresh.md
├── runbook/
│   ├── runbook.md
│   └── deploy.md
└── context/
    ├── intent/
    │   ├── intent.md
    │   ├── INT-<ts>-speed.md
    │   └── retired/
    ├── decision/
    │   ├── decision.md
    │   ├── DEC-<ts>-switch-to-bff.md
    │   └── retired/
    ├── rejected_decision/
    │   ├── rejected_decision.md
    │   ├── REJ-<ts>-email-auth.md
    │   └── retired/
    ├── trial_error/
    │   ├── trial_error.md
    │   ├── TRI-<ts>-kakao-redirect-uri.md
    │   └── retired/
    └── observation/
        ├── observation.md             ← 인덱스
        ├── OBS-<ts>-<slug>.md
        └── retired/
```

- **ssot/runbook은 폴더 중첩 허용**. 영역이 커지면 폴더+인덱스로 분할.
- **ssot/runbook에는 `retired/`가 없다** (§4, §9).
- "비대화 대비 미리 분할"은 YAGNI — 실제 분할 필요 시 수행.

---

## 7. Frontmatter 스키마 (타입별)

### 공통

```yaml
---
title: ...
created_at: 2026-05-28       # ISO 날짜
summary: ...                 # 필수. 인덱스가 여기서 파생
tags: [...]                  # 필수. faceted 검색 근거
audience: [human, agent]     # 선택. 기본 양쪽
---
```

### 타입별 한정 필드

| 필드 | 범위 | 의미 |
|------|------|------|
| `verified_at` | **living 권장, trial_error/observation 선택, 나머지 없음** | "현재 유효함을 마지막 확인한 날" |
| `affects_paths` | **ssot/runbook/trial_error/observation 선택** | 관련 코드 경로 (glob 허용: `src/auth/**`) |
| `search_terms` | **모든 타입 선택** (recognized optional field) | 검색 보조 키워드. capture 기본 생성 X, refresh 검사 X |

### 메타 규칙

- **`status` 필드 없음** — active/retired는 **경로**가 정본. *취지*: 경로와 YAML이 같은 상태를 이중 표현하면 불일치한다.
- **`id` 필드 없음** — basename이 정본.
- **`relations`는 record 타입에만**. ssot/runbook은 키 자체를 두지 않는다 (불변식).
- **생명주기 필드는 top-level** (relations 안에 두지 않음):
  - `supersedes`, `superseded_by`, `retired_at`, `retired_type` (모든 record 공통)

### 필드별 취지

| 필드 | 취지 |
|------|------|
| `summary` | Stage-1 검색 표면. 제목 재탕이 아니라 **핵심 내용에서 추출한 자족적 한 줄**, 검색 키워드 포함 |
| `tags` | 자유 태그는 드리프트로 검색 정확성↓ → **통제 어휘**: `ssot/tag-vocabulary.md`의 `## 어휘` 목록이 허용 집합. refresh가 어휘 밖 태그를 플래그 |
| `verified_at` | "사실/설계는 부패한다." living(ssot/runbook)에 특히 중요. record 중에서는 trial_error/observation만 의미 |
| `affects_paths` | 코드 변경과 문서의 능동적 drift 감지(§13.5). refresh의 `changed-path-stale` 검사 기반 |
| `search_terms` | summary+tags+본문 ripgrep 외의 escape hatch. capture/refresh 무관 |
| `audience` | AI-native 시스템이므로 사람용/에이전트용 구분 축 |

### 타입별 정리표

| 타입 | verified_at | affects_paths | search_terms | relations (자기 작성) | 생명주기 top-level |
|------|-------------|---------------|--------------|----------------------|-------------------|
| intent | 없음 | 없음 | 선택 | 없음 | retired 전용 |
| decision | 없음 | 없음 | 선택 | intents, rejected_decisions, ssot, tasks | supersedes / retired 전용 |
| rejected_decision | 없음 | 없음 | 선택 | intents | supersedes / retired 전용 |
| trial_error | 선택 | 선택 | 선택 | decisions, tasks | supersedes / retired 전용 |
| **observation** | 선택 | 선택 | 선택 | ssot, runbook, decisions, tasks | supersedes / retired 전용 |
| ssot | 권장 | 선택 | 선택 | 없음 | — (retire 안 함) |
| runbook | 권장 | 선택 | 선택 | 없음 | — |

### search_terms — recognized optional field

```
search_terms는 선택 필드다. capture는 기본 생성하지 않고, refresh도 누락을 플래그하지 않는다.
운영 중 summary + tags + 본문 ripgrep만으로 검색 누락이 반복될 때, 운영자가 수동으로 추가할 수 있다.
운영 데이터 누적 후 권장 필드 승격 여부 재검토는 §18 후속.
```

---

## 8. 본문 섹션 스키마 (타입별)

> 고정 섹션 헤더는 **계약**이다. Stage-2(섹션 단위 조회)가 이 고정성에 의존한다. 정확한 안내 문구는 구현(템플릿) 단계에서 확정하되, **섹션 집합과 순서는 본 설계로 고정**한다.

| 타입 | 고정 섹션 |
|------|-----------|
| **intent** | `## 취지`, `## 배경` |
| **decision** | `## 결정`, `## 취지`, `## 배경`, `## 고려한 대안`, `## 트레이드오프`, `## 재평가 조건` |
| **rejected_decision** | `## 대안`, `## 반려 사유`, `## 이 대안의 취지`, `## 재고 조건` |
| **trial_error** | `## 교훈`, `## 상황`, `## 피해야 할 것`, `## 대안 또는 우회`, `## 현재도 유효한가` |
| **observation** | `## 관찰`, `## 근거`, `## 영향`, `## 현재 처리`, `## 후속 분류 조건` |
| **ssot** | `## 현재 상태`, `## 취지`(설명적 문서일 때 prose), `## 구성요소` |
| **runbook** | `## 목적`, `## 절차`, `## 주의점` |

### 섹션 취지

- **decision의 `## 재평가 조건`**: 현역 결정의 **전향적 만료 트리거** — "어떤 조건이면 다시 검토해야 하나". record에만 의미 있다(living은 그냥 고친다).
- **trial_error의 `## 현재도 유효한가`**: active+resolved 판단 근거 — 해결됐어도 다시 밟을 함정이면 active 유지.
- **observation의 `## 후속 분류 조건`**: decision의 `## 재평가 조건`과 짝 — 사전에 분류 기준을 박아두면 라이프사이클이 결정적. capture 시점에 미래를 다 알 수 없으므로 사전 조건이 자연.
- **ssot의 `## 취지`**: decision 없이 만든 설명적 ssot의 "왜"를 본문 prose로 담는 자리(관계 그래프 아님).

### observation 섹션 의미

```
관찰: 무엇을 발견했는가
근거: 어떤 파일, 테스트, 로그, 현상에 기반하는가
영향: 왜 나중에 중요할 수 있는가
현재 처리: 이번 작업에서 처리했는가, 보류했는가, 우회했는가
후속 분류 조건: 어떤 조건이면 TRI/DEC/SSOT 갱신/retire로 이동하는가
```

---

## 9. Active / Retired & 생명주기

### context/* (record) — 불변 + supersede

- active: 타입 폴더 루트. retired: `retired/` 하위로 **물리 이동**(AI 기본 탐색·인덱스에서 제외).
  *취지*: 상태값만 바꾸는 것보다 물리 격리가 검색 오염을 확실히 줄인다.

- **`retired_type`** (모든 record 공통, 2값):
  - `deprecated`: 틀림/무효 (거짓 알람, 상황 변화로 무효가 됨)
  - `superseded`: 당시 유효했으나 새 record로 대체

- **supersede 처리**: 새 record가 기존 record를 대체하면 — 새 문서 top-level `supersedes:[old]`, 기존 문서 top-level `superseded_by:new`, `retired_type:superseded`, `retired_at` 기록 후 `retired/` 이동. 이 쌍은 양방향 **저장**(§11.4 예외).

### observation 라이프사이클 (다른 record와 동일한 2값 모델)

```
active OBS
  ├── (후속 TRI/DEC/다른 OBS로 승격·대체) → retired_type: superseded + superseded_by
  └── (거짓 알람 또는 상황 변화로 무효) → retired_type: deprecated
```

**OBS retire 운영 가이드**:

- OBS가 후속 TRI/DEC/다른 OBS로 이어지면 그 후속 record를 primary successor로 두고 `superseded_by`에 지정.
- **OBS가 SSOT/runbook 갱신만 트리거한 경우에도**, 그 갱신의 근거가 되는 TRI/DEC/OBS를 하나 만들어 primary successor로 둔다. SSOT 갱신 자체는 그 후속 record의 `relations.ssot`/`relations.runbook`로 표현된다.
  - *취지*: lifecycle 축을 "무효/대체" 2값으로 단일화. "분류 완료"는 별도 상태가 아니라 "근거 record로 대체됨"으로 흡수해 retire 모델·검증·예시·테스트의 비대화를 막는다.
- 거짓 알람·상황 변화로 무효가 된 경우만 `deprecated`.

**v1 단순화 — `classified`/`classified_as` 미도입**:

- v1은 다른 record와 동일하게 `deprecated`/`superseded` 2값만 사용 (§17 반려 항목).
- 다중 분류 케이스(한 OBS가 TRI + SSOT 양쪽 트리거)는 primary successor + 후속 record의 `relations.ssot` 조합으로 표현.
- 다중 분류 문제가 실제 운영에서 반복되면 v2에서 `classified`/`classified_as` 재검토 (§18).

### ssot / runbook (living) — retire가 아니라 **갱신**

- 현실이 바뀌면 **문서를 제자리 수정**(현재 정본은 하나여야 하므로).
- "왜 바뀌었나"는 그 변경을 일으킨 **context/ 결정들**이 보유. ssot 본문=지금 어떻게, context 추적=왜/어떻게 변해왔나.
- 주제 자체가 **소멸**할 때만 삭제 — 삭제 근거도 context/ 결정, 옛 내용은 git이 보존.
- **living은 어떤 경우에도 `relations`를 작성하지 않는다 (불변식).** 결정의 ssot 영향이 *나중에* 발견되면, 그 발견 자체가 새 record(observation 또는 trial_error 또는 후속 decision)가 되어 ssot를 가리킨다 — 링크는 항상 record 쪽.

---

## 10. 인덱스 & 탐색

### 인덱스 = 파생 (직접 작성 금지)

- 각 폴더 인덱스(`<폴더명>.md`)는 그 폴더 내 문서의 frontmatter `summary`를 모아 **자동 생성**.
  *취지*: 요약이 본문/인덱스에 이중 존재하면 드리프트. `summary`를 정본으로 두고 인덱스는 투영 → 표류 0.
- **nested 폴더는 폴더별 독립 인덱스**. 예:
  - `ssot/ssot.md` ← `ssot/` 직속 문서들
  - `ssot/auth/auth.md` ← `ssot/auth/` 직속 문서들
  - 재귀 아닌 **폴더 단위 독립**.
- 형식: `- [[<basename>]] — {summary}`. 정렬: 파일명 오름차순. `retired/`는 제외.
- 압축도 계층: **인덱스(요약 모음) → 헤더 summary(한 줄) → 본문(전체)**.

### 루트 README (3역)

1. 오리엔테이션(이 위키가 무엇인가)
2. 각 폴더 인덱스로의 링크
3. **에이전트 탐색 힌트** — "이런 질문 → 이 폴더/인덱스" 라우팅. 최상위 구조가 고정이라 작고 안정적.

### 조회 전략 (recall 스킬, §13.4)

본문 전체를 기본으로 읽지 않는다. Stage 1(요약) → Stage 2(섹션) → Stage 3(전문) → 백링크.

---

## 11. 관계(relations) 모델

### 11.1 정본과 형식

- **관계 정본 = frontmatter YAML의 plain ID.** 본문 wikilink는 사람 탐색용 장식(정본 아님).
  *취지*: AI가 본문이 아니라 YAML을 grep해 그래프를 푼다 → 코드블록 오탐 0.
- **위키 문서 관계 값 = 항상 대상의 전체 basename (= 문서 ID).** record는 `DEC-2026-04-17-143052-switch-to-bff`, living은 `auth-architecture`. 짧은 slug 단독은 **쓰지 않는다.**
- **예외: `relations.tasks`는 외부 작업 시스템 참조.** MVP 값은 GitHub issue ref(`owner/repo#N`). 위키 파일 존재 검사 대상 아님.
- **resolver = basename 정확 일치.** slug 부분 일치·fuzzy 해소 안 함(동일 slug·다른 타임스탬프 충돌 방지).
- **친숙한 참조의 해소는 쓰기 시점(capture)에서만.** capture가 사람이 입력한 slug/제목 조각을 정규 basename으로 해소해 **저장은 항상 basename**.

### 11.2 저장 규칙: "적은 쪽(low-cardinality)에 저장"

- **record(decision, rejected_decision, trial_error, observation)가 관계를 작성**한다.
- **뿌리/허브(intent, ssot, runbook)는 아무것도 작성하지 않는다** — 가리켜지기만 하고 역방향은 **파생**(백링크).

*취지*: 허브(특히 living)는 시간이 가며 수많은 record의 표적이 된다. 허브에 역방향 목록을 쌓으면 헤더가 비대해지고 Stage-1이 비싸진다. 기록은 불변이라 한 번 적힌 링크가 자라지 않는다.

### 11.3 작성 테이블 (이 문서가 자기 헤더에 적는 것)

| 문서 | 적는 relations |
|------|----------------|
| **decision** | `intents`(이 결정의 **이긴 취지**), `rejected_decisions`, `ssot`, `tasks` |
| **rejected_decision** | `intents`(이 대안이 섬길 **진 취지**) |
| **trial_error** | `decisions`, `tasks` |
| **observation** | `ssot`, `runbook`, `decisions`, `tasks` |
| **intent** | 없음 |
| **ssot / runbook** | 없음 (불변식 — `relations` 키 자체를 두지 않음) |

*observation 취지*: 실행 중 발견은 정본(ssot/runbook) 또는 결정(decision)·task에 닿는다. intent에 직접 닿는 경우는 드묾(추상 원칙과 거리 멂).

### 11.4 양방향성

- **양방향 "탐색 가능"**: 보장(파생으로). 그래프는 양쪽 다 다닌다.
- **양방향 "저장"(중복 기입)**: 안 함 — 누적형 관계 비대화.
- **예외**: supersede 쌍은 카디널리티 낮고 `superseded_by`를 독자가 따라가야 하므로 **양쪽 저장**한다. 단, 이는 `relations`가 아니라 top-level 생명주기 필드(`supersedes`, `superseded_by`)에 저장.

### 11.5 취지 트레이드오프

- 결정은 **취지 간 트레이드오프**. `decision.intents`=이긴 취지, `rejected_decision.intents`=진 취지.
- 진 취지는 결정의 이긴 취지에서 **파생되지 않으며**, 공유 INT 문서라 다른 결정/반려에서 재사용된다.
- 효과: 한 intent의 백링크가 **승/패 기록**을 이룬다 — decisions에서 오면 *이긴 자리*, rejected_decisions에서 오면 *진 자리*. → "이 취지를 시간에 따라 어떻게 저울질해왔나"가 통째로 조회된다.

### 11.6 ssot의 "왜"는 어떻게 얻나

- intent가 ssot에 닿는 건 **항상 decision을 거친다** → ssot의 취지는 `ssot ← (백링크) decisions → intents`로 **파생**. 별도 저장 안 함(중복·드리프트·비대화 회피).
- decision 없이 만든 설명적 ssot의 취지는 **본문 prose**(`## 취지`)로.

---

## 12. Obsidian 의존성 정책

**원칙: "Obsidian-호환 뷰어 지원, Obsidian 런타임 의존 0."**

- **AI 검색 정본 경로 = filesystem 단일**(ripgrep + YAML 파싱). 폴백/주경로 이원화 없음.
- **obsidian-cli / Dataview / Bases / 백링크 그래프는 AI 파이프라인에서 제외.** 사람용 편의일 뿐, 어떤 시스템 기능도 이를 요구하지 않는다.
- **근거(취지)**:
  - AI가 주 작성자 → obsidian-cli 메타데이터 캐시 **신선도 지연** 위험.
  - CI·git hook·자율 에이전트·워크트리 등 **헤드리스**에서 Obsidian 미동작.
  - **양방향 관계(파생) + 관계정본 YAML + ISO 날짜**가 obsidian-cli 강점(백링크·alias·타입 쿼리)을 데이터모델로 이미 대체.
  - 1인 vault 수천 노트는 ripgrep 수십 ms — 사전 인덱스 불요.
- **wikilink 문법은 유지**: `[[basename]]`은 파일이 `retired/`로 이동해도 안 깨지고(이동 내성) Obsidian 클릭 탐색 공짜. 단 **정본 아님**.
- `.obsidian/`은 개인 설정 → **gitignore**.
- **Bases**: 선택적 부가물(init 자동 설치 안 함).

---

## 13. 스킬 설계

> 스킬 **계약**(목적·CLI 인자·출력·에러·취지)을 확정한다. 실제 코드는 구현 단계.

### 13.0 공통 규약

- **출력 모드**: 기본 사람용 텍스트. `--json`이면 기계용 JSON — 성공 `{ "ok": true, ... }`, 실패 `{ "ok": false, "error_code": "...", "message": "..." }`.
- **dry-run**: 쓰기 스킬(init, capture, retire)은 `--dry-run` 지원.
- **exit code**: `0` 성공 · `2` 인자/사용 오류 · `3` vault 없음 · `4` 검증 실패 · `5` 충돌(living slug 기존) · `6` refresh `--strict`에서 이슈. (`1` 일반 오류.)
- **vault 경로**: 기본 `wiki/`. `--vault <path>`로 변경.
- **위키 문서 관계 참조 해소**: 인자의 slug/제목 조각 → 정규 basename(§11.1). 복수 매칭/부재 → exit 4. `--tasks`는 외부 작업 ID이므로 형식만 검사한다.
- **agent-neutral**: CLI/출력에 Claude/Codex 등 특정 도구 이름을 사용하지 않는다(§17 반려).

### 13.1 init — vault 초기화 (멱등)

- **목적**: `wiki/` 구조·폴더·루트 README·각 폴더 인덱스 뼈대 생성.
- **CLI**: `init [--vault <path>] [--dry-run] [--json]`
- **동작**: 폴더(§6) 생성(observation 포함) → 루트 README + 각 `<폴더명>.md` 인덱스 생성(없을 때만) → 기존 문서 스캔해 인덱스 자동 등록.
- **출력**: 생성/유지 항목 목록. **에러**: `1`(FS 오류).
- **취지**: 멱등 — 재실행해도 기존 파일 안 덮어쓰고 누락만 보충.

### 13.2 capture — 정식 문서 생성

```
capture <type> --title <t> --summary <s> --tags a,b [--slug <s>]
        [--intents <ref,..>] [--ssot <ref,..>] [--runbook <ref,..>]
        [--rejected <ref,..>] [--decisions <ref,..>] [--tasks <id,..>]
        [--supersedes <ref>] [--affects-paths <p,..>] [--search-terms <t,..>]
        [--verified-at <date>] [--audience human,agent]
        [--vault <path>] [--dry-run] [--json]
```

- 필수: `type` ∈ {intent, decision, rejected_decision, trial_error, observation, ssot, runbook}, `--title`, `--summary`, `--tags`. `--slug` 미지정 시 title에서 kebab-case 파생.
- 관계 인자는 §11.3을 따른다. **허브 타입(intent/ssot/runbook)에 관계 인자 → exit 2.**
- **observation은 ssot/runbook 관계 가능**. intent 관계는 허용 안 함 → exit 2.
- **promotion threshold 검증**: type별 구조 조건(§8 고정 섹션 존재, 필수 frontmatter)이 충족 안 되면 거부. 의미적 승격 가치 판정은 안 함(§3.7).
- **동작**: type 검증 → 경로·basename 결정(§14.1) → frontmatter 채움 + §8 고정 섹션 배치(빈) → 위키 문서 관계 참조를 basename으로 해소·존재 검증, `tasks`는 형식 검증 → `--supersedes` 시 §14.4 → 인덱스에 summary 투영(§14.2).
- **출력**: 생성 경로·basename(ID)·인덱스 갱신·supersede 결과.
- **에러**: `2`(타입/인자 오류, 허브+관계), `3`(vault 없음), `4`(관계 대상 모호/부재), `5`(living slug 기존 존재 → "갱신하세요").

### 13.3 retire — record 비활성화

```
retire <basename> --type deprecated|superseded [--superseded-by <ref>]
       [--vault <path>] [--dry-run] [--json]
```

- 대상은 context/* record만 허용. ssot/runbook은 retire하지 않는다.
- `--type superseded`이면 `--superseded-by` 필수. 해당 참조는 basename으로 해소·존재 검증.
- `--type deprecated`이면 `--superseded-by` 금지.
- **OBS도 다른 record와 동일하게 2값 모델**. SSOT/runbook 갱신만 트리거된 OBS도 primary successor record를 만들어 `superseded` 처리(§9 운영 가이드).
- **동작**: 대상 active record 확인 → top-level 생명주기 필드 기록 → supersede 양방향 갱신(해당 시) → 같은 타입 폴더의 `retired/`로 물리 이동 → 인덱스 재파생.
- **출력**: 이동 전/후 경로·retired_type·supersede 갱신 결과.
- **에러**: `2`/`3`/`4`/`1`.

### 13.4 recall — 계층적 조회 (filesystem 단일, 읽기 전용)

```
recall [query] [--type <t>] [--tag <t>] [--section <name>]
       [--stage 1|2|3] [--limit <N>] [--backlinks-of <basename>]
       [--read <basename[,basename...]>] [--include-retired]
       [--vault <path>] [--json]
```

- **Stage 1**: ripgrep frontmatter 스캔 → `summary` / `tags` / `search_terms`(있으면) / `verified_at`. **토큰 가드 ~2KB**, 초과 시 상위 N + "필터 추가" 제안.
  - `search_terms`는 recognized optional field(§7). 생성·필수 검사는 안 하지만, 있는 경우 Stage 1 매칭 대상에 포함된다.
- **Stage 2**: 고정 섹션(§8) 추출(H2 정규식). **섹션당 ~500B**, 초과 시 절단 + "전문은 --read".
- **Stage 3**: 전문 Read.
- **백링크**(`--backlinks-of`): YAML relations에 대상 basename을 가진 record grep(§14.3). `retired/` 기본 제외(`--include-retired`로 포함).
- **`--read a,b,c` batch 모드**:
  - 입력 순서 보존
  - 존재하지 않는 basename → exit 4
  - JSON 모드: basename별 결과 배열
  - retired 기본 제외, `--include-retired`로 포함
- **출력**: stage별 스키마(JSON이면 배열). 0건도 성공(exit 0).
- **에러**: `2`(인자), `3`(vault 없음), `4`(존재하지 않는 basename).

### 13.5 refresh — 무결성 점검

```
refresh [--check <name|all>] [--days <N>] [--path <subdir>] [--fix <c,..>]
        [--strict] [--vault <path>] [--json]
```

- `--check` ∈ {stale, supersede, broken-rel, task-ref, orphan, index, retired-in-index, active-ref-retired, tags, **changed-path-stale**, **duplicate-basename**, **empty-lesson**, all}. 기본 `all`.
- `--days`: stale 기준(기본 90). `--strict`: 이슈 ≥1건이면 exit 6(CI 게이트). 기본은 점검만 (exit 0).
- **검사**:
  - `stale`: living + (verified_at 있는 trial_error)의 verified_at > N일. **observation은 시간 stale 미적용** (changed-path-stale만, §4 표).
  - `supersede`: supersede 쌍 양방향
  - `broken-rel`: relations.* 중 tasks 제외 값이 실파일(또는 retired/)로 존재
  - `task-ref`: relations.tasks의 `owner/repo#N` 형식
  - `orphan`: 어디서도 안 가리켜지는 record
  - `index`: 인덱스 동기화 (파생 vs 현재)
  - `retired-in-index`: retired/ 문서가 인덱스에 남아있음
  - `active-ref-retired`: active 문서가 retired/ 가리킴(냄새)
  - `tags`: 어휘 밖 태그 (`ssot/tag-vocabulary.md` 없으면 skip)
  - **`changed-path-stale`**: git diff 경로가 `affects_paths`(glob) 매칭이고 `verified_at` 미갱신 (대상: living + trial_error/observation). 단순 코드 read는 ssot 갱신 불요 — 의도된 트레이드오프.
  - **`duplicate-basename`**: vault 전역 basename 중복 검사. 폴더 중첩 도입의 안전망(§5).
  - **`empty-lesson`**: trial_error의 `## 교훈` 섹션이 placeholder만이거나 비어있음 플래그. observation으로 권장하는 운영 신호.
- **`--fix` 화이트리스트**:
  - 허용: `index`(인덱스 동기화), `retired-in-index`(인덱스에서 retired 제거).
  - 그 외 시도 시 거부.
  - 실행 시 stdout에 변경 내역 보고(silent 변경 금지).
- **취지**: 자동수정 안 하는 이유 — 대부분 검사는 **내용 판단** 필요. 리포트→사람/에이전트가 capture·Edit으로 명시 처리해야 추적 가능. 화이트리스트 항목만 순수 파생이라 안전.

### 13.6 promote — sandbox → 정식 (보류, 계약만)

- sandbox 노트의 결론을 추출해 정식 문서(DEC/INT/REJ/TRI/OBS/SSOT…) 생성 + sandbox에 산출물 basename 기록.
- promotion threshold(§3.7)의 **구조 조건만 검증**, 운영 판정은 안 함(agent-operating-model 영역).

### 13.7 sandbox save / load (보류)

- `save`: 현재 논의 상태를 **합성**해 `wiki/sandbox/<topic-slug>.md`에 기록/갱신(스레드 진화형).
- `load`: 파일명으로 읽어 재주입. 인자 없으면 목록.
- 정식 그래프 밖(ID·relations·검색·점검 제외). 승격은 명시적.

---

## 14. 핵심 알고리즘 명세

### 14.1 ID/파일명 생성

```
record:  basename = "{TYPE}-{date +%Y-%m-%d-%H%M%S}-{slug}"
         TYPE ∈ {INT, DEC, REJ, TRI, OBS}
         존재하면 "-b","-c"... 접미사 (타임스탬프 위조 금지)
living:  basename = "{slug}"; 존재하면 → 신규 생성 대신 갱신 안내
         basename 전역 유일성 검증 — 중복 시 exit 5
slug:    제목 kebab-case, 공백·특수문자 '-', 생성 후 불변
```

### 14.2 인덱스 파생

```
for folder in vault 내 모든 인덱스 보유 폴더 (재귀 탐색, retired/ 제외):
  index = "{folder}/{basename(folder)}.md"
  notes = folder 직속 *.md 중 인덱스·retired/ 제외, 파일명 오름차순
  # nested 폴더는 폴더별 독립 (재귀 아님)
  for d in notes: summary = frontmatter(d).summary
  index 본문 "## 노트" 섹션을 "- [[{basename(d)}]] — {summary}" 목록으로 갱신(멱등)
```

### 14.3 백링크 파생 (허브의 역방향)

```
# "이 허브를 가리키는 record들" — YAML relations만 스캔(본문 wikilink 무시)
target = basename(hub)            # 예: auth-architecture, INT-2026-01-10-090000-speed
rg -U --multiline 'relations:' context/**/*.md  로 후보 추출 후
각 record의 relations.* 값에 target 포함 여부 검사 (retired/ 제외)
→ intent의 승/패: relations.intents에 target 포함하는 decision(승) / rejected_decision(패)
→ ssot의 영향 record: 가리키는 decision/observation/trial_error
```

### 14.4 supersede 처리

```
# supersede (모든 record 공통, OBS 포함)
new.supersedes      += [old_basename]      # top-level
old.superseded_by    = new_basename        # top-level
old.retired_type     = "superseded"
old.retired_at       = today
old 파일을 같은 폴더의 retired/ 로 이동
양방향 일관성 확인
```

### 14.5 무결성 검사 핵심

```
stale:                  living + (trial_error에서 verified_at 있는 경우), verified_at < today-Ndays
                        observation은 시간 stale 미적용 (changed-path-stale만)
broken-rel:             relations.* 중 tasks 제외 값이 실파일(또는 retired/)로 존재
task-ref:               relations.tasks의 owner/repo#N 형식 (외부 존재 검증은 작업 시스템 몫)
changed-path-stale:     git diff 경로 vs affects_paths(glob), verified_at 미갱신
duplicate-basename:     vault 전역 basename 중복
empty-lesson:           trial_error의 ## 교훈 placeholder/공백
index-sync:             파생 결과(14.2) ↔ 인덱스 현재 내용 차집합(누락/잔존)
active→retired:         active 문서 relations가 retired/ 가리키면 플래그(냄새)
```

---

## 15. mechanism / policy / agent entry / knowledge — 4계층

| 계층 | 위치 | 담는 것 | 이동 단위 |
|------|------|---------|-----------|
| **mechanism** | 플러그인 (`plugin_definition.md` + rules) | 타입집합·ID포맷·frontmatter 스키마·경로기반 active·파생 인덱스·관계 작성 규칙·조회 단계·생명주기 메커니즘 | 플러그인과 함께 |
| **policy** | `wiki/ssot/agent-operating-model.md` (정본) | Claude/Codex/GitHub 역할, 이벤트 흐름, leaf issue 규약, 운영 promotion triggers, agent별 capture 권한 | 프로젝트마다 정본 |
| **agent entry** | 프로젝트 루트 `CLAUDE.md` / `AGENTS.md` | 정책 ssot로의 짧은 포인터 + 프로젝트별 튜닝 | 프로젝트마다 |
| **knowledge** | `wiki/*` | 실제 축적 내용 | 프로젝트 귀속 |

### 모호성 한 줄

> `wiki/*`는 지식 저장소이며, 그 안의 `agent-operating-model.md`는 운영 정책의 정본이다 — knowledge 계층과 policy 계층의 물리 위치는 같지만 역할이 다르다.

(이 문구는 agent-operating-model.md 첫 섹션에도 동일하게 명시.)

*취지*:
- mechanism은 agent-neutral. agent별 규약은 policy로 격리 → 미래 도구 호환.
- CLAUDE.md/AGENTS.md는 단순 reminder가 아니라 agent의 진입점 — 정책 ssot를 가리키는 포인터.
- policy ssot를 wiki 안에 두면, 운영 모델의 진화도 위키 추적(supersede/verified_at/refresh) 메커니즘 안으로 들어온다(dogfooding).
- CLAUDE.md에 메커니즘을 넣으면 플러그인이 다른 프로젝트로 이동할 때 규칙이 안 따라가 "붙여넣으면 작동"이 깨진다. 플러그인은 CLAUDE.md를 소유하지 않되 **권장 스니펫**을 제공한다.

---

## 16. 문서 예시 (타입별)

> 관계 값은 **전체 basename**이다(§11.1). 아래 예시는 일관된 미니 타임라인(취지=초기, 결정·반려=중기, 시행착오·관찰=결정 직후)으로 cross-reference가 맞물린다. 각 블록 제목의 `파일:` 가 그 문서의 basename(=ID)이다.

### intent (뿌리, relations 없음)
파일: `context/intent/INT-2026-01-10-090000-speed.md`
```markdown
---
title: 가입 전환 속도
created_at: 2026-01-10
summary: 가입 퍼널의 마찰을 최소화해 전환율을 높인다.
tags: [growth, conversion]
audience: [human, agent]
---
## 취지
...
## 배경
...
```

### decision (관계 작성 주체)
파일: `context/decision/DEC-2026-04-17-143052-switch-to-bff.md`
```markdown
---
title: 인증을 BFF 구조로 전환
created_at: 2026-04-17
summary: 세션 토큰을 BFF에서 관리하도록 인증 구조를 전환한다.
tags: [auth, architecture]
relations:
  intents: [INT-2026-01-10-090000-speed]                  # 이긴 취지
  ssot: [auth-architecture]                                # 영향 줄 정본
  rejected_decisions: [REJ-2026-04-17-143055-email-auth]
  tasks: [owner/repo#18]
---
## 결정
## 취지
## 배경
## 고려한 대안
## 트레이드오프
## 재평가 조건
```

### rejected_decision (진 취지를 보유)
파일: `context/rejected_decision/REJ-2026-04-17-143055-email-auth.md`
```markdown
---
title: 자체 이메일 인증
created_at: 2026-04-17
summary: 3rd-party 의존을 피하려 자체 이메일 인증을 검토했으나 반려.
tags: [auth]
relations:
  intents: [INT-2026-01-10-091500-data-sovereignty]   # 이 대안이 섬길 진 취지
---
## 대안
## 반려 사유
## 이 대안의 취지
## 재고 조건
```

### trial_error
파일: `context/trial_error/TRI-2026-04-18-101500-kakao-redirect-uri.md`
```markdown
---
title: 카카오 redirect URI 환경별 불일치
created_at: 2026-04-18
summary: 환경별 redirect URI 정확 일치 미준수 시 로그인 실패.
tags: [auth, kakao]
verified_at: 2026-04-18
affects_paths: [src/auth/oauth/**]
relations:
  decisions: [DEC-2026-04-17-143052-switch-to-bff]
  tasks: [owner/repo#18]
---
## 교훈
## 상황
## 피해야 할 것
## 대안 또는 우회
## 현재도 유효한가
```

### observation
파일: `context/observation/OBS-2026-05-28-153000-webhook-timeout-risk.md`
```markdown
---
title: webhook 처리 타임아웃 리스크
created_at: 2026-05-28
summary: 외부 webhook이 30초 이상 지연될 가능성 발견. 현재는 차단되지 않음.
tags: [webhook, reliability]
verified_at: 2026-05-28
affects_paths: [src/webhook/**]
relations:
  ssot: [webhook-architecture]
  tasks: [owner/repo#42]
---
## 관찰
## 근거
## 영향
## 현재 처리
## 후속 분류 조건
```

후속 TRI로 승격되어 retire된 상태 (`retired/` 내):
```yaml
---
title: webhook 처리 타임아웃 리스크
created_at: 2026-05-28
summary: 외부 webhook이 30초 이상 지연될 가능성 발견. 현재는 차단되지 않음.
tags: [webhook, reliability]
verified_at: 2026-05-28
affects_paths: [src/webhook/**]
retired_at: 2026-06-03
retired_type: superseded
superseded_by: TRI-2026-06-03-093000-webhook-timeout-handler
relations:
  ssot: [webhook-architecture]
  tasks: [owner/repo#42]
---
```

> SSOT(`webhook-architecture`)가 동시에 갱신된 경우에도 OBS는 단일 primary successor(TRI)를 `superseded_by`로 가진다. SSOT 갱신의 근거는 그 후속 TRI의 `relations.ssot`로 표현된다(§9 운영 가이드).

### ssot (living, relations 없음)
파일: `ssot/auth-architecture.md`
```markdown
---
title: 인증 아키텍처
created_at: 2026-01-05
summary: 현재 인증은 BFF가 세션 토큰을 보관하는 구조다.
tags: [auth, architecture]
verified_at: 2026-04-17
affects_paths: [src/auth/**]
---
## 현재 상태
## 취지        # decision 없는 설명적 부분만 prose로
## 구성요소
```

---

## 17. 반려한 대안 모음 (취지 보존)

| 반려안 | 반려 사유 |
|--------|-----------|
| 순차 번호 ID (`DEC-00005`) | 단일 채번자·전역 max 스캔 필요 + 병렬 브랜치 충돌 + 불변·피링크라 재채번 불가 → 병렬과 양립 불가 |
| 머지 시 재채번 | 불변 basename 원칙 위반 |
| 관계 정본을 본문 wikilink로 | 코드블록 오탐, 파싱 모호, 양방향 정합성 검사 곤란, obsidian-cli 절단 전제 붕괴 |
| `ssot.relations.intents` 저장 | intent는 항상 decision 경유 → 파생 가능. 저장 시 중복·드리프트·비대화 |
| obsidian-cli를 AI 검색 주경로 | 캐시 신선도 지연, 헤드리스 미동작, 데이터모델이 강점 대체 |
| 별도 `pattern` 타입 | 성격대로 ssot/runbook/trial_error로 분산 가능 |
| 별도 `fact` 타입 | ssot/runbook이 흡수 |
| `agent-map` 별도 문서 | 최상위 구조 고정 → 루트 README 섹션으로 충분 |
| living에 `retired/` | living은 갱신/삭제. retire 개념은 record 전용 |
| living이 `relations` 작성 | 스키마 검증 복잡화. 늦게 발견된 영향은 새 record가 가리킴(§9) |
| **plugin spec에 agent 이름(Claude/Codex) 침투** | 미래 도구 호환성 깨짐. agent별 규약은 operating model로 격리해야 mechanism이 안정 |
| **promotion 자동 판정** | 승격 판단은 의미·운영 판단이라 plugin이 자동화 시 거짓 양성/음성 누적. plugin은 구조 검증만, 판정은 운영자 |
| **search_terms 권장/필수화** | 운영 데이터 없이 선제 권장은 YAGNI. recognized optional로 두고 운영 후 결정 |
| **GitHub issue template drift 자동 검사** | plugin 범위를 외부 워크플로로 확장 → agent-neutral 경계 흐림. GitHub/task plugin에서 별도 검토 |
| **OBS 전용 `classified` retired_type + `classified_as` 필드** | 의미는 예쁘지만 retire 축이 "무효/대체"에서 "분류 완료"까지 확장되며 lifecycle이 섞임. `classified_as` 도입 시 retire CLI·broken-rel·backlinks·recall·예시·테스트가 모두 부풀어남. OBS는 임시 record이므로 후속 TRI/DEC/SSOT 갱신은 primary successor + 후속 record의 relations로 충분히 표현(§9 운영 가이드). 다중 분류 케이스가 실제 운영에서 반복되면 v2에서 재검토(§18) |
| **stale-check를 모든 record에 적용** | intent/decision/rejected의 유효성은 supersede로만 판정. 시간 stale은 의미 약함 |
| **observation에 시간 stale 적용** | observation은 임시 발견·관찰이고 분류 강제는 OBS aging(§18 후속)으로 별도 검토. 시간 경과로 stale 판정하면 active OBS가 노이즈로 쌓임 |

---

## 18. 미확정 / 후속 과제

| 항목 | 상태 |
|------|------|
| 타입별 본문 섹션 **정확한 안내 문구(템플릿 prose)** | 후속(구현 단계). **비차단** — §8 섹션 집합·순서 확정이라 최소 placeholder로 구현 가능 |
| 스킬 **구현 코드** | 후속. §13 계약(인자·출력·에러·exit code)은 확정 |
| 플러그인 **이름** | 미정·**비차단**. 작업 기본값 `wiki`로 진행 후 변경 가능 |
| **태그 어휘 내용** | 메커니즘 확정(§7·§13.5: `ssot/tag-vocabulary.md`, 없으면 검사 skip). 실제 어휘 목록만 프로젝트별 — **비차단** |
| **sandbox 세부** | 보류 — §13.7 방향만 |
| **planning 경계** | 보류 — 작업 시스템 논의 시 |
| 기존 wiki/ **마이그레이션** + task-github 브릿지 | 후속(설계 차단 아님) |
| **search_terms 권장화 / index 기본 표면 포함** | 운영 데이터 누적 후 권장 필드 승격 여부 결정 |
| **GitHub template drift 검사** | `agent-operating-model.md`와 `.github/ISSUE_TEMPLATE/*` 동기화 검사. plugin 범위 밖. GitHub/task plugin 또는 후속 버전에서 재검토 |
| **OBS aging 검사** | N일 이상 retire/대체되지 않은 active OBS 자동 플래그. 운영 데이터 후 결정 |
| **OBS `classified`/`classified_as` 재도입** | v1은 `deprecated`/`superseded` 2값으로 단순화(§17 반려). 한 OBS가 TRI + SSOT 양쪽 트리거하는 다중 분류 케이스가 실제 운영에서 반복되면 v2에서 재검토 |

---

## 19. 수용 기준 / 테스트

> fixture 기반으로 검증 가능한 최소 수용 기준. 구현 시 각 항목을 테스트로 고정한다.

### 19.1 ID/파일명 생성 (§14.1)
- `decision`, title="Switch to BFF", 시계=2026-04-17T14:30:52 → basename `DEC-2026-04-17-143052-switch-to-bff`.
- 동일 TYPE·초·slug 기존 존재 → `-b` 접미사. 타임스탬프 위조 금지.
- `ssot`, slug 기존 존재 → 신규 생성 안 함, "갱신" 신호(exit 5).
- `capture`에서 `--summary` 또는 `--tags` 누락 → exit 2.
- `observation`, title="webhook timeout risk", 시계=2026-05-28T15:30:00 → `OBS-2026-05-28-153000-webhook-timeout-risk`.
- vault 전역 basename 중복 시도 → exit 5.

### 19.2 인덱스 파생 (§14.2)
- summary 가진 문서 N개 폴더 → `<폴더명>.md` "## 노트"에 `- [[basename]] — summary` N줄, 파일명 오름차순.
- **nested**: `ssot/auth/auth.md`는 `ssot/auth/` 직속 문서만(`ssot/`의 다른 폴더 X).
- `retired/` 문서는 인덱스에 없음.
- 재실행 결과 동일(멱등).

### 19.3 retired 이동 + supersede (§14.4)
- supersede(old,new): old→`retired/`, old.superseded_by=new, old.retired_type=superseded, new.supersedes=[old].
- 이동 후 인덱스에 old 없음. recall 기본에서 old 미반환, `--include-retired`로만 노출.
- refresh supersede 검사 0건. 한쪽을 수동으로 깨면 불일치 1건 보고.
- retire(old, deprecated): old→`retired/`, old.retired_type=deprecated, old.retired_at=today, superseded_by 없음.
- **OBS retire**: 다른 record와 동일한 2값 모델. SSOT/runbook 갱신만 트리거된 OBS도 primary successor record(TRI/DEC/OBS)를 만들어 `superseded` 처리(§9 운영 가이드).
- **`retire --type classified` 또는 `--classified-as` 인자** → exit 2 (v1에서 폐기).

### 19.4 broken relation (§14.5)
- relations의 위키 문서 필드에 존재하지 않는 basename → refresh broken-rel 1건 보고(파일·필드·대상 ID 포함).
- `relations.tasks`는 broken-rel에서 제외, task-ref 검사에서 `owner/repo#N` 형식만.
- 모든 위키 문서 relation이 실파일(또는 retired/)로 해소되고 tasks 형식이 맞으면 → 0건.

### 19.5 recall stage 출력 (§13.4)
- Stage 1: 본문 미포함, frontmatter 필드(summary/tags/search_terms/verified_at)만, 결과 ≤ ~2KB(초과 시 절단+제안).
- **search_terms 매칭**: `search_terms`에만 키워드가 들어있는 문서도 Stage 1 결과에 포함된다(summary/tags 미매칭이어도).
- Stage 2: 지정 섹션만, 섹션당 ≤ ~500B.
- Stage 3: 전문 반환.
- `--backlinks-of X`: YAML relations에 X(basename)를 가진 record만 반환(본문 wikilink 무시), retired/ 기본 제외.

### 19.6 recall batch read
- `recall --read a,b,c`: 순서 보존 배열 반환.
- 존재하지 않는 basename 포함 → exit 4.
- `--include-retired`로 retired 포함 가능.

### 19.7 관계 작성 불변식 (§11.3)
- `capture ssot/runbook` + 관계 인자 → exit 2(허브는 관계 작성 안 함).
- 스키마 검증: ssot/runbook 문서에 `relations` 키 존재 → 위반.
- `capture decision`: 친숙한 참조(slug)를 basename으로 해소해 저장. 모호/부재 → exit 4.
- `capture observation` + intent 관계 → exit 2 (허용 범위 밖).
- `capture observation` + ssot/runbook/decisions/tasks → 정상.
- `supersedes`, `superseded_by`, `retired_at`, `retired_type`은 top-level 필드여야 하며 `relations` 안에 있으면 위반.
- v1에서 `classified_as` 필드는 어디에 있어도 위반(§17 반려).

### 19.8 changed-path-stale / duplicate-basename / empty-lesson
- ssot의 `affects_paths: [src/auth/**]` + 해당 경로 git 변경 + `verified_at` 미갱신 → changed-path-stale 1건.
- vault 전역에 같은 basename 2개 → duplicate-basename 1건.
- trial_error의 `## 교훈`이 placeholder/공백 → empty-lesson 1건.

### 19.9 refresh --fix
- `--fix index,retired-in-index` 허용.
- `--fix broken-rel` 등 그 외 시도 → 거부 메시지 + exit 2.
- 실행 시 변경 내역 stdout 보고(silent 변경 금지).

### 19.10 agent-neutral 원칙
- 스킬 **CLI 인자/출력 메시지**에 "Claude"/"Codex" 등 특정 agent 이름 없음.
- **frontmatter 필드명, 알고리즘 명세, 스키마 정의**에 agent 이름 없음.
- 본문 산문에서 운영 정책 영역(§15) 설명용으로 agent 이름을 언급하는 것은 허용 (예: §15 "Claude/Codex/GitHub 역할은 agent-operating-model.md").

---

## 20. 한눈 요약

```
타입       sandbox(보류) / ssot / runbook / context{intent, decision, rejected_decision, trial_error, observation}
구분 축    living(ssot·runbook: 제자리 갱신) vs record(context/*: 불변+supersede, 모든 record 동일)
ID         record=<TYPE>-<YYYY-MM-DD-HHMMSS>-<slug>  (TYPE ∈ INT/DEC/REJ/TRI/OBS)
           living=<slug>   (basename=정본, vault 전역 유일, id 필드 없음)
인덱스      <폴더명>.md (summary 투영, 파생), nested 폴더별 독립, 루트 README;  그 외 파일=내용
active     경로가 정본(status 없음). record는 retired/ 격리, living은 갱신/삭제
frontmatter 공통=title, created_at, summary*, tags*
           verified_at(living 권장, trial_error/observation 선택) / affects_paths(ssot/runbook/trial_error/observation 선택) / search_terms(전 타입 선택, recognized optional, recall Stage 1 매칭)
관계        정본=YAML plain ID. record(decision·rejected·trial·observation)만 작성, 허브(intent·ssot·runbook)는 파생
           decision.intents=이긴 취지, rejected.intents=진 취지 → intent 백링크가 트레이드오프 승/패 기록
           observation은 ssot/runbook 가리킬 수 있음
           양방향 "탐색"은 파생 보장, "저장"은 supersede 쌍만 예외
retire     deprecated | superseded (모든 record 공통, 2값)
           OBS도 동일 — SSOT/runbook 갱신만 트리거된 경우도 primary successor TRI/DEC/OBS로 superseded 처리(§9 운영 가이드)
           v1은 classified/classified_as 미도입 (§17 반려, §18 v2 재검토)
stale       living + verified_at 있는 trial_error만 시간 stale. observation은 changed-path-stale만
Obsidian   뷰어 전용. AI 검색은 filesystem(ripgrep+YAML) 단일. wikilink는 사람용 장식
스킬        init / capture / retire / recall(3-stage + batch read + search_terms 매칭) / refresh(점검 + --fix 화이트리스트) / promote·sandbox(보류)
4계층      mechanism(plugin) / policy(agent-operating-model.md) / agent entry(CLAUDE.md, AGENTS.md) / knowledge(wiki/*)
원칙        plugin은 agent-neutral. agent 이름은 policy 영역으로 격리 (CLI/스키마/알고리즘 출력 0건, 본문 산문 §15 예외). promotion 판정은 운영자
```
