---
title: Observations — 관찰
created_at: 2026-05-29
summary: 발견·관찰. 분류 전 임시 record. 후속 TRI/DEC/SSOT 갱신으로 승격되며 supersede.
tags: [meta]
audience: [human, agent]
---

# Observations — 관찰

발견·관찰. 분류 전 임시 record. 후속 TRI/DEC/SSOT 갱신으로 승격되며 supersede.

## 노트

- [[OBS-2026-06-02-200327-knowledge-capture-감사-어휘가-3계층에-중복-정의됨]] — task-github 사후 리뷰에서 recorded/proposed/none 어휘가 rules/knowledge-capture.md·agent-operating-model §1.1·DESIGN §13.1.1 3곳에 중복돼 이미 문구가 어긋난 drift를 발견. 해소: 플러그인이 위키 없이도 산출하는 어휘이므로 메커니즘(rules/knowledge-capture.md)을 정본으로 단일화하고, policy는 의무 규정+포인터, DESIGN은 포인터로 격하. policy를 정본으로 삼는 안은 graceful-degradation(불변식 20) 위반이라 기각. 리뷰 종합 판정은 '취지 충실'.
- [[OBS-2026-06-02-203000-refresh-strict-does-not-catch-empty-observation-body-sections]] — Review found observation records with all fixed body sections empty while wiki refresh --strict still returned no issues. This leaves Stage-2 recall with headers but no evidence.
- [[OBS-2026-07-07-212026-siblings-maybe-phases-신호-설계-2-of-3-대신-테마-필수-구조-corroboration]] — [[DEC-2026-07-07-204311-분해-판정에-don-t-split-프로브와-재합침-우선-원리-도입]] 구현 중 적대적 리뷰(3렌즈→검증 8에이전트)가 DEC 초안의 '신호 2+개'(단일클러스터/동일검증/공통테마 중 2) 조합이 monorepo 독립 모듈에 오발함을 실측 확인 — 공유 npm test(identical_verification 상시참) + 제네릭 명사 '모듈/구현'(shared_theme 오발)로 2신호 성립. 발동 규칙을 '공통 feature 테마(필수 판별자) + 구조신호 1개 이상'으로 재설계하고 build-generic 명사를 stopwords에 추가해 해소했다. 구조신호만으론 monorepo 공유 test·co-location 때문에 같은-테마-N표면과 독립-모듈-N개를 못 가르며, 실제 feature 이름 교집합만 판별력을 갖는다는 것이 근거. 각 신호는 mutation 5종 테스트로 load-bearing 고정. [[TASK-2026-07-07-204702-define-분해-게이트에-유사-형제-재합침-원리-반영]] 실행 산출.
- [[OBS-2026-07-08-225315-studio-v0-1-0-baseline-검증-not-theatre-critic-안티연극-작동-pairing-title-join-버그-발견]] — notes-cli 미션으로 솔로 1 vs 팀 2run(brainstorm+pairing) 실행. theatre=false(팀 valid delta 45), critic이 pairing 모순 증거를 alive=false로 Kill. pairing 브로커 defended↔open title-string 조인 버그 발견(brainstorm index-join과 동종).
