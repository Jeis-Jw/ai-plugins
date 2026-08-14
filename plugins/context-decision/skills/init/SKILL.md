---
name: init
description: exact compatible context-core를 확인하고 필요한 core bootstrap과 decision area 등록을 한 번에 완료한다.
---

# Init

먼저 context-core 설치와 `context-common/v1` compatibility를 확인한다. host가 exact plugin inventory, read-only doctor receipt, active installed core의 public `context_cli.py` 경로를 준비한 뒤 아래 orchestration entrypoint를 **한 번만** 호출한다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/init/scripts/decision_init.py" \
  --host <codex|claude-code> \
  --core-inventory @file \
  --core-doctor @file \
  --core-cli /absolute/active-installed/context-core/skills/context/scripts/context_cli.py \
  --json
```

- missing/source mismatch/disabled/incompatible이면 repository와 host configuration write 0으로 중단하고 exact marketplace/plugin/source와 수동 install/enable/update, reload·재시도 안내를 반환한다.
- partial/invalid이면 자동 repair하지 않고 issue/path와 수동 복구 안내를 반환한다.
- 이 entrypoint가 exact preflight를 먼저 실행하고, ready 또는 absent일 때만 fixed descriptor/index seed를 명시적으로 제공된 active installed core의 public `context_cli.py bootstrap --descriptor @file --index-seed @file --json` surface에 그대로 전달한다. cache path를 추측하거나 core를 내장·복제하지 않는다.

core public bootstrap은 absent core seed를 먼저 적용한 뒤 decision area를 등록한다. 두 단계는 `phases`에 `applied|noop|failed`로 보고하며, 중간 실패 뒤 같은 `$context-decision:init`을 재시도하면 완료된 단계는 noop, 남은 단계만 적용된다. 이미 둘 다 ready이면 모두 noop이다. 이 명시적 init의 fixed seed 외 DEC/user-content mutation은 exact digest approval을 계속 요구한다. agent policy는 별도 명시 요청 없이는 설치하지 않는다.
