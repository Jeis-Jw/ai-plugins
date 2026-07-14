---
name: define
description: provider-neutral DefinitionArtifact로 작업을 정의하거나 revision을 만든다. 자동 과분해 없이 독립 책임, dependency, 병렬 이득, 검증 경계를 기준으로 work graph를 만든다. "task-worker:define", "작업 정의해줘", "로컬 작업 트리로 나눠줘" 요청에 사용한다.
---

# define

요구사항을 immutable `DefinitionArtifact`로 만든다. GitHub Issue나 Studio track은 생성하지 않는다.

## 분해 기준

- 독립 책임·write-set·rollback·검증 경계 또는 병렬 해금이 있을 때만 child를 만든다.
- 문서화와 검증만을 별도 leaf로 만들지 말고 산출물 완료 기준에 포함한다.
- dependency는 직접 제약만 기록한다. 방어적·transitive blocker를 추가하지 않는다.
- 서로 독립인 leaf는 blocker 없이 두어 `ready_actions[]`에 함께 나타나게 한다.

## 실행

spec은 `definition_id`, `delivery`, `root`, `children[]`를 갖는다. 새 정의에는 provider-specific `record`를 넣지 않는다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" create \
  --spec {SPEC} --store .task-worker/definitions
```

기존 revision을 바꿔야 하면 overwrite하지 않고 `revise --previous {ARTIFACT}`를 사용한다. 출력 artifact path와 digest를 다음 단계에 전달한다.
