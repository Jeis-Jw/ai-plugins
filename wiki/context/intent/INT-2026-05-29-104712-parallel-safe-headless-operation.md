---
title: 병렬·헤드리스 안전성
created_at: 2026-05-29
summary: ID·관계·인덱스 메커니즘은 CI/git hook/워크트리/자율 에이전트 등 헤드리스 환경에서 충돌 없이 작동해야 한다.
tags: [wiki, architecture, principle]
---

## 취지

ID 생성·인덱스 갱신·관계 검증 메커니즘은 CI/git hook/워크트리/자율 에이전트 등 헤드리스·병렬 환경에서 race condition·채번 충돌 없이 작동해야 한다.

## 배경

- 순차 번호 ID(`DEC-00005`) 방식은 단일 채번자·전역 max 스캔이 필요해 병렬 브랜치 동시 채번 시 충돌.
- 머지 시 재채번은 불변 basename 원칙을 위반(이미 가리켜진 ID가 흔들림).
- GUI 도구 정본은 headless 자동화 불가 → 채번도 거기 의존 시 같은 문제.

해결: **타임스탬프(`YYYY-MM-DD-HHMMSS`) + slug** 방식은 채번 조율 0(날짜는 로컬 지식). 동일 초·동일 TYPE·동일 slug 충돌은 사실상 0이며, 발생 시 `-b`,`-c` 접미사로 안전 회피(타임스탬프 위조 금지).

