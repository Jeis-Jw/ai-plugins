---
name: orchestrate
description: task-worker work graph의 모든 ready leaf를 bounded parallel로 dispatch하고 각 lane의 검증·closeout 뒤 다음 ready set을 계산한다. GitHub나 Studio를 요구하지 않는다. "task-worker:orchestrate", "작업 트리 병렬 실행해", "ready 작업 전부 돌려" 요청에 사용한다.
---

# orchestrate

## 루프

1. `ready`로 `ready_actions[]` 전체를 계산한다.
2. 저장소 concurrency 한도와 resource lock을 적용한 뒤, 서로 독립인 action을 별도 worktree에서 병렬 dispatch한다.
3. 각 lane은 `start → run → verify → done`을 수행한다.
4. 완료 receipt를 반영하고 다음 ready set을 계산한다.
5. `integration_candidates[]`가 생기면 변경된 통합 상태에 대한 명시적 gate를 수행한다. leaf evidence는 입력으로 재사용하되 통합 gate 자체를 생략하지 않는다.
6. `dispatch: manual`이면 같은 graph를 계산하되 `manual_actions[]`를 보고하고 worker lane을 만들지 않는다.

review edge에서는 reviewer를 호출하기 **직전** binding의 permit을 소비한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" review-permit \
  --ref {DEFINITION_OR_ALIAS} --episode-id {EPISODE_ID} --edge-id {EDGE_ID} \
  --state-root .task-worker/local
```

- lease 없음: 기존 task-worker review policy를 그대로 적용한다.
- `owner=task-worker`: 선택한 native/session-review reviewer를 기존 흐름으로 dispatch한다.
- `owner=studio`: reviewer를 dispatch하지 않고 `externally-owned` handoff를 Studio에 반환한다.
- permit은 reviewer dispatch만 제어한다. `run`, `verify`, `done`, integration evidence와 gate는 어떤 owner에서도 생략하지 않는다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" ready \
  --artifact {ARTIFACT} --state-dir .task-worker/local/runs
```

외부 provider graph는 `task-worker.work-graph/v1` snapshot을 `plan-graph`에 전달한다. 출력의 `ready_actions[]`는 병렬 dispatch 대상, `integration_candidates[]`는 자식 완료로 새 상태가 만들어진 container/root gate 대상이다.

## 금지

- `ready_actions[0]`만 반복 실행해 그래프를 직렬화하지 않는다.
- parallelism을 높이려고 같은 worktree에서 동시에 수정하지 않는다.
- 비용 절감을 이유로 독립 node나 필수 review/integration gate를 제거하지 않는다.
- `owner=studio` handoff를 review 완료로 간주하거나 verify/integration gate를 건너뛰지 않는다.
- plugin을 호출할 때마다 fresh agent/session을 만들지 않는다.
- tracker 기록이 필요하면 caller가 provider adapter를 연결한다. task-worker가 직접 외부 상태를 쓰지 않는다.
