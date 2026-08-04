---
title: Studio production scale의 취지는 host-native 모델로 계승, 메커니즘은 runtime과 함께 폐기
created_at: 2026-08-04
summary: DEC-2026-07-26-031028의 세 원칙(manager-only, 규모 비례 소집, verification 직교)은 host-native 모델(producer SKILL.md·rules/casting.md·execute review route)에 계승됐다. solo/standard/major 계약명·critic/theatre 판정·broker workflows·studio.py evidence/backlog/track schema는 9644f0c에서 자체 runtime과 함께 폐기됐다.
tags: [studio, production-scale, host-native, supersede]
supersedes: [DEC-2026-07-26-031028-studio-production-scale과-producer-manager-only-운영-모델]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
  ssot: [studio-plugin]
---

## 결정

production scale 개념(DEC-2026-07-26-031028)이 추구한 세 원칙 — Producer manager-only, 규모 비례 소집, verification 독립 — 은 현재 host-native 모델(0.12.0~)에 재구현 없이 계승됐다. 이를 구현하던 구체 메커니즘(solo|standard|major 계약명, interaction critic/theatre 판정, broker workflows, studio.py의 evidence 집계·backlog/track schema)은 9644f0c에서 자체 runtime 전체와 함께 폐기됐다. 계승 매핑: (1) manager-only → `plugins/studio/skills/producer/SKILL.md`: "Producer는 미션 산출물을 직접 만들지 않는다." (2) 규모 비례 소집 → `plugins/studio/rules/casting.md` 선택 규칙: "Producer는 미션에 필요한 가장 작은 역할 조합을 선택한다", "한 agent가 자연스럽게 끝낼 수 있는 작업을 회의로 만들지 않는다" + `config.example.yml`의 provider×role별 model/effort 차등. (3) verification 직교 → `skills/execute/SKILL.md` '## 3. review 경로'가 review를 work와 분리된 독립 route로 유지하고 `crew/reviewer.md` 역할이 그대로 남아 있다.

## 취지

[[INT-2026-07-08-164552-studio-살아있는-에이전트-팀]]의 '일의 정의부터 시연까지 팀 안에서 스스로 수행'과 '살아있음은 목적이 아니라 품질 수단'이라는 취지를 잇는다. production scale이 추구했던 '작은 일도 과도한 리추얼 없이'와 'Producer는 우회하지 않는다'는 정신은 host-native 모델의 casting 선택 규칙과 producer manager-only 불변식으로 형태만 바뀌어 남았다.

## 배경

DEC-2026-07-26-031028은 Studio 0.9~0.11.1의 custom runtime(broker JS workflow 3종, studio.py 5838줄, persistent app-server 등) 위에서 production scale·critic/theatre 판정을 구현했다. DEC-2026-07-29-233844가 Codex sandbox loopback EPERM 실패를 계기로 감사해 studio가 app-server·binary pinning·auth home·persistent store·실행/검수 계약까지 자체 소유하던 문제를 확인했고, 9644f0c(호스트 subagent orchestration만 남기고 자체 runtime 제거)에서 broker 3종·studio.py·critic/rubric.md·execution_control.py·persistent_* 8개 파일 등을 포함해 30090줄을 삭제하고 406줄만 추가했다(git show --stat 확인). 그 결과 production scale DEC의 메커니즘(계약명·critic 판정·backlog/track schema)은 구현 대상이 사라졌지만 취지(관리자 전용·규모 비례·독립검증)는 재구현 없이 host-native 모델에 남아 있다.

## 고려한 대안

(a) DEC-2026-07-26-031028을 active로 유지 — 기각: 본문이 삭제된 broker/critic/studio.py를 현재 구현 계약처럼 서술해 독자를 오도한다. (b) 그냥 deprecated로 retire — 기각: 취지 자체는 유효하므로 '틀렸다'는 신호가 부정확하고 후속 독자가 계승 경로를 찾을 수 없다. (채택) superseded — 계승 매핑을 명시한 새 DEC으로 대체해 무엇이 살아남고 무엇이 폐기됐는지 한 곳에서 보여준다.

## 트레이드오프

얻음: production scale 취지가 host-native 모델의 어느 파일·구절에 남았는지 추적 가능. 잃음: 신·구 DEC 사이 매핑 유지 비용(supersede 관계로 흡수). 위험: 계승 매핑이 향후 파일 이동/재작성으로 다시 깨질 수 있음 — affects_paths와 다음 재검증이 감지.

## 재평가 조건

producer SKILL.md의 manager-only 문장, rules/casting.md 선택 규칙, execute의 review 분리 서술 중 하나라도 제거·모순되면 이 계승 판단을 재평가한다. Studio가 다시 자체 runtime을 두게 되면(DEC-2026-07-29-233844의 재평가 조건과 동일 트리거) production scale 메커니즘 재도입 여부도 함께 재검토한다.
