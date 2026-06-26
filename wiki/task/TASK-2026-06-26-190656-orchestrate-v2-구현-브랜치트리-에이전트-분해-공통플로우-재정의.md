---
title: orchestrate v2 구현 — 브랜치트리 + 에이전트 분해 + 공통플로우 재정의
created_at: 2026-06-26
summary: task-github orchestrate 스킬을 공통 플로우(worktree·PR 필수) 위 브랜치트리 머지업 + 전문 에이전트 분해로 구현. 설계 r5 정본.
tags: [orchestrate, task-github, architecture, branch-tree, config]
relations:
  decisions: [DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]
---

## 개요

이슈트리(직렬·병렬 혼합)를 루트에서 시작해 task-github 규칙대로 절차적 자동수행하는 orchestrate 스킬을 구현한다. 공통 플로우(open→start→run→done→[review]→merge→close)를 이슈트리 위에서 자동 구동하는 레이어. 현재 orchestrate는 PLAN.md만 있고 미구현.

## 근거

사람의 이슈트리 수동 드라이브(next→실행 반복)를 자동화 + 코드 통합(머지업)을 완료 플로우에 포함. 결정 근거 = DEC-2026-06-26-190009. r1~r4 단일역할·micro-light·CLAUDE.md 프로파일 프로즈를 개정하는 plugin 전체 규칙 변경(major).

## 범위와 완료 기준

> 이 task 노드가 orchestrate v2 구현의 **정본 작업정의 + 설계**다. 구현 착수 시 `define`이 이 노드를 소비해 GitHub 구현트리를 만든다. 근거 결정: [[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]].

### 완료 기준 (구현 영향면)

- **스파인 정돈**: start(점유만)·run(worktree)·done(PR+부모base+in-review)·merge(충돌해소+close)
- **트리 선행 정돈**: define(child spec gear + dep 필수 materialize + Execution Contract)·open(parent_branch/topology 브리핑)
- **신규**: `skills/orchestrate/`(SKILL.md 루프 + `ready_leaves.py`) · 워크스페이스 루트 `.task-github.yml`(정본 config) · conflict-agent(v2)
- **재사용**: work-agent=Agent로 start→run→done / reviewer-agent=session-review / 위임=`*-tool` config
- **동반 갱신**: `rules/workflow.md`·`rules/task-protocol.md`(worktree·PR 필수 + 프로파일→`.task-github.yml mode` 이관 + orchestrate solo 게이트)·`DESIGN.md §4.x` · setup(scaffold)·doctor(validate)
- **제거**: next 스킬(status 중복)
- v1/v2 staging은 아래 설계 §11.4.

---

## 설계 (PLAN r5 정본)

## 1. 문제

GitHub 이슈+서브이슈로 정의된 작업트리(직렬·병렬 혼합)를, 루트 이슈에서 시작해
task-github 규칙대로 절차적으로 자동 수행하고 싶다. 현재는 사람이 세션을 직접 열어
`next`→실행을 반복하는 수동 드라이브 외 오케스트레이션 수단이 없다.

## 2. 핵심 통찰

- **작업트리 = GitHub에 영속.** 에이전트 중첩/재귀 불필요.
- 상태 = 이슈 라벨(`in-progress`/`in-review`/`changes-requested`/`gear:*`) + dependency + 트리관계.
- 실행 = **평평한 루프 1개**가 임의 깊이 트리를 순회. 매 tick GitHub에서 ready-set 재유도.
- GitHub = SoT. 루프가 트리 상태를 컨텍스트에 **캐싱하지 않는다**(드리프트 방지).

## 3. 역할 (2개 — 고정트리라 판단 LLM 불필요)

| 역할 | 정체 | 책임 |
|------|------|------|
| root | main thread (skill 실행) | 루프 구동, ready-set 산출, worker spawn, **컨테이너 close**, **사람 게이트 STOP** |
| worker × N | Agent 서브에이전트 | 리프 이슈 1개 수행(기존 start→run→done 재사용), **상태 라벨 전이 전담**, 요약만 리턴 |

오케스트레이터 서브에이전트는 두지 않는다(고정트리 전제, r1 검증됨). LLM 역할 = worker 하나.

## 4. 직렬/병렬 인코딩 (선언적)

| 관계 | GitHub 표현 |
|------|-------------|
| 부모-자식(트리 깊이) | sub-issue |
| 병렬 형제 | dependency 엣지 없음 (동시 ready) |
| 직렬 형제 | `blocked_by` 체인 |
| 컨테이너 완료 | `subIssuesSummary{total,completed}` total==completed (S2: GitHub이 직접 줌) |

스케줄을 코딩하지 않는다. dependency 그래프 = 스케줄 그 자체.

예시 트리:
```
main (병렬: 1, 2)
 ├ 1 (직렬)   1-2 ─blocked_by→ 1-1
 │  ├ 1-1  └ 1-2
 └ 2 (병렬: 2-1, 2-2)
    ├ 2-1 (직렬)  2-1-2 ─blocked_by→ 2-1-1
    │  ├ 2-1-1  └ 2-1-2
    └ 2-2
```
tick0 ready = {1-1, 2-1-1, 2-2} → 캐스케이드 → main close.
**이 검산은 ready_leaves self-check fixture로 고정한다(nit).**

## 5. 산출물

