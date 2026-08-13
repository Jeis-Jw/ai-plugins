---
name: init
description: context-core index를 preview하고 선택적으로 repository-root agent policy marker를 설치한다.
---

# Init

`context_cli.py init --json`은 complete core-init bundle만 만든다. 사용자가 exact digest를 승인하기 전에는 적용하지 않는다.

agent policy는 repository root의 `AGENTS.md` 또는 `CLAUDE.md`만 허용한다. 기존 파일의 managed marker 밖 byte는 그대로 보존하고, marker가 깨졌거나 중복됐거나 target이 symlink·nested path이면 중단한다. policy preview도 자동 적용하지 않으며 exact approval 뒤 context-core `transaction apply`만 사용한다.
