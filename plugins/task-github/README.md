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

## Closeout (gear-gated merge)

머지 경로는 review 필요 여부가 결정한다(DEC-2026-07-02-224910). **micro/normal 리프**와 `--review=skip`의 major 리프는 PR 없이 worker가 `ready_for_closeout`을 기록하고, orchestrator의 `BASE_BRANCH`별 closeout lane이 로컬 FF(`git fetch . task/issue-{leaf}:task/issue-{parent}`, checkout 없는 refspec)로 부모에 합류시킨다. **review가 필요한 major 리프/컨테이너**만 PR+review 경로를 타며, 승인 뒤 `ready_for_pr_closeout`으로 같은 closeout lane에서 PR merge 순간을 직렬화한다. 컨테이너 gear는 자식 누적 승격(`container_gear_promotion`: micro×3→normal, normal×2→major)으로 계산하고, review skip이면 gear/skip evidence를 남긴다. closeout은 로컬 `git checkout`/`git merge`를 하지 않고 base 갱신도 fetch refspec으로 처리해, 오케스트레이션 중 메인 워크트리 HEAD가 trunk를 벗어나지 않는다(DEC-2026-07-02-212109 불변식 유지). 충돌은 항상 리프 worktree에서 해소한다.

## Define Challenge Review

co-design(정착된 분해 제안 / 사령관 확인 게이트, [[DEC-2026-07-02-190102]]) **뒤**, GitHub 이슈 트리 생성 **전**에 두는 적대 challenge 게이트다. fresh-context 서브에이전트가 refute 스탠스(default-reject)로 분해 **제안**(git PR이 아니라 이슈가 생기기 전의 제안 문서)을 4 cut-reason(병렬 이득 / 위험 격리 / 정보 가치 경계 / 병렬 해금)·blocker-direct-only·verify/docs/runbook-not-leaves·container-as-demand·gear 정직성, 그리고 위키 결정 그래프(제안 리프가 REJ/DEC를 회귀시키는가)에 비추어 감사한다([[DEC-2026-07-03-012207]]).

- **on/off**: 기본 **off**. `task-github:define --review`(또는 이번 run의 명시 사령관 지시)로 켠다.
- **도구 우선순위**(켰을 때만): **지시 > 설정(`define.review-tool`) > 하네스(내장)**. `orchestrator_ops.resolve_review_tool`이 해소하고, tool 모드면 `orchestrator_ops.compose_tool_command`으로 relay를 만든다.
- **터미널 = 하네스**(STOP 아님): define의 challenge는 사람이 이미 있는 co-design 자리에서 돌므로, 도구가 없으면 멈추지 않고 내장 fresh-context challenge 서브에이전트로 떨어진다. 하네스 fallback은 **진짜 challenge**(4 cut-rule + 위키 결정 그래프에 근거한 refute)이지 제안을 다시 읽는 co-design 에이전트가 아니다.
- **저-의존**: 하네스 fallback은 standalone으로 동작(session-review에 hard dep 없음). 외부 도구는 선택적 업그레이드다. session-review는 PR/git 지향이라 doc-review 모드 없이는 자연스러운 define 리뷰어가 아니다 — 내장이 primary 경로다.
- **경계**: 1 challenge 라운드, blocking 판정만 게이트(advisory는 로그), 사람이 blocking을 판정, auto-loop 없음.
- **복잡도 넛지**(off-default 유지): 제안 트리 리프 수/깊이가 임계 초과면(plan 시점 task-count warn 재사용) `--review`를 권하는 non-blocking 힌트를 낸다. 여전히 기본 off이며, 넛지는 가장 값진 케이스(크고 복잡한 트리)를 조용히 건너뛰지 않게 할 뿐이다.

`.task-github.yml`은 orchestrate의 review-tool 패턴을 그대로 미러링한다(`scripts/task_config.py`로 읽음):

