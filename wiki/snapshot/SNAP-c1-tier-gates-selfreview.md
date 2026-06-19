---
title: session-review(self): C1 tier gates
created_at: 2026-06-19
summary: Self-flow review of task-github tier-gate wiring.
tags: [session-review, review, dogfood]
type: snapshot
updated_at: 2026-06-19
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "diff"
target_ref: "task/c1-tier-gates"
base_ref: "1d8b709f7276a075926e6fa75c265716afa7e70a"
responding_to: "d75ffb9"
round: 1
flow_mode: "self"
review_strength: "normal"
blocking_count: 0
```

### 리뷰 피드백 (round 1)

판정: approved (blocking 0). C1 tier 게이트 배선은 정확하고 9개 문서 전반이 일관된다.

**검증한 것:**
- 게이트 명령 유효성 (smoke + 적대 실측): `refresh --level integrity --strict --json`은 integrity 등급 이슈가 있을 때만 exit 6, hygiene-only면 exit 0. broken-rel을 심은 볼트에서 integrity 필터 출력은 tier:integrity 이슈만 포함(hygiene 누출 없음). `refresh --level hygiene --json`은 tier:hygiene만, --strict 없으니 report-only exit 0. bad --level → exit 2. repo 본 볼트는 양쪽 exit 0(클린). `--level`+`--strict` 합성은 SKILL 가정대로 동작(코드 2349-2350 필터 → 2914 strict-on-issues).
- 일관성: task-github 내 bare `refresh --strict` 잔존 0건 — 전부 `--level integrity --strict`로 이행. quality-gates/wiki-bridge/task-protocol/DESIGN/README + verify/merge/done SKILL 모두 integrity=차단·hygiene=경고·drift(changed-path-stale)=차단으로 합치. quality-gates.md의 tier 목록(integrity 6개 / hygiene 9개)이 코드 INTEGRITY_CHECKS·HYGIENE_CHECKS와 정확히 일치.
- 정책 타당성: integrity/hygiene 분리는 머지 게이트로 합리적(구조적 깨짐만 차단, 청소거리는 경고). changed-path-stale은 코드상 HYGIENE_CHECKS 소속이나 task-github가 hard drift 게이트로 유지하는 "의도적 예외"가 quality-gates.md line 11·DESIGN.md에 명시됨.
- 하위호환: integrity 이슈 0이면 종전 --strict와 동일 통과(integrity 필터 빈 집합 → strict exit 0). done/merge/verify의 `[ -d ./wiki ]` graceful skip 유지(done은 블록 가드 내, merge는 종전과 동일하게 prose 가드 — 이 diff가 도입한 회귀 아님).
- 버전: task-github 0.5.0 — claude plugin.json·codex plugin.json·marketplace 3곳 일치.

**비차단 관찰(nit, 반영 선택):**
- merge/SKILL.md Step 4의 hard-gate bash 블록은 `[ -d ./wiki ] && echo`(표시용) + prose 가드라 done/SKILL.md의 `if [ -d ./wiki ]; then ... fi` 명시 가드와 형태가 다르다. 신규 HYG= 줄도 같은 prose-가드 레벨에 있어 주변 코드와는 일관(기존 STRICT=/DRIFT=와 동일). 회귀 아님이나, 차후 merge SKILL의 게이트 블록도 done처럼 명시 if-가드로 감싸면 graceful-skip 표현이 SKILL 간 통일됨.

승인. worker는 PR → 머지 진행 가능.

## 리뷰 요청 (round 1, flow_mode=self)

C1: task-github 게이트를 wiki B2 tier로 배선. 대상 diff: git diff main..HEAD.
hard gate refresh --strict → --level integrity --strict, hygiene 비차단 경고, drift(changed-path-stale) hard 유지.
정확성·게이트 명령 유효성·문서 일관성(quality-gates/wiki-bridge/SKILL/DESIGN) 관점. task-github는 유닛테스트 없음, 밑단 tier는 wiki에서 테스트됨.

## 배경

target_mode=diff, base_ref=1d8b709f7276a075926e6fa75c265716afa7e70a, review_branch=task/c1-tier-gates-review, flow_mode=self

## 정해진 것



## 아직 열린 질문



## 다음에 볼 것



## 관련 파일/문서



## 승격 후보
