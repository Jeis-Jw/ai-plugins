# GitHub/Git 워크플로우 규약

> 이 룰은 GitHub·Git 조작의 **공통 절차**다. 모든 스킬이 공유한다.

---

## 0. 스크립트 경로 해소 (Claude Code · Codex 공통)

스킬의 python 스크립트/CLI 경로는 **레포-vendored 상대경로를 하드코딩하지 않는다**(`plugins/task-github/...`는 cache 설치·Codex·리프 워크트리에서 존재하지 않아 조용한 스킵을 유발한다). 모든 호출부는 플러그인 루트를 아래 순서로 인라인 해소한다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/<name>.py" ...
```

- `TASK_GITHUB_ROOT` — 명시 override(절대경로). orchestrate 핸드오프가 worker에 주입하고, 사용자/하네스도 지정할 수 있다. **항상 최우선**.
- `CLAUDE_PLUGIN_ROOT` — Claude Code가 스킬 실행 시 자동 설정하는 플러그인 루트.
- **Codex 등 둘 다 없는 하네스**: 이 스킬이 로드된 플러그인 루트로 `TASK_GITHUB_ROOT`를 지정한다(session-review와 동일 규약).
- Bash 툴은 호출마다 새 셸이라 env가 블록 간 유지되지 않으므로, 각 호출부가 위 파라미터 확장을 **인라인**으로 다시 쓴다(블록 간 변수 대입에 기대지 않는다). heredoc은 `python3 - "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}" <<'PY'`로 argv[1]에 루트를 넘긴다.
- **해소 실패는 fail-loud STOP**이다 — 게이트/ledger 스텝을 조용히 스킵하지 않는다. 예: `[ -f "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" ] || { echo "[중단] 루트 미해소"; exit 1; }`.

회귀 방지: `tests/test_skill_path_portability.py`가 skills/rules 마크다운에 `plugins/task-github/` 리터럴이나 `CLAUDE_SKILL_DIR` 사용이 남으면 실패한다.

---

## 1. 라벨 체계

라벨은 **2계열**로 나뉜다.

### 상태 라벨 (작업 단계, 교체/제거)

| 라벨 | 의미 |
|------|------|
| `in-progress` | 작업/재작업 중 |
| `in-review` | 리뷰 대기/검토 중 |
| `changes-requested` | 피드백 반영 필요 |

### 기어 라벨 (작업 성격, 1개 필수, 영구 유지)

| 라벨 | 의미 | 색상 |
|------|------|------|
| `gear:micro` | 자기 파일 내부 | `0E8A16` |
| `gear:normal` | 자기 서비스 내부 | `FBCA04` |
| `gear:major` | 외부 계약 변경 | `D93F0B` |

> **불변식**: 상태 라벨은 "교체만", 기어 라벨은 "한 번 붙이면 유지". 정리 로직(done/review/merge)은 **상태 라벨만 제거하고 `gear:*`는 절대 건드리지 않는다.**

---

## 2. 상태 전이

### Issue
```
(없음) ──start──► in-progress ──done(PR생성)──► in-review
                                              │
         ┌────────────────────────────────────┘
         │ review
         ▼
  APPROVED → merge → (라벨 제거 + close)
  CHANGES_REQUESTED → changes-requested ──run(재작업)──► in-progress
```

### PR
```
done(PR 생성, 라벨 없음) ──review 픽업──► in-review ──► APPROVED → merge
                                                    └─► CHANGES_REQUESTED → changes-requested
```
- `done`은 PR을 **라벨 없이** 생성한다(Issue만 `in-review`로 전이). PR의 `in-review`는 **`review`가 픽업할 때** 부착한다(중복 검토 방지). 재작업 후 push 시 PR `in-progress`는 제거돼 다시 리뷰어 픽업 대기 상태(라벨 없음)로 돌아간다.

### 위키 task 노드 (이진 상태, 연동 시)
```
define(capture) ──► 활성(wiki/task/) ──루트 이슈 close(merge)──► 완료(wiki/task/done/)
                       완료 ──reopen(이슈 재오픈)──► 활성
