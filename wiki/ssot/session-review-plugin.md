---
title: session-review 플러그인
created_at: 2026-06-18
summary: 독립 두 세션(작업자·리뷰어)이 wiki snapshot 소통채널과 git 리뷰브랜치로 산출물을 리뷰 루프로 수렴시키는 플러그인 설계 정본
tags: [session-review, review, design]
verified_at: 2026-06-19
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
| `self` | 작업자가 띄운 **서브에이전트**(fresh 컨텍스트) | 한 세션 안에서 작업자가 양쪽 턴을 오케스트레이션, 사용자 릴레이 없이 자율 수렴 | 빠른 자율 수렴 |
| `separate` | **독립 세션**의 다른 에이전트 | 두 세션이 git+snapshot으로 비동기, 사용자가 릴레이 | 완전 독립·사용자 개입 |

- 서브에이전트 미지원 환경이면 `separate`가 기본이자 유일.
- **두 모드는 동일 메커니즘**(핸드셰이크 snapshot·ssot target·git 브랜치/커밋·상태머신·status block)을 공유한다. 다른 것은 reviewer의 정체성과 릴레이 방식뿐 — `self`의 서브에이전트도 fresh 컨텍스트라 독립성이 있고, 같은 핸드셰이크에 `review: feedback`를 커밋한다.
- **완료 게이트는 두 모드 공통으로 사용자 확인 필수.** `self`도 리뷰 라운드는 자율로 돌리되 완료(squash merge/discard)는 자동화하지 않고 반드시 사용자에게 올린다.
- 모드는 status block `flow_mode`에 기록해 콜드 핸드오프가 어느 모드인지 알 수 있게 한다.

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

### 브랜치 라이프사이클
작업브랜치 → 리뷰브랜치 분기(base commit 기록) → 리뷰브랜치에 턴제 커밋 누적 → 수렴 + 유저확인 → `base..HEAD`를 squash merge로 작업브랜치 반영 → 리뷰브랜치 삭제 + 핸드셰이크 discard. 작업브랜치 worktree 여부 무관. diff 범위 = `base..리뷰브랜치 HEAD`.

### 상태 머신
- **phase** (수렴 상태, owner=다음 행위자): `awaiting-review`(→reviewer) / `changes-requested`(→worker) / `approved`(→worker, 유저확인 진행) / `awaiting-user-confirmation`(→user) / `completed`(terminal) / `blocked`(→user).
- **lock** (동시성): `active_actor` = none|worker|reviewer. 턴 시작 시 획득, 핸드오프 커밋 시 해제. 타인이 active면 행위 금지.
- **턴/상태 정본 = 스냅샷 body의 parseable status block.** wiki snapshot은 frontmatter를 기능이 고정 관리하므로 커스텀하지 않는다. 대신 스냅샷 `## 현재 논의` 섹션의 **첫 fenced ```yaml``` 블록**을 두어 기계가 읽는다(파서는 문서 전체가 아니라 이 섹션의 첫 블록만 신뢰): `phase`, `active_actor`, `lock_since`, `next_actor`, `target_mode`, `target_ref`, `base_ref`, `responding_to`, `round`, `flow_mode`, `review_strength`. **타입 규약: 식별자/ref/enum 필드(`phase`·`active_actor`·`next_actor`·`target_mode`·`target_ref`·`base_ref`·`responding_to`·`flow_mode`·`review_strength`)는 모두 quoted string으로 저장**한다(YAML 스칼라 타입 안정성). 특히 전부-숫자 커밋 SHA가 Integer로 파싱되는 걸 막도록 `base_ref`/`responding_to`는 반드시 따옴표. `round`만 정수, `lock_since`는 ISO8601 string 또는 `null`. parser는 식별자 필드를 string으로 normalize한다. 플러그인은 이 블록으로 phase/lock을 강제한다(owner 아닌 행위자·중복 active 차단).
- **커밋 메시지 규약 (양쪽 역할 공통)**: `review: request`/`review: feedback`는 **handoff commit discovery marker**(git log에서 핸드오프 커밋을 찾는 고정 영문 접두사)다 — 상태/락 정본은 어디까지나 body status block이고 이 접두사는 커밋 탐색용이다. 그 뒤에 **양쪽 모두 의미 있는 한 줄 요약을 붙인다** — request=무엇을 왜 봐달라는지, feedback=판정(approved/changes-requested)+요지. `review: feedback`만 같은 bare 마커는 금지. **요약 언어 = 환경 기본 언어**(이 워크스페이스=한국어, 사령관 가독성). 예: `review: feedback — approved, status block 파싱 확인, 새 blocking 없음`.

