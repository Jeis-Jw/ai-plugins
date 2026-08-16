---
name: init
description: 사용자가 현재 repository의 context-decision 초기화나 bootstrap을 명시적으로 요청했을 때 exact compatible context-core를 확인하고 필요한 core bootstrap과 decision area 등록을 한 번에 완료한다. 일반 decision capture 중에는 자동 실행하지 않는다.
---

# Init

먼저 context-core 설치와 `context-common/v1` compatibility를 확인한다. host가 exact plugin inventory, read-only doctor receipt, active installed core의 public `context_cli.py` 경로를 준비한다. host/skill catalog가 이 loaded `SKILL.md`의 actual absolute path를 제공하면, 그 파일의 sibling `scripts/decision_init.py`를 resolve해 orchestration entrypoint를 **한 번만** 호출한다. cwd, plugin cache 탐색 또는 `$CLAUDE_PLUGIN_ROOT`를 Codex 경로 fallback으로 사용하지 않는다.

```bash
INIT_SKILL_FILE="/absolute/path/from-loaded-skill-catalog/plugins/context-decision/skills/init/SKILL.md"
INIT_ENTRYPOINT="${INIT_SKILL_FILE%/SKILL.md}/scripts/decision_init.py"
python3 "$INIT_ENTRYPOINT" \
  --host <codex|claude-code> \
  --core-inventory @file \
  --core-doctor @file \
  --core-cli /absolute/active-installed/context-core/skills/context/scripts/context_cli.py \
  --json
```

Claude Code에서는 host가 제공한 plugin root를 알고 있을 때만 `INIT_SKILL_FILE="${CLAUDE_PLUGIN_ROOT}/skills/init/SKILL.md"`를 optional route로 사용할 수 있다. Codex에서는 반드시 loaded skill catalog의 absolute `SKILL.md` path를 사용한다.

- missing/source mismatch/disabled/incompatible이면 repository와 host configuration write 0으로 중단하고 exact marketplace/plugin/source와 수동 install/enable/update, reload·재시도 안내를 반환한다.
- partial/invalid이면 자동 repair하지 않고 issue/path와 수동 복구 안내를 반환한다.
- 이 entrypoint가 exact preflight를 먼저 실행하고, ready 또는 absent일 때만 fixed descriptor/index seed와 `--host`를 명시적으로 제공된 active installed core의 public `context_cli.py bootstrap --descriptor @file --index-seed @file --host <host> --json` surface에 그대로 전달한다. cache path를 추측하거나 core를 내장·복제하지 않는다.

core public bootstrap은 absent core seed, decision area, 현재 host 운영지침을 순서대로 맞춘다. 운영지침은 Codex의 `AGENTS.md` 또는 Claude Code의 `CLAUDE.md`에 marker로 경계된 단일 managed block으로 설치·갱신되며 marker 밖의 bytes를 보존한다. 세 단계는 `phases`에 `applied|noop|failed`로 보고하고 재시도하면 완료된 단계는 noop, 남은 단계만 적용된다. 이 명시적 init이 허용하는 write는 fixed core seed·area registration·policy installation뿐이며 DEC/user-content mutation은 exact digest approval을 계속 요구한다.
