---
title: 에이전트 운영 모델 (레거시 정책 슬롯)
created_at: 2026-05-29
summary: 이전 4계층 설계에서 작업환경 운영정책 정본으로 쓰던 레거시 슬롯. 2026-06-03 이후 운영정책 statement는 CLAUDE.md/AGENTS.md 자동로드 entry 표면이 정본이고, 이 문서는 이관 기록과 구버전 참조 호환만 담당한다.
tags: [wiki, policy, ssot]
verified_at: 2026-06-03
---

## 현재 상태

> 본 문서는 더 이상 운영정책 statement의 정본이 아니다. 현재 정본은 루트 `CLAUDE.md`와 `AGENTS.md`의 `agent-operating-policy` 관리 블록이다.

이 문서는 v3 이전의 **작업관리 플러그인 `task-github`(marketplace `jeis-ai-plugins/task-github`)와 위키의 결합 규약**을 보존하는 레거시 슬롯이다. task-github mechanism 정본은 그 플러그인의 `rules/`·`skills/`·`DESIGN.md`에 있고, 위키 타입·관계의 정본은 [[wiki-data-model]]에 있다. 현재 policy 위치 변경 결정은 [[DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다]].

위키 미가용 환경(`./wiki/` 없음)에서도 task-github는 mechanism만으로 완전 동작한다. policy statement도 wiki recall 없이 자동로드 entry에서 읽힌다.

## 취지

이 문서는 기존 결정을 깨지 않고 이관 흔적을 남기기 위한 자리다. 장문 rationale까지 `CLAUDE.md`/`AGENTS.md`에 넣으면 prompt 비용과 파일 혼합 문제가 생기지만, 짧은 operative statement는 자동로드 표면에 있어야 한다 → [[DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다]].

이 repo에서는 플러그인 설계 결정을 wiki `decision`으로 dogfood하지만, 소비 프로젝트의 wiki vault에는 운영정책을 자동 생성하지 않는다. plugin은 구조만 검증하고 의미 판정은 자동로드 policy statement가 담당한다 → [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]].

## 구성요소

### 1. 캡처 권한 (어느 스킬이 어떤 타입을)

| 스킬 | 캡처/전이 가능 | 방식 |
|------|--------------|------|
| `define` | `task` 생성, (선택) `intent` | 제안 후 확인 |
| `run` | `observation` | 자동 (저위험) |
| `verify` | `decision`, `rejected_decision`, `trial_error`, `observation`→상위 승격 | 제안 후 확인 |
| `done`(major) | `decision`(ADR) | 제안 후 확인 |
| `merge` | `task`→`complete`(done/), `ssot` 갱신 안내 | 자동 전이 / 갱신은 제안 |

1급 노드(task/decision/intent/rejected/trial_error) 캡처와 모든 승격은 **제안 후 확인**. observation만 자동(분류 전·저위험). 자동 승격 금지 → [[plugin-definition]].

### 1.1 Knowledge Capture Audit

모든 비 trivial 작업은 종료 전 **Knowledge Capture Audit**를 수행한다. 특히 `DESIGN.md`, `rules/`, `skills/`, `wiki/ssot/`, `wiki/runbook/`처럼 운영 규약이나 정책을 바꾼 작업은 생략할 수 없다.

감사는 `recorded`/`proposed`/`none` 중 하나로 끝나야 한다. 각 값의 정의·타입 판정·출력 형식 정본은 task-github의 `rules/knowledge-capture.md`(메커니즘)에 둔다 — 이 어휘는 위키 없이도 플러그인이 산출하므로 메커니즘이 정본이고, 본 policy는 의무를 규정한다.

에이전트는 기록 후보를 판단하기 전에 `recall`로 기존 기록을 확인한다. observation은 자동 캡처할 수 있지만, 1급 노드 캡처와 observation 승격은 반드시 제안 후 확인한다. 이슈가 없는 작업이라도 감사는 수행하며, 자동 observation에는 `--tasks`를 생략할 수 있다.

