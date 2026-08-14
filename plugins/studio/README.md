# studio — host-native crew orchestrator

Studio는 Codex와 Claude Code가 제공하는 subagent를 역할별 crew로 소집하고, host가 제공한
skill catalog의 공개 설명으로 필요한 skill을 선택해 작업 배정, 메시지 중계, 결과 회수,
리뷰와 재작업을 관리하는 플러그인이다.

Studio 자체 runtime이나 상태 저장소는 없다.

## 제품 경계

Studio가 하는 일:

- mission과 완료 조건 정리
- 공개 description 기반 work/review/delivery skill 선택과 root orchestration
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
- 특정 plugin의 적합성 규칙, CLI 순서, lifecycle을 Studio 내부에 복제
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

## Skill 선택과 Execute 설정

현재 host가 제공한 skill catalog의 `name + description`이 Studio의 유일한 discovery
surface다. Studio는 plugin directory를 스캔하거나 이름만 보고 용도를 추측하지 않는다.
description으로 후보를 고른 뒤 선택한 `SKILL.md`를 끝까지 읽고 그 skill의 precondition,
negative trigger, lifecycle과 verification 계약을 따른다.

`.studio.yml`의 `execute`는 사용자가 특정 skill을 선호하거나 고정할 수 있는 optional
policy다. `command`는 shell이 아니라 host catalog의 skill identifier이며, 아래 값은 구성
형식을 보여주는 사용자 설정 예시일 뿐 Studio의 내장 plugin map이 아니다.

```yaml
execute:
  work:
    command: task-worker:define
    activation: auto       # auto|always|never
    fallback: native       # native|stop
  review:
    command: session-review:request-review
    activation: auto
    fallback: native
  delivery:
    command: task-github:done
    enabled: false         # operator가 명시적으로 on/off
    fallback: skip         # skip|stop
```

`studio:execute`는 메인 Producer 세션 전용 진입점이다.

| 설정 | 의미 |
|---|---|
| route 미설정 | work/review는 host catalog description으로 정상 선택, delivery는 skip |
| `activation:auto` | configured skill은 선호 후보이며 description이 미션과 맞을 때만 선택 |
| `activation:always` | 사용자가 고른 exact skill을 사용하고 다른 skill로 바꾸지 않음 |
| `activation:never` | 해당 route에서 외부 skill을 선택하지 않음 |
| delivery `enabled:true` | 명시적으로 선택한 delivery skill을 실행할 수 있음 |

선택한 skill의 사용 순서와 완료 판정은 그 skill이 소유한다. Studio는 작업 형태별
hard-coded routing rule, 별도 축약 lifecycle, 외부 skill의 artifact/evidence schema를 만들지
않는다. leaf crew는 자기 lane만 수행하고 전체 skill 선택과 orchestration은 root Producer가
유지한다.

route 확인:

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" route \
  --path .studio.yml --kind work
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
| `skills/execute/SKILL.md` | description 기반 skill 선택과 root orchestration |
| `skills/cockpit/SKILL.md` | 명시된 상태 소스의 opt-in read-only 집계 |
| `crew/*.md` | host에 독립적인 역할 prompt |
| `rules/casting.md` | 최소 cast 기본값 |
| `templates/mission.md` | 선택적으로 쓰는 mission 양식 |
| `scripts/studio_config.py` | model/effort 설정 scaffold·검증·해석 |
| `scripts/mission_receipt.py` | mission 재개 인덱스 CLI — `.studio/receipt/<mission_id>.json` |
| `scripts/cockpit.py` | cockpit skill 전용 read-only adapter |
| `config.example.yml` | 선택적인 spawn policy 예시 |

runtime, daemon, `studio:doctor`는 없다. 설치 후 Producer skill이 host 기능을 바로
사용하며, CLI는 config policy, mission receipt, opt-in cockpit을 위한 결정적 helper만
제공한다.

## 다른 플러그인과의 경계

전문 기능을 제공하는 각 plugin/skill은 공개 frontmatter description에 `무엇을 하는지`와
`언제 쓰는지`를 적는다. Studio는 host가 노출한 그 설명을 읽고 선택할 뿐, 특정 plugin의
목록이나 사용법을 내장하지 않는다.

위 설정 예시의 identifier들은 사용자가 명시할 수 있는 policy 사례다. Studio manifest는
이를 dependency로 선언하지 않으며, 선택된 skill의 상태·schema·CLI·완료 판정을 import하거나
복제하지 않는다. 다른 dependency가 필요한지는 선택된 skill 자신의 preflight가 소유한다.

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

- `0.14.0`: mission receipt 재개 인덱스와 opt-in read-only cockpit을 추가했다.
- `0.13.0`: `studio:execute`, optional work/review/delivery routing, root-only
  orchestration과 provider×role model/effort native spawn 계약을 추가했다.
- `0.12.0`: host-native subagent orchestration skill만 남기고 runtime, state, broker,
  execution/review/context/economics 계층을 제거했다.
