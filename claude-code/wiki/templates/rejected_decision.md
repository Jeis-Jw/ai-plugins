---
# relations.intents — 이 대안이 *섬길* 진 취지. 거부됐지만 미래에 다시 가치 있을 수 있다.
title: <반려된 대안의 한 줄 이름>
created_at: YYYY-MM-DD
summary: <어떤 대안을 왜 거부했는지 한 줄>
tags: [<통제 어휘에서>]
audience: [human, agent]
relations:
  intents: [INT-...]
---

## 대안

거부된 대안의 내용 — 무엇을 하려 했는가.

## 반려 사유

왜 채택하지 않았는가. 비교 대상 decision이 이긴 이유. (※ 비교 대상 decision은 `relations`로 연결하지 않는다 — 양방향 카디널리티는 decision 쪽이 `rejected_decisions`로 가리킨다.)

## 이 대안의 취지

이 대안이 *어떤 취지를 섬기려 했는가*. 그 취지가 `relations.intents`에 적힌 INT 문서다. **거부됐지만 이 취지는 여전히 유효할 수 있음** — 다른 결정에서 다시 저울질될 수 있다.

## 재고 조건

어떤 조건이 발생하면 이 대안을 *다시 검토*할 가치가 있는가. (예: 비용 구조가 바뀐다, 새 기술이 나온다, 사용자 패턴이 변한다)
