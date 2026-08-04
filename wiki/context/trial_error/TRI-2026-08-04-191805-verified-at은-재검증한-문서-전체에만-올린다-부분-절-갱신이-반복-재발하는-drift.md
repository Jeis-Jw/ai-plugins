---
title: verified_at은 재검증한 문서 전체에만 올린다 — 부분 절 갱신이 반복 재발하는 drift
created_at: 2026-08-04
summary: studio/task-worker SSOT와 관련 OBS에서 절 일부만 갱신하고 문서 전체 verified_at을 올리는 패턴이 최소 3회(9c6d736·46ac147, b72f812, 1f342c6) 재현됐다. verified_at은 전체 재검증 문서에만, 부분 갱신 시 금지, affects_paths로 자동 감지를 보강한다.
tags: [wiki, verified-at, drift, process]
---

## 교훈

verified_at은 문서 전체를 실제 코드와 대조해 재검증했을 때만 올린다. 절 일부만 고치고 문서 전체 stamp를 올리면, 나머지 절의 stale 사실은 방치된 채 '검증됨'으로 위장된다. 자동 감지(refresh stale/changed-path-stale)는 verified_at·affects_paths가 실제로 채워져 있다는 전제 위에서만 작동한다.

## 상황

2026-07-31 새벽 studio/task-worker SSOT와 관련 OBS 재검증 라운드(#83/#85 커밋군)에서 반복 관찰, 같은 8월 4일 curator 정렬 세션에서도 유사 패턴 재확인. 9c6d736·46ac147은 studio-plugin.md의 mission receipt·cockpit 절은 실제로 갱신했지만 본문 첫 문장 'Studio 0.12.0은…'은 그대로 두고 verified_at만 두 커밋 모두 2026-07-31로 올렸다. b72f812는 task-worker-plugin.md의 telemetry 절 1개만 채우고 문서 전체 verified_at을 07-31로 스탬프했는데 본문의 버전 이력 문장(0.7.0)과 task-github 참조(0.26.0)는 그대로 남아 다음 정렬 라운드까지 stale이었다. 1f342c6은 커밋 메시지가 'OBS 재검증'이라 주장하지만 실제로는 verified_at만 07-29에서 07-31로 옮겼고, 그 관찰이 서술하는 studio.py·pairing.workflow.js·broker가 전날(9644f0c, 07-30) 이미 전량 삭제된 사실은 확인하지 않았다(해당 OBS는 이후 supersede 처리됨).

## 피해야 할 것

절 일부만 고치고 문서 전체 verified_at을 올리는 것. 커밋 메시지의 '재검증'이라는 주장만 믿고 실제 대상 코드/파일 존재 여부를 다시 확인하지 않는 것. affects_paths 없이 verified_at만 있는 문서에 의존하는 것 — changed-path-stale은 affects_paths가 없으면 아예 매칭하지 못한다.

## 대안 또는 우회

verified_at을 올리기 전에 문서 전체를 실제 코드(plugin.json, DESIGN.md, 소스, git log)와 줄 단위로 대조한다. 절 일부만 갱신했다면 그 절만 고치고 verified_at은 건드리지 않는다 — 나머지가 다음 refresh stale 검사에 잡히게 둔다. living/trial_error/observation 문서에는 affects_paths를 채워 changed-path-stale 자동 감지를 실제로 활성화한다.

## 현재도 유효한가

유효. affects_paths가 비어 있으면 changed-path-stale 검사가 작동하지 않으므로 필드를 채우는 것이 재발 방지의 절반이고, 나머지 절반은 습관(부분 갱신 시 문서 전체 stamp 금지)이다. 이 저장소에서 동일 패턴이 최소 3회 재현됐다.
