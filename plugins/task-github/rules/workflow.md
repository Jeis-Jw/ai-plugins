# GitHub/Git 워크플로우 규약

> 이 룰은 GitHub·Git 조작의 **공통 절차**다. 모든 스킬이 공유한다.

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

코드 변경 작업은 워크트리를 사용한다. orchestrate에서는 parent issue 브랜치를 base로, 루트는 `.task-github.yml base_branch`를 base로 쓴다.
```bash
touch .gitignore
grep -qxF ".worktrees/" .gitignore || printf "\n.worktrees/\n" >> .gitignore
git worktree add .worktrees/issue-{N} -b task/issue-{N} <base-branch>
git worktree remove .worktrees/issue-{N} && git branch -d task/issue-{N}
```
- `.worktreeinclude` 파일이 있으면 gitignore된 파일(`.env` 등)을 워크트리로 복사.
- 워크트리 생성 전 대상 프로젝트 `.gitignore`에 `.worktrees/`가 없으면 추가한다.
- 진입 후 `git status --short`로 잔재 점검 — 있으면 `git clean -fd` **제안만**(자동 실행 금지).

---

## 5. Execution Contract (루트 이슈)

integration 전략은 매번 profile+gear에서 재추론하지 않고, root issue 생성 시 body에 materialize한다. 형식은 parser-safe JSON fenced block이다:

````markdown
```task-github-execution
{"schema_version":1,"wiki_task":"TASK-...","topology":"stacked","gate":"pr","parent_branch":"task/root-10","leaf_policy":{"risk_class":"normal"},"required_checks":[["python3","-m","pytest","plugins/task-github/tests/","-q"]],"closeout_mode":"pr"}
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

## 6. Closeout (all-PR)

모든 머지는 PR 경로(`gh pr merge`, remote) 하나다. 리프 PR도, 컨테이너/epic 머지업 PR도 `closeout.py --pr {PR}`로 닫는다. 로컬 `git checkout`/`git merge` 경로는 없다 — 머지 후 base 브랜치 갱신도 `git fetch origin {base}:{base}`(base가 현재 HEAD면 `git pull --ff-only`)로 처리해, 오케스트레이션 중 사령관의 메인 워크트리 HEAD가 trunk를 벗어나지 않는다([[DEC-2026-07-02-212109]]).

머지 전 hard gate(위키 가용 시 `refresh --level integrity --strict` + PR diff `changed-path-stale`)는 merge 스킬이 closeout **전에** 적용한다 — closeout 스크립트는 wiki를 모른다([merge](../skills/merge/SKILL.md) Step 2).

epic/컨테이너 브랜치는 worker가 없어 PR이 자동 생성되지 않으므로, orchestrate가 `gh pr create --base task/issue-{parent} --head task/issue-{container}`로 통합 PR을 만든 뒤 리뷰 없이 즉시 머지한다(자식은 이미 리뷰·머지됨). PR 자체가 통합 로그라 별도 ledger를 만들지 않는다. (orchestrate 실행 중 `.task-github/orchestrate/{root}.json` write-through ledger는 run-state 추적용으로 별개이며 wiki task에 쓰지 않는다.)

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
