# task-worker

GitHub·Wiki·Studio와 무관하게 작업 정의, dependency planning, ready-set 병렬 실행, 검증 evidence, 통합 gate, 재개 상태를 소유하는 provider-neutral 실행 플러그인이다.

## 핵심 계약

- immutable `task-worker.definition/v1`과 stable node identity
- `ready_actions[]` 전체 반환과 node별 worktree/lease 격리
- `dispatch: worker|manual`, `delivery: local-ff|external` 분리
- child 완료 뒤 실행 가능한 `run_kind: integration` gate
- binding/context/work-graph checkpoint를 통한 세션 간 재개
- 동일 definition/node/HEAD/command/environment/tool version의 성공 evidence 재사용
- provider closeout receipt의 idempotent event 기록
- `workflow-review-lease/v1` owner permit으로 Studio/task-worker reviewer 이중 dispatch 차단
- GitHub·Wiki API 호출 없는 provider-neutral runtime

provider별 원격 상태와 mutation은 adapter가 담당한다. task-worker가 Wiki TASK ID나 GitHub root Issue를 alias로 보관할 수는 있지만, 그 문자열을 해석하거나 외부 API를 직접 호출하지 않는다.

review가 필요한 edge만 binding의 `review_leases[]`에 exact lease를 저장한다. `review-permit`은 `owner=studio`이면 `externally-owned/skip` handoff를, `owner=task-worker` 또는 lease 없음이면 기존 local review policy를 반환한다. permit은 reviewer dispatch만 제어하며 구현·verify evidence·done·integration gate를 억제하지 않는다.

## 설정

`.task-worker.yml`이 실행 정책 정본이다. 예시는 [config.example.yml](config.example.yml)에 있다.
프로젝트별 argv command profile과 diff→검증 영향 규칙은 `command-profiles`/`impact-rules`가 가리키는 JSON에 둔다. raw shell 문자열을 실행 계약으로 저장하지 않는다.

```yaml
mode: solo
state-root: .task-worker/local
dispatch: worker
delivery: local-ff
orchestrate:
  review-mode: gear
  max-workers: 3
evidence:
  reuse: true
  duplicate-guard: true
  max-physical-runs: 3
recovery:
  lease-ttl-seconds: 3600
```

GitHub `base_branch`, Issue projection, PR/merge 설정은 여기에 두지 않는다.

## 사용 흐름

```bash
# 정의
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" create \
  --spec work.json --store .task-worker/local/definitions

# Wiki TASK 또는 provider ref와 persistent binding
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" bind \
  --artifact .task-worker/local/definitions/example/revision-000001.json \
  --state-root .task-worker/local --alias TASK-2026-07-14-000000-example

# 새 세션에서 재개
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" resume \
  --ref TASK-2026-07-14-000000-example --state-root .task-worker/local

# reviewer dispatch 직전 owner permit
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" review-permit \
  --ref TASK-2026-07-14-000000-example --episode-id episode-1 --edge-id pr-42 \
  --state-root .task-worker/local

# ready leaf 전체 계획
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" ready \
  --artifact .task-worker/local/definitions/example/revision-000001.json \
  --state-dir .task-worker/local/runs
```

`manual`은 외부 개발자에게 맡길 때 사용한다. 분해·dependency·ready-set은 동일하게 계산하지만 local run/worktree를 만들지 않는다. `worker`는 ready leaf를 bounded parallel로 실행한다.

## 상태 디렉터리

```text
.task-worker/local/
  definitions/   immutable artifact revisions
  bindings/      TASK/provider ref ↔ definition pin
  contexts/      digest-pinned compact handoff
  graphs/        provider-normalized work graph snapshots
  runs/          local execution ledgers
  evidence/      execution fingerprint evidence
  receipts/      workflow/provider closeout receipts
```

이 디렉터리는 같은 머신·workspace에서 세션을 이어가기 위한 로컬 상태다. 여러 머신 간 동기화 정본이 아니다.

## 변경 이력

- `0.5.0`: Studio와 공유하는 canonical verification contract를 기준으로 command profile·impact 범위·delta/full QA 허가를 계산하고, atomic physical execution claim, immutable receipt/evidence, run cap, token telemetry와 external spend gate를 추가했다. ready-set 병렬 실행·worktree 격리·독립 검증·통합 gate는 그대로 유지한다.
- `0.4.0`: exact `workflow-review-lease/v1` binding과 digest/conflict 검증, reviewer dispatch 직전 `review-permit`을 추가했다. Studio-owned review는 externally-owned handoff로 반환하고 task-worker-owned/standalone review, verify evidence, integration gate는 그대로 유지한다.
- `0.3.0`: `.task-worker.yml`, `dispatch: manual|worker`, provider binding/context/work-graph resume, executable integration gate, evidence fingerprint duplicate guard, provider event receipt를 추가했다. task-github 기존 설정의 generic 실행 정책을 이쪽으로 이동했다.
- `0.2.0`: task-github가 versioned JSON CLI contract로 planner/local lifecycle을 소비하도록 분리했다.
