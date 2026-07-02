---
title: orchestrate 세리머니를 merge-edge gear로 이동 + 분해를 payoff 원리로 재정의
created_at: 2026-07-02
summary: orchestrate 오버헤드(리프당 ~20분 고정비×리프 수)를 잡기 위해 세리머니(plan/verify/PR/review)를 리프 속성이 아닌 부모 머지 edge의 gear 속성으로 옮기고(micro/normal=로컬 FF 머지 무PR, major=PR+review, 컨테이너 gear=자식 누적 승격), 분해를 payoff>고정비 원리(절단 사유 4개, 하드캡 없음)로 재정의. DEC-212109 all-PR을 gear-gated로 부분 개정하되 메인 트리 HEAD 불변은 유지.
tags: [orchestrate, task-github, architecture, decomposition, gear, branch-tree]
relations:
  intents: [INT-2026-05-29-104712-parallel-safe-headless-operation]
---

## 결정

orchestrate의 세리머니(plan/verify/PR/review) 부착 지점을 "리프 속성"에서 "부모 브랜치로 머지되는 edge의 gear 속성"으로 이동하고, 분해 기준을 "절단 payoff > 리프 고정비" 원리로 재정의한다.

(1) 분해 규칙 — 절단 사유는 4개뿐이고, 없으면 묶는다(기본). 크기 자체는 절단 사유가 아니며 하드캡도 없다. ① 병렬 이득(독립 조각, 각 normal 이상일 때만; micro는 흡수 또는 sweep 리프로 배치 — 병렬값 < 고정비). ② 위험 격리(비가역·고위험, 크기 무관). ③ 정보 가치 경계(직렬용: "A 검증 결과가 B 계획을 바꾸나?" / "B만 revert할 상황이 현실적인가?" 둘 중 yes면 절단. 개념 구분만으론 안 자른다). ④ 병렬 해금(lane 간 계약을 선행 spec 리프로, 산출물=바인딩 가능 artifact(타입/stub), 자기 크기 무관; lane 내부 계약은 이슈 본문). 검증·문서·runbook은 리프 금지 → 완료조건으로 흡수. blocker는 직접 의존만(transitive·방어적 선언 금지). plan 시점 태스크 과다는 STOP이 아니라 warn. 큰 리프의 세션 열화는 실행 위생(완료조건 단위 커밋 + 점진 verify)으로 흡수.

(2) 세리머니 = merge edge 속성. gear별 flow: micro=run만, 로컬 FF 머지(PR 없음). normal=plan+run+verify, 로컬 FF 머지(PR 없음). major=plan+run+verify, PR+review. 컨테이너 gear는 자식 누적 승격으로 결정: min=max(자식), micro 3개 이상→normal, normal 2개 이상→major. 컨테이너 merge-up이 자기 gear 규칙을 적용 → normal 무더기 컨테이너는 major=PR+review. 결과: trunk 도달 전 어딘가에서 반드시 리뷰 게이트를 통과한다. 병렬 중인 노드는 gear 무관 PR로 합류(PR=운송수단), review는 여전히 major edge에서만.

(3) 브랜치/worktree 메커니즘. 리프=자기 worktree+자기 브랜치(base=부모 브랜치). 컨테이너=순수 브랜치 ref(worktree 없음, 체크아웃 없음, FF로만 전진). 합류 = "git fetch . task/issue-{leaf}:task/issue-{parent}" + origin push. 부모가 diverge했으면 리프 worktree에서 부모를 역머지 → 충돌 해소 → verify 재실행 → FF. 충돌은 항상 리프 쪽에서 해소한다(worker 생존 시 본인, 사후엔 conflict-agent를 리프 worktree에 투입, 의미적 모호는 STOP). major는 직렬 체인 중이라도 자기 브랜치를 딴다(리뷰 안 된 diff 위에 후속 작업 금지). 이슈 close 증거: micro/normal은 merged PR 대신 verify 리포트+커밋 SHA range.

(4) 서브에이전트 3역할 불변(worker=start→run→done+자기 리프 FF 합류·충돌 해소, reviewer=major edge PR 검증, conflict-resolver=사후 충돌). 메인스레드=오케스트레이션만(tick·spawn·ledger·close·컨테이너 merge-up·STOP 게이트, 코딩·verify 판정·충돌 해소 안 함). 변경은 역할이 아니라 일의 분배: 리프→부모 FF 합류가 worker done으로 이동해 orchestrator 이슈당 개입이 줄고, orchestrator 머지는 전부 기계적 FF ref 이동이라 "오케스트레이터는 코딩 안 함" 불변식이 더 순수해진다.