### 5.1 `skills/orchestrate/scripts/ready_leaves.py` (신규 — prior art 재사용, 신규 로직 최소)

reviewer 확인: context_bundle.py는 단일이슈·gh미호출이라 재사용 불가가 맞다.
**prior art 재사용 범위를 정직하게 한정한다(S1 — r4 보정):**
- `skills/open/SKILL.md` Step2-3에서 재사용하는 것은 **GraphQL 쿼리 shape**(필드명
  `subIssues`/`subIssuesSummary`/`parent`)뿐이다. open은 `subIssues(first:50)` **1레벨
  스냅샷**(재귀 없음, 커서 없음, open/SKILL.md:30·57)이므로 **임의 깊이 walk는 차용 대상이
  아니라 신규 로직**이다. §4 예시의 depth-3(`2-1-2`)을 도는 재귀 하강 + 커서 페이지네이션은
  net-new임을 명시한다(이게 self-check 개수를 늘리는 근거 — 아래).
- `closeout.py`의 `_parent` / `_open_blockers` / `_blocking` / `_detect_root_task` = 구현·테스트됨 → 노드단위 판정 헬퍼로 그대로 import/이식(여기는 진짜 재사용).

- 입력: root 이슈# + root 루프가 가진 `spawned_set`/`failed_set`.
  GitHub만으로는 "이번 루프가 띄운 worker"를 알 수 없으므로 helper가 추론하지 않는다.
- 동작: 서브이슈 재귀 walk(GraphQL `subIssues`, **커서 페이지네이션 루프 필수** — `open/SKILL.md`의 `first:50` 예시는 그대로 복사하지 않는다), 노드별 open/리프/blocker 판정
- 출력 JSON:
  - `ok` — false면 진행 불가. **모든 STOP은 단일 `stop_reason` 채널로 흐른다(C6 — r4 신규)**:
    enum `human_gate_review | human_gate_major | invalid_gear | stuck | dep_cycle |
    api_failure | no_progress | empty_tree`. 분기별로 7가지 shape를 SKILL 루프가 각각
    패턴매치하던 것을 평평한 dispatch 1개로 접는다. **누락 케이스가 조용한 `ready=[]`로
    degrade되는 것을 구조적으로 막는다** — §5.1이 이미 "API 실패를 조용한 ready=[]로
    숨기지 않는다"고 약속한 원칙을 API 너머로 일반화한 것.
  - `ready[]` — 수행가능 리프. **각 항목에 `gear` 포함**(B1: spawn 전 게이트용)
  - `blocked[]` — 열린 blocker 있는 리프
  - `review_waiting[]` — `in-review`/`changes-requested` 등 사람 review/merge가 필요한 리프 → `stop_reason: human_gate_review`
  - `invalid_gear[]` — gear 라벨이 없거나, 여러 개거나, `micro|normal|major` 밖인 ready 리프 → `stop_reason: invalid_gear`. default 금지.
    - **한계(F2): `invalid_gear`는 구조적 위반만 잡는다(결손/중복/집합 밖). _의미적 오분류_(파급 큰 리프에 잘못 붙은 `gear:micro`)는 못 잡는다.** orchestrate는 define 시점 gear를 신뢰한다(B1 trust model, §6 참조).
  - `stuck[]` — **in-progress 리프 중 active spawned worker가 아닌 것** → `stop_reason: stuck`. root가 넘긴
    `spawned_set`/`failed_set`으로만 판정한다. 각 항목 `reason: prior_run|spawned_failed` (C4)
  - `done_containers[]` — root issue를 제외한, `subIssuesSummary` total==completed 인 미close 컨테이너 (S2). STOP 아님(root가 close 후 re-tick).
  - `root_done` — root issue 완료는 이 경로로만 보고하고 `done_containers[]`에 넣지 않는다
- **엣지 케이스(F5 — r4 신규, 조용한 오판 방지):**
  - **빈 트리 / root-is-leaf**: root에 subIssue 0개면 root 자체가 리프다 → `ready=[{root}]`이
    아니라 즉시 `root_done`도 아니다. v1은 `stop_reason: empty_tree`로 STOP(orchestrate는
    트리 실행 도구 — 단일이슈는 기존 start/run/done이 담당). 시작 즉시 크래시 방지.
    `ponytail:` upgrade path — root-is-leaf = size-1 degenerate tree. 루프는 이미 단일 리프
    실행법(spawn→start/run/done)을 안다. start-gate parity 확인되면 STOP 대신 single-leaf로
    실행하도록 승급(v1은 명확한 브리핑 STOP가 ceiling).
  - **`blocked_by` 사이클**: 모든 열린 리프가 서로 blocked → ready=∅인데 트리 미완.
    완료처럼 보이지 않도록 `stop_reason: dep_cycle`로 명시(D3 no_progress와 구분).
  - **root가 gear:major**: root는 컨테이너라 spawn 대상이 아니므로 gear는 무시(컨테이너는
    worker가 실행하지 않음). 단 root가 동시에 리프면(위 empty_tree 경로) STOP.
  - **blocked이면서 컨테이너인 노드**: 자식 전부 closed지만 자기 `blocked_by`가 열림 →
    `done_containers`도 `ready`도 아님. blocker close까지 어느 분기에도 안 들어가
    starvation처럼 보이나, blocker가 닫히면 다음 tick에 done_containers로 승급한다.
    **어느 set에서도 조용히 drop되지 않음을 self-check로 고정**(F3).
