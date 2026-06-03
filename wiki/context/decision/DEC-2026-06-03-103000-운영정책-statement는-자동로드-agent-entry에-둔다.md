---
title: 운영정책 statement는 자동로드 agent entry에 둔다
created_at: 2026-06-03
summary: wiki-markdown 배포 설계에서 작업환경 운영정책 statement의 정본 위치를 소비 프로젝트 wiki/ssot/agent-operating-model.md가 아니라 CLAUDE.md/AGENTS.md 같은 자동로드 agent-entry 표면으로 재배치한다. 이 repo의 위키에는 플러그인 설계 결정만 dogfood로 남기고, 플러그인 패키지는 agent-policy 스캐폴드로 CLAUDE.md/AGENTS.md 관리 블록을 만든다.
tags: [wiki, layering, policy, agent-entry]
search_terms: [agent-operating-model, CLAUDE.md, AGENTS.md, agent-policy]
supersedes: [DEC-2026-05-29-105318-four-layer-separation, TRI-2026-05-29-105533-claude-md-as-policy-conflates-mechanism-and-policy]
relations:
  ssot: [wiki-four-layer-separation]
---

## 결정

`wiki-markdown`의 배포 설계에서 작업환경 운영정책 statement의 정본 위치를 소비 프로젝트의 `wiki/ssot/agent-operating-model.md`에서 `CLAUDE.md` / `AGENTS.md` 같은 자동로드 agent-entry 표면으로 옮긴다.

이 repo의 위키에는 이 변경을 **플러그인 설계 결정**으로 dogfood 기록한다. 반대로 플러그인을 설치한 소비 프로젝트의 wiki vault에는 운영정책 파일을 자동 생성하지 않는다. 플러그인 패키지는 새 `agent-policy` 스킬을 제공해 `CLAUDE.md`와 `AGENTS.md`에 짧은 관리 블록을 멱등 병합한다.

## 취지

항상 적용되어야 하는 작업환경 규칙은 세션 시작 시 자동로드되어야 한다. 운영정책이 wiki vault 안에 있으면 agent가 먼저 recall해야 보이는데, 정책의 존재를 모르는 세션은 recall 자체를 하지 못한다.

동시에 plugin mechanism은 agent-neutral이어야 하고, 소비 프로젝트의 wiki는 제품·서비스·시스템 지식 저장소로 남아야 한다. 따라서 policy statement는 자동로드 entry에, policy rationale은 프로젝트가 정한 별도 이력 위치에 둔다. 이 플러그인 개발 repo는 wiki 자체를 제품 설계 저장소로 dogfood하므로 이번 결정만 wiki `decision`으로 남긴다.

## 배경

v1의 4계층 결정은 policy를 `wiki/ssot/agent-operating-model.md`에 두고 `CLAUDE.md`/`AGENTS.md`는 그 포인터로만 쓰도록 했다. 이 구조는 mechanism과 policy를 분리한다는 장점이 있었지만, 실제 세션에서 운영정책이 자동로드되지 않아 동시 작업 격리와 capture 권한을 agent가 즉흥 판단하는 문제가 드러났다.

특히 여러 세션이 같은 working tree와 wiki index를 동시에 수정하면 작업 문서와 파생 인덱스가 엉킬 수 있다. "동시 task는 worktree로 격리" 같은 규칙은 recall 대상 지식이 아니라 세션 시작 전부터 적용되는 운영 규칙이다.

## 고려한 대안

- **기존 유지**: `wiki/ssot/agent-operating-model.md`를 policy 정본으로 유지. mechanism/policy 분리는 선명하지만 자동로드 실패를 해결하지 못해 반려했다.
- **CLAUDE.md에 장문 정책과 근거를 모두 저장**: 자동로드는 해결하지만 prompt 비용이 커지고 mechanism·policy·rationale이 한 파일에 섞여 반려했다.
- **정책 statement만 자동로드 entry에 저장**: 짧은 실행 규칙은 `CLAUDE.md`/`AGENTS.md`, 근거는 프로젝트가 정한 이력 위치에 둔다. 이 안을 채택했다.

## 트레이드오프

자동로드 entry 파일에 운영정책 statement가 들어가므로 매 세션 토큰 비용이 조금 늘어난다. 대신 정책 존재를 recall해야만 아는 닭-달걀 문제가 사라진다.

소비 프로젝트 wiki에는 운영정책 rationale이 자동으로 남지 않는다. 이는 의도적이다. 소비 프로젝트 wiki를 작업환경 정책 저장소로 만들지 않고, 필요한 프로젝트만 별도 운영 로그나 docs를 선택하게 한다. 이 플러그인 개발 repo는 플러그인 설계 자체가 도메인이므로 wiki decision을 유지한다.

## 재평가 조건

- Claude/Codex가 별도 파일 include를 안정적으로 자동로드해 `CLAUDE.md`/`AGENTS.md` 본문을 더 줄일 수 있게 된 경우.
- `agent-policy` 스캐폴드의 관리 블록이 너무 길어져 prompt 비용이 policy 자동로드 이익을 상쇄하는 경우.
- 소비 프로젝트들이 운영정책 rationale을 wiki 안에 자동으로 남기길 명시적으로 요구하고, 제품 지식과 작업환경 정책을 구분할 별도 타입/namespace가 마련된 경우.
