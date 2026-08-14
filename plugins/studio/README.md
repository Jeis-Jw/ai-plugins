# studio — host-native crew orchestrator

Studio는 Codex와 Claude Code가 제공하는 subagent를 역할별 crew로 소집하고, 설정된
work/review/delivery command를 선택해 작업 배정, 메시지 중계, 결과 회수, 리뷰와 재작업을
관리하는 skill 플러그인이다.

Studio 자체 runtime이나 상태 저장소는 없다.

## 제품 경계

Studio가 하는 일:

- mission과 완료 조건 정리
- optional work/review/delivery command 선택과 root orchestration
- 역할·persona·최소 cast 선택
- 선택적인 provider×role model/effort spawn policy 해석
- host subagent 생성과 작업 배정
- host agent id를 사용한 메시지 relay와 재작업
- 결과 회수, review routing, 최종 보고

Studio가 하지 않는 일:

- agent process, model runtime, sandbox, permission, auth 관리
- provider별 모델 catalog 탐색이나 지원 여부 추정
- tool inventory capture와 별도 입장 검사
- Codex/Claude CLI, app-server, broker, reducer, workflow runner 실행
- state store, lease, execution permit, verification ledger 구현
- worktree, PR, wiki, review workflow 상태 복제
- leaf crew에 orchestration을 위임하거나 nested agent topology를 요구

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

## Execute 설정

`.studio.yml`의 `execute`는 optional command routing policy다. command는 shell이 아니라
skill/plugin identifier이며, 미설정·비활성 command는 discovery/probe하지 않는다.

```yaml
execute:
  work:
    command: task-worker
    activation: auto       # auto|always|never
    fallback: native       # native|stop
  review:
    command: session-review
    activation: auto
    fallback: native
  delivery:
    command: task-github
    enabled: false         # operator가 명시적으로 on/off
    fallback: skip         # skip|stop
```

`studio:execute`는 메인 Producer 세션 전용 진입점이다.

- `auto` work는 둘 이상의 unit에 실제 dependency/ready-set 병렬성이 있거나 integration
  gate, cross-session resume, 외부 실행 handoff가 필요할 때만 configured command를 선택한다.
  단일 bounded 작업은 위험하거나 review가 필요해도 native로 실행하고 review route를 별도로
  판단한다. 선호 worktree나 일반 evidence pin만으로 task-worker를 선택하지 않는다.
- configured work command가 작업 분해와 ready planning을 소유한다. Producer는 mission
  경계와 완료 조건을 보존하고 메인 세션에서 orchestration을 수행한다.
- Producer가 ready action마다 적합한 crew를 생성한다. leaf crew는 자기 lane만 수행하며
  작업 재분해, orchestration, nested subagent 생성을 하지 않는다.
- review command는 독립성이나 위험상 필요할 때만 선택한다. external handoff를 approved로
  간주하지 않는다.
- delivery command는 `enabled:true`일 때만 실행하고 work orchestration을 대체하지 않는다.

route 확인:

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" route \
  --path .studio.yml --kind work

python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" select-work \
  --path .studio.yml --work-units 2 --dependency-graph
```

## 크루 model/effort 설정

workspace 루트의 `.studio.yml`은 선택적인 spawn policy다. 파일이 없거나 값이 비어 있으면
현재 host 세션의 model/effort를 상속한다. Studio는 이 파일에 agent 상태나 workflow 진행
상태를 기록하지 않는다.

```yaml
defaults:
  model:
  effort: medium

roles:
  reviewer:
    effort: high

providers:
  codex:
    roles:
      dev:
        model: gpt-5.6-sol
        effort: high
  claude:
    roles:
      dev:
        model: sonnet
        effort: high
