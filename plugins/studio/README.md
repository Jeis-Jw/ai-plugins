# studio — host-native crew orchestrator

Studio는 Codex와 Claude Code가 제공하는 subagent를 역할별 crew로 소집하고, 작업 배정,
메시지 중계, 결과 회수, 리뷰와 재작업을 관리하는 skill 플러그인이다.

Studio 자체 runtime이나 상태 저장소는 없다.

## 제품 경계

Studio가 하는 일:

- mission과 완료 조건 정리
- 역할·persona·최소 cast 선택
- host subagent 생성과 작업 배정
- host agent id를 사용한 메시지 relay와 재작업
- 결과 회수, review routing, 최종 보고

Studio가 하지 않는 일:

- agent process, model runtime, sandbox, permission, auth 관리
- tool inventory capture와 별도 입장 검사
- Codex/Claude CLI, app-server, broker, reducer, workflow runner 실행
- state store, lease, execution permit, verification ledger 구현
- worktree, PR, wiki, review workflow 상태 복제

## Host adapter

Adapter는 별도 코드가 아니라 Producer가 현재 대화의 native tool을 직접 호출하는 규약이다.

| 동작 | Codex | Claude Code |
|---|---|---|
| agent 생성 | `spawn_agent` | `Agent` |
| 같은 agent 후속 작업 | `followup_task` | `SendMessage` |
| 실행 중 메시지 | `send_message` | `SendMessage` |
| 진행·결과 확인 | `wait_agent`, `list_agents` | `Agent` result |
| 중단 | `interrupt_agent` | `TaskStop` |

Host가 반환한 agent id 또는 canonical task name을 후속 호출에 그대로 사용한다. Claude
Code의 subagent와 resume 계약은
[공식 문서](https://code.claude.com/docs/en/sub-agents)를 따른다.

필요한 host 동작이 없으면 실제 오류를 보고하고 중단한다. Studio가 다른 runtime이나
fallback process를 만들지 않는다.

## 구성

| 경로 | 역할 |
|---|---|
| `skills/producer/SKILL.md` | 소집·배정·중계·회수 규약 |
| `crew/*.md` | host에 독립적인 역할 prompt |
| `rules/casting.md` | 최소 cast 기본값 |
| `templates/mission.md` | 선택적으로 쓰는 mission 양식 |

`init`, `doctor`, daemon, CLI는 없다. 설치 후 Producer skill이 host 기능을 바로 사용한다.

## 다른 플러그인과의 경계

필요한 전문 기능은 담당 agent가 직접 사용한다.

- 구현·worktree·검증: `task-worker`
- GitHub Issue/PR delivery: `task-github`
- 독립 review workflow: `session-review`
- 장기 지식: `wiki-markdown`

Studio는 이 플러그인들의 상태를 import하거나 복제하지 않는다.

## 마이그레이션

0.12.0은 0.11.x의 custom runtime과 control plane을 제거한 경계 변경이다.

- 기존 `.studio/` 상태와 `.studio.yml`은 더 이상 읽지 않는다.
- 진행 중 작업은 host가 보유한 agent id가 있을 때 해당 host 기능으로 직접 재개한다.
- agent id가 없으면 필요한 작업만 새 agent에게 다시 배정한다.

## 버전

- `0.12.0`: host-native subagent orchestration skill만 남기고 runtime, state, broker,
  execution/review/context/economics 계층을 제거했다.
