---
title: 에이전트 운영 모델 (정책 정본)
created_at: 2026-05-29
summary: 이 위키를 사용하는 에이전트들의 운영 정책 정본. 4계층 분리(plugin_definition)에서 policy 계층에 해당. task-github 작업관리 플러그인↔위키 결합 규약(캡처 권한·task 노드 연결·promotion·PR 흐름)을 여기서 정의.
tags: [wiki, policy, ssot]
verified_at: 2026-05-29
---

## 현재 상태

> `wiki/*`는 지식 저장소이며, 그 안의 본 문서(`agent-operating-model.md`)는 **운영 정책의 정본**이다 — knowledge 계층과 policy 계층의 물리 위치는 같지만 역할이 다르다 (4계층 분리: [[plugin-definition]]).

본 ssot는 **작업관리 플러그인 `task-github`(marketplace `jeis-ai-plugins/task-github`)와 위키의 결합 규약**을 담는다. task-github는 agent-neutral *mechanism*(작업 프로토콜)이고, "누가·언제·어떤 타입을 캡처/승격/연결하는가"의 *policy*가 본 문서다. task-github의 mechanism 정본은 그 플러그인의 `rules/`·`skills/`·`DESIGN.md`에 있고, 위키 타입·관계의 정본은 [[wiki-data-model]]에 있다.

위키 미가용 환경(`./wiki/` 없음)에서도 task-github는 mechanism만으로 완전 동작한다 — 본 정책은 위키가 있을 때만 적용된다.

## 취지

Plugin 메커니즘과 운영 정책을 **다른 변경 빈도**로 분리하기 위한 정책 정본 자리. CLAUDE.md/AGENTS.md에 운영 정책을 직접 적으면 안정 자산(plugin spec)과 변동 자산(agent 운영 규약)이 한 파일에 묶여 함께 흔들린다 → [[TRI-2026-05-29-105533-claude-md-as-policy-conflates-mechanism-and-policy]].

본 ssot가 정책 정본이면, 운영 정책의 진화도 위키 메커니즘(supersede / verified_at / refresh) 안으로 들어와 추적 가능(dogfooding). plugin은 구조만 검증하고 의미 판정은 여기 둔다 → [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]].

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

작성·갱신 시에는 일반 ssot처럼 제자리 수정 + `verified_at` 갱신. 운영 정책 자체의 결정/반려/교훈은 `wiki/context/`에 record로 capture해 본 ssot가 그 record들로 anchor됨.
