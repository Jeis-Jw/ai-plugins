---
name: doctor
description: task-worker config, local state, command profile, impact rule의 실행 준비 상태를 읽기 전용으로 진단한다. "task-worker:doctor", "worker 설정 검사해줘" 요청에 사용한다.
---

# doctor

consumer workspace의 task-worker 준비 상태를 변경 없이 진단한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" doctor \
  --root {WORKSPACE} [--json]
```

검사 항목:

- `.task-worker.yml` parse와 provider-neutral schema validation
- `state-root` 디렉터리 존재 여부
- 선택한 command profile/impact rule 파일의 존재와 canonical loader 통과 여부
- init이 만든 TODO policy인지, 실제 실행 가능한 policy인지

종료 코드는 다음 의미다.

- `0`: 실행 준비 완료 또는 `minimal`에서 command policy를 명시적으로 사용하지 않음
- `1`: config는 정상이나 TODO policy를 프로젝트 명령으로 채워야 함
- `2`: config/state/policy가 없거나 잘못됨

doctor는 GitHub·Wiki·Studio·reviewer provider를 호출하거나 수정하지 않는다. TODO는 약한 기본 명령으로 대체하지 않고 `ready=false`로 보고한다.