- item shape는 `{number,title,state,labels,reason?}`까지만 맞춘다. 별도 formatter는 아직 만들지 않는다.
- self-check는 **6개** 동봉(F1·F7로 4→6): ① §4 예시트리 tick0 ready(**실제 depth-3 fixture**, flat mock 금지), ② `invalid_gear`, ③ dependency API failure, ④ done_containers+ready 동시 → close 후 re-tick(**버린 ready[]가 다음 tick에 재등장함도 assert** — drop만 확인하면 starvation 회귀 가림), ⑤ **>50 자식 컨테이너 커서 페이지네이션**(N1 — 2페이지 stub 응답으로 리프 truncation 없음 확인; 가장 가능성 높은 silent data-loss 경로인데 현재 무검증), ⑥ **blocked-컨테이너 non-drop**(F3).
- **API 실패 거동(N2)**: `subIssues`/`dependencies` 조회 실패 시 **부분 ready-set 스폰 금지** — `ok:false` + `stop_reason: api_failure` 반환, 루프는 STOP(`rules/dependencies.md` §7 루프 버전).

### 5.2 `skills/orchestrate/SKILL.md` (절차 문서 — root 루프)
```
loop:
  r = ready_leaves.py(root, spawned_set, failed_set)  # 실패 시 stop_reason=api_failure → STOP
  # 분기 순서(C5, F8 보정): stuck을 root_done보다 먼저 — stuck이면 root_done 도달 불가.
  if not r.ok       → stop_reason 출력 + 브리핑 + 종료 (부분 진행 금지)
  r.stuck 있음      → 사람 게이트: STOP(stuck) + 브리핑 (자동 재시도 금지, B2)
  r.root_done       → 종료 + 보고          # stuck=∅ 전제下에서만 도달
  r.done_containers → container별 열린 blocked_by/API 실패 guard 후 root가 직접 close,
                      같은 tick의 ready[]는 버리고 re-tick         # STOP 아님
  r.review_waiting  → 사람 게이트: STOP(human_gate_review) + 브리핑
  r.invalid_gear    → 사람 게이트: STOP(invalid_gear) + 브리핑 (default 금지)
  r.ready 중 gear:major → 사람 게이트: STOP(human_gate_major) (spawn 전 거름, B1)
  r.ready (gear:micro|normal) → --max-workers 수만큼 worker spawn (기본 1)
                      batch barrier: 전부 return/fail/**per-worker timeout** 될 때까지 다음 tick 금지
                      timeout/fail은 failed_set에 넣고 STOP 브리핑
                      worker = 기존 start→run→done, 상태라벨 전이 전담, 요약만 리턴
  진행 단조성 검사: (closed leaf + done_containers) 증가 없으면 STOP(no_progress) (D3)
  max-iter = backstop (D3)
```
- **worker liveness(F4)**: barrier의 "timeout"은 **per-worker wall-clock 타임아웃**으로
  구체화한다 — 무한 hang(return도 fail도 아님)이 batch barrier를 livelock시키지 않도록.
  v1 `--max-workers 1` 기본에서는 hang worker = 즉시 STOP이라 영향 작음. multi-worker
  liveness 정밀화는 v1 이후로 미룬다(`ponytail:` 주석으로 ceiling 명시).
worker 새 코드 0. 기존 start/run/done 재사용.

## 6. 사람 게이트 (solo 정책 정합)

- review / merge / `gear:major` / `stuck` = **자동 금지, STOP + 브리핑.** solo capture authority.
- gear:major는 **spawn 전** ready_leaves의 `gear` 필드로 거른다(B1 — start 시점 라벨링에 의존하지 않음).
- gear 결손/중복/unknown은 default하지 않고 `invalid_gear[]` STOP으로 처리한다.
- 자동화 범위 = `gear:micro|normal` 리프의 start/run/done.

### gear 신뢰 모델 (B1 — F2로 명시화)

B1은 define 시점에 박힌 gear 라벨을 **신뢰**한다. 이게 "고정트리=완전스케줄" 철학의
직접 귀결이다(스케줄이 트리에 다 박혀 있어야 절차적 자동수행이 성립). 따라서:

- **correctness 책임 = spec 저자(define 시점).** `create_issue_tree.py`에는 gear 판단
  로직이 없다 — spec에 적힌 값을 라벨로 박을 뿐. orchestrate는 그 값을 재판단하지 않는다.
- **이건 start의 "기어 부여 유일 지점"(start/SKILL.md:8) 불변식을 orchestrate tree에 한해
  이동시킨다.** §8 cross-file 갱신이 이 이동을 명시 문서화한다(문구만 맞추는 게 아니라
  "누가 gear correctness를 소유하는가"를 적는다).
- **한계 자인**: `invalid_gear`는 구조만 검증한다. 의미적 오분류(파급 큰 리프에 `gear:micro`)는
  자동으로 통과해 spawn된다. solo 프로파일에선 수용 가능(저자=실행자=리뷰어 동일인)하나,
  **무비판 신뢰임을 PLAN에 적는다** — 숨기지 않는다.
