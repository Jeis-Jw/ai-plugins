# Quality Gates v0

task-github는 GitHub 이슈/PR 흐름을 정본으로 두되, 위키가 가용하면 아래 gate를 적용한다. v0는 모델 판단이 아니라 deterministic static rules만 사용한다.

## G1. Hard Gate (severity-tiered)

위키 check는 두 등급(wiki-markdown ≥0.11.0)으로 나뉜다. hard gate는 **구조적 깨짐(integrity)** 과 **코드↔문서 drift** 만 막고, **청소거리(hygiene)** 는 경고로만 보고한다.

- **integrity (차단):** schema, broken-rel, task-ref, duplicate-basename, supersede, active-ref-retired.
- **hygiene (경고, 비차단):** stale, orphan, index, retired-in-index, tags, changed-path-stale, empty-lesson, decision/task-quality.
- **drift (차단):** `changed-path-stale` 명시 check — hygiene 등급이지만 task-github는 코드-문서 drift를 PR/머지 차단 사유로 유지한다(의도적 예외).

게이트 명령:

- `verify`: `wiki refresh --level integrity --strict --json` (hard) + `wiki refresh --level hygiene --json` (경고 surface).
- `done` 경로 A(PR 생성 전): `wiki refresh --check changed-path-stale --changed-path "$FILES" --json` (drift hard).
- `merge`: `wiki refresh --level integrity --strict --json` (hard) + PR diff 기반 `changed-path-stale` (drift hard).

hard gate에 걸리면 해당 skill은 PR 생성/머지/완료 전이를 진행하지 않고 `[중단]` 또는 `CHANGES_REQUESTED`로 보고한다. hygiene 경고는 진행을 막지 않고 리포트에만 남긴다(사령관이 청소 시점을 판단). 위키 자체가 없는 워크스페이스는 기존처럼 위키 단계를 skip한다.

`refresh --level integrity --strict`는 integrity 이슈가 있을 때만 exit 6을 반환한다(hygiene-only면 exit 0). `changed-path-stale` 단독 check는 report command라 exit 0일 수 있으므로 JSON `issues` 배열을 검사해 차단한다.

## G2. Decision Quality Flag

`wiki refresh --check decision-quality --json`은 active decision 문서의 구조 결함을 `severity: flag`로 보고한다.

- `relations.intents` 최소 1개
- `## 취지`
- `## 배경`
- `## 고려한 대안`
- `## 트레이드오프`
- `## 재평가 조건`

이 check는 기본 `all`에 포함하지 않는다. v0에서는 block이 아니라 FLAG-to-human이다.

## G3. Define/Task Quality Flag

`wiki refresh --check task-quality --json`은 active task 문서의 구조 결함을 `severity: flag`로 보고한다.

- `relations.intents` 또는 `relations.decisions` 최소 1개
- `## 근거`
- `## 범위와 완료 기준` 안의 완료 기준 anchor
- 검증/테스트 anchor
- 영향 경로/파일 anchor

define/plan은 등록 전 확인안에 위 항목을 포함한다. flag가 있으면 confirm 전에 보완하거나 사령관에게 의도적 예외인지 묻는다.

## G4. Escalation Criteria

아래 중 하나면 `gear:major` 또는 human-confirm으로 승급한다.

- 품질 flag가 존재하는데 자동 보완 근거가 부족함
- 분해 단위 간 touched/affects path가 겹치고 dependency가 선언되지 않음
- 완료 기준이 결과물 중심이 아니라 작업 행위 중심임
- 설계/문서 결정이 여러 issue 또는 wiki node에 복리로 전파됨
- 기존 decision/rejected_decision과 충돌 가능성이 있음

v0의 목적은 confirm 제거가 아니라, confirm 전에 구조적 결함을 싸게 걸러 사용자의 확인 비용을 줄이는 것이다.
