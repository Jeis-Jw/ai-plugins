---
# v1: decision은 verified_at을 두지 않는다. 결정의 유효성은 supersede로만 판정.
# relations 각 키 의미:
#   intents             — 이 결정이 *섬긴* 이긴 취지(들). 필수에 가깝다.
#   rejected_decisions  — 같이 검토하다 거부된 동생들.
#   ssot                — 이 결정이 영향 줄 living 정본.
#   tasks               — 외부 작업 ID(owner/repo#N). 형식만 검증, 위키 파일 아님.
title: <결정의 한 줄 이름>
created_at: YYYY-MM-DD
summary: <어떤 결정을 했는지 한 줄>
tags: [<통제 어휘에서>]
audience: [human, agent]
relations:
  intents: [INT-...]
  rejected_decisions: [REJ-...]
  ssot: [<slug>]
  tasks: [owner/repo#N]
---

## 결정

무엇을 결정했는가. **명확한 한 단락** (의도·범위·핵심 선택).

## 취지

이 결정이 어떤 취지(들)를 어떻게 섬기는가. 위 `relations.intents`에 적은 INT 문서들과 같은 줄에 있는 *이유*. (intents가 비어 있다면, 이 섹션이 *왜* 그 결정을 택했는지 prose로 보강한다.)

## 배경

결정 당시의 맥락 — 데이터·제약·이해관계자. 1년 뒤에 봐도 "왜 이 결정이 합리적이었는지" 추적 가능해야 한다.

## 고려한 대안

여기엔 *고려는 했지만 굳이 별도 REJ 문서까지 만들 정도는 아닌* 대안들의 한 줄 요약을 적는다. 본격 반려는 별도 `rejected_decision`을 만들어 `relations.rejected_decisions`로 연결한다.

## 트레이드오프

이 결정이 무엇을 얻고 무엇을 포기했는가 (취지 간 저울질). 어떤 취지가 *이겼고*(이 결정으로) 어떤 취지가 *졌는가*(reject 문서로).

## 재평가 조건

**어떤 조건이 발생하면 이 결정을 다시 검토해야 하는가**. 전향적 만료 트리거 — 향후 refresh/사람이 이 조건을 만나면 새 결정으로 supersede할지 판단한다.
