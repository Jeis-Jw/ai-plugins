---
title: session-review: wiki-markdown 개선 방향 초안
created_at: 2026-06-25
summary: wiki-markdown 0.12.0 개선 분석+방향 초안의 리뷰 핸드오프 (round 1, hard)
tags: [session-review, review, wiki-markdown]
type: snapshot
updated_at: 2026-06-25
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "document"
target_ref: "docs/proposals/wiki-markdown-improvement-direction.md"
base_ref: "1b56e9e"
responding_to: "61a10f2"
round: 3
flow_mode: "separate"
review_strength: "hard"
blocking_count: 0
```

### 리뷰 피드백 (round 3)

[approved] blocking 0. round 3 수렴안은 round 2 피드백 9건을 충실히 흡수했다. 특히 closeout을 새 `wiki closeout` 명령이 아니라 `complete/reopen` payload 강화로 낮춘 점, authority를 기본 recall 강제정렬이 아니라 additive label로 낮춘 점, `recall --pack`을 deterministic projection으로 제한한 점, 구현 단위를 A/B/C로 나눈 점 모두 방향이 맞다. 이 문서는 이제 lock해도 된다.

[should-reflect-before-implementation] Unit A의 범위는 끝까지 "surface + additive payload"로 고정해야 한다. `--level` 문서화, compact SKILL, 예제 교체, capture payload 확장 외에 behavior semantics를 같이 넣으면 P0가 다시 커진다. Unit A의 성공 기준은 기존 command 의미 불변 + hidden CLI surface 제거 + read-back 감소다.

[should-reflect-before-implementation] baseline 표는 합리적인 방향성이다. 다만 숫자는 아직 추정치이므로 구현 task에는 `expected baseline`으로 두고, 구현 후 실제 command/read/edit count와 JSON bytes를 채우는 방식이 좋다. 특히 `snapshot save->load`는 절감 항목이 아니라 control row에 가깝고, `active task closeout`의 절감은 payload가 `suggested_git_paths`/`updated_indexes`까지 제공할 때만 성립한다.

[should-reflect-before-implementation] Unit C의 stale/authority는 relation-aware 원칙을 테스트 케이스로 고정해야 한다. anchor 없는 snapshot/observation에 `possibly_stale`를 붙이지 말고 `authority_unknown` 또는 warning 없음으로 처리해야 오탐이 늘지 않는다. 관련 decision을 찾을 수 있는 경우에만 stale warning을 내라.

[non-blocking] `capture --json` payload 필드명은 구현 전에 한 번 더 줄이는 게 좋다. `sections`, `section_flags`, `filled_sections`, `empty_sections`, `indexes_updated`는 충분하지만, `indexes_updated`는 boolean보다 touched index path list가 더 agent-friendly하다. 다만 path list가 noisy하면 `index_changed: true` + `index_paths` optional 정도가 적당하다.

[non-blocking] body-file/STDIN은 Unit B에서 설계할 때 snapshot과 capture를 같이 보라. 원래 pain은 `snapshot save --discussion`에서도 나왔으므로 capture만 해결하면 UX가 반쪽이다. 단, 섹션별 file flag 폭발은 피하고 `@file` convention이나 stdin 하나로 통일하는 기존 방향은 유지.

[non-blocking] closeout P2는 지금처럼 별도 후보로 남기는 게 맞다. 구현 우선순위는 A -> B/C 중 하나 -> closeout 순서가 낫다. closeout부터 하면 task-github 경계와 엮여 다시 범위가 커진다.

[nit] round 3 문서 제목의 `(수렴 중 · round 3 confirmation)`은 lock 후에는 `(수렴 완료)`나 `(방향 확정)`으로 바꾸는 게 다음 세션이 읽기에 더 명확하다.

## 리뷰 요청 (round 1 · separate · hard)

대상: docs/proposals/wiki-markdown-improvement-direction.md
(wiki-markdown 0.12.0 개선 분석 + 방향 초안)

목적: 분석 정확성 검증 + 우선순위 도전 + 새 아이디어. 구현 아님 — 방향 수렴.

리뷰어 체크포인트:
1. §2 판정표(피드백×실측) 오류를 코드로 반박 — 특히 ✅이미구현 / 🔁오진 판정이 맞는지.
2. §4 우선순위 재배치 — P0(SKILL.md progressive disclosure)이 정말 최대 ROI인가? 빠진 P0 후보는?
3. 두 피드백/이 분석이 놓친 개선 아이디어.
4. §5 긴장점 1·2·4·6(계층 귀속 + 오진 처리)에 입장.

작성자 핵심 주장: 시끄러운 요청 다수(capture --sec-* 1-step, --lite, 인덱스 자동동기화,
recall --stage 압축)가 이미 코드에 있고 SKILL.md에 노출만 안 됨 → 최대 레버는
신규 기능이 아니라 문서/표면 재설계. 이 주장의 타당성을 코드로 검증해 달라.

## 배경

target_mode=document, target_ref=docs/proposals/wiki-markdown-improvement-direction.md, base_ref=c8ecde431d1b1616af737f130dec542b774b3efa, worker_branch=wiki-markdown-improvement, review_branch=wiki-markdown-improvement-review, flow_mode=separate, review_strength=hard

## 정해진 것

수렴 확정 (round 1·2·3 approved · reviewer lock).
헤드라인: SKILL drift 3건(--sec-*/--lite/--level); 최대 레버=agent-facing 표면 재설계(신규코드 최소).
P0-선행 bounded drift audit / P0 Unit A(compact SKILL·예제교체·capture payload additive·negative trigger·--level 문서화) / P1 Unit B(discard 가드·body-file/STDIN) · Unit C(recall --pack deterministic·authority/stale additive·relation-aware) / P2 closeout=complete/reopen payload 강화(새 명령 아님).
구현 순서 A→(B|C)→closeout. 구현 단계 이월 노트는 문서 §8. 긴장점 전부 해소(잔여 0).

## 아직 열린 질문

수렴 확정 — 잔여 이견 0.
다음: complete(squash-merge review→worker + snapshot discard) — 사용자 확인 후. 이후 worker→main 반영 + 본 방향을 wiki/context/decision DEC로 캡처(별도) + 구현 Unit A 착수.

## 다음에 볼 것

reviewer가 review 브랜치 체크아웃 → snapshot-load 후 review 스킬(hard)을 실행한다.

## 관련 파일/문서

docs/proposals/wiki-markdown-improvement-direction.md

## 승격 후보
