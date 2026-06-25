---
title: session-review reviewer posture 구현
created_at: 2026-06-25
summary: 검증 리뷰와 공동설계 리뷰를 구분하도록 session-review에 target_nature/round_type, derived review posture, feedback taxonomy, confirm lock-check, should-reflect carryover policy를 구현한다.
tags: [session-review, review, process, implementation]
relations:
  ssot: [session-review-plugin]
  decisions: [DEC-2026-06-18-224414-session-review를-wiki-기능-위-리뷰-루프로-설계, DEC-2026-06-19-144637-session-review-스냅샷-백엔드-하이브리드화]
---

## 개요

session-review reviewer posture 수렴 결과를 구현하는 작업이다. 목표는 기존 phase/status machine을 늘리지 않고, 리뷰 대상 성격과 라운드 목적을 표현해 코드 검증 리뷰와 아이디어/방향 co-design 리뷰를 구분하는 것이다.

최종 수렴안은 target_nature와 round_type을 primary input으로 두고, review_posture는 required field가 아니라 derived default plus optional override로 둔다. posture 값은 verify, challenge, co-design만 허용하고 confirm은 posture가 아니라 round_type으로만 표현한다.

## 근거

round 3 confirm 리뷰에서 approved, blocking_count=0, 잔여 이견 없음, lock 가능으로 수렴했다. 실제 dogfooding 결과, explore -> converge -> confirm 흐름이 동작했고 reviewer는 검증만 하는 역할이 아니라 2축화, confirm-round gap, carryover policy 경계를 능동적으로 보강했다. worker는 frame과 최종 synthesis ownership을 유지했다.

핵심 합의: approved는 의견 없음이 아니라 blocking_count=0이다. should-reflect-before-implementation은 approved와 양립 가능하며 구현 전 반영, 보류, 반박 근거를 남겨야 한다. 첫 구현에서 should-reflect carryover는 CLI 자동 파싱이 아니라 complete skill policy로 처리한다.

## 범위와 완료 기준

범위:
- status block 선택 필드로 target_nature와 round_type을 추가하고 review_posture는 optional override로만 둔다.
- target_nature 값은 code, spec, direction, process, general. document target은 target_nature 명시를 요구하고 general은 fallback으로만 사용한다.
- round_type 값은 explore, converge, confirm, review. confirm은 별도 lock-check behavior를 가진다.
- effective_review_posture를 target_nature + round_type에서 계산한다. 값은 verify, challenge, co-design이다.
- feedback label을 blocking, should-reflect-before-implementation, directional, nice-to-have, nit로 정리하고 blocking_count는 blocking만 센다.
- review skill은 round_type=confirm일 때 이전 반영 충실도, lock 가능성, 새 scope 금지를 우선 확인한다.
- request-review skill은 document target에서 target_nature를 묻고, co-design/challenge일 때 approved != no opinion 계약을 노출한다.
- address-feedback skill은 should-reflect 항목을 accepted, deferred, rejected-with-rationale 중 하나로 정리하게 한다.
- complete skill은 approved feedback과 worker synthesis에서 unresolved should-reflect를 final briefing과 다음 구현 단위로 carryover하도록 지시한다. 첫 단계에서는 CLI 자동 파싱을 요구하지 않는다.
- wiki/ssot/session-review-plugin.md와 README에 short contract를 반영한다.
- parser/validator test는 enum과 derivation을 검증하고, policy behavior는 dogfooding 시나리오로 검증한다.

완료 기준:
- 기존 phase 전이는 변경하지 않는다.
- review_posture=confirm은 허용하지 않는다.
- round_type=confirm lock-check가 derived posture와 별도로 동작한다.
- approved semantics는 blocking_count=0만 의미한다.
- should-reflect carryover가 complete path에서 소실되지 않는다.
- self/separate flow 모두 같은 status block으로 동작한다.
- session-review SSOT와 skill 문서, helper 검증, 테스트가 일관된다.
