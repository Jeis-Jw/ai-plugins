---
title: session-review를 wiki 기능 위 리뷰 루프로 설계
created_at: 2026-06-18
summary: 산출물=wiki ssot, 소통=wiki snapshot, git 리뷰브랜치+squash merge로 두 독립 세션의 리뷰 루프를 구성. 별도 파일포맷·디렉터리(bespoke)는 기각.
tags: [session-review, design, architecture]
---

## 결정

session-review 플러그인을 **wiki 기능 위에** 짓는다. 산출물(설계/스펙)은 wiki **ssot** 노드([[session-review-plugin]]), 두 세션의 소통 채널은 wiki **snapshot**, 진행은 작업브랜치에서 분기한 **리뷰브랜치**에 턴제 커밋을 쌓고 수렴 시 **squash merge**로 작업브랜치에 반영한다. 별도 파일포맷·디렉터리를 새로 만들지 않는다.

## 취지

독립 두 세션(작업자·리뷰어)이 작업→피드백→재작업/완료를 반복해 결과물을 수렴시키되, **처음 보는 세션이 핸드셰이크 + git log만으로 다음 턴을 안전하게 수행**할 수 있어야 한다. 이미 있는 wiki 메커니즘(snapshot=세션 간 컨텍스트 이어받기, ssot=프로젝트 지식 정본)이 이 요구에 정확히 부합하므로, 재발명하지 않고 그 위에 얹는다.

## 배경

이 워크스페이스는 4계층 분리(mechanism/policy/rationale/knowledge)를 따르고 지식은 wiki에 둔다. session-review는 PR 리뷰(`task-github:review`/`pr-verifier`)와 별개인 워크스페이스 내부 협업 프로토콜이다. 설계는 session-review 루프 자체로 도그푸드하여 6라운드(request↔feedback) 만에 reviewer approved + 사용자 확인으로 수렴했다. 상세 현재 상태는 [[session-review-plugin]].

## 고려한 대안

- **bespoke 파일·디렉터리**(`.session-review/handshake.md`, `plugins/session-review/PRD.md` 등 전용 포맷): 디커플링은 깔끔해 보였으나 "wiki 기능을 활용한다"는 사령관 결정에 반하고 볼트 밖 별도 메커니즘을 새로 유지해야 함 → **기각**.
- **wiki snapshot CLI를 그대로 호출**(고정 7섹션에 우겨넣기) vs **wiki에 리뷰 모드 확장**: 전자는 의미 불일치, 후자는 지식그래프 플러그인에 리뷰 책임 침투 → 패턴/기능 재사용(현 결정)으로 절충.
- **상태를 커밋 메시지·자유문장에만 보관**: 기계 파싱·강제가 불가 → 스냅샷 body의 typed parseable status block으로 대체.

## 트레이드오프

- 얻음: 재발명 없음, 감사·재개 가능(git+vault), 4계층 정합, 콜드 세션 안전 핸드오프.
- 잃음: wiki snapshot frontmatter가 고정이라 상태를 body status block에 둬야 함(약간의 우회); 소통 채널이 볼트 스크래치존을 점유(완료 시 discard로 정리).

## 재평가 조건

- wiki snapshot/ssot 기능의 스키마가 크게 바뀌어 status block·타입 규약이 깨질 때.
- self 실행 모드(서브에이전트 reviewer) 비중이 커져 git 기반 비동기 핸드셰이크가 과한 오버헤드가 될 때.
- PR 리뷰(task-github)와 경계가 흐려져 통합이 더 단순해질 때.
