---
# task — 제3 범주. record/living 어느 쪽도 아니다:
#   본문은 제자리 갱신(living처럼) + relations 보유(record처럼) + 이진 상태(활성/done).
# 상태는 경로로 표현: 활성=wiki/task/, 완료=wiki/task/done/ (complete/reopen 명령).
#   상태 변경마다 supersede 하지 않는다(=`--supersedes` 금지). 무효 task만 retire --type deprecated.
# relations 각 키 의미 (allowed: intents / decisions / ssot / tasks):
#   intents   — 이 업무가 따르는 상위 취지(들).
#   decisions — 이 업무를 낳은 결정(들). 근거의 정본.
#   ssot      — 이 업무가 건드리는 현재 상태 영역(들).
#   tasks     — 외부 작업 ID(owner/repo#N). 보통 이 업무의 루트 이슈. 형식만 검증.
# task는 순수 잎: 다른 타입이 task를 가리키지 않는다. 역방향은 파생 백링크로 조회.
title: <업무의 한 줄 이름>
created_at: YYYY-MM-DD
summary: <무슨 업무이고 어떤 결정·취지에서 나왔는지 한 줄>
tags: [<통제 어휘에서>]
relations:
  intents: [INT-...]
  decisions: [DEC-...]
  ssot: [<slug>]
  tasks: [owner/repo#N]
---

## 개요

무슨 업무인지 한눈에. 위키 탐색자가 보는 **요약** 다리. 상세(범위·체크박스·실행)는 연결된 이슈(`relations.tasks`)에 있고, 여기엔 그 입구만 둔다.

## 근거

이 업무가 **어떤 결정·취지에서 나왔는가**, 왜 지금 필요한가. 위 `relations.decisions` / `relations.intents`에 적은 문서들과 같은 줄에 있는 *이유*를 prose로.

## 범위와 완료 기준

이 업무의 범위 경계 + "완료"의 정의. 세부 실행 단계가 아니라, 1년 뒤에 봐도 유효한 **요약 수준의 정의**. 완료되면 `complete`로 `done/`으로 이동(연결 시 GitHub 이슈 close가 정본).
