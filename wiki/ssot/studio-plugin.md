---
title: Studio 플러그인
created_at: 2026-07-14
summary: Codex와 Claude Code가 제공하는 subagent 기능으로 역할 기반 crew를 운용하는 orchestration skill. 영속 상태는 mission receipt 재개 인덱스 하나뿐이다.
tags: [studio, orchestration, crew, codex, claude-code]
verified_at: 2026-08-14
affects_paths: [plugins/studio/**]
---

## 현재 상태

Studio 0.14.0은 owner의 미션을 역할별 작업으로 나누고, 현재 host가 제공하는 subagent를
소집해 배정·중계·결과 회수·review/rework를 관리한다. 0.12.0에서 자체 runtime(broker,
`scripts/studio.py`, `pairing.workflow.js` 등 Codex Workflow Runner 서브시스템 포함)을
전량 제거하고 host subagent orchestration만 남겼고, 0.13.0에서 `.studio.yml` 기반
optional work/review/delivery command 해석과 root Producer 전용 독립 실행 경로
(`$execute`)를 추가했으며, 0.14.0에서 mission receipt·cockpit을 추가했다. Studio는
별도 agent runtime, 결정 권한을 갖는 상태 저장소, control plane service를 두지 않는다.
2026-08-14 최신 계약에서 execute command는 Studio 내장 도구 지식이 아니라 사용자가 지정한
skill policy로 한정했고, 일반 선택은 host가 제공한 skill catalog의 공개 description을 따른다.
유일한 영속 상태는 재개 인덱스인 mission receipt(`.studio/receipt/<mission_id>.json`,
`studio.mission-receipt/v1`) 하나다
([[DEC-2026-07-30-235418-studio-mission-receipt를-상태-저장소-금지의-예외-재개-인덱스로-둔다]]).

```text
owner
  ↕
Producer skill
  ↕
Codex: spawn_agent / followup_task / send_message / wait_agent / interrupt_agent
Claude Code: Agent / SendMessage / TaskStop
  ↕
host-owned subagents
```

Codex와 Claude Code의 도구 이름은 다르지만 Studio가 요구하는 의미는 같다.

| 의미 | Codex | Claude Code |
|---|---|---|
| 생성 | `spawn_agent` | `Agent` |
| 같은 agent에 후속 작업 | `followup_task` | `SendMessage` |
| 메시지 중계 | `send_message` | `SendMessage` |
| 진행 확인 | `wait_agent`, `list_agents` | `Agent` 결과 |
| 중단 | `interrupt_agent` | `TaskStop` |

Host가 제공하지 않는 기능을 Studio가 흉내 내지 않는다. 실제 host 오류를 보고하고 해당
작업을 중단하거나 host가 지원하는 범위로 cast를 줄인다.

## Execute 기반 독립 오케스트레이션 (0.13.0)

`studio:execute`는 root Producer 세션 전용 진입점이다. leaf crew로 호출되면 재분해하지
않고 원래 Producer에게 반환한다. Studio가 읽는 discovery surface는 host가 이미 제공한
skill catalog의 `name + description`뿐이다. plugin directory scan, 별도 inventory capture,
이름 기반 용도 추정은 하지 않는다.

- route가 미설정이면 work/review는 공개 description으로 정상 선택하고 delivery는 skip한다.
- `.studio.yml execute.*.command`는 shell이 아니라 사용자가 지정한 skill identifier다.
- `activation:auto`는 description match가 필요한 선호 후보, `always`는 exact 사용자 선택,
  `never`는 route 비활성이다.
- 선택 뒤 full `SKILL.md`를 읽고 그 skill의 precondition, negative trigger, lifecycle,
  verification과 closeout을 따른다.
- Studio는 특정 작업 형태에 어떤 plugin을 쓰는지 hard-code하거나 선택한 skill의 CLI 순서,
  state, evidence schema, 완료 판정을 복제하지 않는다.
- delivery는 외부 변경 gate이므로 `enabled:true` 또는 명시적 실행 override가 있을 때만 쓴다.

## Studio가 소유하는 것

- mission의 objective, 완료 조건, 제약, owner gate
- 역할·persona와 작업의 대응
- host subagent 호출
- 공개 description과 사용자 policy 기반 work/review/delivery skill 선택 및 root orchestration
- owner·crew·reviewer 사이 메시지 relay
- 같은 host agent id를 사용한 feedback과 rework routing
- 결과 회수와 최종 보고
- 미션 재개 앵커: `.studio/receipt/<mission_id>.json` — 고정 스키마
  `studio.mission-receipt/v1`, 쓰기 이벤트 5종(착수/lane 전이/gate/pause/완료) 한정,
  fail-closed. pause는 wiki SNAP handoff를 재사용한다(soft dep).

이 정보는 현재 작업의 대화 맥락으로 관리하고, 재개 앵커(유계면: mission/lane/agent id,
status, ready_next, owner_gate, snapshot_ref)만 mission receipt에 영속화한다. crew 중간
추론 컨텍스트·산출물 본문·메시지 로그는 영속화하지 않는다(무계면 재유도). 별도 board,
database, broker를 정본으로 만들지 않는다.

## Studio가 소유하지 않는 것

- agent process, model runtime, sandbox, 인증, 권한, tool inventory
- Codex/Claude CLI, app-server, reducer, workflow runner
- provider capability snapshot, fallback runtime, agent lease
- 선택한 skill의 command permit, verification evidence, token·비용 계측
- worktree, CI, GitHub Issue/PR, wiki knowledge lifecycle

각 전문 plugin/skill은 자신이 무엇을 하고 언제 쓰이는지를 frontmatter description에
공개한다. Producer는 그 설명이 현재 미션과 맞는 경우에만 선택하며, 선택한 skill이 자신의
상태와 계약을 소유한다.

## 수명주기

```text
mission 정리
→ 필요한 최소 역할 선택
→ host subagent 생성과 작업 배정
→ 진행 확인과 필요한 메시지 중계
→ 결과 회수
→ finding이 있으면 같은 agent id에 후속 작업
→ 완료 조건과 남은 위험 보고
```

같은 역할·같은 작업의 재작업은 새 agent를 만들지 않고 original host agent id에 보낸다.
실행 중이면 메시지를 보내고, 완료된 agent면 host의 resume/follow-up 기능을 사용한다.
역할이나 작업 경계가 실제로 달라질 때만 새 agent를 만든다.

## 핵심 불변식

1. Producer는 manager다. crew 산출물을 대신 만들지 않는다.
2. agent 생성·재개·중단은 host API로만 수행한다.
3. host agent id는 감싸거나 재발급하지 않고 그대로 사용한다.
4. tool inventory capture와 별도 preflight를 만들지 않는다.
5. 외부 변경·비용·배포처럼 실제 owner 결정이 필요한 지점만 owner gate로 둔다.
6. host 기능 부재를 custom runtime이나 fallback process로 보충하지 않는다.
7. 역할별 prompt는 특정 host tool 이름이나 model에 의존하지 않는다.
8. mission receipt는 재개 인덱스다. 결정 권한을 갖는 저장소로 승격하거나 crew 추론
   컨텍스트를 필드에 넣지 않는다.

## 구성

- `skills/producer/SKILL.md`: host-native orchestration 규약 (mission receipt 쓰기 시점 포함)
- `skills/execute/SKILL.md` + `scripts/studio_config.py`: description 기반 skill 선택,
  optional 사용자 policy 해석(`route`), provider×role model/effort spawn policy 해석
  (`resolve`/`validate`/`scaffold`) — helper는 적합성을 판정하지 않고 상태를 갖지 않음
- `skills/cockpit/SKILL.md` + `scripts/cockpit.py`: 그 skill 자체의 공개 description에 명시된
  고정 4소스 read-only 집계 (`studio.cockpit/v1`). Producer의 일반 skill 선택 지식과는
  분리된 opt-in integration skill이며 상태를 변경하지 않음
- `crew/*.md`: host-independent role prompt
- `rules/casting.md`: 최소 cast 기본값
- `templates/mission.md`: 선택적 mission 양식
- `scripts/mission_receipt.py`: 재개 인덱스 CLI (init/lane/gate/pause/close/show)

`studio:init`, `studio:doctor`, daemon은 없다. 설치 후 Producer가 현재 host 기능을
직접 사용하며, CLI는 결정적 helper(config 해석, cockpit read-only 상태 집계,
mission receipt)만 제공한다.

## 마이그레이션

0.11.x runtime state(`.studio/`의 board/context/review/lease)는 읽거나 변환하지 않는다.
`.studio/receipt/`는 mission receipt(재개 인덱스)의 신규 네임스페이스로 과거 runtime
상태와 무관하다. 진행 중 작업은 receipt lane의 host agent id가 있으면 host 기능으로
직접 재개하고, id가 없으면 필요한 작업만 새로 배정한다.

관련 결정: [[DEC-2026-07-29-233844-studio는-호스트-에이전트만-오케스트레이션한다]],
[[DEC-2026-07-30-235418-studio-mission-receipt를-상태-저장소-금지의-예외-재개-인덱스로-둔다]]