이 결정은 [[DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거]]의 all-PR 통합을 gear-gated PR로 부분 개정한다 — 그 DEC의 재평가 조건("깊은 스택에서 머지업 PR 수가 노이즈로 문제화")을 이번 ledger 실측이 발동시켰다. 단 그 DEC의 핵심 불변식(메인 워크트리 HEAD가 trunk를 벗어나지 않음)은 유지된다: 로컬 FF를 fetch refspec으로 처리(checkout 없음)하고, 충돌 해소는 리프 worktree에서 하지 메인 트리에서 하지 않는다. 관련: [[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]](v2 발전), [[DEC-2026-06-19-190302-ceremony를-파급력-gear-에-비례시킨다]](gear 비례 확장), [[DEC-2026-07-02-190102-define은-topology-판단을-제안-게이트에-필수-포함]](분해 topology).

## 취지

혼자서 여러 AI worker를 병렬 구동하되 품질 게이트와 감사 흔적을 사람 개입 최소로 유지하는 자율 실행기의 취지는 지키면서, 리프당 ~20분 고정비(worker spawn + 세리머니 + PR + CI + merge lane)가 리프 수에 선형으로 곱해지는 오버헤드를 제거한다. 분해는 사고 단위로 자유롭게 하여 추적 입자를 보존하되, 오버헤드는 리프 수가 아니라 merge edge의 gear가 통제하게 한다. CLAUDE.md의 "decompose for thinking, bundle for shipping"을 세리머니 부착 지점 재배치로 실현.

## 배경

MVP 이슈트리(#81, 리프 12·컨테이너 4) run의 ledger 실측: 리프당 고정비 ~20–25분(작업 크기·gear 무관, runbook 문서 리프도 22분), 리뷰/머지 lane은 병목이 아님(38초~7분). 남은 트리가 사실상 직렬 체인 8개(89→90→…→99)라 병렬성 0, --max-workers가 무의미. 과분해(검증·문서를 독립 리프로)+transitive/방어적 blocker+이슈=PR 전제가 원인. 기존 v2([[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]])는 always-PR·worktree 필수로 micro까지 PR을 강제했고, [[DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거]]가 컨테이너까지 all-PR화 — 이 균일성이 오버헤드의 곱셈 인자였다.

## 고려한 대안

- 분해만 굵게(리프 수 축소)하고 세리머니 모델은 유지 — 직렬 체인 병렬성 0과 이슈=PR 오버헤드가 미해결이라 불충분.
- 하드캡(세션 용량 초과 시 강제 분할) — 정보 가치 없는 경계는 가짜 체크포인트라 고정비만 부과. 크기 부작용을 실행 위생으로 흡수할 수 있어 warn으로 강등.
- major도 부모 브랜치에 직접 커밋 후 컨테이너 머지업에서 몰아 리뷰 — 리뷰 안 된 major 위 후속 작업의 재작업 반경 확대 + 격리 리뷰 의미 소실로 기각. major는 위치 무관 자기 브랜치.
- normal 독립 2개를 묶어 major 취급 — 병렬값>고정비인데 wall-clock을 늘리고 rollback 단위를 오염(하나 revert 시 다른 하나까지)해 기각. 묶기는 직렬·같은 rollback 단위일 때만.
- worktree 공유 + 브랜치 스위칭(초기 안) — 리프 무조건 worktree + FF ref 합류가 gear 균일·병렬 기본 대응·스위칭 상태 관리 소멸로 우수.

## 트레이드오프

얻음: micro/normal의 PR+CI+merge lane 소멸(이번 run 기준 PR 7→2~3), 직렬 구간 worker spawn·컨텍스트 재탐색 감소, 과분해 억제, 오케스트레이터 개입/머지의 기계화. trunk 리뷰 보호는 gear 누적 승격으로 보존(trunk 진입 전 반드시 게이트 통과). 메인 트리 HEAD 불변 유지. 포기: 이슈별 PR 감사 흔적(micro/normal은 verify 리포트+SHA range로 대체), gear 승격 상수·이중 리뷰(major 리프 review 후 승격 부모 재review) 등 캘리브레이션 부담. blast radius = define/start/run/done/orchestrate SKILL + closeout evidence guard + ready_leaves/ledger + rules = major.

## 재평가 조건

승격 상수(micro 3개→normal, normal 2개→major)는 초기값이며 run 데이터로 조정한다. 이중 리뷰(major 리프 review 후 승격 부모에서 재review) 비용을 관찰. plan-time warn 임계(태스크 ~7개) 조정. verify 리포트+SHA range 감사 흔적이 PR 이력 대비 부족하면 재검. micro/normal 로컬 FF 합류가 병렬 형제 diverge에서 충돌 빈발하면(리프 역머지 부담) 부분 재검.
