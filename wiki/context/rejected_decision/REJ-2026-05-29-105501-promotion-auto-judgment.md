---
title: promotion 자동 판정
created_at: 2026-05-29
summary: Plugin이 어떤 발견을 정식 record로 승격할지 자동 판정하는 안. 의미·운영 판단이라 자동화 시 거짓 양/음성 누적. plugin은 구조 검증만, 판정은 운영자로 반려.
tags: [wiki, plugin, rejected]
---

## 대안

Plugin이 발견이나 대화 내용을 분석해 어떤 정보가 DEC/TRI/OBS/SSOT로 승격될지 자동 판정하는 방식이다. 운영자가 명시하지 않아도 plugin이 장기 기록 가치가 있는 내용을 골라 capture하게 하는 접근이다.

## 반려 사유

승격 여부는 의미 판단과 운영 맥락에 의존한다. 자동 판정은 false positive로 잡음 record를 만들거나, false negative로 중요한 맥락을 놓칠 수 있다.

Plugin은 타입별 구조 조건과 스키마를 검증하는 mechanism에 머물고, 언제 무엇을 기록할지는 운영 모델과 사람/agent 정책이 결정한다.

## 이 대안의 취지

AI-driven documentation 목표를 더 강하게 밀어, 사용자가 문서화 여부를 매번 판단하지 않아도 되게 하려는 목적이었다. 장기적으로는 작업 중 발생한 의미 있는 지식을 자동으로 보존할 수 있다.

## 재고 조건

충분한 운영 데이터와 명확한 라벨링 기준이 쌓여 특정 승격 판단을 신뢰할 수 있게 되면 보조 추천 기능으로 검토할 수 있다. 자동 capture가 아니라 "후보 제안"부터 시작해야 한다.