- **surfaced 대안(reviewer 제안, 미채택)**: define 시점 pre-stamp 대신 ready_leaves가
  _missing gear_를 `stop_reason: judgment_needed` STOP으로 돌려 start의 판단 지점을
  보존하는 길도 있다(start/SKILL.md:78 "부여/유지"와 합성 가능, cross-file diff 더 작음).
  B1은 2라운드 approved 결정이라 이번엔 유지하되, 의미적 오분류 리스크가 실제 문제가 되면
  이 대안으로 전환하는 게 upgrade path다. **사용자 결정 사항으로 남긴다.**

## 7. 도구 선택

- worker = Agent 서브에이전트 (기존 스킬 재사용)
- 루프 = main thread가 foreground로 skill 실행. `/loop` unattended와 persistent spawned ledger는 v1에서 제외한다.
- 헬퍼 = python + gh GraphQL (open/closeout prior art 재사용). v1 API scope는 `blocked_by` 중심으로 시작한다.
- v1 기본은 `--max-workers 1`; 병렬 설계는 유지하되 rate limit/worktree lock/라벨 race 디버깅을 나중으로 미룬다.
- Workflow 미사용 (v1 라지; 병렬 강화 필요시 업글 경로)

## 8. 불변식 + 선행 입력

### 불변식
- **상태 라벨 전이는 worker만**(start/run/done/review). root는 컨테이너 close + 사람게이트 STOP만 → 라벨 경합 설계상 0 (D2).
- GitHub = SoT. 트리 상태 캐싱 금지.
- 부분 ready-set 스폰 금지 — API 실패면 전체 STOP.

### 선행 입력 (define/분해 산출물 — 루프 시작 전 트리에 박혀 있어야)
- **직렬 형제 `blocked_by` 엣지**
- **각 리프의 `gear:*` 라벨**(B1 — gear:major 사전식별 위해 define/분해 시점 선결. 고정트리=완전스케줄 철학과 정합)
  - **구현 주체(C1)**: `create_issue_tree.py` child spec(validate_spec)에 현재 `gear`/`labels` 필드 없음 → child spec에 `gear` 필드 추가 + `create_child_issue` execute에서 `gh issue edit {N} --add-label gear:{v}` 1줄. 이게 "gear 선결"의 실행 지점.
  - `plugins/task-github/skills/define/SKILL.md`의 spec 예시와 "기어 라벨 안 붙임" 불변식도 같은 커밋에서 orchestrate tree 예외로 갱신한다.
  - `plugins/task-github/DESIGN.md`와 `plugins/task-github/skills/start/SKILL.md`의 "start가 gear 부여 지점" 문구도 같은 커밋에서 선결 gear 예외를 최소 문구로 맞춘다.
- **모든 `blocked_by` dependency가 GitHub에 materialize되어야 한다.**
  `create_issue_tree.py`의 comment-only fallback은 수동 define에는 남길 수 있지만,
  orchestrate/gear-bearing tree에서는 dependency 생성 실패를 `dep_create_failed`로 실패 처리해 non-runnable로 둔다.
  - **구현 지점(F6)**: 현재 `add_dependency`(create_issue_tree.py:238)는 `IssueTreeError`를
    삼키고 comment를 달며 None 리턴 → `execute()`(:258)는 실패를 **알 수조차 없고**
    `dependencies_out`에 무조건 append한다. N3를 지키려면 `add_dependency`가 실패를
    호출자에 전파해야 한다. 최소 diff: `strict_deps` 플래그를 `add_dependency`→`execute`에
    스레드 — orchestrate tree는 raise(→`dep_create_failed`), 수동 define은 기존 comment
    fallback 유지. 공유 함수 1곳 + execute 결과 수집 1곳 변경.

### 알려진 한계 (구현시 `ponytail:` 주석)
- 동시 worktree 생성 경합 = 경로충돌 아님(경로 `issue-{N}` keyed). 공유 `.gitignore` append + `git worktree add` 레지스트리 락 → **worktree 생성단계만 직렬화** (D1)
- 병렬 worker 컨텍스트 누적 → 요약 리턴으로 억제
- `subIssues` 페이지네이션 커서 루프 필수 (N1)

## 9. 미해결 (r1 4 → r2 0)

- **확정(C3)**: 컨테이너 close = **root가 `done_containers` 신호로 직접 close**. 단 close 직전 열린 `blocked_by`와 dependency 조회 실패를 guard하고, 실패/열린 blocker면 STOP 브리핑한다. closeout.py는 root-close 감지만(트리 walk 캐스케이드를 떠안으면 single-issue 도구 성격이 흐려짐). 완료감지는 S2(subIssuesSummary)로 해결. → 미해결 0.

## 11. 브랜치트리 + 에이전트 오케스트레이션 (r5 — co-design 확장)

> v1 골격(§1~§9: 평평한 루프 + 단일 worker + 컨테이너=이슈상태)을 **코드 통합까지 포함하는
> 완료 플로우 + 전문 에이전트 분해**로 확장한다. §5.2의 v1 루프를 이 섹션의 flow가 대체/확장한다.

### 11.1 취지 (왜)

- **v1 한계**: 실행 자동화만 하고 **코드 통합(머지)은 사람 몫**으로 남았다. 이슈트리는 자동
  순회하되, 리프 PR을 main에 모으는 일은 수동.
