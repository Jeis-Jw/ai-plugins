# orchestrate — 이슈트리 절차적 자동수행 (기획 드래프트 r3)

> 상태: 기획 드래프트 round 3 (fast self-review feedback 반영).
> 범위: **고정 이슈트리 실행만.** 이슈 분해(define/brainstorm)는 범위 밖.

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

### 5.1 `scripts/ready_leaves.py` (신규 — prior art 재사용, 신규 로직 최소)

reviewer 확인: context_bundle.py는 단일이슈·gh미호출이라 재사용 불가가 맞으나,
**진짜 prior art는 따로 있다 → 재사용으로 신규 코드 대폭 축소(S1):**
- `skills/open/SKILL.md` Step2-3 = GraphQL `subIssues` + `subIssuesSummary` + 자식별 ready 계산 **이미 함** → walk·완료감지 로직 차용
- `closeout.py`의 `_parent` / `_open_blockers` / `_blocking` / `_detect_root_task` = 구현·테스트됨 → 그대로 import/이식

- 입력: root 이슈# + root 루프가 가진 `spawned_set`/`failed_set`.
  GitHub만으로는 "이번 루프가 띄운 worker"를 알 수 없으므로 helper가 추론하지 않는다.
- 동작: 서브이슈 재귀 walk(GraphQL `subIssues`, **커서 페이지네이션 루프 필수** — first:50 잘리면 leaf 영영 누락, N1), 노드별 open/리프/blocker 판정
- 출력 JSON:
  - `ready[]` — 수행가능 리프. **각 항목에 `gear` 포함**(B1: spawn 전 게이트용)
  - `blocked[]` — 열린 blocker 있는 리프
  - `review_waiting[]` — `in-review`/`changes-requested` 등 사람 review/merge가 필요한 리프
  - `invalid_gear[]` — gear 라벨이 없거나, 여러 개거나, `micro|normal|major` 밖인 ready 리프. default 금지, 루프 STOP.
  - `stuck[]` — **in-progress 리프 중 active spawned worker가 아닌 것**. root가 넘긴
    `spawned_set`/`failed_set`으로만 판정한다. 각 항목 `reason: prior_run|spawned_failed` (C4)
  - `done_containers[]` — `subIssuesSummary` total==completed 인 미close 컨테이너 (S2)
  - `root_done`
- self-check 1개 동봉(§4 예시트리 fixture로 tick0 ready=={1-1,2-1-1,2-2} 단언)
- **API 실패 거동(N2)**: `subIssues`/`dependencies` 조회 실패 시 **부분 ready-set 스폰 금지** — 빈/에러 반환하고 루프는 STOP(`rules/dependencies.md` §7 루프 버전).

### 5.2 `skills/orchestrate/SKILL.md` (절차 문서 — root 루프)
```
loop:
  r = ready_leaves.py(root, spawned_set, failed_set)  # 실패 시 STOP (부분 진행 금지)
  r.root_done            → 종료 + 보고
  r.stuck 있음           → 사람 게이트: STOP + 브리핑 (자동 재시도 금지, B2)
  r.done_containers      → root가 컨테이너 issue 직접 close (closeout.py 위임 아님)
  r.review_waiting 있음  → 사람 게이트: review/merge STOP + 브리핑
  r.invalid_gear 있음    → 사람 게이트: STOP + 브리핑 (default 금지)
  r.ready 중 gear:major  → 사람 게이트: STOP (spawn 전 거름, B1)
  r.ready (gear:micro|normal) → 리프마다 worker spawn (병렬, 워크트리 격리)
                           worker = 기존 start→run→done, 상태라벨 전이 전담, 요약만 리턴
  진행 단조성 검사: (closed leaf + done_containers) 증가 없으면 STOP (D3)
  max-iter = backstop (D3)
  # 분기 순서 안전(C5): stuck > done_containers > review_waiting > invalid_gear > spawn.
  # stuck 있으면 root_done 도달 불가.
```
worker 새 코드 0. 기존 start/run/done 재사용.

## 6. 사람 게이트 (solo 정책 정합)

- review / merge / `gear:major` / `stuck` = **자동 금지, STOP + 브리핑.** solo capture authority.
- gear:major는 **spawn 전** ready_leaves의 `gear` 필드로 거른다(B1 — start 시점 라벨링에 의존하지 않음).
- gear 결손/중복/unknown은 default하지 않고 `invalid_gear[]` STOP으로 처리한다.
- 자동화 범위 = `gear:micro|normal` 리프의 start/run/done.

## 7. 도구 선택

- worker = Agent 서브에이전트 (기존 스킬 재사용)
- 루프 = main thread가 skill 실행 (unattended는 `/loop` 옵션)
- 헬퍼 = python + gh GraphQL (open/closeout prior art 재사용)
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

### 알려진 한계 (구현시 `ponytail:` 주석)
- 동시 worktree 생성 경합 = 경로충돌 아님(경로 `issue-{N}` keyed). 공유 `.gitignore` append + `git worktree add` 레지스트리 락 → **worktree 생성단계만 직렬화** (D1)
- 병렬 worker 컨텍스트 누적 → 요약 리턴으로 억제
- `subIssues` 페이지네이션 커서 루프 필수 (N1)

## 9. 미해결 (r1 4 → r2 0)

- **확정(C3)**: 컨테이너 close = **root가 `done_containers` 신호로 직접 close**. closeout.py는 root-close 감지만(트리 walk 캐스케이드를 떠안으면 single-issue 도구 성격이 흐려짐). 완료감지는 S2(subIssuesSummary)로 해결. → 미해결 0.