```yaml
define:
  review-tool:      # 비우면 하네스(내장 challenge). 채우면 그 도구로 relay.
  review-command:   # 선택 인자; define.review-tool이 있어야 함
  review-required: false  # true면 spec.challenge_review.verdict==approved 없이는 이슈 생성 거부
```

알 수 없는 `define` 키는 경고하고, `define.review-command`는 `define.review-tool`을 요구한다. `define.review-required`는 boolean이어야 하며, invalid config는 define helper가 fail-closed로 중단한다.

## Orchestrate Ledger

`orchestrate`는 시작/재개/오류 복구 때 GitHub snapshot을 `.task-github/orchestrate/{root}.json`에 reconcile하고, 평상시 tick은 ledger를 읽는다. 성공한 write는 `events[]`와 derived issue/PR state에 즉시 반영하므로 방금 merge/close한 상태를 확인하려고 tree를 다시 읽지 않는다. 최종 closeout과 CI/mergeability/reviewDecision처럼 외부 상태가 바뀌는 경계에서만 GitHub를 다시 조회한다.

ledger v3는 비용 분석과 evidence reuse를 위해 `github_reads`, `read_decisions`, `merge_evidence`, `gate_evidence`, `preflight_evidence`를 분리한다. GitHub read는 시작/재개, 실패 복구, 긴 대기 후, pre-merge/mergeability/CI/reviewDecision 확인, final closeout 같은 boundary에서 reason과 함께 기록한다. `merge_preflight.py`가 남긴 fresh `preflight_evidence`는 같은 PR/head, 짧은 TTL, status OK 조건에서 closeout의 PR view 입력으로 재사용된다. 실제 merge는 `--match-head-commit`으로 preflight 때 본 head SHA를 고정하므로 head drift가 있으면 GitHub merge가 실패한다. parent/root PR gate는 전역 integrity strict를 항상 유지하되, child `gate_evidence`가 valid하면 `changed-path-stale` target에서 해당 child path를 제외한다. evidence가 없거나 base/head/version/drift hash/path hash/parent overlap 조건이 맞지 않으면 해당 child path는 fallback target에 포함한다.

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

