# task-github

GitHub 기반 자율 작업 프로토콜. AI 에이전트가 작업을 점유·계획·실행·검증·완료하는 구조를 GitHub Issue/PR/Label 위에 얇게 올리고, 같은 마켓플레이스의 **`wiki-markdown` 결정 그래프와 `task` 노드로 연계**한다.

## 빠른 시작

```bash
# 1. 환경 초기화 (git + GitHub repo + 라벨)
task-github:setup

# 2. 업무 정의 (루트 이슈 + 위키 task 노드 1:1)
task-github:define

# 3. 작업 시작 (리프 점유 + 기어 판단)
task-github:start {N}

# 4. (normal/major) 계획 → 승인
task-github:plan {N}

# 5. 실행
task-github:run {N}

# 6. 검증 (지식 승격 제안)
task-github:verify {N}

# 7. 완료 (PR 생성 + 드리프트 점검)
task-github:done {N}

# 8. 리뷰 → 머지 (task 노드 done 전이)
task-github:review {PR} --auto-merge

# 상태/오케스트레이션/진단
task-github:status {N}
task-github:orchestrate {N}
task-github:doctor --json
task-github:reconcile --apply
```

## 3축 분류

- **프로파일**(환경): `.task-github.yml` `mode: solo|team` (`solo` 기본)
- **기어**(파급력): `micro` / `normal` / `major` — 영향 반경으로만 판단
- **flow options**: `plan` / `verify` / `pr-review`

## 위키 연계

`./wiki/` vault가 있으면 자동 연동(없으면 그레이스풀 스킵):
- **업무 1개 = 루트 이슈 1개 + 위키 `task` 노드 1개** (1:1 다리)
- 작업 중 `[결정]/[시행착오]/[관찰]`을 위키 결정 그래프로 승격
- `recall --backlinks-of {DEC}`로 "이 결정이 낳은 작업" 추적
- `refresh --level integrity --strict`와 PR diff `changed-path-stale`를 완료/머지 hard gate로 적용(hygiene 등급은 경고)
- `decision-quality`/`task-quality`로 결정·정의 구조 결함을 FLAG-to-human으로 탐지

연동 메커니즘은 [rules/wiki-bridge.md](rules/wiki-bridge.md), 품질 gate는 [rules/quality-gates.md](rules/quality-gates.md), 운영 정책은 자동로드 agent-entry 파일(`CLAUDE.md` / `AGENTS.md`)에 있다. `wiki-markdown`의 `agent-policy` 스킬로 두 파일의 관리 블록을 스캐폴드할 수 있다.

## Issue dependency

하위 작업의 병렬/직렬 실행 가능성은 GitHub **Issue dependencies**가 정본이다.
- sub-issue는 업무 분해 구조만 표현한다.
- `define`은 `skills/define/scripts/create_issue_tree.py`로 루트/서브이슈/dependency를 한 spec에서 생성한다.
- `blocked_by`가 없으면 병렬 가능으로 간주한다.
- 열린 `blocked_by`가 있으면 `start`/`run`/`done`/`merge`가 차단한다.
- 이슈 완료 후에는 `blocking` downstream을 안내한다.

세부 규약은 [rules/dependencies.md](rules/dependencies.md)에 있다.

## Execution Contract

root issue body에는 필요 시 `task-github-execution` fenced JSON block을 둔다. 여기에는 integration 실행 전략(`topology`, `gate`, `parent_branch`, `leaf_policy`, `required_checks`, `closeout_mode`)을 materialize한다. `required_checks`는 argv array만 허용한다(shell string 거부). contract가 없으면 기존 profile+gear 기본 판단을 사용하며, context bundle은 이를 `default_source: "profile+gear"`로 드러낸다.

이 contract는 GitHub root issue에만 존재하는 실행 계약이다. wiki `TASK` 노드의 작업정의·취지를 대체하지 않는다.

## Closeout (all-PR)

