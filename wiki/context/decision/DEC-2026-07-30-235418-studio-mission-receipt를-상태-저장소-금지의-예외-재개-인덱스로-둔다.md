---
title: studio mission receipt를 상태 저장소 금지의 예외 재개 인덱스로 둔다
created_at: 2026-07-30
summary: '.studio/receipt/<mission_id>.json' 고정 스키마 파일 1개를 허용한다. DEC-2026-07-29의 상태 저장소 금지 조항을 재개 인덱스에 한해 좁힌다.
tags: [studio, mission-receipt, persistence]
---

## 결정

studio는 미션 재개 앵커(mission_id, objective, done_when, lane 상태, host agent id, ready_next, owner_gate, snapshot_ref)를 .studio/receipt/<mission_id>.json 파일 1개에 영속화할 수 있다. 고정 필드 집합(fail-closed), 쓰기 이벤트 5종(착수/lane 전이/gate/pause/완료) 한정. crew 중간 추론 컨텍스트·산출물 본문·메시지 로그는 스키마에 없다. [[DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다]]의 runtime/broker/lease/board 금지는 유지되며, 이 결정은 그 중 '상태 저장소' 문구를 '결정 권한을 갖는 상태 저장소'로 좁힌다.

## 취지

세션을 옮겨도 미션이 이어져야 한다는 보존성 요구와 stateless 지향의 절충. 유계면(mission/lane/agent id)만 영속화, 무계면(추론 컨텍스트)은 재유도.

## 배경

스위트 평가에서 '자율·지속 엔진 역할의 studio만 보존성 0'이 최대 모순으로 지목됨. 일시중지 핸드오프는 기존 SNAP 경로 재사용.

## 고려한 대안

SNAP-only(휘발 staging만, DEC 변경 0): 재개 앵커로는 수명이 약해 기각. 스키마 슬림(3-state): 절충안이었으나 사령관이 원안 채택.

## 트레이드오프

receipt 파일이 늘어나는 만큼 stale 위험. 갱신은 이벤트 5종에만 묶어 완화. .gitignore 유지로 워크스페이스 로컬 한정.

## 재평가 조건

receipt가 결정 권한(브로커/lease)을 갖기 시작하거나, crew 컨텍스트 필드가 스키마에 들어오려 하면 재평가.
