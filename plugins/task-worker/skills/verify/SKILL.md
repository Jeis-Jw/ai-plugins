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

physical command 전에 canonical contract digest에 맞는 `execution-permit/v1`을 만들고 command profile·impact rule을 통과시킨 뒤 atomic claim을 획득한다. definition/node/cycle/unit은 attribution일 뿐 physical identity가 아니다. `claimed`가 아니면 명령을 시작하지 않는다. `reuse-evidence`면 physical command를 건너뛰고 반환된 evidence ref를 verify event에 연결한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" execution-claim \
  --permit {PERMIT_JSON} --profiles {COMMAND_PROFILES_JSON} --impact-rules {IMPACT_RULES_JSON} \
  --changed-path {CHANGED_PATH} --cwd {RESOLVED_CWD} --environment '{"KEY":"resolved-value"}' \
  --claimed-by {EXECUTOR_ID} --state-root .task-worker/local
```

실행 뒤에는 exact claim에 묶인 immutable `command-receipt/v1`과 `verification-evidence/v1`로 완료한다. fail-closed permit에서 token coverage가 unavailable이면 완료를 pause하며, report-only일 때만 `tokens:null`을 0으로 바꾸지 않고 보존한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" execution-complete \
  --permit {PERMIT_JSON} --claim-id {CLAIM_ID} --receipt {COMMAND_RECEIPT_JSON} \
  --evidence {VERIFICATION_EVIDENCE_JSON} --state-root .task-worker/local
```

구 `evidence-plan`/`evidence-record`는 migration read compatibility이며 새 physical run의 authorization으로 사용하지 않는다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact {ARTIFACT} --run-state {RUN_STATE} --event verify \
  --evidence '{"head":"...","paths":["..."],"commands":["..."],"result":"pass"}'
```

검증 실패 시 `verify` event를 기록하지 않는다. 수정 범위와 invalidation 이유를 남기고 다시 검증한다.
review lease의 owner/provider와 무관하게 verify evidence는 필수다. 외부 reviewer handoff를 검증 evidence나 integration gate의 대체물로 사용하지 않는다.