- **브랜치트리 = 이슈트리 미러**를 두면 완료 플로우에 통합을 넣을 수 있다:
  - 컨테이너 브랜치 = 깨끗한 **rollback/리뷰 단위**.
  - 충돌이 **토픽 응집된 형제끼리, 일찍, 국소적으로** 해소된다(flat→main은 무관한 작업이
    main에서 늦게 충돌).
  - 완료 의미가 git으로 구체화: "부모 done = 자식들이 부모 브랜치에 통합됨".
- **오케스트레이터는 조율만**, 판단/작업은 전문 서브에이전트로 분리 → 단일책임 + 컨텍스트 격리.

### 11.2 논의 과정 (요약 라운드 로그)

1. 브랜치트리 제안 → 풀 1:1 미러 검토. repo CLAUDE.md "bundle for shipping" 반대논거는
   **잘못 적용**(그건 우리 dogfood 운영정책이지 설계 중 플러그인의 사용자대상 제약 아님)으로 **철회**.
2. 머지 비용 재평가: 비용 = **충돌해소뿐**, 총량은 보존되되 **국소화**(오히려 이득).
   `closeout.py`에 `parent_branch` + `run_merge_simulation`(`--no-commit --no-ff`,
   `simulation_merge_failed`) 이미 존재 → 기계 대부분 있음.
3. 과장한 약점 철회(top-down 브랜치생성=싸다 / "stacked rebase"=PR-stacking 용어오용,
   여긴 표준 integration merge / solo-가치=정책오적용). **진짜 약점만 남김**: ① micro 병렬
   write-race, ② GitHub auto-close가 non-default 브랜치 머지엔 안 터짐.
4. **always-PR 채택**: 모든 코드변경 리프가 PR을 올린다(자기 브랜치 → PR → 부모 브랜치).
   → micro 직접커밋 특수경로 제거, **race 소멸**(공유 브랜치 직접쓰기 없음 + GitHub server-side
   머지 직렬화), auto-close 미발화는 **명시 `gh issue close`**로.
5. 역할 분해 원칙: **결정론 op = 오케스트레이터 인라인 / 판단 op = 서브에이전트.**
   → work-closer는 전부 결정론(blocker체크=ready_leaves, 머지=closeout, close=gh)이라
   **에이전트 불필요, 스크립트.** LLM 래퍼 = 순수 오버헤드.
6. work-agent **단일경로**(항상 PR+report)로. 머지 결정+실행을 **1곳(오케스트레이터)**에 모음 —
   work-agent에 self-merge 분기를 주면 행동이 둘로 갈리고 머지권한이 분산돼 **더 복잡**.
7. **용어 충돌 수정**: "root"=루트 이슈/브랜치 전용, 조율 역할="오케스트레이터".
8. **session-review 매핑**: work-agent=worker, reviewer-agent=reviewer, 오케스트레이터=
   session-review **separate flow의 사람 릴레이를 자동화**한 것. (self flow 아님 — nested
   subagent spawn 불확실.) 그래서 changes-requested → work-agent 재spawn(address-feedback
   handoff 주입) → 라운드 캡 초과 STOP.
9. **completion-agent 폐기**: root 완료 시점 = 모든 자식·서브에이전트 끝난 **루프 종료상태** →
   동시성 보호 불필요 → **메인스레드 직접**. 위키는 **root 완료 1점에만**(서브이슈엔 task 노드
   없음). capture authority 가드 추가.
10. **리뷰정책 옵션** 추가(force-all / skip / gear-default).

### 11.3 최종 결정

**11.3.1 오케스트레이트 모드 + 옵션**
- **플로우는 공통(open→start→run→done→[review]→merge→close), 모드 무관.** orchestrate는
  그 공통 플로우를 **이슈트리 위에서 자동 구동**하는 레이어일 뿐 별도 플로우가 아니다.
  단일이슈 플로우도 같은 공통 규칙으로 갱신된다(worktree·PR 필수화 — §12, base 델타).
- 선택 이슈에서 파생되는 이슈트리를 메인스레드가 오케스트레이터로서 관리·운영.
- **설정 파일 `.task-github.yml` (워크스페이스 루트, 신규)** — 정본 config. 값은 영어, 기본 `solo`/`gear`.
  ```yaml
  mode: solo               # solo | team — 글로벌 운영모드(기본 solo)
  planning-tool:           # 플러그인/스킬 이름 — 비면 하네스가 plan 수행
  verify-tool:             # 플러그인/스킬 이름 — 비면 하네스가 verify 수행
  review-tool:             # 플러그인/스킬 이름 — 비면 하네스가 review 수행
  orchestrate:
    review-mode: gear      # gear | all | skip — orchestrate 전용(기본 gear)
  ```
  - harness-neutral 단일 정본(Claude+Codex 중복 제거, 스크립트 파싱 가능). 기존 CLAUDE.md
    `프로파일:` 줄을 **여기로 이관**(rules/task-protocol.md §1 갱신). doctor validate, setup scaffold.
  - `mode`의 **ambient 판단강도 효과**(task-protocol.md §3)는 스킬이 진입 시 config 로드해
    working 컨텍스트에 노출(이미 context-bundle 읽으므로 추가비용 작음).
- **mode 게이트 (orchestrate = solo 전용)**: `mode: team`이면 orchestrate refuse.
  **이유**: 자동 드라이브 + 자동 머지가 팀 리뷰/소유권 규범과 충돌. solo capture authority
  (저자=실행자=리뷰어 동일) 전제에서만 안전. team은 사람 분업이라 auto-orchestration 부적합.
  `mode`는 **글로벌 설정만** — 실행 시 오버라이드 없음.
