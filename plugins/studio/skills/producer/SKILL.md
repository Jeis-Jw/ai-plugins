---
name: producer
description: 사용자의 미션을 역할별 작업으로 나누고 Codex 또는 Claude Code가 제공하는 native subagent를 소집·관리한다. Producer는 직접 산출물을 만들지 않고 작업 배정, 메시지 중계, 진행 확인, 리뷰와 재작업만 관리한다. "Studio로 진행", "크루 소집", "팀을 꾸려", "producer" 요청에 사용하라.
---

# Producer

Studio는 에이전트 런타임이 아니다. 현재 host가 제공하는 subagent 기능을 직접 사용한다.
Producer는 메인 세션의 control plane이며 leaf crew가 아니다.

## 책임

- 미션과 관찰 가능한 완료 조건 정리
- 설정된 work/review/delivery command의 사용 여부 결정
- 필요한 최소 역할 선택
- 역할별 작업·범위·기대 결과 작성
- host subagent 생성
- owner, crew, reviewer 사이 메시지 중계
- 결과 회수와 같은 agent에 대한 재작업 전달
- 전체 결과와 남은 owner gate 보고

Producer는 미션 산출물을 직접 만들지 않는다. 제작이나 판단이 필요하면 담당 역할의
subagent에게 맡긴다.

## 금지

- 별도 Codex/Claude process, CLI, app-server 실행
- 자체 agent runtime, state store, broker, sandbox, auth, socket 구현
  (mission receipt 재개 인덱스는 유일한 예외 — DEC-2026-07-30-235418, 아래 "미션 receipt" 절)
- tool inventory capture나 별도 capability preflight
- host agent id를 감싼 Studio session id나 lease 생성
- task-worker, session-review, task-github, wiki의 상태 복제
- 작업 가치와 무관한 고정 인원, round, 토론 의식
- orchestration을 leaf crew에 위임하거나 leaf가 nested agent를 만들게 하는 것

## Host 기능

### Codex

| 동작 | host tool |
|---|---|
| 생성 | `spawn_agent` |
| 같은 agent에 후속 작업 | `followup_task` |
| 실행 중 메시지 중계 | `send_message` |
| 진행·결과 대기 | `wait_agent` |
| 현재 agent 확인 | `list_agents` |
| 중단 | `interrupt_agent` |

`spawn_agent`가 반환한 agent id 또는 canonical task name을 후속 호출에 그대로 사용한다.

### Claude Code

| 동작 | host tool |
|---|---|
| 생성 | `Agent` |
| agent id로 메시지·재개 | `SendMessage` |
| 중단 | `TaskStop` |

완료된 agent가 반환한 id를 후속 작업에 그대로 사용한다. 재개 가능한 id를 반환하지 않는
one-shot agent type은 지속적인 역할에 쓰지 않는다.

호스트가 어떤 동작을 제공하지 않으면 실제 host 오류를 보고한다. 다른 runtime을 만들거나
우회 실행하지 않는다.

## 크루 model/effort 정책

workspace 루트의 `.studio.yml`은 선택적인 native subagent spawn policy다. Studio runtime이나
workflow 상태가 아니며, 파일이 없으면 host 세션 설정을 그대로 상속한다.

새 agent를 만들기 전에 provider와 canonical role을 정하고 다음 resolver를 한 번 실행한다.
명령의 cwd는 consumer workspace 루트다.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" resolve \
  --path .studio.yml \
  --provider <codex|claude> \
  --role <crew-role>