전이표:
| from | to | trigger | required check |
|------|----|---------|----------------|
| (init) | `awaiting-review` | worker 첫 요청 | 리뷰브랜치 생성, base 기록, 대상 명시 |
| `awaiting-review` | `changes-requested` | reviewer 차단이슈 | 피드백 1+ (severity 태그) |
| `awaiting-review` | `approved` | reviewer 수렴 | blocking 0 |
| `changes-requested` | `awaiting-review` | worker 재작업+재요청 | unresolved 처리 or 반박 기록 |
| `approved` | `awaiting-user-confirmation` | worker 완료 제안 | phase=approved |
| `awaiting-user-confirmation` | `completed` | **유저 명시 확인** | 완료 게이트 통과 |
| `*` | `blocked` | 애매한 판단 차이·교착 (worker가 사용자에게 질문) | 사유 기록 |

### 리뷰 대상 모드
- `diff`: `base..HEAD` 변경이 대상, 핸드셰이크=context.
- `document`: 지정 문서가 산출물(이 ssot가 그 예), 핸드셰이크=프로세스 채널.
- 대상/모드 미명시면 리뷰어는 추론하지 말고 `blocked`.

### 완료 게이트
`approved` ≠ `completed`. `complete`(worker)는 아래를 **모두** 만족해야 머지/정리:
- phase ∈ {`approved`, `awaiting-user-confirmation`}
- **worker가 리뷰 내용(쟁점·해결·결론)을 사용자에게 요약 브리핑**
- 현재 세션에 **유저 명시 확인** 존재
- 리뷰브랜치가 작업브랜치 파생 + base 추적 가능
- working tree clean
- 핸드셰이크 최종 summary 존재 + 필요한 결정/관찰이 wiki로 승격(또는 "없음" 명시)

통과 시 `base..HEAD`를 squash merge → 작업브랜치, 리뷰브랜치 삭제, 핸드셰이크 snapshot **discard**. → `completed`는 장기 저장 상태가 아니라 squash 커밋·(승격된) wiki record·git history에 남는 **결과 상태**다(스냅샷 자체는 사라진다). 이 게이트는 `self`/`separate` 두 모드 공통 — self 모드도 완료는 자동화하지 않고 사용자 확인을 받는다.

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
- **worker**: 요청 초점 좁히기(대상+렌즈), 이미 기각한 대안 명시, 피드백 맹종 금지(수용=명시/이견=근거 반박), 수렴 우선(blocking만 처리·나머지 defer), 항목별 처리 추적, **커밋 메시지에 의미 있는 요약을 환경 기본 언어로** 작성, **판단·결정·완료 소통 담당**(애매한 판단 차이→사용자에게 질문, 승인 후→리뷰 내용 요약 브리핑+사용자 확인; 운영 릴레이는 별개). 시작 시 필독: 핸드셰이크 + `git log <직전 핸드오프>..HEAD` + 대상.
- **reviewer**: severity 태그 필수(blocking/non-blocking/nit), 실행가능(모호 금지·구체 요구), 스코프 바운드(대상+진짜 차단결함만·무단 재설계 금지), 결정적 판정, **유저확정 결정 재오픈 금지**(이견은 challenge 1회), 검증 후 발언, 수렴 책임(불변식 무한확장 금지·합의된 건 좁히기), **커밋 메시지에 판정+요지를 환경 기본 언어로** 작성(bare `review: feedback` 금지), **사용자에게 판단 질문·완료 확인을 요청하지 않음**(운영 상태 보고는 허용), **`review_strength`에 맞춰 검토 깊이·blocking 기준 보정**. 시작 시 필독: 핸드셰이크 + diff/대상 + resolved 요약.

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