이 감사 정책의 채택 결정은 [[DEC-2026-06-02-120100-task-github-작업-종료-전-knowledge-capture-audit-의무화]], 누락 사례의 교훈은 [[TRI-2026-06-02-120200-작업-종료-전-지식-기록-감사를-생략하면-결정-그래프가-비게-된다]]에 기록한다.

### 2. 업무↔이슈 연결 규약 (leaf issue 규약)

- **업무 1개 = 위키 `task` 노드 1개 + GitHub 루트 이슈 1개 (1:1).** task 노드는 업무 단위 — 리프·서브이슈마다 만들지 않는다.
- **task 노드**: `relations.tasks: [owner/repo#<루트이슈>]` + `relations.decisions`/`intents`(근거). 본문은 업무 **요약**.
- **루트 이슈** 본문에 고정 섹션 `## Wiki Context` — task 노드를 **메인**, 결정/취지를 **보조**로:
  ```markdown
  ## Wiki Context
  **메인**: [[TASK-...]] — 이 업무의 정의(요약·근거)
  **보조**:
  - [[DEC-...]] — 근거가 된 결정
  - [[INT-...]] — 상위 취지
  ```
- 항목은 위키 노드 **basename**. wikilink는 사람용 탐색 장식, 정본 연결은 위키 노드의 `relations`.
- **타입별 관계 제약**: `--tasks` 역링크는 decision/trial_error/observation/task에만. intent/rejected/ssot/runbook은 단방향(에픽↔intent는 decision/task 경유) → [[wiki-data-model]].

### 3. promotion 트리거

- `observation` → `trial_error`/`decision` 승격은 **verify에서 분류가 확정될 때 제안**. 자동 판정 금지.
- 승격 시: 후속 노드 `capture`(`--supersedes <OBS>`) → `refresh --check supersede`로 양방향 확인.
- 승격 가치 기준(추상): 장기 재사용성 · 구조적 영향 · 반복 가능성 · 되돌리기 비용 · 후속 작업자 필요성 중 ≥1 → [[wiki-four-layer-separation]].

### 4. PR 리뷰 흐름 ↔ 위키

- `review`/`pr-verifier`는 연결 task 노드의 `decisions`를 받아 **PR이 반려된 대안(rejected_decision)으로 회귀하지 않는지** 점검.
- 머지 후 drift 리포트(`changed-path-stale`)에 걸린 ssot/runbook은 `verified_at` 갱신 또는 supersede(안내만, 자동 변경 금지).

### 5. task 노드 상태 동기화 정책

- 연동 시 **GitHub 루트 이슈가 상태 정본**, 위키 task(활성/done 이진)는 투영.
- 전이 시점: 루트 이슈 close(머지/직접) → `complete`. 이슈 reopen → `reopen`.
- 위키 CLI는 GitHub을 모른다 — out-of-band(밖에서 닫힌 이슈) reconcile은 task-github가 `gh`로 읽어 정렬(`open`/`merge` 시 점검).

### 6. 기어별 연동 강도

| 기어 | task 노드 | recall | capture | drift |
|------|:---:|:---:|:---:|:---:|
| micro | 보통 생략(단발) | — | 발견 시 observation/trial_error | — |
| normal | ✅ 업무면 생성 | ✅ | decision/trial_error/observation | ✅(done) |
| major | ✅ + intent/rejected 연결 | ✅ | + ADR decision | ✅(done) |

### 7. GitHub template (선택)

`.github/ISSUE_TEMPLATE/`의 루트 이슈 템플릿에 `## Wiki Context` 빈 섹션을 포함해 본 규약과 동기(운영 시점 도입).

---

이 문서는 일반 ssot처럼 제자리 수정 + `verified_at` 갱신으로 레거시 상태를 표시한다. 현재 운영정책 statement 변경은 `CLAUDE.md`/`AGENTS.md` 관리 블록에서 수행하고, 이 repo의 플러그인 설계 결정만 `wiki/context/`에 dogfood 기록한다. 작업 보고에는 Knowledge Capture Audit 결과(`recorded`/`proposed`/`none`)를 포함한다.
