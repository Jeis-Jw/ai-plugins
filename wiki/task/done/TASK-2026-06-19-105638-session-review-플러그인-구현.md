---
title: session-review 플러그인 구현
created_at: 2026-06-19
summary: 승인된 설계 정본(ssot)과 결정(DEC)에 따라 session-review 플러그인을 plugins/session-review/에 구현한다.
tags: [session-review, implementation]
relations:
  ssot: [session-review-plugin]
  decisions: [DEC-2026-06-18-224414-session-review를-wiki-기능-위-리뷰-루프로-설계]
  tasks: [Jeis-Jw/ai-plugins#10]
---

## 개요

승인된 설계 정본 [[session-review-plugin]](ssot)대로 session-review 플러그인을 `plugins/session-review/`에 구현한다. (working name `session-review` — 정식 이름 확정 필요.)

**먼저 읽어라**:
- 설계 *무엇/어떻게* = [[session-review-plugin]] ssot (동결됨, 그대로 따른다).
- 설계 *왜* = 연결된 DEC (`relations.decisions`).
- 구조 관례 = `plugins/wiki-markdown/`, `plugins/task-github/`.

## 근거

설계를 session-review 리뷰 루프 자체로 도그푸드해 6라운드 만에 reviewer approved + 사용자 확인으로 수렴, main 머지 완료. 이제 정본 스펙을 실제 플러그인으로 구현하는 단계다. **설계는 동결** — 이견이 생기면 ssot 갱신은 새 리뷰 라운드/사령관 승인을 거친다(임의 재설계 금지).

## 범위와 완료 기준

**범위 (ssot 기준)**
- 스킬 4개: `request-review`(리뷰브랜치 fork + flow mode·review strength 선택), `address-feedback`, `review`, `complete`(유저확인 게이트). 자연어 트리거 매핑은 ssot 표 참조.
- 핸드셰이크 = wiki **snapshot 기능** 사용(`snapshot save/load`). 별도 파일포맷·디렉터리 신설 금지.
- `target_mode` diff|document. 상태머신 `phase`+`lock`. body **parseable status block**(`## 현재 논의` 첫 fenced yaml, typed). 커밋 마커.
- 브랜치 라이프사이클(리뷰브랜치 → squash merge → 핸드셰이크 discard). 실행 모드 self/separate. 리뷰 강도 fast/normal/hard. 사용자 소통(판단·완료=worker 전담, 운영 릴레이 허용).

**구현 주의 (리뷰어 non-blocking 노트)**
- status block 파서 = `## 현재 논의` 섹션의 **첫 fenced yaml만** 신뢰(문서 전체 X).
- 식별자/ref 필드 **string normalize**(전부-숫자 커밋 SHA가 Integer로 파싱되는 것 방지).
- 커밋 접두사 `review: request|feedback` = **handoff commit discovery marker**(상태 정본 아님 — 정본은 status block).
- `hard` 강도라도 blocking은 일관성·정확성·엣지 리스크 중심, 순수 nit은 nit.

**완료 기준**
- 스킬 4개 동작, self/separate 두 모드 지원.
- status block read/write + `phase`·`lock` 강제(owner 아닌 행위자 차단).
- `complete`가 **유저 확인 없이는 squash merge 차단**.
- 핸드셰이크가 실제 wiki snapshot 기능 사용(별도 포맷 0).
- 플러그인 구조가 기존 `plugins/` 관례 준수.

**열린 항목**
- 정식 플러그인 이름 확정(working name `session-review`).
- GitHub 이슈 등록 시 `/task-github:start`로 이 task에 연결(`relations.tasks`에 `owner/repo#N` 추가).