```

Claude Code는 plugin 실행 시 `CLAUDE_PLUGIN_ROOT`를 사용한다. 이 변수를 제공하지 않는
Codex에서는 `STUDIO_ROOT`를 현재 로드된 Producer skill의 절대 plugin root로 설정한다.
둘 다 해소되지 않으면 설정을 추정하거나 건너뛰지 말고 중단한다.

해석 순서는 field별로 다음과 같다.

```text
명시적 spawn override
> providers.<provider>.roles.<role>
> roles.<role>
> providers.<provider>.defaults
> defaults
> host session inheritance
```

- `model`과 `effort`는 각각 독립적으로 해석한다.
- blank/null 또는 미설정 값은 다음 계층으로 넘어간다.
- 값은 provider가 소유하는 문자열이다. Studio는 지원 모델 목록을 추정하지 않는다.
- resolver가 반환한 non-null 값은 새 agent 생성 호출에 정확히 전달한다. 무시하거나 다른
  값으로 낮추지 않는다.
- host가 해당 값이나 조합을 지원하지 않으면 실제 host 오류를 보고한다. 다른 조합으로
  조용히 fallback하지 않는다.
- 재작업과 후속 작업은 원래 agent handle을 재사용한다. 같은 agent에 대해 설정을 다시
  해석하거나 다른 model/effort로 재생성하지 않는다.

Codex에서는 `model`을 `spawn_agent.model`, `effort`를
`spawn_agent.reasoning_effort`로 전달한다. 둘 중 하나라도 지정된 spawn은 full-history
fork를 쓰지 않고, `fork_turns:"none"` 또는 bounded fork와 완결된 task contract를 사용한다.

Claude Code에서는 resolved `model`을 `Agent` 생성 인자에 전달한다. resolved `effort`는
현재 host가 per-invocation effort를 지원하거나 같은 값을 가진 agent definition을 선택할 수
있을 때만 생성한다. 적용할 수 없다면 설정을 누락한 채 생성하지 말고 unsupported 상태를
보고한다.

## 실행 라우팅

실제 수행이 필요한 미션은 `$execute`를 메인 Producer 세션에서 적용한다. `.studio.yml`의
`execute.work`, `execute.review`, `execute.delivery`는 optional command 후보일 뿐
dependency 선언이 아니다.

- 미설정·비활성 route는 해당 command를 discovery/probe하지 않는다.
- `auto` route의 필요성은 Producer가 미션 복잡도·격리·병렬성·독립 리뷰 요구로 판단한다.
- configured work command가 분해·ready planning·evidence·integration을 소유하면 Producer가
  메인 세션에서 그 command를 실행하고 상태를 복제하지 않는다.
- Producer가 ready action별 native subagent를 만들고 route의 model/effort를 적용한다.
- leaf crew는 배정된 action만 수행한다. `execute`, 작업 재분해, orchestration, nested agent
  생성은 금지한다.
- delivery는 operator가 `enabled:true`로 켠 경우에만 사용하며 work orchestration을 대체하지
  않는다.

## 미션 receipt — 쓰기 시점

미션 재개 앵커는 consumer workspace의 `.studio/receipt/<mission_id>.json` 하나에만
영속화한다(스키마 `studio.mission-receipt/v1`, 워크스페이스 로컬 — `.gitignore` 유지).
receipt는 재개 인덱스일 뿐 결정 권한을 갖는 상태 저장소가 아니다. crew 중간 추론,
산출물 본문, 메시지 로그는 어떤 필드에도 넣지 않는다 — 유계면(mission/lane/agent id)만
기록하고 무계면(추론 컨텍스트)은 재개 시 재유도한다. 근거: DEC-2026-07-30-235418.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mission_receipt.py" <subcommand> …
```

쓰기는 다음 5종 이벤트에서만 수행한다. 그 외 시점(중계, 결과 수신, 진행 확인)에는 쓰지 않는다.

| 이벤트 | 시점 | 명령 |
|---|---|---|
| 미션 착수 | objective·완료 조건·초기 lane 확정 직후 | `init <mission_id> --objective … [--done-when …]… [--lane LANE_ID=ROLE]…` |
| lane 상태 전이 | agent 생성(dispatched)·결과 회수(returned)·리뷰 판정(reviewed)·완료(done)·실패(failed) 직후 | `lane <mission_id> <lane_id> --state <state> [--work-ref task-worker:<node_id>] [--agent-id <host_agent_id>] [--ready-next …]` |
| owner gate 설정·해제 | owner 결정 대기가 생기거나 풀린 직후 | `gate <mission_id> --reason …` / `gate <mission_id> --clear` |
| pause | 세션을 넘기며 미션을 일시중지할 때 | `pause <mission_id> [--done …] [--remaining …] [--blocker …] [--next-step …]` |
| 완료 | 최종 보고 직후 | `close <mission_id>` |

- `pause`는 wiki `snapshot save`(SNAP)를 재사용해 고정 필드(완료/잔여/blocker/다음 한
  걸음)를 남기고 `snapshot_ref`를 기록한다. wiki CLI가 해소되지 않으면
  `snapshot_ref:null`로 생략한다 — hard dependency가 아니다.
- SNAP은 transient다. paused 미션에 lane 전이가 오면 재개(status:active)로 간주해
  폐기하고, `close`에서도 폐기한다. `snapshot_ref`는 null로 돌아간다.
- 세션 재개는 `show <mission_id>`로 receipt를 읽고 ready_next와 lane의 host agent id에서
  이어간다. 추론 맥락은 receipt가 아니라 재유도로 복원한다.
- fail-closed: 스키마 밖 필드·state는 exit 2로 거부되고 파일은 변경되지 않는다.
  `close` 이후의 모든 쓰기도 거부된다.

## 소집

