---
title: siblings_maybe_phases 신호 설계: 2-of-3 대신 테마 필수 + 구조 corroboration
created_at: 2026-07-07
summary: [[DEC-2026-07-07-204311-분해-판정에-don-t-split-프로브와-재합침-우선-원리-도입]] 구현 중 적대적 리뷰(3렌즈→검증 8에이전트)가 DEC 초안의 '신호 2+개'(단일클러스터/동일검증/공통테마 중 2) 조합이 monorepo 독립 모듈에 오발함을 실측 확인 — 공유 npm test(identical_verification 상시참) + 제네릭 명사 '모듈/구현'(shared_theme 오발)로 2신호 성립. 발동 규칙을 '공통 feature 테마(필수 판별자) + 구조신호 1개 이상'으로 재설계하고 build-generic 명사를 stopwords에 추가해 해소했다. 구조신호만으론 monorepo 공유 test·co-location 때문에 같은-테마-N표면과 독립-모듈-N개를 못 가르며, 실제 feature 이름 교집합만 판별력을 갖는다는 것이 근거. 각 신호는 mutation 5종 테스트로 load-bearing 고정. [[TASK-2026-07-07-204702-define-분해-게이트에-유사-형제-재합침-원리-반영]] 실행 산출.
tags: [task-github, define, decomposition, siblings-maybe-phases, adversarial-review]
verified_at: 2026-07-10
affects_paths: [plugins/task-github/skills/define/scripts/create_issue_tree.py]
---

## 관찰

## 근거

## 영향

## 현재 처리

## 후속 분류 조건
