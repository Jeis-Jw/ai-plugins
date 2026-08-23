---
name: doctor
description: session-review의 snapshot provider 설정, provider root(vault/context), git worktree 준비 상태를 변경 없이 진단한다. "session-review:doctor", "리뷰 플러그인 진단해줘" 요청에 실행하라.
---

# doctor — review 환경 진단

현재 workspace의 review 준비 상태를 읽기 전용으로 확인한다.

```bash
python3 "${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}" doctor --json
```

다른 workspace/vault를 확인할 때:

```bash
python3 "${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}" doctor \
  --root /path/to/project --vault /path/to/project/wiki --json
```

진단 항목:

- snapshot provider: `.session-review.yml`(또는 `SESSION_REVIEW_SNAPSHOT_PROVIDER`)이
  정한 `builtin|wiki-markdown|context-core`, 선택 출처(env|config|default), 해석된 CLI 경로
- provider가 `builtin`이 아닌데 CLI를 못 찾으면 `backend.ready=false` + `error`
  (`snapshot-cli:` 또는 `SESSION_REVIEW_SNAPSHOT_CLI`로 지정)
- provider root: wiki vault(builtin/wiki-markdown)의 존재·생성 가능 여부, 또는
  context-core의 `context/snapshot/snapshot.index.md` 초기화 여부(미초기화면 `blocked`,
  `context_cli.py init` 필요)
- Git executable, worktree root, branch, HEAD, dirty 여부

## 불변식

- config, vault, snapshot, branch, git index를 만들거나 변경하지 않는다.
- builtin provider는 지원되는 정상 상태다. 외부 플러그인 미설치는 오류가 아니다 —
  설정으로 지목한 플러그인의 CLI가 없을 때만 오류다.
- `.session-review.yml`을 만들거나 고치지 않는다(사용자가 작성한다).
- review flow에 필요한 git worktree가 없거나 provider root를 사용할 수 없으면 nonzero로 종료한다.
