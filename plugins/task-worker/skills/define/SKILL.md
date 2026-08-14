---
name: define
description: dependency, 유의미한 ready-set 병렬성, 별도 integration gate, cross-session resume 또는 외부 handoff가 필요한 multi-unit 작업을 provider-neutral DefinitionArtifact work graph로 정의하거나 revise한다. standalone bounded 작업이나 대화 안에서 끝나는 질문에는 사용하지 않는다. "task-worker:define", "작업 트리로 나눠줘", "복잡한 작업을 병렬 오케스트레이션해줘" 요청에 사용한다.
---

# define

요구사항을 immutable `DefinitionArtifact`로 만든다. GitHub Issue나 Studio track은 생성하지 않는다.

## 쓰지 않는 경우 (negative triggers)

define은 기본 경로가 아니다 — 분해·추적·검증 이득이 있을 때만 진입한다.

- standalone 단일 작업은 파일 수나 위험도와 무관하게 기본적으로 플러그인 진입 없이 직접
  수행한다. 위험도가 높다면 실행 graph를 만드는 대신 독립 review를 별도로 붙인다.
- 대화 안에서 완결 가능한 질문·조사는 define 대상이 아니다.
- 리프 고정비(worker spawn + 세리머니, ~20분+)를 넘는 payoff가 없으면 진입하지 않는다.

1-node 실행은 기존 work graph가 조건 분기로 하나만 남았거나, 사용자가 canonical
cross-session resume·외부 실행 handoff를 명시적으로 요구한 경우의 호환 경로다. standalone
단일 작업을 위해 별도 `single-run` 제품 경로나 축약 lifecycle을 만들지 않는다.

## 분해 기준

- 독립 책임·write-set·rollback·검증 경계 또는 병렬 해금이 있을 때만 child를 만든다.
- 문서화와 검증만을 별도 leaf로 만들지 말고 산출물 완료 기준에 포함한다.
- dependency는 직접 제약만 기록한다. 방어적·transitive blocker를 추가하지 않는다.
- 서로 독립인 leaf는 blocker 없이 두어 `ready_actions[]`에 함께 나타나게 한다.

## 실행

spec은 `definition_id`, `dispatch`, `delivery`, `root`, `children[]`를 갖는다. 새 정의에는 provider-specific `record`를 넣지 않는다. `dispatch: worker`는 local 실행, `dispatch: manual`은 ready graph만 제공하고 실행은 외부 담당자에게 남긴다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" create \
  --spec {SPEC} --store .task-worker/local/definitions
```

기존 revision을 바꿔야 하면 overwrite하지 않고 `revise --previous {ARTIFACT}`를 사용한다. 출력 artifact path와 digest를 다음 단계에 전달한다.

Wiki TASK나 provider ref로 다른 세션에서 재개해야 하면 provider API를 artifact에 섞지 말고 binding을 만든다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" bind \
  --artifact {ARTIFACT} --state-root .task-worker/local \
  --alias {TASK-ID} --provider wiki --provider-data {WIKI_BINDING_JSON} \
  --context {COMPACT_CONTEXT_JSON}
```