```
- 연동 시 **GitHub 이슈가 상태 정본**, 위키 task는 그 투영. merge가 루트 이슈를 close하면 task를 `complete`로 전이. 상세는 [wiki-bridge.md](wiki-bridge.md).

### DefinitionArtifact local lifecycle

새 define 경로의 정본은 immutable DefinitionArtifact revision이다. local run은 `definition_id + revision + digest`를 pin하며 다음 전이만 허용한다:

```
started ──run──► running ──verify──► verified ──done──► done ──closeout──► closed
```

- `recover`는 현재 state와 다음 event를 반환하며 상태를 추정하거나 건너뛰지 않는다.
- `record:none`은 GitHub Issue write를 금지한다. delivery는 별도 축이므로 `local-ff|pull-request` 중 하나를 독립 선택한다.
- `record:github`은 root, 모든 descendant, 모든 dependency edge가 projection checkpoint에 materialize된 뒤에만 `local-start`를 허용한다. partial projection은 같은 artifact digest로 resume한다.
- 신규 local identity는 stable node id에서 파생한 `task/definition-*` / `.worktrees/definition-*`을 사용한다. revision이 바뀌어도 logical node key가 같으면 identity가 유지된다.
- legacy Issue-first는 기존 `task/issue-{N}` / `.worktrees/issue-{N}`과 Issue 상태 전이를 그대로 유지한다.

helper 호출:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact "$ARTIFACT" --run-state "$RUN_STATE" --event run
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" recover \
  --artifact "$ARTIFACT" --run-state "$RUN_STATE"
```

closeout 후 binding receipt schema v1을 방출한다. token 측정값은 `exact`, 없으면 `tokens:null`, `token_coverage:unavailable`이며 0이나 추정값으로 대체하지 않는다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" receipt \
  --run-state "$RUN_STATE" --workflow task-github
