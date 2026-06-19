---
title: session-review: docs/design/wiki-markdown-efficiency-direction.md
created_at: 2026-06-19
summary: Review handoff for wiki-markdown 효율 개선 방향 설계 초안 (round 2)
tags: [session-review, review]
type: snapshot
updated_at: 2026-06-19
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "document"
target_ref: "docs/design/wiki-markdown-efficiency-direction.md"
base_ref: "c17d87b805c16ec45c317709e78ffcab31318993"
responding_to: "b1e7d614d4c55377f724ae26a862bb2404076d67"
round: 2
flow_mode: "separate"
review_strength: "normal"
```

## 재리뷰 요청 (round 2)

리뷰 round 1 반영 완료. blocking 2건 수용, non-blocking 2건 승인+팁 반영. 반박 없음.

반영 내역:
- #1 blocking (Item 2) — default flip 철회. 기본 replace 유지, `--merge`를 명시 opt-in으로. 공통 원칙(하위호환 기본값) 준수.
- #2 blocking (Item 4) — 진단 정정. quality check는 QUALITY_REFRESH_CHECKS(opt-in)라 기본 refresh 미실행. 문제를 "quality check 명시 실행 시 lite 평가"로 좁히고, lite skip을 opt-in quality check 내부 동작으로 설계. --strict 관계 재서술.
- #3 non-blocking (Item 1) — 승인. `incoming_sources = all_active + done`로 done만 명시 포함, retired 제외.
- #4 non-blocking (Item 3) — 승인. SECTION_FLAGS 병행 테이블로 초기 구현, 추후 TypeSpec 합류.

코드 검증: #2의 ALL_REFRESH_CHECKS vs QUALITY_REFRESH_CHECKS 분리 사실 확인함(wiki_cli.py:2013-2022).

대상 문서: docs/design/wiki-markdown-efficiency-direction.md (review 브랜치 design/wiki-md-efficiency-review)

## 리뷰 피드백 (round 2)

판정: approved

Blocking 없음. round 1의 blocking 2건은 수용되어 문서와 현재 코드 사실이 일치한다.

1. non-blocking — 아까 논의한 "hard gate vs hygiene warning" 관점은 별도 후속 범위로 남기면 좋다. 현재 문서는 `changed-path-stale`와 quality 쪽을 다루지만, task-github의 merge/done hard gate가 어느 check까지 막아야 하는지까지는 직접 설계하지 않는다. `integrity-hard(schema, broken-rel, duplicate-basename, task-ref)`와 `hygiene-warn(orphan, stale, quality, changed-path-stale 일부)`를 분리하는 후속 item을 추가하면 운영 오버헤드 완화 취지가 더 선명해진다.

2. non-blocking — "merge closeout 자동화"는 wiki-markdown 0.9.0 범위 밖(task-github 쪽)으로 보인다. 그래도 이 문서의 `횡단 사항`이나 후속 작업 후보에 `task-github merge/done closeout automation`을 한 줄 추가하면 좋다. 이번 실제 운영에서 PR merge 후 `wiki complete -> refresh -> closeout commit/push -> branch cleanup`가 수동으로 이어졌고, 이 부분이 체감 오버헤드의 핵심이었다.

3. non-blocking — Item 5는 방향은 맞지만, "기어별 문서 예산"까지 명시하면 정책 효과가 더 커진다. 예: micro는 wiki task 생략/감사 none 기본, normal은 후보 있을 때만 capture, major/workflow는 task+DEC/SSOT 유지. 이는 위키 취지는 살리면서 모든 작업을 같은 문서 강도로 처리하지 않게 하는 안전장치다.

## 배경

target_mode=document, target_ref=docs/design/wiki-markdown-efficiency-direction.md, base_ref=c17d87b805c16ec45c317709e78ffcab31318993, review_branch=design/wiki-md-efficiency-review

## 정해진 것

리뷰 round1 blocking 2건 수용(반박 없음): Item2 default flip 철회, Item4 quality 진단 정정. non-blocking 2건 승인 반영.
round2 reviewer approved. 남은 보강은 후속 범위/정책 문구 수준이며 blocking 아님.

## 아직 열린 질문

없음. 후속 후보: hard/hygiene gate 분리, task-github closeout 자동화, 기어별 문서 예산 명문화.

## 다음에 볼 것

worker가 리뷰 내용 요약 후 사용자 확인을 받아 complete 진행.

## 관련 파일/문서

docs/design/wiki-markdown-efficiency-direction.md

## 승격 후보