```

field별 우선순위는 다음과 같다.

```text
명시적 spawn override
> providers.<provider>.roles.<role>
> roles.<role>
> providers.<provider>.defaults
> defaults
> host session inheritance
```

사용 가능한 role id는 `architect`, `creator`, `curator`, `dev`, `planner`,
`product-designer`, `qa`, `researcher`, `reviewer`, `strategist`,
`visual-designer`다. `roles`와 각 `providers.<provider>.roles`에는 필요한 role만 적는다.

모델명과 effort 값은 provider가 소유한다. Studio는 문자열 구조만 검증하고, 해석된 non-null
값을 새 agent 생성 호출에 그대로 전달한다. host가 지원하지 않는 값이나 조합이면 다른
조합으로 fallback하지 않고 실제 오류를 보고한다.

Codex는 `model`과 `reasoning_effort` spawn 인자에 직접 대응한다. Claude Code는 model을
agent 생성 시 선택할 수 있으며, effort는 현재 host 호출이나 agent definition으로 정확히
적용할 수 있을 때만 생성한다. 적용할 수 없는 설정을 조용히 무시하지 않는다.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" scaffold --path .studio.yml
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" validate --path .studio.yml
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" resolve \
  --path .studio.yml --provider codex --role dev
```

Claude Code 밖에서는 `STUDIO_ROOT`를 설치된 Studio plugin의 절대 경로로 설정한다.
예시는 `config.example.yml`에도 있다.

## 구성

| 경로 | 역할 |
|---|---|
| `skills/producer/SKILL.md` | 소집·배정·중계·회수 규약 |
| `skills/execute/SKILL.md` | 설정 기반 root execution routing·orchestration |
| `crew/*.md` | host에 독립적인 역할 prompt |
| `rules/casting.md` | 최소 cast 기본값 |
| `templates/mission.md` | 선택적으로 쓰는 mission 양식 |
| `scripts/studio_config.py` | model/effort 설정 scaffold·검증·해석 |
| `scripts/mission_receipt.py` | mission 재개 인덱스 CLI — `.studio/receipt/<mission_id>.json` |
| `config.example.yml` | 선택적인 spawn policy 예시 |

runtime, daemon, `studio:doctor`는 없다. 설치 후 Producer skill이 host 기능을 바로
사용하며, CLI는 spawn policy config helper와 mission receipt(재개 인덱스) helper
두 개만 제공한다.

## 다른 플러그인과의 경계

전문 기능은 config에 명시된 경우에만 Producer가 메인 세션에서 late-bind한다.

- work command 예: `task-worker`
- review command 예: `session-review`
- delivery command 예: `task-github`

Studio manifest는 이 플러그인들을 dependency로 선언하지 않는다. command가 선택되기 전에는
가용성을 조회하지 않고, 선택된 뒤에도 그 command의 상태·schema를 import하거나 복제하지
않는다. `task-github`가 task-worker를 필요로 하는지는 task-github 자신의 preflight가
소유한다. `wiki-markdown`은 execute route와 독립적으로 동작한다.

## 마이그레이션

0.13.0은 runtime을 복원하지 않고 `.studio.yml`의 model/effort spawn policy만 복원한다.

- 0.11.x runtime state(`.studio/`의 board/context/review/lease)는 읽지 않는다.
- `.studio/receipt/`는 mission receipt(세션 간 재개 인덱스)의 신규 네임스페이스다.
  과거 runtime 상태와 무관하며 `scripts/mission_receipt.py`만 읽고 쓴다
  (워크스페이스 로컬 — `.gitignore` 유지). 근거: DEC-2026-07-30-235418.
- `.studio.yml`에서는 `execute` route와 `defaults`, `roles`, `providers`의 model/effort만
  읽는다. 과거 `agents`, `rituals`, broker, runtime capability 설정은 지원하지 않는다.
- 진행 중 작업은 receipt lane의 host agent id가 있을 때 해당 host 기능으로 직접 재개한다.
- agent id가 없으면 필요한 작업만 새 agent에게 다시 배정한다.

## 버전

- `0.13.0`: `studio:execute`, optional work/review/delivery routing, root-only
  orchestration과 provider×role model/effort native spawn 계약을 추가했다.
- `0.12.0`: host-native subagent orchestration skill만 남기고 runtime, state, broker,
  execution/review/context/economics 계층을 제거했다.