- **리뷰모드 (orchestrate 한정)** — PR은 항상 필수, 토글되는 건 **리뷰**:
  - **우선순위**: `--review` 실행 인자 > `.task-github.yml` `orchestrate.review-mode` > 기본 `gear`.
  - `all` — 모든 spawn된 리프 PR을 reviewer로 강제 리뷰.
  - `skip` — 모든 PR을 리뷰 없이 직머지.
  - `gear` — gear 기반: `gear:micro` 직머지 / `gear:normal` 리뷰.
  - **독립성**: 리뷰모드는 PR 리뷰 게이트만 제어. `gear:major`의 **spawn 전 사람 STOP**(B1)과
    무관 — `skip`이어도 major는 spawn 게이트가 막아 auto-merge되지 않는다.

**11.3.2 브랜치트리 (이슈트리 미러)**
- 컨테이너(root/서브이슈) = 자체 작업 브랜치. 리프 = worktree(부모 브랜치에서 분기).
- **선행입력 추가**: 컨테이너 브랜치는 자식 spawn 전에 생성·**remote push**돼 있어야 PR base로 쓸 수 있다(오케스트레이터가 트리 하강 중 결정론으로 생성, 컨테이너당 `git branch`+push 1회).
- micro도 **항상 worktree**(직접커밋 특수경로 없음). 스킵하는 건 PR/리뷰 tier가 아니라 — always-PR이므로 PR도 안 스킵. micro가 스킵하는 건 **리뷰**뿐.

**11.3.3 always-PR 머지-업 completion flow**
- 모든 코드변경 리프 → PR(`gh pr create --base <부모브랜치>`, work-agent가 선언적 지정).
- 머지 = **`gh pr merge`로 부모 브랜치에 통합**. 자식 done → 부모, 부모 done → 조부모, root → main.
- 코드변경 없는 리프 = PR 없이 바로 close(done 경로 B).
- **auto-close 미발화 대응**: non-default 브랜치 머지는 `Closes #N` 자동 close가 안 터지므로
  **오케스트레이터가 명시 `gh issue close`**. S2 완료신호(closed count)는 이 명시 close에 의존.
- **머지 트리거 규칙**: "머지승인 상태를 쥔 쪽이 트리거" — 다만 실행은 전부 오케스트레이터(단일
  main thread → 자연 직렬화). micro=정책승인 / 리뷰=verdict approved / 컨테이너=완료.

**11.3.4 역할 (서브에이전트 3 + 오케스트레이터)**
```
서브에이전트 (LLM, 판단):
  work-agent     : 리프 점유 → worktree → 작업 → PR 생산 → report(PR#). 단일경로, 분기 0.
  reviewer-agent : PR 리뷰 → verdict만 오케스트레이터에 return (+ GitHub 코멘트는 규칙대로).
  conflict-agent : 머지 충돌 해소. test-gated.
오케스트레이터 (메인스레드, 결정론 + 조율):
  루프 · ready_leaves · 컨테이너 브랜치 생성 · work-agent spawn ·
  머지(gh pr merge) · 이슈 close · 게이트 STOP · root 완료 위키처리.
  직접 코딩 0, 리프 머지결정 1곳.
```

**11.3.5 PR 리뷰 = session-review relay**
- 리뷰 필요 PR은 **session-review 플러그인**으로 처리. work-agent=worker, reviewer-agent=reviewer,
  오케스트레이터 = separate-flow의 사람 릴레이를 자동화.
