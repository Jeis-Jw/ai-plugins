---
name: verify
description: task-worker node의 완료 조건과 변경 범위를 검증하고 구조화 evidence를 local run에 기록한다. leaf delta 검증과 integration gate를 구분한다. "task-worker:verify", "이 작업 검증해", "run-state evidence 기록" 요청에 사용한다.
---

# verify

artifact node의 완료 조건, 실제 diff, 영향 경로를 기준으로 검증한다.

- leaf에서는 변경된 범위의 test/typecheck/lint/build와 diff를 우선한다.
- 공유 계약·빌드 설정·cross-package 변경은 영향 범위를 확대한다.
- 통합으로 새 상태가 생겼다면 leaf evidence와 별도로 integration gate를 수행한다.
- finding 수정 후에는 무효화된 조건만 delta 검증한다.

evidence에는 최소한 `head`, `paths`, `commands`, `result`를 기록한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact {ARTIFACT} --run-state {RUN_STATE} --event verify \
  --evidence '{"head":"...","paths":["..."],"commands":["..."],"result":"pass"}'
```

검증 실패 시 `verify` event를 기록하지 않는다. 수정 범위와 invalidation 이유를 남기고 다시 검증한다.