- `0.19.0`: define 분해 게이트 재합침 원리 — 절단 판정에 헤드라인 질문("다른 워커가 독립 점유해 끝낼 수 있는가")과 **don't-split 프로브**(검증 명령 동일/같은 shared component 수정/context 연속)를 추가해 사유①의 가짜 독립을 잡는다. same-theme write-set 겹침은 `blocked_by` 직렬화보다 **1리프+phase 재합침**을 먼저 검토한다(quality-gates G4·challenge review 기준 반영). `create_issue_tree.py` dry-run에 `siblings_maybe_phases` 경고(공유 단일 선행 뒤 fan-out 3+개 + 공통 feature 테마(필수) + 구조신호(단일 클러스터·동일 검증) 1개 이상)를 추가하고, 재합침한 큰 리프는 phase 체크리스트(phase별 커밋·체크포인트·마지막 full-verify·세션 재진입)로 운영한다(0.18.1 dogfood #119 회고, DEC-2026-07-07-204311).
- `0.18.1`: FF closeout edge primitive — review-free `ready_for_closeout` 처리에서 git/gh/test/ledger 연쇄를 `closeout_ff_edge.py` 한 번으로 감싸 compact JSON만 모델에 노출한다. 성공 ledger 기록은 closeout events와 completed 정리를 한 write로 적용한다.
- `0.18.0`: orchestrate closeout lane — implementation worker 병렬성은 유지하고, `BASE_BRANCH`별 FIFO one-shot closeout lane으로 FF/PR merge 순간만 직렬화한다. worker는 review가 필요 없으면 `ready_for_closeout`을 기록하고, review가 필요한 edge는 PR/review log를 남긴 뒤 `ready_for_pr_closeout`으로 PR closeout에 들어간다. ledger에 `ready_for_closeout`/`ready_for_pr_closeout`/`closeout_started`/`closeout_done`/`closeout_failed` 이벤트와 compact `--summary` 출력, 실패 closeout 재큐잉 helper를 추가했다.
- `0.15.3`: 0.14~0.15 계열 hardening — wiki vault가 없는 consumer repo에서는 merge preflight가 `vault_missing`으로 죽지 않고 명시적 skip evidence를 남긴다. child `gate_evidence` 재사용은 `changed-path-stale`에 영향을 주는 active wiki frontmatter surface(`type`/`affects_paths`/`verified_at`/as-of date) hash가 현재와 같을 때만 허용한다. micro/normal FF 경로도 `merge_preflight.py --ff-gate`로 `gate_evidence`를 ledger에 기록한다. `define.review-required`는 `.task-github.yml` 검증을 통과한 boolean만 신뢰하며 invalid config는 이슈 생성을 막는다.
- `0.15.2`: define challenge review 코드 강제 — `.task-github.yml` `define.review-required=true`면 `create_issue_tree.py`가 spec의 `challenge_review.verdict=="approved"` 없이는 dry-run 포함 이슈 트리 생성을 거부한다. 프롬프트 준수에 기대던 review 필수화를 agent-independent precondition으로 올렸다.
- `0.15.1`: closeout preflight evidence 재사용 — `merge_preflight.py`가 PR view/status를 `preflight_evidence`로 ledger에 기록하고, `closeout.py`는 같은 PR/head의 fresh evidence를 PR view 입력으로 재사용한다. TTL 만료·필드 누락·status 실패·PR/head 불일치면 기존 GitHub 조회로 fallback한다. 실제 merge에는 `--match-head-commit`을 붙여 preflight 이후 head drift를 차단한다.
- `0.15.0`: define challenge review — co-design 뒤·이슈 트리 생성 전 적대 challenge 게이트([[DEC-2026-07-03-012207]]). 기본 off, `--review`로 on. 도구 우선순위 지시>설정(`define.review-tool`)>하네스(내장); `orchestrator_ops.resolve_review_tool`/`compose_tool_command`으로 해소·relay. 터미널=하네스(STOP 아님, co-design 자리라 내장 fresh-context refute 서브에이전트로 fallback). 대상=분해 제안(4 cut-reason + 위키 결정 그래프). 1 라운드·blocking만 게이트·사람 판정. 복잡도 넛지(트리 리프 수/깊이 초과 시 `--review` 권장, off 유지). 저-의존(하네스 fallback standalone, session-review hard dep 없음).
- `0.14.0`: merge-edge gear — 세리머니(plan/verify/PR/review)를 리프가 아니라 부모로 합류하는 머지 엣지의 gear 속성으로 이동([[DEC-2026-07-02-224910]]). micro/normal 리프는 로컬 FF 머지(무PR, `ff_merge_command`)로 close 증거는 verify+SHA range; major만 PR+review. 컨테이너 gear는 자식 누적 승격(`container_gear_promotion`: micro×3→normal, normal×2→major)으로 결정. ledger `ff_merged` 이벤트 추가. all-PR([[DEC-2026-07-02-212109]])을 gear-gated로 부분 개정하되 메인-트리-HEAD-불변식 유지.
- `0.13.0`: merge closeout를 all-PR로 통합 — local mode(`--mode local`)·local merge simulation·Integration Ledger 제거. epic/컨테이너 머지업도 PR화(`gh pr create`+`gh pr merge`)하고, 머지 후 base 갱신을 checkout→`git fetch`로 바꿔 오케스트레이션 중 메인 워크트리 HEAD가 trunk 불변([[DEC-2026-07-02-212109]]).
- `0.12.0`: gear별 `plan`/`verify`/`pr-review` flow option과 `orchestrate.gear-options` 설정 추가.
- `0.11.0`: orchestrate write-through ledger, ledger-only ready tick, non-default base issue close, post-merge cleanup warnings, `gear:normal` review skip.
- `0.8.0`: context bundle resolver, Execution Contract, PR/local closeout, local merge simulation, Integration Ledger, status next_action, doctor/reconcile 추가.