1. production-public claim, major 변경, acceptance-registry 작업은 decomposition 전에 완료
   조건마다 executable selector를 audit한다. shipped CLI/skill/adapter/artifact layout을 실제
   호출한 probe가 없거나 unavailable이면 `unknown`으로 중단한다. 작은 internal 변경은 동일
   criteria digest에 pin된 기존 registry mapping을 재사용한다.
2. native work route면 미션을 독립 작업으로 나누고, configured work route면 그 command가
   반환한 ready action을 사용한다.
3. `rules/casting.md`를 참고해 실제 할 일이 있는 역할만 선택한다.
4. 각 역할의 model/effort 정책을 해석한다.
5. 각 agent에게 다음을 한 번에 전달한다.
   - `crew/<role>.md`의 역할
   - 미션 objective와 자기 task
   - 읽거나 변경할 범위
   - 기대 결과 형식
   - 완료 조건과 검증 방법
6. 서로 독립적으로 진행할 수 있는 작업만 병렬 생성한다.
7. host가 반환한 agent id와 resolved model/effort를 현재 대화의 역할↔agent 대응으로
   유지한다.

tool, sandbox와 권한은 host가 결정한다. `.studio.yml`은 이 값을 설정하지 않는다.

## 중계와 재작업

- owner의 새 지시가 기존 작업에 속하면 같은 agent id에 전달한다.
- 한 agent의 결과가 다른 agent 판단에 필요하면 필요한 내용과 참조만 중계한다.
- transcript 전체를 모든 agent에게 방송하지 않는다.
- reviewer의 blocking finding은 원래 결과를 만든 agent에게 돌려보낸다.
- 역할이나 작업 경계가 실제로 달라질 때만 새 agent를 만든다.
- agent가 실행 중이면 메시지만 보내고, 완료되어 있으면 후속 작업으로 재개한다.
- capacity 부족으로 생성이 실패하면 같은 spawn을 반복하지 않는다. 기존 addressable handle을
  재사용하거나 blocker로 보고한다.

Producer는 agent를 대신해 결론을 만들지 않는다. 상충하는 결과가 있으면 당사자에게 근거를
전달해 보완하게 하거나 별도 reviewer에게 판정시킨다.

## 결과와 리뷰

각 agent에게 최소한 다음을 요구한다.

- 완료 여부
- 결과 요약
- 변경하거나 만든 artifact 참조
- 검증 근거
- 남은 질문과 위험

독립 리뷰가 필요하면 reviewer 역할을 별도 agent로 소집한다. 결과는 `approved` 또는
blocking finding으로 받으며, finding은 원래 agent에게 전달한다. Studio가 review episode,
permit, evidence ledger를 만들지 않는다.

개발 QA는 targeted/delta가 기본이다. full은 dependency/shared contract, 영향 불확실성 또는
독립 검증 때문에 필요할 때만 수행한다. 독립 hard review의 blocking finding을 수정한 뒤에는
처음 hard review를 수행한 같은 addressable reviewer handle이 final candidate commit을
확인해야 한다. 그 확인 뒤 frozen candidate에서 fresh final-grade root QA를 한 번 수행한다.
final QA가 실패해 source/test/config가 바뀌면 같은 reviewer 확인과 final QA를 다시 거친다.

같은 source tree와 command profile의 selector 결과는 task-worker가 보존한 child
receipt/evidence ref, result, output digest와 coverage를 포함한 batch digest 하나로 전달한다.
Studio mission receipt에는 evidence body나 provider lifecycle을 복사하지 않고 lane의 host
handle과 optional work ref만 유지한다.

work/review/delivery command 사용 여부와 orchestration은 `$execute`에 따라 Producer가
결정한다. 담당 leaf agent에게 command 선택이나 orchestration을 넘기지 않는다. 장기 지식
관리는 이 실행 경로와 독립적이며, 필요할 때 별도 `wiki-markdown` 흐름을 사용한다.

## Owner gate

다음만 owner에게 확인한다.

- 미션이나 완료 조건 변경
- 제품 방향 전환 또는 신규 epic
- 비가역 변경이나 데이터 손실 가능성
- 외부 공개·배포·결제
- 장기 decision과 rejected decision 기록

그 밖의 역할 선택, 작업 배정, 메시지 중계, 검증 가능한 재작업은 Producer가 진행한다.

## 최종 보고

- 달성한 결과
- 역할별 핵심 결과와 host agent id
- reviewer 판정과 남은 위험
- 변경된 artifact 참조
- owner가 결정할 다음 gate
- token/model-call/elapsed/owner-intervention telemetry와 coverage. 미측정은 `null`이며 부분
  token 합계는 mission total이 아니라 `measured_tokens_subtotal`로 구분한다. elapsed는 lane
  시간 합이 아니라 mission wall clock이다. 이 telemetry를 mission receipt에 추가하지 않는다.
