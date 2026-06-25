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
| 메인 브랜치 | `main` |
| 작업 브랜치 | `task/issue-{N}` |
| 워크트리 경로 | `.worktrees/issue-{N}` |
| 커밋 형식 | `{type}: {요약} (#{N}) — {Why}` |
| 커밋 type | `feat`/`fix`/`docs`/`refactor`/`test`/`chore` |
| 커밋 원칙 | 원자적(1커밋=1논리변경), WIP 금지 |

워크트리 사용 조건: 병렬 작업 / main 오염 방지 / 다중 브랜치 전환.
```bash
touch .gitignore
grep -qxF ".worktrees/" .gitignore || printf "\n.worktrees/\n" >> .gitignore
git worktree add .worktrees/issue-{N} -b task/issue-{N}
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
{"schema_version":1,"wiki_task":"TASK-...","topology":"stacked","gate":"local-merge","parent_branch":"task/root-10","leaf_policy":{"risk_class":"normal"},"required_checks":["python3 -m pytest plugins/task-github/tests/ -q"],"closeout_mode":"local"}
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

## 6. Local / Stacked Closeout

PR 없는 self-flow는 `closeout.py --mode local`을 쓴다. local mode는 편의 기능이 아니라 **검증된 로컬 머지**다.

| leaf 위험 클래스 | 강제 게이트 |
|---|---|
| `micro` / `normal` | leaf verify + drift + blocker |
| `major` | 위 항목 + self-flow |
| `irreversible` / `db` / `public-api` / `security` / `data-loss` | 위 항목 + PR 또는 hard self-flow |

local closeout은 반드시 temp worktree에서 parent branch 기준 merge simulation을 만든 뒤, Execution Contract의 `required_checks` + `changed-path-stale` evidence + integrity evidence가 모두 통과해야 parent branch에 실제 merge한다.

Integration Ledger는 `topology=stacked` + `closeout_mode=local`에서만 root issue comment에 append-only로 남긴다:

````markdown
<!-- task-github:integration-ledger:v1 -->
```task-github-ledger
{"schema_version":1,"leaf":42,"sha":"abc123","checks":[],"drift":{"issues":[]},"downstream":[]}
```
````

flat/PR 흐름은 PR 자체가 실행 로그이므로 ledger를 만들지 않는다. Ledger는 GitHub root issue 산출물이며 wiki task에 쓰지 않는다.

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

*이 룰이 바뀌면 모든 스킬의 GitHub 조작이 바뀐다.*
