---
title: session-review: plugins/task-github/skills/orchestrate/PLAN.md
created_at: 2026-06-26
summary: orchestrate 기획 드래프트 리뷰 핸드오프 (co-design)
tags: [session-review, review]
type: snapshot
updated_at: 2026-06-26
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "document"
target_nature: "spec"
target_ref: "plugins/task-github/skills/orchestrate/PLAN.md"
base_ref: "60e5ce5d310d08598fd5f0334634a6055488c7b9"
responding_to: "212daacfb851e2dc2dddc965cd9fed5f678cd2f5"
round: 2
round_type: "converge"
flow_mode: "self"
review_strength: "normal"
review_posture: "co-design"
blocking_count: 0
```

### 리뷰 피드백 (round 2)
round_type=converge / co-design / document(spec) / normal. r1 합의 피드백 반영 여부 확인 + 잔여 이견이 lock을 막는지 판단. scope 확대 안 함. **blocking_count=0 → approved.**

## r1 → r2 반영 검증 (10개 전부 확인)

- **B1 (gear spawn-전 게이트)** — §5.1 `ready[]`에 `gear` 포함 + §5.2 `r.ready 중 gear:major → STOP` + §6 "spawn 전 거름" + §8 선행입력에 "각 리프 gear:* 라벨 define 선결". 구조적으로 닫힘 — gear가 트리에 선결되면 루프가 spawn 전 major를 본다. ✅ (단 C1 참고)
- **B2 (부분실패 복구)** — §5.1 `stuck[]` + §5.2 `r.stuck → 자동재시도 금지, 사람게이트 STOP`. 좀비 leaf가 더이상 조용히 누락되지 않고 STOP으로 표면화. ✅ (단 C2 참고)
- **S1 (prior art)** — §5.1이 open/SKILL.md(subIssues+subIssuesSummary) + closeout.py(`_parent`/`_open_blockers`/`_blocking`/`_detect_root_task`) 재사용 명시. 재검증함: 네 헬퍼 전부 `closeout.py`에 실재(238/220/229/249행), open/SKILL.md Step2-3에 walk+summary+자식ready 실재. ✅
- **S2 (컨테이너 완료)** — §4 표 + §5.1 `done_containers`(total==completed) + §9에서 완료감지 제거. ✅
- **D1 (worktree race 사유)** — §8 "경로충돌 아님(issue-{N} keyed), .gitignore append + 레지스트리 락 → 생성단계만 직렬화". workflow.md §4와 정합. ✅
- **D2 (라벨경합)** — §3 표 + §8 불변식 "상태라벨 worker 전담, root는 컨테이너close+STOP만". 스냅샷 '정해진 것'에도 승격됨. start/run/done/review가 라벨 전이 유일주체임을 재확인. ✅
- **D3 (진행 단조성)** — §5.2 "(closed leaf + done_containers) 증가 없으면 STOP, max-iter backstop". ✅
- **N1 (페이지네이션)** — §5.1 "커서 페이지네이션 루프 필수" + §8 한계. ✅
- **N2 (API 실패 STOP)** — §5.1 "부분 ready-set 스폰 금지, STOP" + §8 불변식. ✅
- **nit (self-check fixture)** — §4 "이 검산은 ready_leaves self-check fixture로 고정". ✅

합의된 r1 피드백은 전부 반영됐고 새 scope를 넓히지 않았다. 아래는 approval과 양립하는 구현 전 정밀화 — **lock을 막지 않는다.**

### [should-reflect-before-implementation] C1. B1 "gear define 선결"은 방향은 맞으나 `create_issue_tree.py`가 아직 gear를 못 박는다 — define-side 변경을 선행조건으로 명시하라

B1을 코드로 재검증: `skills/define/scripts/create_issue_tree.py`의 child spec 스키마(validate_spec)는 `key/title/body/affects_paths/blocked_by`만 받고 **`labels`/`gear` 필드가 없다.** `create_child_issue`(GraphQL createIssue)도 라벨을 안 붙인다. 즉 현재 define은 leaf에 gear를 **선결할 수단이 없다.**

이건 B1 방향(트리에 gear 선결)이 틀렸다는 게 아니라, r1 B1이 경고했던 "문제를 start→define으로 옮겼는데 define이 그걸 못 옮긴다"가 실제로 남아 있다는 뜻이다. PLAN은 §8 선행입력에 "gear 라벨 선결"을 적었지만 **그걸 누가 어떻게 박는지**가 비어 있다.

**대안(택1, lock 안 막음 — 구현 시 닫으면 됨):**
- (A 권장) `create_issue_tree.py` child spec에 `gear` 필드 추가 + `create_child_issue` 후 `gh issue edit {N} --add-label gear:{v}` 1줄. 가장 작은 변경, 기존 dependency 선결과 같은 경로(execute 루프 안). PLAN §8 선행입력에 "(구현: create_issue_tree.py child.gear 추가)"를 괄호로 달면 된다.
- (B) gear 선결을 안 하고, ready_leaves가 gear 라벨이 **없는** leaf를 만나면 `stuck`/STOP로 보내 사람이 gear를 판단. fail-safe지만 자동화율이 떨어진다. A가 낫다.

근거가 코드라 directional보다 위로 올렸지만, 기획 드래프트라 approval과 양립한다.

### [should-reflect-before-implementation] C2. B2 `stuck[]`의 "활성 worker 없음"은 GitHub state로 판정 불가 — 루프의 self-spawn 집합으로 정의하라

§5.1 `stuck[]` 정의 = "open + in-progress 인데 **활성 worker 없음**". 코드/메커니즘 사실: GitHub 이슈는 worker가 살아있든 죽었든 `in-progress`로 똑같이 보인다. `gh`로 worker liveness를 알 방법이 없다(라벨·assignee 어디에도 PID/heartbeat 없음). 즉 "활성 worker 없음"을 GitHub만 보고는 못 정한다 — 그런데 §2는 "GitHub=SoT, 캐싱 금지"라 긴장이 생긴다.

**더 단순하고 안전한 정의(co-design):** 단일 루프 오케스트레이터는 **자기가 이번 run에 spawn한 worker 집합을 안다.** 따라서 `stuck` = "in-progress leaf 중 **이번 루프가 spawn하지 않은** 것". 이건 GitHub state(in-progress) + 루프의 in-memory spawn-set 교집합이라 결정론적이고, "GitHub 캐싱 금지"와도 안 부딪힌다(spawn-set은 트리 상태 캐시가 아니라 이번 세션 행위 로그다). 

이렇게 정의하면 부수효과로 좋아진다: 첫 tick에 발견된 기존 in-progress(이전 run 잔재)는 전부 stuck→STOP로 사람에게 보고되고, 루프가 만든 in-progress는 worker 리턴으로 자연 해소된다. PLAN §5.1 stuck 정의를 "활성 worker 없음"에서 "**루프 spawn-set에 없는 in-progress leaf**"로 한 줄 고치면 메커니즘이 명확해진다. lock 안 막음(구현 디테일).

### [directional] C3. 잔여 §9 1개(컨테이너 close 경계)는 blocking 아님 — 이미 답이 좁혀져 있다

§9의 "root가 done_containers로 직접 close vs closeout이 캐스케이드까지" — 이건 둘 다 동작하는 깔끔한 either/or라 lock을 막지 않는다. 다만 가벼운 추천: **root가 done_containers를 직접 close**(현 §5.2 `r.done_containers → 컨테이너 close`)가 맞다. 이유 — closeout.py는 `_detect_root_task`로 "merge 결과 root가 닫혔나"를 **사후 감지**하는 책임이고, "지금 자식 다 닫혔으니 컨테이너를 닫아라"는 **루프의 tick 결정**이다. 둘을 합치면 closeout이 트리 walk 책임까지 떠안아 single-issue 도구 성격이 흐려진다. 현 PLAN대로 root=close 실행, closeout=root-close 감지로 갈라둔 게 옳다. §9를 "확정: root가 done_containers close, closeout은 감지만"으로 닫으면 미해결 0.

### [nice-to-have] C4. stuck/STOP 브리핑에 "왜 stuck인지" 분류를 실어라

C2대로 stuck이 (a)이전 run 잔재 (b)이번 worker 실패 두 출처로 갈리면, 사람 게이트 브리핑이 둘을 구분해주면 복구 판단이 빨라진다(잔재면 reconcile, 실패면 재작업). ready_leaves `stuck[]` 항목에 `reason: prior_run|spawned_failed` 한 필드. 구현 시 곁다리.

### [nit] C5. §5.2 의사코드 분기 순서에 stuck이 done_containers보다 위에 있다(좋음 — 안전 먼저). 다만 `root_done` 체크가 맨 위인데, stuck이 있는 채로 root_done이 참일 수 없으므로(자식 미완) 순서 무해. 명시적 주석 한 줄("stuck 있으면 root_done 도달 불가")이면 독자 안심.

---
**판정 근거**: r1 blocking 2개(B1/B2)가 구조적으로 닫혔다(spawn-전 gear 게이트 + stuck STOP). S1/S2 prior-art 재사용은 실제 코드(closeout.py 헬퍼 4개, open/SKILL.md walk)와 정합 확인. 새로 생긴 약점은 **구현 디테일 2개(C1 define-side gear 박기, C2 stuck 정의)**뿐이고 둘 다 기획 드래프트 단계에서 approval과 양립하며 구현 시 닫으면 된다 — 설계 방향 자체는 옳다. 잔여 §9 1개는 either/or라 lock 비차단. **approved, blocking_count=0.**

## 리뷰 요청 (co-design)

대상: 이슈트리 절차적 자동수행 오케스트레이터 **기획 드래프트** (코드 없음, 설계 문서).
posture=co-design: 비판만 말고 **함께 설계**하라. 더 나은 분해/대안 구조 제안 환영.

계약: approved = blocking_count=0 이지 "의견 없음" 아님. 승인에도
[should-reflect-before-implementation]/[directional]/[nice-to-have]/[nit] 남길 것.

봐줄 것:
1. 실현가능성 — ready_leaves.py 재귀 walk(gh sub-issues + dependencies API). context_bundle 재사용 불가 판단 맞나. 더 나은 데이터소스 있나?
2. 정책정합 — solo/wiki-bridge/gear 충돌. 사람 게이트(review·merge·gear:major 자동금지) 경계 적절한가. 더 나은 게이트 설계?
3. 실패모드 — 병렬 worker 실패 부분진행 복구, worktree race, 라벨 갱신 경합(worker vs root), 무한루프 가드.
4. 역할단순화 — 오케스트레이터 서브에이전트 제거 결정이 고정트리 전제에서 타당한가.
5. §9 미해결 포인트 우선순위 + 빠진 설계축 있나.

## 배경

target_mode=document, target_ref=plugins/task-github/skills/orchestrate/PLAN.md, base_ref=60e5ce5d310d08598fd5f0334634a6055488c7b9, review_branch=main-orchestrate-plan-review, flow_mode=self, posture=co-design

## 정해진 것

C4/C5 nice: stuck reason 필드, 분기순서 stuck>done_containers>spawn 주석 (반영)

## 아직 열린 질문



## 다음에 볼 것

reviewer가 snapshot-load 후 review skill을 co-design posture로 실행한다.

## 관련 파일/문서

plugins/task-github/skills/orchestrate/PLAN.md

## 승격 후보
