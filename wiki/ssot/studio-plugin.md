---
title: Studio 플러그인
created_at: 2026-07-14
summary: Codex와 Claude Code가 제공하는 subagent 기능으로 역할 기반 crew를 운용하는 orchestration skill. 영속 상태는 mission receipt 재개 인덱스 하나뿐이다.
tags: [studio, orchestration, crew, codex, claude-code]
verified_at: 2026-08-04
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
않고 원래 Producer에게 반환한다. `.studio.yml`의 `execute.work|review|delivery`를
`scripts/studio_config.py route`로 해석해 command를 결정하며, Studio는 여전히 command
runtime이나 상태 저장소를 만들지 않는다.

- `decision:native|skip` / `invoke-command` / `producer-decision` 세 갈래로 discovery
  여부를 정하고, 실행 override(기본 `activation:always`, `fallback:stop`)가 config보다
  우선한다.
- work는 `activation:auto`에서 독립 work unit 복수, worktree/ready-set/재개 필요,
  integration gate, evidence pin 중 하나라도 실질적이면 configured command(예:
  `task-worker`)를 선택하고, 그렇지 않으면 native로 Producer가 직접 crew를 소집한다.
  configured 경로에서는 command가 분해·ready planning을 소유하고 Producer는 미션
  경계·완료 조건만 보존하며, leaf crew는 자기 lane(`start→run→verify→done`)만 수행하고
  재분해·orchestration·nested subagent 생성을 하지 않는다.
- review는 독립성 요구·major blast radius·보안/데이터/배포 gate가 있을 때만 configured
  review command를 선택한다. external handoff는 review 완료로 간주하지 않으며 approved
  verdict와 요구 evidence 확인 전에는 closeout하지 않는다.
- delivery는 `enabled:true`일 때만 configured command를 사용한다. Producer가 자동
  활성화하지 않으며, 꺼져 있으면 command를 조회하지 않고 local 결과로 끝낸다.

command는 shell 문자열이 아니라 opaque skill/plugin identifier다.

## Studio가 소유하는 것

- mission의 objective, 완료 조건, 제약, owner gate
- 역할·persona와 작업의 대응
- host subagent 호출
- optional work/review/delivery command 선택(라우팅)과 root orchestration
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
- command permit, verification evidence, token·비용 계측
- worktree, CI, GitHub Issue/PR, wiki knowledge lifecycle

구현·worktree·검증은 `task-worker`, GitHub delivery는 `task-github`, review workflow는
`session-review`, 장기 지식은 `wiki-markdown`이 각자 소유한다. Producer는 필요한 agent에게
해당 플러그인을 사용하도록 지시할 뿐 상태와 계약을 복제하지 않는다.

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
- `skills/execute/SKILL.md` + `scripts/studio_config.py`: optional work/review/delivery
  command 해석(`route`)과 provider×role model/effort spawn policy 해석(`resolve`/
  `validate`/`scaffold`) — 읽기 전용 결정 helper, 상태를 갖지 않음
- `skills/cockpit/SKILL.md` + `scripts/cockpit.py`: 고정 4소스(task-worker/session-review/task-github/studio) read-only 상태 집계 (`studio.cockpit/v1`, 상태 변경 없음)
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
