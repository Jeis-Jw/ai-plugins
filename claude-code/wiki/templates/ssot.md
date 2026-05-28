---
# 권장: verified_at — 이 정본이 현재도 유효함을 마지막 확인한 날 (YYYY-MM-DD)
# 선택: affects_paths — 관련 코드 경로 (glob). refresh changed-path-stale 기반.
# ※ ssot는 relations 키를 두지 않는다 (불변식). 영향은 record가 ssot로 가리킨다.
title: <주제명 — 예: 인증 아키텍처>
created_at: YYYY-MM-DD
summary: <현재 어떻게 구성/동작하는지 한 줄>
tags: [<통제 어휘에서>]
verified_at: YYYY-MM-DD
affects_paths: [src/<area>/**]
audience: [human, agent]
---

## 현재 상태

현재 시점에서 이 주제가 **어떻게 동작/구성되는가**. 결정 이력은 적지 않는다 — 그건 context/decision의 영역. 본문은 *지금* 상태에만 집중.

## 취지

decision 없이 만든 설명적 ssot라면 이 자리에 *왜 이런 구조인지* prose로 보강한다. decision 경유로 만들어진 ssot라면 비워두거나, decision 백링크가 다 설명한다고 간주.

## 구성요소

이 정본을 구성하는 모듈·리소스·계약. 다른 ssot로 분기되면 wikilink로 연결.

---

**갱신 정책**: 현실이 바뀌면 이 문서를 **제자리 수정**한다. retire하지 않는다 — 갱신의 *왜*는 그 변경을 일으킨 context/decision이 보유한다. 주제 자체가 소멸할 때만 삭제.
