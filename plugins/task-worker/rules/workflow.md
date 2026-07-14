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

## review lease

review가 필요한 edge만 exact `workflow-review-lease/v1`을 binding의 `review_leases[]`에 둔다. 리뷰가 없으면 lease도 없다. lease owner는 `studio|task-worker`, provider는 `native|session-review`, requirement는 `self|independent`다. 같은 `lease_id` 또는 `edge_id`에 다른 내용이 들어오면 fail-closed한다.

모든 reviewer dispatch 전에 `review-permit`을 조회한다. `owner=studio`는 `externally-owned/skip`, `owner=task-worker`나 lease 없음은 기존 local review policy다. 이 계약은 reviewer 중복 소집만 막으며 run/verify/done/integration gate를 줄이지 않는다.

동일 physical command를 줄이기 위해 논리 node를 합치거나 integration gate를 생략하지 않는다.

## portable script path

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" --help
```
