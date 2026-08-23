---
title: context-core snapshot update는 섹션 입력의 trailing whitespace에 owner_result_invalid로 실패한다
created_at: 2026-08-24
summary: context_cli snapshot update --sec-* 본문이 공백/개행으로 끝나면 'draft semantic projection differs from artifact content'. 저장 전 strip된 값과 raw 입력을 비교하는 context-core 쪽 edge. session-review adapter는 strip으로 회피.
tags: [context-core, session-review, edge-case]
affects_paths: [plugins/session-review/scripts/session_review.py]
relations:
  ssot: [session-review-plugin]
---

## 관찰

context-core(0.4.1 설치본, 0.5.1 source 동일) `snapshot update --id … --merge --sec-context @file`에서 파일 본문이 trailing space/newline으로 끝나면 exit 5, `owner_result_invalid: draft semantic projection differs from artifact content`. 같은 본문을 `.strip()`해서 주면 성공. 특정 상황은 session-review의 context-core adapter가 status block + 리뷰 피드백을 `현재 맥락`에 넣을 때 처음 발견(2026-08-23).

## 근거

재현: `- [nit] 길게 ` × 300(끝 공백)로 update → 실패; `'\n'.join(...)`로 끝 공백 없이 → 성공. 원인 경로: `build_snapshot_update_bundle`이 projection `primary_claim`에 raw 입력을 넣고, 검증은 `parse_document`가 `'\n'.join(buffer).strip()`한 섹션과 비교(`_validate_owner_result` 'draft semantic projection differs'). `snapshot save` 경로는 `_validate_owner_inputs`가 먼저 정규화해 영향 없음.

## 영향

context-core CLI를 직접 쓰는 모든 호출자(스킬이 `@file` 본문을 에디터 저장 그대로 넘기면 흔히 개행으로 끝남)에 영향. 에러 메시지가 원인을 말하지 않아 디버깅 비용 큼.

## 현재 처리

session-review 0.7.0 adapter(`_cc_section_args`)가 모든 섹션 값을 strip 후 전달해 회피(commit 0243cfd). context-core 자체 수정은 `context-manager/context-plugins` repo 몫 — update 경로에서 섹션 입력을 strip(또는 projection을 parse 결과에서 생성)하면 해결.

## 후속 분류 조건

context-core가 update 입력을 정규화하면 이 OBS는 `deprecated`로 retire하고 adapter의 strip은 무해한 방어로 남긴다. context-core가 이를 계약("입력은 strip된 본문")으로 문서화하면 그 결정으로 supersede.
