---
title: 위키 라이프사이클
created_at: 2026-05-29
summary: Record와 Living의 라이프사이클 정본: 경로 기반 active/retired, deprecated/superseded 2값 retire 모델, supersede pair 양방향 저장, task 이진 상태(활성/done) + 정본 위임. plugin-definition 영역의 sub-ssot.
tags: [wiki, lifecycle, ssot]
verified_at: 2026-05-29
---

## 현재 상태

### Active vs Retired (경로 기반)

- **경로가 정본** — YAML `status` 필드 없음. *경로와 YAML이 같은 상태를 이중 표현하면 불일치한다.*
- active = 타입 폴더 루트 (`context/decision/DEC-...md`)
- retired = `retired/` 하위로 **물리 이동** (`context/decision/retired/DEC-...md`)
- AI 기본 탐색·인덱스는 retired 제외 (`recall --include-retired`로 명시 포함)

### Retire 모델 (2값, 모든 record 공통)

| `retired_type` | 의미 | 추가 필드 |
|----------------|------|-----------|
| `deprecated` | 틀림/무효 (거짓 알람, 상황 변화로 무효) | — |
| `superseded` | 당시 유효했으나 새 record로 대체 | `superseded_by: <new-basename>` (필수) |

생명주기 필드는 모두 **top-level** (relations 안에 두지 않음): `supersedes`, `superseded_by`, `retired_at`, `retired_type`.

→ [[DEC-2026-05-29-105234-retire-two-value-model]]

### Supersede 알고리즘

새 record가 기존 record를 대체할 때:
1. `new.supersedes += [old_basename]` (top-level)
2. `old.superseded_by = new_basename` (top-level)
3. `old.retired_type = "superseded"`, `old.retired_at = today`
4. `old` 파일을 같은 타입 폴더의 `retired/` 로 물리 이동
5. supersede 쌍만 **양방향 저장** (다른 관계는 단방향 + 파생)
6. successor는 반드시 **active context/* record** (ssot/runbook은 successor 불가)

### Living (ssot/runbook) — retire 없음

- 현실이 바뀌면 **제자리 수정** (정본은 현재 상태 하나)
- "왜 바뀌었나"는 그 변경을 일으킨 context/ decision/observation/trial_error가 보유 (백링크로 추적)
- 주제 자체가 **소멸**할 때만 삭제 — 옛 내용은 git이 보존
- Living은 어떤 경우에도 `relations` 키 자체를 갖지 않음 (불변식)

### Observation 라이프사이클

다른 record와 같은 2값 모델. SSOT/runbook 갱신만 트리거된 OBS도 그 갱신의 근거 TRI/DEC/OBS를 primary successor로 만들어 `superseded` 처리 (분류 완료를 별도 상태로 두지 않음).

→ [[REJ-2026-05-29-105500-obs-classified-retired-type]] (v1에서 반려)

### Task 라이프사이클 (이진 상태, 경로 기반)

- task는 retire 2값 모델이 아니라 **이진 상태**: 활성(`task/`) vs 완료(`task/done/`). 완료는 `done/`로 **물리 이동**(`retired/`의 형제, "경로=정본 상태" 동일 원칙).
- 본문은 **제자리 갱신**(living처럼) + 상태 전이는 **폴더 이동** — 둘이 직교.
- 전이 명령: `complete`(활성→`done/`), `reopen`(`done/`→활성). retire(틀림/대체)와 별개 — 정상 완료다.
- **정본 위임**: 작업 플러그인 미연결이면 위키가 완료/미완 정본. 연결되면 **외부 트래커(GitHub 이슈)가 정본**이고 위키 `done/`는 그 투영 — 동기화는 작업 플러그인 책임이며 위키 CLI는 외부 트래커를 모른다.
- task가 완료가 아니라 **무효**(잘못 만들어짐)일 때는 일반 record처럼 `retire`로 처리(`done`과 구분).

→ [[DEC-2026-05-29-181259-task-binary-state-github-sot]]

## 취지

이 라이프사이클 모델이 추구하는 일급 원칙:

- [[INT-2026-05-29-104708-atomic-knowledge-records]] — 각 record는 자기 라이프사이클을 가짐
- [[INT-2026-05-29-104713-single-canonical-current-state]] — Living은 하나의 현재 상태만, 이력은 record가 보유

## 구성요소

이 영역에 응집된 결정 anchor:

- [[DEC-2026-05-29-105234-retire-two-value-model]] — 2값 retire 모델
- [[DEC-2026-05-29-181259-task-binary-state-github-sot]] — task 이진 상태 + 정본 위임

반려 대안: [[REJ-2026-05-29-105500-obs-classified-retired-type]] (분류 완료 상태를 별도 retired_type으로 만들자는 안) / [[REJ-2026-05-29-181259-wiki-holds-task-detailed-phase]] (위키가 상세 단계 보유).

