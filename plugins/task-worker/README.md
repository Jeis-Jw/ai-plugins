# task-worker

`task-worker`는 외부 tracker와 무관하게 작업을 정의·분해하고, 실행 가능한 leaf 전체를 병렬 처리하며, worktree 단위 실행과 검증 evidence를 닫는 플러그인이다.

## 책임

- immutable `DefinitionArtifact`와 stable node identity
- direct dependency 검증과 cycle 차단
- DefinitionArtifact와 provider `WorkGraphSnapshot`을 같은 planner로 처리
- 단일 next action이 아닌 `ready_actions[]`와 `integration_candidates[]` 계획
- leaf별 branch/worktree identity와 local run lifecycle
- 검증 evidence를 포함한 idempotent 상태 전이
- provider-neutral workflow receipt
- `task-github.definition/v1` 및 `task-github.local-run/v1` 입력 호환

GitHub Issue/PR/label/merge, Studio mission, wiki graph, session-review 상태는 소유하지 않는다. 외부 provider 연결은 adapter가 담당한다.

## 핵심 흐름

```text
define/revise
  → ready plan
  → ready leaf를 서로 다른 worktree에서 병렬 실행
  → leaf별 verify evidence
  → local closeout 또는 external delivery request
```

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" create \
  --spec work.json
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" ready \
  --artifact .task-worker/definitions/example/revision-000001.json
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" plan-graph \
  --snapshot provider-work-graph.json
```

0.2.0부터 task-github가 versioned JSON CLI contract로 이 planner와 local lifecycle을 소비한다. plugin 경계는 subprocess adapter 경계일 뿐 새 agent/session을 만들지 않는다. task-github의 Issue/PR/merge lifecycle은 adapter에 남고, 범용 실행 코어는 이 플러그인 한 곳에만 존재한다.