모든 머지는 `closeout.py --pr {PR}` → `gh pr merge`(remote) 하나다. 리프 PR도, epic/컨테이너 머지업 PR도 같은 경로다. epic 브랜치는 worker가 없어 PR이 자동 생성되지 않으므로 orchestrate가 `gh pr create`로 통합 PR을 만든 뒤 넘긴다. closeout은 로컬 `git checkout`/`git merge`를 하지 않고 머지 후 base 갱신도 `git fetch origin {base}:{base}`로 처리해, 오케스트레이션 중 메인 워크트리 HEAD가 trunk를 벗어나지 않는다(DEC-2026-07-02-212109). PR 자체가 통합 로그라 별도 ledger를 만들지 않는다.

## Orchestrate Ledger

`orchestrate`는 시작/재개/오류 복구 때 GitHub snapshot을 `.task-github/orchestrate/{root}.json`에 reconcile하고, 평상시 tick은 ledger를 읽는다. 성공한 write는 `events[]`와 derived issue/PR state에 즉시 반영하므로 방금 merge/close한 상태를 확인하려고 tree를 다시 읽지 않는다. 최종 closeout과 CI/mergeability/reviewDecision처럼 외부 상태가 바뀌는 경계에서만 GitHub를 다시 조회한다.

## Orchestrate Gear Options

기본값은 `micro = plan:x verify:o pr-review:x`, `normal = plan:o verify:o pr-review:x`, `major = plan:o verify:o pr-review:o`다. 우선순위는 commander 지시 > `.task-github.yml` `orchestrate.gear-options` > 기본값이다.

## Knowledge Capture Audit

비 trivial 작업은 끝내기 전에 위키 기록 후보를 감사한다.
- `observation`은 분류 전·저위험이면 자동 캡처한다.
- `decision`/`rejected_decision`/`trial_error`와 `ssot`/`runbook` 갱신은 제안 후 확인한다.
- 후보가 없으면 `none`과 이유를 최종 보고나 Issue 코멘트에 남긴다.

세부 규약은 [rules/knowledge-capture.md](rules/knowledge-capture.md)에 있다.

## 구성

| 구성요소 | 역할 |
|---------|------|
| `rules/task-protocol.md` | 프로파일·기어·플로우·태그·완료조건 (헌법) |
| `rules/workflow.md` | 라벨·상태전이·브랜치·커밋·PR |
| `rules/dependencies.md` | GitHub Issue dependencies 기반 선후관계·차단 |
| `rules/knowledge-capture.md` | 작업 종료 전 지식 기록 감사 |
| `rules/wiki-bridge.md` | 위키 감지·호출·task 노드 연동 (mechanism) |
| `skills/*` (14종) | setup·open·define·start·plan·run·verify·done·review·merge·status·orchestrate·doctor·reconcile |
| `agents/pr-verifier.md` | PR 독립 검증 서브에이전트 |
| `agents/conflict-resolver.md` | merge conflict 해소 전용 서브에이전트 |

자세한 설계·불변식·이관 가이드는 [DESIGN.md](DESIGN.md) 참조.

## 변경 이력

- `0.13.0`: merge closeout를 all-PR로 통합 — local mode(`--mode local`)·local merge simulation·Integration Ledger 제거. epic/컨테이너 머지업도 PR화(`gh pr create`+`gh pr merge`)하고, 머지 후 base 갱신을 checkout→`git fetch`로 바꿔 오케스트레이션 중 메인 워크트리 HEAD가 trunk 불변([[DEC-2026-07-02-212109]]).
- `0.12.0`: gear별 `plan`/`verify`/`pr-review` flow option과 `orchestrate.gear-options` 설정 추가.
- `0.11.0`: orchestrate write-through ledger, ledger-only ready tick, non-default base issue close, post-merge cleanup warnings, `gear:normal` review skip.
- `0.8.0`: context bundle resolver, Execution Contract, PR/local closeout, local merge simulation, Integration Ledger, status next_action, doctor/reconcile 추가.
