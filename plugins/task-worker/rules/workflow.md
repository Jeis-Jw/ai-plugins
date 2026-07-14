# task-worker workflow

## 실행 단위

- container node는 실행하지 않는다.
- direct dependency가 닫힌 leaf만 ready다.
- `ready_actions[]`는 순서가 아니라 집합이다. write-set이나 resource lock이 겹치지 않으면 동시에 실행한다.
- 동시에 실행되는 leaf마다 별도 worktree와 branch를 사용한다.
- plugin 위임만으로 새 agent나 clean session을 추가하지 않는다.

## 검증 단위

- leaf: 변경 범위의 test/typecheck/diff와 완료 조건
- parent/integration: 병합으로 새로 생긴 interface와 통합 상태
- finding 수정: 무효화된 scope만 delta 검증
- 독립 검토가 명시된 edge: caller가 선택한 reviewer provider 사용

동일 physical command를 줄이기 위해 논리 node를 합치거나 integration gate를 생략하지 않는다.

## portable script path

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" --help
```