```

### 중복 방지 쿼리 (team 협업)
```bash
is:open is:issue label:in-progress,in-review                  # 점유됨(건드리지 않음)
is:open is:issue label:changes-requested                      # 재작업 대기(원작업자 우선)
is:open is:issue -label:in-progress -label:in-review -label:changes-requested no:assignee  # 가용
is:open is:pr -label:in-review -label:in-progress             # 리뷰 가능 PR
```

---

## 3. Issue dependency

GitHub sub-issue는 업무 분해 구조이고, 작업 선후관계는 GitHub Issue dependencies가 정본이다. 자세한 절차는 [dependencies.md](dependencies.md).

| 관계 | 의미 | 워크플로우 효과 |
|------|------|----------------|
| dependency 없음 | 선행 제약 없음 | 병렬 가능 |
| `blocked_by` | 선행 이슈 완료 대기 | 열린 blocker가 있으면 `start`/`run`/`done`/`merge` 차단 |
| `blocking` | downstream을 막음 | 완료 후 downstream ready 후보 안내 |

---

## 4. 브랜치 · 커밋 · 워크트리

| 항목 | 규칙 |
|------|------|
| 기본 브랜치 | `.task-github.yml` `base_branch` (필수, 예: `main`) |
| 작업 브랜치 | `task/issue-{N}` |
| 워크트리 경로 | `.worktrees/issue-{N}` |
| 커밋 형식 | `{type}: {요약} (#{N}) — {Why}` |
| 커밋 type | `feat`/`fix`/`docs`/`refactor`/`test`/`chore` |
| 커밋 원칙 | 원자적(1커밋=1논리변경), WIP 금지 |

코드 변경 작업은 워크트리를 사용한다. **모든 리프**는 자기 워크트리(`.worktrees/issue-{N}`) + 자기 브랜치(`task/issue-{N}`, base=부모 브랜치)를 갖는다. **컨테이너/부모 브랜치는 순수 ref**다 — 워크트리도 체크아웃도 없이 closeout lane이 FF로만 전진한다([[DEC-2026-07-02-224910]]). orchestrate에서 리프 base는 parent issue 브랜치, 루트는 `.task-github.yml base_branch`다.
```bash
touch .gitignore
grep -qxF ".worktrees/" .gitignore || printf "\n.worktrees/\n" >> .gitignore
git worktree add .worktrees/issue-{N} -b task/issue-{N} <base-branch>
git worktree remove .worktrees/issue-{N} && git branch -d task/issue-{N}
```
- 리프 워크트리는 issue closeout 이후 정리한다. review 없는 edge는 closeout lane의 로컬 FF 이후, review 있는 edge는 PR merge 이후 정리한다.
- `.worktreeinclude` 파일이 있으면 gitignore된 파일(`.env` 등)을 워크트리로 복사.
- 워크트리 생성 전 대상 프로젝트 `.gitignore`에 `.worktrees/`가 없으면 추가한다.
- 진입 후 `git status --short`로 잔재 점검 — 있으면 `git clean -fd` **제안만**(자동 실행 금지).

---

## 5. Execution Contract (루트 이슈)

integration 전략은 매번 profile+gear에서 재추론하지 않고, root issue 생성 시 body에 materialize한다. 형식은 parser-safe JSON fenced block이다:

````markdown
```task-github-execution
{"schema_version":1,"wiki_task":"TASK-...","topology":"stacked","gate":"pr","parent_branch":"task/root-10","leaf_policy":{"risk_class":"normal"},"required_checks":[["pytest","-q"]],"closeout_mode":"pr"}
```
````

stable keys:
- `wiki_task`
- `topology`
- `gate`
- `parent_branch`
- `leaf_policy`
- `required_checks`
- `closeout_mode`

unknown key는 parser가 무시한다. contract가 없으면 context bundle은 `topology/gate/parent_branch=null`과 `default_source=profile+gear`를 낸다.

> 경계: Execution Contract는 루트 이슈의 실행 계약(how)이다. 작업정의와 취지(why/what)는 계속 wiki TASK 노드가 맡는다. branch/worktree/PR metadata나 contract가 wiki TASK를 대체하지 않는다.

---

## 6. gear-gated merge

머지 의식(ceremony)은 리프의 속성이 아니라 **머지 엣지**(노드가 부모에 합류하는 방식)의 속성이고, review 필요 여부가 transport를 게이트한다([[DEC-2026-07-02-224910]]). micro/normal은 review 없이 로컬 FF closeout, major는 기본적으로 PR+review다. 단, orchestrate `--review=skip`이면 major도 verify 후 로컬 FF closeout으로 가되 gear와 skip 근거를 ledger/report에 남긴다.

| 머지 엣지 기어 | 절차 | 머지 방식 |
|------|------|-----------|
| `micro` | run만 | 부모로 로컬 FF(PR 없음) |
| `normal` | plan+run+verify | 부모로 로컬 FF(PR 없음) |
| `major` | plan+run+verify | PR + 리뷰 후 머지 (`--review=skip`이면 로컬 FF closeout) |

**리프 머지업**
- review 불필요 edge(micro/normal, 또는 `--review=skip`의 major): worker는 구현/검증/커밋 뒤 부모 ref를 직접 전진시키지 않고 `ready_for_closeout` ledger 이벤트를 기록한다. closeout one-shot lane이 `BASE_BRANCH`별 lock을 잡고 `orchestrator_ops.ff_merge_command(child_branch=, parent_branch=)`가 내는 `git fetch . task/issue-{leaf}:task/issue-{parent}`로 부모 ref를 FF한다. close 증거는 **verify 리포트 + 커밋 SHA range**(머지된 PR을 대체). ledger에는 `ready_for_closeout` 이후 `ff_merged`/`closeout_done` 이벤트를 기록한다:
  ```bash
  python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" {LEDGER} --event ready_for_closeout --issue {N} --base task/issue-{parent} --head task/issue-{N} --head-sha {HEAD_SHA}
  ```
  closeout lane의 `ff_merged` 이벤트는 issue state를 `close_expected`로 두고 `ff_merged` 증거를 남긴다. `orchestrator_ops.child_merge_evidence`는 자식별로 세 가지 close 증거를 받는다: `closed_no_pr`(no-code no-op close) / `merged_pr:{base}`(review 필요 PR 머지) / `ff_merged:{base, sha_range}`(로컬 FF — `sha_range`는 머지된 PR을 대신하는 필수 필드).
- review 필요 edge(기본 major): PR 경로 그대로다. PR 생성/리뷰 대기 동안 parent lock을 잡지 않고, 승인 후 merge 순간만 closeout lane이 `BASE_BRANCH` lock을 잡는다. `closeout.py --pr {PR}`로 닫고, ledger에는 `pr_merged` 이벤트를 남긴다. close 증거는 머지된 PR.

머지 전 hard gate(위키 가용 시 `refresh --level integrity --strict` + PR diff `changed-path-stale`)는 merge 스킬이 closeout **전에** 적용한다 — closeout 스크립트는 wiki를 모른다([merge](../skills/merge/SKILL.md) Step 2).

**컨테이너/epic 머지업 (container_gear_promotion 게이트)**

컨테이너의 머지업 기어는 자기 라벨이 아니라 **자식들에 대한 누적 승격**으로 매 머지 엣지에서 새로 계산한다 — `orchestrator_ops.container_gear_promotion(child_gears)`. 베이스는 자식 기어의 최대치(micro<normal<major)이고, 여기서 micro 3개↑는 최소 normal로, normal 2개↑는 major로 승격한다(알 수 없는/없는 자식 기어는 micro로 셈, 컨테이너 자기 gear 라벨은 무시). 따라서 normal×2→major, micro×3→normal이라 작은 작업의 누적은 **trunk에 닿기 전 반드시 리뷰 게이트를 한 번 통과**한다. (`ready_leaves`의 `container_done`/`done_parents` 항목과 `plan_tick`의 `merge_container` 액션은 이 누적 실효 기어를 `gear` 필드로 실어 나른다.)

- review 필요 컨테이너(major 또는 major로 승격된 컨테이너): epic/컨테이너 브랜치는 worker가 없어 PR이 자동 생성되지 않으므로, orchestrate가 `gh pr create --base task/issue-{parent} --head task/issue-{container}`로 통합 PR을 만들고 리뷰를 거친 뒤 머지한다(자식은 이미 리뷰·머지됨). PR 자체가 통합 로그라 별도 ledger를 만들지 않는다.
- review 불필요 컨테이너: 리프와 동일하게 closeout lane이 `ff_merge_command`가 내는 fetch refspec으로 컨테이너 브랜치를 부모로 로컬 FF 전진시킨다. PR 없음.

(orchestrate 실행 중 `.task-github/orchestrate/{root}.json` write-through ledger는 run-state 추적용으로 별개이며 wiki task에 쓰지 않는다.)

**웨이브 동결 (머지업 개시 후)**

컨테이너 머지업이 시작되면 그 웨이브의 리프/컨테이너 브랜치는 **동결**된다 — 통합 PR/FF가 진행 중일 때 리프에 늦은 커밋을 밀어넣으면 통합이 그 커밋을 앞질러 머지돼 trunk에서 누락되는 near-miss가 난다. 머지업 개시 전 orchestrate는 pending-work 스캔으로 **미커밋** 리프 워크트리를 STOP(`pending_work`)으로 잡는다(커밋된 미통합 작업은 `child_merge_evidence`가 이미 게이트하므로 여기선 uncommitted만 본다; [orchestrate](../skills/orchestrate/SKILL.md) container_done). 머지업 개시 뒤 발견한 수정은 그 웨이브에 끼워넣지 않고 **새 micro 이슈**로 뒤따른다(별도 FF/PR로 trunk에 합류).

**메인 워크트리 HEAD 불변식 ([[DEC-2026-07-02-212109]], 유지)**

오케스트레이션 중 사령관의 메인 워크트리 HEAD는 trunk를 벗어나지 않는다. FF가 fetch refspec(체크아웃이 아님)이라서다 — git은 non-FF ref 업데이트를 거부하고 체크아웃된 브랜치를 건드리길 거부하므로 어떤 워크트리 HEAD도 움직이지 않는다. 충돌(non-FF 거부)은 **항상 리프 워크트리 쪽에서** 해소한다: 호출자가 부모를 리프 워크트리로 역머지(reverse-merge)해 leaf-side에서 resolve하고, 재검증 후 재시도한다 — 사령관의 메인 워크트리에서 충돌을 풀지 않는다. 이번 변경은 [[DEC-2026-07-02-212109]]을 **부분 개정**한다: all-PR 획일성은 review-required edge만 PR로 완화하고(review-free edge는 로컬 FF, PR 없음), 메인-트리-HEAD-불변식은 그대로 둔다. 병렬 형제가 같은 부모를 두고 경합하는 경우도 별도 PR 경로가 아니라 `BASE_BRANCH`별 closeout lane + fetch-refspec FF + 리프측 역머지로 처리한다.

---

## 7. PR 규약

PR 본문은 다음을 포함한다:
```
Closes #{N}

## 구현 결과
- 무엇을 만들었는가

## 테스트 증거
- 어떻게 검증했는가

## 검토 포인트
- 사령관이 특히 확인할 부분
```

---

## 8. 브랜치트리 / orchestrate

- GitHub 이슈트리의 각 노드는 `task/issue-{N}` 브랜치를 가질 수 있다.
- 자식 PR base는 부모 브랜치다. 루트 PR base는 `.task-github.yml base_branch`다.
- non-default branch merge는 GitHub auto-close에 의존하지 않는다. merge/orchestrate가 `gh issue close`를 명시 수행한다.
- orchestrate는 시작/재개/실패 복구 때만 GitHub를 reconcile하고, 평상시 tick은 `.task-github/orchestrate/{root}.json` write-through ledger를 읽는다. 성공한 issue/PR write는 ledger `events[]`와 derived state에 즉시 반영한다.
- orchestrate는 configured review-tool/conflict-agent가 있을 때만 자동화한다. 없으면 review 필요 PR은 `human_gate_review`, merge conflict는 `merge_conflict`로 STOP한다. 병렬 worker는 issue별 background lane으로 dispatch하고 completion re-tick으로 review를 시작한다.

*이 룰이 바뀌면 모든 스킬의 GitHub 조작이 바뀐다.*