- verdict approved → 머지. changes-requested → **work-agent 재spawn**(address-feedback handoff =
  PR#·브랜치·피드백 주입) → 반복. **라운드 캡 초과 → 사람 STOP**(무한 fix 루프 차단).
- reviewer-agent는 **verdict만 return**(GitHub 코멘트는 규칙대로 남기되, 상태정본은 오케스트레이터로).

**11.3.6 충돌 = conflict-agent (test-gated)**
- `gh pr merge` 실패(server-side 충돌, un-mergeable) → 오케스트레이터가 **conflict-agent 즉시 위임**.
- conflict-agent: 해당 브랜치 충돌 해소 + **build/test 통과 강제** → push → 오케스트레이터 머지 재시도.
- **의미적 모호 충돌은 자동커밋 금지 → 사람 STOP 에스컬레이트.** blind commit 절대 금지.

**11.3.7 root 완료 = 위키 처리 (메인스레드 직접, capture authority 가드)**
- 위키 터치 = **root 완료 정확히 한 점.** 리프·컨테이너(non-root)는 task 노드 없음 → merge+close만.
- root 완료 시(루프 종료상태, 동시성 무관) 메인스레드가:
  1. 트리 전체에서 모인 결정/시행착오/위키대상 집계(worker **요약 리턴**이 런 내내 누적한 재료).
  2. 연결 task 노드 → done 전이(wiki-bridge §5 lifecycle).
  3. `refresh` 1회(런 끝 배치, per-node 아님 — CLAUDE.md 정합).
- **capture authority 가드(필수)**: 저위험 **observation만 자동 기록**.
  **decision/시행착오/rejected = 수집해 사용자에 제시 → 확인 후 기록.** silent DEC write 금지.
  task 노드 done 전이는 lifecycle라 자동 OK.
- "연결 위키문서 ⟺ root 이슈" — task 노드는 define 시점 root 이슈와 1:1.

**11.3.8 불변식 / 직렬화**
- D2 확장(라벨경합 여전히 0, 이슈당 순차): 점유→in-review = work-agent / in-review→
  changes-requested = reviewer-agent / changes-requested→재PR = work-agent / →closed = 오케스트레이터.
- 머지는 전부 오케스트레이터(단일 main thread) → 자연 직렬화. always-PR이라 GitHub server-side
  직렬화도 보조.
- §3 "LLM 역할 = worker 하나" 불변식은 **이 r5에서 다역할(work/reviewer/conflict)로 개정**된다
  (단 오케스트레이터 서브에이전트는 여전히 없음 — 조율은 메인스레드).

### 11.4 구현 단계 (staging — YAGNI)

- **v1**: 브랜치트리 + always-PR 머지-업 + work-agent + 오케스트레이터 결정론(브랜치생성/머지/
  close) + 게이트 STOP. reviewer/conflict 자리는 **STOP 슬롯**으로 비워둠
  (normal/major PR = 사람 STOP, 충돌 = STOP). `--max-workers 1` 기본 유지.
- **v2**: STOP 슬롯에 투입 — reviewer-agent(= session-review self/fast) + conflict-agent
  (test-gated). 리뷰정책 옵션의 `all`/자동 fix루프가 여기서 의미 가짐.
- 단계는 빌드 순서 권고일 뿐, flow 정본은 §11.3.

### 11.5 전체 flow 의사코드 (v2 타겟)
```
orchestrate(root_issue, --review {all|skip|gear}):
  오케스트레이터.loop:
    r = ready_leaves.py(root, spawned_set, failed_set)   # 실패 → stop_reason → STOP
    게이트: stuck / invalid_gear / gear:major(spawn전) → 사람 STOP
    컨테이너 done → 컨테이너 브랜치 PR(base=조부모) → merge → close   # 결정론
    ready 리프:
      컨테이너 브랜치 보장(없으면 생성+push)
      work-agent spawn (start→run→done까지, 머지 안 함):
        start 점유(in-progress) → run 워크트리(부모브랜치 base)
          → [gear: plan → ] 수행 [ → verify(같은 세션 자기검증) ]   # micro=수행만 / normal·major=plan·verify 포함
          → done: PR(base=부모, in-review)
          ├ 코드변경 → report(PR#)
          ├ 변경없음 → close → report(no-change)
          └ 실패 → report(fail) → failed_set → STOP
      리뷰 필요?  (all→예 / skip→아니오 / gear→micro:아니오·normal:예)
        아니오 → gh pr merge → gh issue close
        예     → reviewer-agent(session-review relay) → verdict
                   approved → gh pr merge → gh issue close
                   changes-requested → work-agent 재spawn(handoff) → 반복 / 캡 초과 STOP
      gh pr merge 실패(충돌) → conflict-agent(test-gated) → 재시도 / STOP
    root_done → main 머지 + close + 위키 처리(집계 + task done + refresh, capture 가드)
```

## 12. 스킬 인벤토리 재정돈 (r5 — 공통 플로우 전환)

> 공통 플로우(open→start→run→done→[review]→merge→close) + 브랜치트리 머지업 + 에이전트
> 오케스트레이션으로의 전환에 맞춰, 현 15개 스킬을 **정돈/유지/신규/제거**로 분류한다.

### 12.1 공통 플로우 스파인 스킬 (정돈)

| 스킬 | 분류 | 변경 | 이유 |
|------|------|------|------|
| **start** | 정돈 | 점유 전담으로 축소. **worktree 생성 제거**(→run). micro 직접편집/PR스킵 경로 삭제. gear 판단·claim·wiki 맥락 유지 | 스테이지 책임 재배치(start=점유). micro-light(worktree/PR 스킵) 철학 폐기 — 공통 플로우 일관성 우선 |
| **run** | 정돈 | **worktree 생성 추가(전 기어 필수)** + 실행. observation 캡처 유지 | 스테이지 재배치(run=worktree+작업). worktree 필수화로 브랜치트리 머지업 성립 |
| **done** | 정돈 | PR **항상** 생성(no-PR 경로 삭제) + `in-review` 전이 + **PR base=`parent_branch`**(트리). drift hard gate 유지 | PR 필수 + 부모브랜치 머지업. 코드변경 없는 리프만 PR 없이 close |
| **merge** | 정돈 | pr 머지 + **충돌 해소 스테이지 추가**(현재는 감지만) + close. `--mode local`/stacked closeout 재사용 | 충돌 해소가 머지 스테이지 책임. 트리 머지업의 종착 |
| **review** | 유지(소폭) | **작업과 별개 세션의 독립검증**(separate). 위임 = `.task-github.yml` `review-tool`(비면 하네스가 review subagent). orchestrate에선 reviewer-agent relay | verify와 **방법 차이 아니라 단계+태도 차이**: review=별개 세션 독립검증 |

### 12.2 트리 선행입력 스킬 (정돈)

| 스킬 | 분류 | 변경 | 이유 |
|------|------|------|------|
| **define** | 정돈 | child spec에 **gear 필드**(B1) + **dependency 필수 materialize**(`dep_create_failed`, N3) + **Execution Contract**(`topology=stacked`, `parent_branch`, `leaf_policy`) 방출 | orchestrate가 gear게이트·브랜치트리·머지업을 트리에서 바로 쓰려면 define 시점에 다 박혀야 |
| **open** | 유지(소폭) | read-only 유지. Execution Contract의 `parent_branch`/`topology`도 브리핑 | 트리 컨텍스트 노출 |

### 12.3 gear 게이트 / ops 스킬 (유지)

| 스킬 | 분류 | 이유 |
|------|------|------|
| **plan** | 유지 | planned(normal/major) 1단계. **계획 알고리즘 아님** — 위임 = `planning-tool`(비면 하네스 Plan Mode). 스킬은 "계획+기록+승인" 절차 마커. 얇게 유지 |
| **verify** | 유지(태도 명시) | **작업과 같은 세션의 자기검증**(self). 위임 = `verify-tool`(비면 하네스 self-check). planned 마지막(run 뒤) | review와 단계+태도 차이: verify=같은 세션 자기검증 |
| **setup** | 유지(소폭) | git init/repo 생성 + **`.task-github.yml` scaffold**(mode/tool/review-mode 기본값) |
| **doctor** | 유지(소폭) | linkage 진단 + **`.task-github.yml` validate**(키/값 유효성, tool 존재 확인) |
| **reconcile** | 유지 | bridge mismatch 복구 — ops 복구, 플로우 무관 |
| **status** | 유지 | read-model JSON. orchestrate `ready_leaves`도 일부 재사용 |

### 12.4 신규

| 산출물 | 종류 | 이유 |
|--------|------|------|
| **orchestrate** | 신규 스킬(빌드) | 현재 PLAN.md만 존재. 루프 + `ready_leaves.py` + 에이전트 spawn + 머지/close + 게이트 STOP + root완료 위키 — 본 설계의 핵심 산출물 |
| **conflict-agent** | 신규 에이전트(v2) | 머지 충돌 전담 해소. test/build 게이트 + 의미적 모호 STOP. merge 스테이지가 위임 — 격리된 충돌해소 |

### 12.5 신규 아님 (재사용으로 충족)

| 역할 | 충족 방법 | 이유 |
|------|-----------|------|
| **work-agent** | orchestrate가 Agent로 start→run→done **까지만** 호출(= PR + in-review). PR# report 후 종료 | 공통 플로우 스킬 조합 = 새 스킬 0. **머지 안 함** — 머지 결정+실행은 오케스트레이터 단일 지점(직렬화·게이트) |
| **reviewer-agent** | session-review **separate-flow**(별개 세션) | review 스테이지 = 독립검증 |
| **merge 실행** | 오케스트레이터(자동) 또는 사람(수동)이 merge 스킬 호출 | work-agent가 아님. 머지 트리거 = 승인 쥔 쪽, 실행은 단일 지점 |
| **close 스테이지** | merge 스킬(closeout.py)에 흡수 | 머지+close 원자 처리. 별도 스킬 = 불필요 분할 |

### 12.6 제거

| 스킬 | 분류 | 이유 |
|------|------|------|
| **next** | **제거 확정** | status와 **같은 `status_next.py` + 같은 입력**, status가 이미 `next_action: 반드시 1개` 출력 → next는 그 필드만 격리한 subset 뷰 = 순수 중복. 단일이슈는 status, 트리는 orchestrate 루프(ready_leaves)가 대체. 터스함만으론 별도 스킬 정당화 불가 |

### 12.7 base 규칙 문서 영향 (스킬 아님, 동반 갱신)

`rules/workflow.md`(상태전이·브랜치·PR), `rules/task-protocol.md`(기어·플로우 — worktree/PR 필수
**+ 프로파일을 `.task-github.yml` `mode`로 이관 + orchestrate solo 전용 게이트**),
`DESIGN.md §4.x`(express/planned 표에 worktree·PR 항상 반영).
**신규 `.task-github.yml`**(워크스페이스 루트) = 정본 config — `mode`/`planning-tool`/`verify-tool`/
`review-tool`/`orchestrate.review-mode`. setup이 scaffold, doctor가 validate. 이 갱신이 없으면 스킬과 규칙이 발산.

## 13. 직전 라운드(r4) 보강 요약

- **C6 stop_reason taxonomy**: 모든 STOP을 단일 enum 채널로 — 누락 케이스 silent `ready=[]` degrade 구조적 차단(§5.1).
- **F1 S1 정직화**: open 재사용 = 쿼리 shape뿐, 재귀 walk+커서는 net-new로 명시.
- **F2 gear 신뢰 모델**: B1은 define gear 무비판 신뢰임을 자인 + invalid_gear는 구조만 검증(의미적 오분류 통과). 대안(judgment_needed STOP) surfaced, 사용자 결정 보류.
- **F3 blocked-컨테이너 non-drop**, **F4 per-worker timeout**, **F5 엣지(empty_tree/dep_cycle/root-gear)**, **F6 strict_deps 구현지점**, **F7 self-check 4→6**, **F8 분기순서 stuck>root_done**.
- **열린 결정(사용자)**: B1 pre-stamp 유지 vs judgment_needed 전환(§6 surfaced 대안).
