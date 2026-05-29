---
title: Wiki
created_at: 2026-05-29
summary: AI-native wiki — context(intent/decision/rejected_decision/trial_error/observation)와 ssot/runbook을 결정 그래프로 관리.
tags: [meta]
audience: [human, agent]
---

# Wiki

이 vault는 1인 개발자 + AI 에이전트가 프로젝트의 **취지·결정·반려 대안·시행착오·관찰**과 **현재 상태(SSOT)·운영 절차(Runbook)**를 축적·조회하는 정본 저장소다.

## 폴더 인덱스

- [[ssot/ssot]] — 현재 유효한 설계 정본 (living)
- [[runbook/runbook]] — 운영 절차 (living)
- [[context/intent/intent]] — 취지 (record)
- [[context/decision/decision]] — 결정 (record)
- [[context/rejected_decision/rejected_decision]] — 반려된 대안 (record)
- [[context/trial_error/trial_error]] — 시행착오 (record)
- [[context/observation/observation]] — 관찰 (record, 분류 전 임시)

## 에이전트 탐색 힌트

- "왜 이렇게 결정했나요?" → `context/decision/`, 거기서 `relations.intents`로 취지 추적
- "이 취지 어떻게 다뤄왔나?" → `context/intent/`의 백링크 (decisions=승 / rejected=패)
- "현재 어떻게 동작하나?" → `ssot/`
- "이건 어떻게 운영하나?" → `runbook/`
- "이 함정 또 안 밟으려면?" → `context/trial_error/`
- "이거 발견했는데 어디로 분류할지 모르겠다" → `context/observation/`
- 검색: `wiki:recall <query>` (Stage 1 frontmatter scan)
- 점검: `wiki:refresh` (무결성 리포트)
