---
name: init
description: consumer workspace에 provider-neutral task-worker 설정과 로컬 상태 경로를 안전하게 초기화한다. "task-worker:init", "worker 기본 설정 만들어줘", "task-worker quality preset" 요청에 사용한다.
---

# init

task-worker가 소유하는 실행 정책과 로컬 상태 경로만 초기화한다. GitHub, Wiki, Studio, reviewer provider를 탐색하거나 외부 상태를 변경하지 않는다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" init \
  --root {WORKSPACE} --preset {local|manual|quality|minimal} [--force] [--dry-run] [--json]
```

## preset

| preset | dispatch | delivery | command/impact skeleton | token coverage |
|---|---|---|---|---|
| `local` | `worker` | `local-ff` | TODO, fail-closed | optional |
| `manual` | `manual` | `external` | TODO, fail-closed | optional |
| `quality` | `worker` | `local-ff` | TODO, fail-closed | required |
| `minimal` | `worker` | `local-ff` | disabled | optional |

`local`, `manual`, `quality`은 제품별 명령을 추측하지 않는다. 빈 TODO policy는 유효한 JSON이지만 command execution을 허가하지 않는다. 실제 프로젝트의 command profile과 impact rule을 명시한 뒤 `task-worker:doctor`로 준비 상태를 확인한다.

## 안전 규칙

- 같은 preset 재실행은 `skip`, `changed=false`, exit 0이다.
- 내용이 다른 기존 `.task-worker.yml` 또는 policy file은 `--force` 없이는 하나도 변경하지 않고 nonzero로 종료한다.
- `--force`도 task-worker 소유 config/policy만 갱신하며 `.gitignore`의 다른 줄을 보존한다.
- `--dry-run`은 실제 적용과 같은 paths/action/validation을 반환하지만 파일이나 디렉터리를 만들지 않는다.
- `.task-worker/local/`만 gitignore하고 command/impact policy는 프로젝트 설정으로 추적 가능하게 둔다.
- init은 분해, ready-set 병렬성, worktree 격리, 독립 검증, integration gate를 변경하지 않는다.

JSON 결과에는 항상 `plugin`, `action`, `changed`, `paths`, `validation`, `dry_run`이 포함된다.
