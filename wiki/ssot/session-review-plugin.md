---
title: session-review 플러그인
created_at: 2026-06-18
summary: worker/reviewer가 audit snapshot 또는 fast context와 reviewer lease로 리뷰를 수렴시키는 플러그인 설계 정본
tags: [session-review, review, design]
verified_at: 2026-07-10
affects_paths: [plugins/session-review/**]
---

## 현재 상태

세 계층으로 분리된다.

### 3계층
| 계층 | 무엇 | 성격 | 완료 시 |
|------|------|------|---------|
| 핸드셰이크(소통 채널) | 프로세스 상태·피드백·핸드오프 운반 | wiki **snapshot 기능** 사용. 단일 가변, 매 턴 갱신 | discard |
| 리뷰 대상(산출물) | 실제 작업 결과 — 이 ssot 같은 문서 또는 코드 diff | 수렴 대상 | 작업브랜치로 squash merge |
| 역할 | worker(산출물 생성/수정+요청), reviewer(검토+피드백) | 독립 두 세션 | — |

핸드셰이크는 wiki snapshot 기능을 그대로 쓴다(별도 파일/디렉터리 신설 안 함). 대화 전체 이력·과거 diff는 누적하지 않고 git log가 보관 — 핸드셰이크는 "git log와 합치면 전체 맥락 복원" 수준의 압축 현재상태만 유지한다.

### 실행 모드 (flow mode) — 시작 시 선택
리뷰 플로우 시작(`request-review`) 시 모드를 정한다. 작업자 에이전트가 **서브에이전트를 지원**하는 경우에만 선택지가 열린다.

| 모드 | reviewer 주체 | 진행 방식 | 용도 |
|------|--------------|-----------|------|
| `self` | 작업자가 띄운 분리 reviewer(초회 fresh, 수정 라운드는 유효 lease reuse) | 한 세션 안에서 작업자가 양쪽 턴을 오케스트레이션, 사용자 릴레이 없이 자율 수렴 | 빠른 자율 수렴 |
| `separate` | **독립 세션**의 다른 에이전트 | 두 세션이 git+snapshot으로 비동기, 사용자가 릴레이 | 완전 독립·사용자 개입 |

- 서브에이전트 미지원 환경이면 `separate`가 기본이자 유일.
- 두 모드는 동일한 상태·lease·판정 계약을 공유한다. audit는 snapshot/review branch/round commit을 유지하고, fast는 context JSON으로 같은 상태를 전달한다.
- 완료는 기본적으로 사용자 확인이 필요하다. 단 `self_automation=turnkey`는 최초 요청이 complete 승인까지 포함하므로 추가 확인 없이 완료할 수 있다.
- 모드는 status block `flow_mode`에 기록해 콜드 핸드오프가 어느 모드인지 알 수 있게 한다.

### Reviewer episode lease
- round 1은 항상 fresh reviewer다. 수정 라운드는 scope digest, target/base ref, review strength, round horizon이 유지되고 harness가 `reviewer_ref`를 다시 address할 수 있을 때만 reuse한다.
- lease 만료는 `scope_changed`, `ref_changed`, `risk_changed`, `round_expired`, `harness_unaddressable` fresh fallback reason으로 기계 판정한다. 기본 horizon은 최초 획득 뒤 수정 라운드 2회다.
- status에는 `lease_id`, optional `reviewer_ref`, `reviewed_ref`, `scope_digest`, `finding_digest`, started/updated timestamp, expiry round, `fresh_count`/`reuse_count`, `fresh_required`를 저장한다. `reviewed_ref`와 `finding_digest`는 함께 기록한다.
- lease가 없는 legacy snapshot은 reviewer identity를 추정하지 않고 `fresh_required: true`, `fresh_fallback_reason: legacy_snapshot`으로 lazy migration한다.
- fast mode는 snapshot 대신 동일한 전체 status JSON을 reviewer context로 전달한다. recording overhead만 제거하며 worker/reviewer 분리는 유지한다.

### Workflow receipt v1
`emit-receipt`는 `schema`, `emitter`, `workflow`, `run_id`, started/finished timestamp, `elapsed_ms`, `tokens`, `token_coverage`, `counters`, `quality`를 출력한다. 토큰을 정확히 알 수 없으면 `tokens:null`, `token_coverage:unavailable`이며 0이나 추정값으로 치환하지 않는다.

### 리뷰 강도 (review strength) — 시작 시 선택
리뷰 깊이와 수렴 바를 시작 시 정한다. status block `review_strength`에 기록하고 reviewer가 이에 맞춰 검토한다. 기본값 `normal`.

| 강도 | reviewer 검토 깊이 | blocking 기준 | 수렴 경향 | self 모드 |
|------|-------------------|--------------|----------|-----------|
| `fast` | 표면·sanity 체크(치명/명백 결함 위주) | critical만 | 빠른 approve 지향 | 1 패스 |
| `normal` | 표준(정확성 + 주요 설계) | 정확성·설계 결함 | 균형 (기본값) | 단일 reviewer |
| `hard` | 심층·적대적, 다각(엣지·일관성·대안) | 사소한 결함도 가능, 높은 바 | 수렴까지 라운드 더 | 다중 reviewer/적대적 검증 |

- 강도는 blocking 임계와 검토 범위만 조정한다. reviewer 계약의 다른 원칙(severity 태그·스코프 바운드·결정적 판정)은 강도와 무관하게 유지 — `fast`라도 발견한 건 태그를 단다.
- `hard`라도 blocking은 일관성·정확성·엣지 리스크 중심이다 — 순수 스타일 nit은 사용자가 명시하지 않는 한 nit로 둔다(thrash 방지).
- `self` 모드 + `hard`면 작업자가 다중 서브에이전트 reviewer나 적대적 검증 패스를 띄울 수 있다.

### 브랜치 라이프사이클 (audit)
작업브랜치 → 리뷰브랜치 분기(base commit 기록) → 리뷰브랜치에 턴제 커밋 누적 → 수렴 + 유저확인 → `base..HEAD`를 squash merge로 작업브랜치 반영 → 리뷰브랜치 삭제 + 핸드셰이크 discard. 작업브랜치 worktree 여부 무관. diff 범위 = `base..리뷰브랜치 HEAD`.

### 상태 머신
- **phase** (수렴 상태, owner=다음 행위자): `awaiting-review`(→reviewer) / `changes-requested`(→worker) / `approved`(→worker, 유저확인 진행) / `awaiting-user-confirmation`(→user) / `completed`(terminal) / `blocked`(→user).
- **lock** (동시성): `active_actor` = none|worker|reviewer. 턴 시작 시 획득, 핸드오프 커밋 시 해제. 타인이 active면 행위 금지.
- **턴/상태 정본 = parseable status object.** audit는 snapshot `## 현재 논의`의 첫 fenced `yaml` block, fast는 context JSON을 쓴다. 공통 필드는 phase/actor/target/round/profile/verdict와 reviewer lease 필드다. 식별자/ref/enum/digest/timestamp는 string, `round`·`blocking_count`·expiry/fresh/reuse counter는 integer, `fresh_required`는 boolean, `lock_since`는 ISO8601 string 또는 `null`이다. 전부-숫자 commit SHA도 string으로 normalize하며, helper가 phase/lock/verdict/lease 일관성을 강제한다.
- **리뷰 대상 성격/라운드 목적.** `target_nature`는 `code|spec|direction|process|general`, `round_type`은 `explore|converge|confirm|review`, `review_posture` override는 `verify|challenge|co-design`만 허용한다. `review_posture=confirm`은 금지다. `confirm`은 posture가 아니라 `round_type`이며 별도 lock-check behavior를 갖는다. 기본값은 보수적이다: `target_mode=diff`면 `target_nature=code`, document/unknown은 `general` fallback, `round_type` 누락은 `review`. helper는 `target_nature + round_type`에서 `effective_review_posture`를 계산한다.

파생 기본값:

| target_nature | explore | converge | confirm | review |
|---|---|---|---|---|
| `code` | `verify` | `verify` | `verify` | `verify` |
| `spec` | `co-design` | `challenge` | `verify` | `challenge` |
| `direction` | `co-design` | `challenge` | `verify` | `challenge` |
| `process` | `co-design` | `challenge` | `verify` | `challenge` |
| `general` | `challenge` | `challenge` | `verify` | `verify` |

`round_type=confirm`의 `verify`는 evidence posture일 뿐이고, reviewer는 별도 confirm lock-check(이전 반영 충실도, 잔여 이견, 새 scope 금지)를 수행한다.
- **커밋 메시지 규약 (양쪽 역할 공통)**: `review: request`/`review: feedback`는 **handoff commit discovery marker**(git log에서 핸드오프 커밋을 찾는 고정 영문 접두사)다 — 상태/락 정본은 어디까지나 body status block이고 이 접두사는 커밋 탐색용이다. 그 뒤에 **양쪽 모두 의미 있는 한 줄 요약을 붙인다** — request=무엇을 왜 봐달라는지, feedback=판정(approved/changes-requested)+요지. `review: feedback`만 같은 bare 마커는 금지. **요약 언어 = 환경 기본 언어**(이 워크스페이스=한국어, 사령관 가독성). 예: `review: feedback — approved, status block 파싱 확인, 새 blocking 없음`.

전이표:
| from | to | trigger | required check |
|------|----|---------|----------------|
| (init) | `awaiting-review` | worker 첫 요청 | 리뷰브랜치 생성, base 기록, 대상 명시 |
| `awaiting-review` | `changes-requested` | reviewer 차단이슈 | `blocking_count >= 1` |
| `awaiting-review` | `approved` | reviewer 수렴 | `blocking_count == 0` |
| `changes-requested` | `awaiting-review` | worker 재작업+재요청 | unresolved 처리 or 반박 기록 |
| `approved` | `awaiting-user-confirmation` | worker 완료 제안 | phase=approved |
| `awaiting-user-confirmation` | `completed` | **유저 명시 확인** | 완료 게이트 통과 |
| `*` | `blocked` | 애매한 판단 차이·교착 (worker가 사용자에게 질문) | 사유 기록 |

### 리뷰 대상 모드와 성격
- `diff`: `base..HEAD` 변경이 대상, 핸드셰이크=context. 기본 `target_nature=code`.
- `document`: 지정 문서가 산출물(이 ssot가 그 예), 핸드셰이크=프로세스 채널. request-review는 `target_nature` 명시를 요구하고, 불명확할 때만 `general` fallback을 쓴다.
- `target_nature=general`은 편한 기본값이 아니라 성격 미확정 표시다.
- 대상/모드 미명시면 리뷰어는 추론하지 말고 `blocked`.

### 완료 게이트
`approved` ≠ `completed`. `complete`(worker)는 아래를 **모두** 만족해야 머지/정리:
- phase ∈ {`approved`, `awaiting-user-confirmation`}
- `blocking_count == 0`이며 누락되지 않음
- **worker가 리뷰 내용(쟁점·해결·결론)을 사용자에게 요약 브리핑**
- 현재 세션에 **유저 명시 확인** 존재(단 self turnkey는 최초 profile 동의로 대체)
- 리뷰브랜치가 작업브랜치 파생 + base 추적 가능
- working tree clean
- 핸드셰이크 최종 summary 존재 + 필요한 결정/관찰이 wiki로 승격(또는 "없음" 명시)
- 최신 approved feedback과 worker synthesis에서 미해결 `[should-reflect-before-implementation]`을 final briefing과 다음 구현 단위로 이월. 이어지는 구현이 없으면 "implementation carryover 없음"을 명시.

audit 통과 시 `base..HEAD`를 squash merge → 작업브랜치, 리뷰브랜치 삭제, 핸드셰이크 snapshot **discard**. `completed`는 장기 저장 상태가 아니라 squash 커밋·(승격된) wiki record·git history에 남는 결과 상태다. self turnkey만 최초 profile 동의로 추가 사용자 확인을 대체한다.

### 사용자 소통 — 판단성은 worker 전담, 운영 릴레이는 허용
- **판단·결정성 소통은 worker 전담.** 사용자에 대한 판단/결정 요청, 완료 브리핑·확인, 정책 판단은 worker만 한다. reviewer는 사용자에게 판단 질문이나 완료 확인을 요청하지 않는다.
- **운영 릴레이는 별개로 허용.** separate 모드에서 사용자가 reviewer 세션을 깨우는 트리거("리뷰해")와 reviewer의 짧은 상태 보고("리뷰 끝, 커밋함")는 판단 소통이 아니라 턴 진행 신호이므로 허용된다. (reviewer-user 직접 접촉을 완전히 금지하려면 separate 모드를 user relay가 아니라 worker-mediated handoff로 둬야 한다 — 여기서는 운영 릴레이는 허용하고 판단 소통만 worker로 제한한다.)
- **애매한 판단 차이 → worker가 사용자에게 질문.** 두 에이전트 판단이 갈리고 어느 쪽으로도 명확히 기울지 않아 수렴이 안 되면, worker가 phase=`blocked`로 두고 사용자에게 물어 결정을 받는다(reviewer는 계속 자기 리뷰 의견만 낸다).
- **승인 후 → worker가 브리핑하고 사용자 확인.** reviewer가 `approved`하면 worker가 리뷰에서 오간 내용(쟁점·해결·결론)을 사용자에게 요약 브리핑하고 완료 확인을 받는다.

## 취지

- **목적**: 한 세션의 작업을 독립 세션이 리뷰하고, 작업→피드백→재작업/완료를 반복해 수렴시킨다. 완료는 유저 확인 필수.
- **성공 조건 (north star)**: 처음 보는 세션이 리뷰브랜치 checkout 후 **핸드셰이크 + git log만으로 다음 턴을 안전하게 수행**할 수 있다. "리뷰 가능"이 아니라 "안전한 핸드오프 가능"이 기준.
- **왜 wiki 기능 위에 짓나**: 소통 채널은 wiki **snapshot**("다른 세션이 이어받도록 토론을 저장")에 정확히 부합 → 재발명하지 않는다. 산출물/설계 지식은 **ssot**(이 레포 4계층: knowledge→`wiki/*`). 별도 파일포맷·디렉터리를 새로 만들지 않는다.
- **왜 PR 리뷰와 별개**: `task-github:review`/`pr-verifier`는 PR↔Issue 검증기. 이건 워크스페이스 내부 협업 프로토콜로, 코드뿐 아니라 문서(이 ssot처럼)도 대상이다.

## 구성요소

### 핸드셰이크 (wiki snapshot)
`SNAP-<slug>`, 고정 7섹션에 매핑:
| snapshot 섹션 | 리뷰 용도 |
|---------------|-----------|
| discussion(현재 논의) | **맨 앞 parseable status block(yaml)** + 이번 라운드 핸드오프 |
| background(배경) | 목적·브랜치 토폴로지·리뷰 대상 |
| decided(정해진 것) | resolved feedback + 확정 결정 |
| open_questions(열린 질문) | unresolved feedback + 리뷰 질문 |
| next_steps(다음에 볼 것) | next actor + 리뷰 요청(렌즈) |
| references(관련 파일/문서) | 대상 문서·브랜치·base commit |
| promotion_candidates(승격 후보) | wiki decision으로 승격할 결정 |

### 역할 동작 계약
- **worker**: 요청 초점 좁히기(대상+렌즈), 이미 기각한 대안 명시, 피드백 맹종 금지(수용=명시/이견=근거 반박), 수렴 우선(`[blocking]`만 처리·나머지 defer), `[should-reflect-before-implementation]`은 `accepted`/`deferred`/`rejected-with-rationale` 중 하나로 정리, 항목별 처리 추적, **커밋 메시지에 의미 있는 요약을 환경 기본 언어로** 작성, **판단·결정·완료 소통 담당**(애매한 판단 차이→사용자에게 질문, 승인 후→리뷰 내용 요약 브리핑+사용자 확인; 운영 릴레이는 별개). 시작 시 필독: 핸드셰이크 + `git log <직전 핸드오프>..HEAD` + 대상.
- **reviewer**: feedback label 필수(`[blocking]`, `[should-reflect-before-implementation]`, `[directional]`, `[nice-to-have]`, `[nit]`), 실행가능(모호 금지·구체 요구), 스코프 바운드(대상+진짜 차단결함만·무단 재설계 금지), 결정적 판정, **유저확정 결정 재오픈 금지**(이견은 challenge 1회), 검증 후 발언, 수렴 책임(불변식 무한확장 금지·합의된 건 좁히기), **커밋 메시지에 판정+요지를 환경 기본 언어로** 작성(bare `review: feedback` 금지), **사용자에게 판단 질문·완료 확인을 요청하지 않음**(운영 상태 보고는 허용), **`review_strength`와 `effective_review_posture`에 맞춰 검토 깊이·blocking 기준 보정**. 시작 시 필독: 핸드셰이크 + diff/대상 + resolved 요약.

`approved`는 `blocking_count=0`만 뜻한다. `co-design`/`challenge` 리뷰의 approved feedback에는 `[should-reflect-before-implementation]`, `[directional]`, `[nice-to-have]`, `[nit]`가 남을 수 있다.

### 플러그인 표면 (잠정 — 상태머신/스키마 확정 후 상세화)
| 동사 | 역할 | 자연어 트리거(예) |
|------|------|-------------------|
| `request-review` | worker | "리뷰 요청해" (첫 요청 = 리뷰브랜치 fork + **flow mode·review strength 선택**) |
| `address-feedback` | worker | "피드백 왔어 / 확인해" |
| `review` | reviewer | "n라운드 리뷰요청 왔어 / 새 리뷰 필요해" |
| `complete` | worker | "완료해" (유저확인 게이트) |

### 동시성 / 이탈 경로
- 동시 작업: lock으로 방지(타인 active면 중단).
- bypass(리뷰 무시하고 머지): `complete`가 phase=`approved`+유저확인 요구 → 우회 불가.
- deadlock(상대 턴 착각): phase가 owner 단일 정본 → 착각 불가.
- 애매한 판단 차이·교착: worker가 `blocked`로 두고 **사용자에게 질문**(reviewer는 사용자와 직접 소통 안 함).
