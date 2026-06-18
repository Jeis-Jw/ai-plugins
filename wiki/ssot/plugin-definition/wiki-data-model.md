---
title: 위키 데이터 모델
created_at: 2026-05-29
summary: 위키 그래프의 정적 구조 정본: 5종 record + 2종 living + 1종 task(작업지시서형 제3 범주) 타입 체계, graph 밖 snapshot staging layer, basename 정본 ID, YAML 관계 모델(비대칭 작성). plugin-definition 영역의 sub-ssot.
tags: [wiki, data-model, ssot]
verified_at: 2026-06-12
---

## 현재 상태

### 타입 체계

- **Living** (제자리 갱신): `ssot`, `runbook`
- **Record** (불변 + supersede): `context/intent`, `context/decision`, `context/rejected_decision`, `context/trial_error`, `context/observation`
- **Task** (작업지시서형 제3 범주 — 제자리 갱신 + 관계 보유): `task`. 결정·취지·SSOT를 묶어 수행자에게 넘기는 handoff/context 브릿지 노드(순수 잎). 외부 작업 시스템 없이도 완결되며, 연계 작업이면 `relations.tasks`에 Issue/PR 같은 외부 실행 기록 링크를 둔다. 상태는 이진(활성 / 완료=`done/` 경로 이동), 외부 연계의 상세 진행과 동기화는 연결된 작업 플러그인에 위임 ([[wiki-lifecycle]]).
- **Snapshot** (graph 밖 staging layer): `snapshot/`. 아직 정식 `observation`/`decision`/`ssot`/`runbook`으로 정리하지 않은 대화 맥락 체크포인트. `TYPE_SPECS`에 들어가지 않으며 관계 그래프·recall·refresh 무결성 검사 대상이 아니다.

→ [[DEC-2026-05-29-105231-wiki-type-taxonomy]] / [[DEC-2026-05-29-105322-observation-record-type]] / [[DEC-2026-05-29-181259-task-third-category]]

### ID 체계

- Record basename: `<TYPE>-<YYYY-MM-DD-HHMMSS>-<slug>.md` (TYPE ∈ INT/DEC/REJ/TRI/OBS)
- Task basename: `TASK-<YYYY-MM-DD-HHMMSS>-<slug>.md` (record와 동일 채번, 경로 `wiki/task/`)
- Snapshot basename: `SNAP-<slug>.md` (graph 밖 staging ID, 토론당 파일 하나, slug 제자리 갱신)
- Living basename: `<slug>.md`, **vault 전역 유일**
- basename 자체가 정본 ID, YAML `id` 필드 없음
- ssot/runbook은 영역이 커지면 **nested 폴더 허용** (예: `wiki/ssot/plugin-definition/`)

→ [[DEC-2026-05-29-105230-record-living-id-system]] / [[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]]

### 관계 모델

- 정본 = frontmatter YAML의 plain basename (본문 wikilink는 사람용 장식, [[wiki-external-tools-policy]] 참조)
- **Record만 작성**, 허브(intent/ssot/runbook)는 **백링크로 파생**
- 작성 테이블:
  - `decision.relations`: intents(이긴 취지), rejected_decisions, ssot, tasks
  - `rejected_decision.relations`: intents(진 취지)
  - `trial_error.relations`: decisions, tasks
  - `observation.relations`: ssot, runbook, decisions, tasks
  - `task.relations`: intents, decisions, ssot, tasks(외부 작업 ref: Issue/PR 등) — **순수 잎**(다른 타입이 task를 가리키지 않음; 역방향은 파생 백링크)
  - `intent` / `ssot` / `runbook`: **relations 키 자체 없음** (불변식)
- 양방향 *탐색* 보장, 양방향 *저장*은 supersede 쌍만 예외 ([[wiki-lifecycle]])
- 관계 보강은 `capture` 또는 `relate` CLI로만 수행한다. `relate`는 task 노드의 semantic relation 보강과 record의 외부 `tasks` ref 추가만 허용한다. record의 semantic relation을 바꿀 필요가 있으면 새 record를 capture/supersede한다.

→ [[DEC-2026-05-29-105232-relations-asymmetric-write]]

### Frontmatter 코어

- 공통 필수: `title`, `created_at`, `summary`, `tags`
- 타입별 한정 (요지):
  - `verified_at`: living 권장, trial_error/observation 선택, intent/decision/rejected 없음
  - `affects_paths`: ssot/runbook/trial_error/observation 선택 ([[wiki-retrieval]])
  - `search_terms`: 전 타입 선택 (recognized optional)
- 금지: `id`, `status`, `classified_as`
- 생명주기 필드는 top-level (relations 안에 두지 않음): `supersedes`, `superseded_by`, `retired_at`, `retired_type` ([[wiki-lifecycle]])

## 취지

이 데이터 모델이 추구하는 일급 원칙:

- [[INT-2026-05-29-104708-atomic-knowledge-records]] — 각 record가 독립 라이프사이클
- [[INT-2026-05-29-104712-parallel-safe-headless-operation]] — timestamp+slug 채번이 병렬 충돌 0
- [[INT-2026-05-29-104707-token-efficient-context-loading]] — 작은 단위 → 선택 읽기

## 구성요소

이 영역에 응집된 결정 anchor:

- [[DEC-2026-05-29-105230-record-living-id-system]] — 이중 ID 체계
- [[DEC-2026-05-29-105231-wiki-type-taxonomy]] — 5종 record + 2종 living
- [[DEC-2026-05-29-105322-observation-record-type]] — observation 신설
- [[DEC-2026-05-29-105232-relations-asymmetric-write]] — 비대칭 관계 작성
- [[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]] — nested + 전역 유일
- [[DEC-2026-05-29-181259-task-third-category]] — task 제3 범주 신설(작업↔결정 브릿지)
- [[DEC-2026-06-03-155419-define-batch-helper-and-wiki-relate]] — `wiki relate`와 define 배치 헬퍼 배포

반려 대안: [[REJ-2026-05-29-105454-sequential-numeric-id]] / [[REJ-2026-05-29-105456-wikilink-as-relation-source]] / [[REJ-2026-05-29-105458-living-writes-relations]] / [[REJ-2026-05-29-181259-task-as-immutable-record]] / [[REJ-2026-05-29-181259-task-as-living-relax-invariant]].
