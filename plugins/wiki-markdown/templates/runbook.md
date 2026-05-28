---
# 권장: verified_at — 이 절차가 현재도 유효함을 마지막 실행/확인한 날 (YYYY-MM-DD)
# 선택: affects_paths — 관련 코드 경로 (glob). refresh changed-path-stale 기반.
# ※ runbook도 relations 키를 두지 않는다 (불변식).
title: <절차명 — 예: 프로덕션 배포>
created_at: YYYY-MM-DD
summary: <이 절차가 무엇을 위한 것인지 한 줄>
tags: [<통제 어휘에서>]
verified_at: YYYY-MM-DD
affects_paths: [src/<area>/**]
audience: [human, agent]
---

## 목적

이 절차가 어떤 상황에서 누구를 위해 무엇을 달성하는가.

## 절차

순서대로 따라하면 끝나는 단계들. 각 단계는 **검증 가능한 결과**를 포함하라 (예: "`curl ... | grep 200`이 보여야 함").

1. ...
2. ...
3. ...

## 주의점

자주 틀리는 부분·롤백 절차·실패 시 점검할 곳. 함정 자체는 별도 `trial_error`로 빼고 여기선 링크만 둘 수 있다.

---

**갱신 정책**: 절차가 바뀌면 이 문서를 **제자리 수정**. 큰 변화 시 그 변경을 일으킨 context/decision으로 *왜*를 추적한다.
