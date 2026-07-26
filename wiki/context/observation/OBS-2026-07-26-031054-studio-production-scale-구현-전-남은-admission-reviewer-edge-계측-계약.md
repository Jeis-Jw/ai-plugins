---
title: Studio production scale 구현 전 남은 admission·reviewer edge·계측 계약
created_at: 2026-07-26
summary: production scale 구현 전에 solo admission 비용 조건, independent reviewer 실행 edge, studio.py 변경 표면, mixed-scale track 계약과 token telemetry를 닫아야 한다.
tags: [studio, production-scale, implementation-gap, telemetry, review]
verified_at: 2026-07-26
search_terms: [solo admission, reviewer edge, mixed-scale track, token telemetry, studio evidence]
affects_paths: [plugins/studio/**]
relations:
  ssot: [studio-plugin]
  decisions: [DEC-2026-07-26-031028-studio-production-scale과-producer-manager-only-운영-모델]
---

## 관찰

승인된 제품 방향과 구현 가능 계약 사이에 다섯 공백이 남아 있다.

1. solo production 1회는 criterion source와 기계적 pass/fail measure가 upstream에 이미 있을 때만 참이다. 없으면 정의 crew 1회와 실행 crew 1회가 필요하다.
2. verification independence를 직교축으로 분리했지만 reviewer attachment의 실행 primitive와 정확한 routing output은 아직 정본화되지 않았다. reviewer persona의 두 번째 solo run과 Producer의 independence 판정을 우선 후보로 둔다.
3. 실제 blast radius에는 scripts/studio.py의 theatre evidence 집계, minutes 생성, backlog parser와 critic/rubric.md가 포함된다.
4. standalone micro mission의 compact contract가 mission validate, budget, KPI backlog 계약을 어떤 최소 필드로 만족할지 미정이다.
5. mixed-scale item이 한 track worktree에 섞일 때 criteria digest, F-xxxx review cycle, readyForIntegration, 동일 파일 write 직렬화 단위가 미정이다.

## 근거

session-review round 2는 DEC 방향을 approved/blocking 0으로 승인하면서 R2-S1~S3를 구현 전 필수 반영으로 남겼다. 현재 pairing.workflow.js는 dev artifact를 강제 interaction delta로 넣고, studio.py evidence는 전체 run의 valid delta 합계로 theatre를 계산하며, run record는 모든 run에 minutes를 생성한다. 최근 board run의 token telemetry는 null이라 production profile 간 비용 비교도 아직 할 수 없다. 리뷰 receipt는 rounds=2, fresh=1, reuse=1, tokens=null, token_coverage=unavailable이다.

## 영향

solo.workflow.js만 추가하면 interaction 호출 수는 줄어도 계약 고정비와 evidence false positive가 남을 수 있다. admission 조건 없이 1회 절감을 주장하면 owner가 잘못된 비용 근거로 DEC 범위를 승인하게 된다. reviewer edge와 mixed-scale integration 단위가 없으면 구현자가 임의 계약을 만들고 Producer manager-only 또는 review single-owner 경계를 다시 깨뜨릴 수 있다.

## 현재 처리

아직 구현 task를 만들지 않는다. 다음 설계 단계에서 ① admission에 criterion source ref와 mechanical measure를 포함하고 ② routing 결과가 production profile과 verification edge를 분리해 반환하도록 하며 ③ reviewer edge primitive와 Producer 판정권을 확정하고 ④ scripts/studio.py·rubric까지 변경 범위에 포함한다. telemetry 복구 전에는 static routing을 구현할 수 있지만 비용 개선 검증이나 dynamic tuning 완료를 주장하지 않는다.

## 구현 후 상태

다섯 공백을 static v1 계약으로 닫았다. solo admission은 source ref+mechanical measure를
강제하고, cast output은 production profile과 review owner를 분리한다. mixed-scale track은
item별 criteria digest/review cycle/readiness와 same-file 직렬화를 명시한다. model call과
elapsed는 exact coverage이며 token은 unavailable을 보존한다. controlled benchmark는
calls 17→10, elapsed 243→144ms, quality drop 0%였다.

## 후속 분류 조건

위 계약이 owner/DEC gate에서 확정되면 implementation task의 acceptance criteria로 승격하고 Studio SSOT를 갱신한다. 실제 run receipt가 production profile별 token·elapsed·quality coverage를 제공하면 비용 가설을 observation에서 검증된 운영 사실 또는 후속 최적화 decision으로 재분류한다. mixed-scale track이 필요 없다는 구현 증거가 나오면 해당 공백은 근거와 함께 닫는다.
