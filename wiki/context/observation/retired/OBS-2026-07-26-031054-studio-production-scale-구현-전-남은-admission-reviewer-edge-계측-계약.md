---
title: Studio production scale 구현 전 남은 admission·reviewer edge·계측 계약
created_at: 2026-07-26
summary: production scale 구현 전에 solo admission 비용 조건, independent reviewer 실행 edge, studio.py 변경 표면, mixed-scale track 계약과 token telemetry를 닫아야 한다.
tags: [studio, production-scale, implementation-gap, telemetry, review]
verified_at: 2026-07-31
search_terms: [solo admission, reviewer edge, mixed-scale track, token telemetry, studio evidence]
affects_paths: [plugins/studio/**]
relations:
  ssot: [studio-plugin]
  decisions: [DEC-2026-07-26-031028-studio-production-scale과-producer-manager-only-운영-모델]
retired_at: 2026-08-04
retired_type: superseded
superseded_by: DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다
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

`TASK-2026-07-28-155552-studio-native-persistent-crew-production-경로-적용`에서 후속
구현을 추적한다. criterion source와 mechanical measure를 solo admission에 결합하고,
production profile과 verification edge를 분리했으며, `scripts/studio.py`를 포함한
정적 계약을 회귀 검증했다. read-only brainstorm의 native persistence는 회의 workflow
범위로만 Production에 올리고 pairing/write와 cross-meeting persistence는 제외한다.
token·wall-time·물리 실행 telemetry가 없는 상태에서 그 절감을 주장하지 않는다.

## 구현 후 상태

다섯 공백을 static v1 계약으로 구현했다. solo admission은 source ref+mechanical measure와
criteria digest를 end-to-end bind하고, production profile과 review owner를 분리한다.
mixed-scale track은 board-backed plan/dispatch/complete 전이에서 item binding과 same-file
선행 완료를 강제한다. sealed independent-review broker replay는 동일한 4개
시나리오에서 기존 isolated `full` 21 calls와 persistent `standard` 13 calls를 확인했고,
15개 criterion 모두 100점 floor를 통과했다. 이 38.10%는 Studio 0.9 profile 효율 하한
보존이며 native adapter, wall-time, token, 물리 실행 절감 근거가 아니다. token
unavailable은 그대로 보존한다.

## 후속 분류 조건

Production live canary와 전체 회귀·wiki integrity를 최종 integration gate에서 fresh
검증한다. 실제 운영 receipt가 profile별 token·elapsed·physical-process coverage를
제공하기 전에는 비용 개선을 운영 사실로 승격하거나 dynamic tuning 완료로 분류하지 않는다.
