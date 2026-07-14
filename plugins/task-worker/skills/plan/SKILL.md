---
name: plan
description: DefinitionArtifact node의 실행 계획을 완료 조건·영향 경로·기존 context/evidence에 맞춰 수립한다. provider comment를 쓰지 않고 필요 시 artifact revision 또는 compact context를 갱신한다. "task-worker:plan", "로컬 작업 계획 세워줘", "worker 계획" 요청에 사용한다.
---

# plan

계획은 provider 기록이 아니라 실행 입력이다. binding이 있으면 먼저 resume해 이전 세션의 context와 현재 ready set을 재사용한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" resume \
  --ref {DEFINITION_OR_TASK_OR_PROVIDER_REF} --state-root .task-worker/local
```

계획에는 대상 node, 완료 조건, write-set, 직접 dependency, 검증 범위, owner gate를 포함한다. 이미 artifact에 충분히 고정돼 있으면 별도 계획 파일을 만들지 않는다. 기준이 달라졌다면 기존 revision을 덮어쓰지 말고 `revise`로 새 digest를 만든 뒤 binding을 갱신한다.

분해 자체는 `define`, ready-set 실행은 `orchestrate`가 소유한다. 계획 단계에서 독립 leaf를 임의로 합치거나 root 통합 gate를 제거하지 않는다.
