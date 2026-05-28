---
# 선택 필드:
#   verified_at    — 이 함정이 지금도 유효함을 확인한 마지막 날 (YYYY-MM-DD)
#   affects_paths  — 관련 코드 경로 (glob). refresh changed-path-stale 기반.
# relations 키 의미:
#   decisions      — 이 시행착오가 어떤 결정과 관련된 함정인가
#   tasks          — 외부 작업 ID(owner/repo#N). 형식만 검증.
title: <함정/시행착오의 한 줄 이름>
created_at: YYYY-MM-DD
summary: <뭘 잘못/헷갈렸고 어떤 교훈을 얻었는지 한 줄>
tags: [<통제 어휘에서>]
verified_at: YYYY-MM-DD
affects_paths: [src/<area>/**]
audience: [human, agent]
relations:
  decisions: [DEC-...]
  tasks: [owner/repo#N]
---

## 교훈

가장 중요한 한 줄. "다음번엔 이렇게 하자/이거 보자/이걸 의심하자". 본문 맨 위에 둬서 빨리 보이게.

## 상황

언제·어디서·어떻게 이 함정을 만났는가. 재현 가능한 수준으로 — 그러나 너무 길게 적지 말 것 (recall Stage 2는 500B 가드).

## 피해야 할 것

구체적으로 어떤 행동·코드·설정이 문제였는가. 일반화 가능한 안티패턴 형태로 적는다.

## 대안 또는 우회

올바른 접근·우회·디버깅 방법. 가능하면 코드/명령 예시.

## 현재도 유효한가

이 함정이 *지금도 밟힐 수 있는가*. 시스템/도구가 바뀌어 더 이상 발생 안 하면 retire(deprecated) 후보. 해결됐어도 다시 밟을 수 있는 함정이면 active 유지.
