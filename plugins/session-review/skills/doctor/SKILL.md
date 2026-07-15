---
name: doctor
description: session-review의 backend resolver, wiki vault, git worktree 준비 상태를 변경 없이 진단한다. "session-review:doctor", "리뷰 플러그인 진단해줘" 요청에 실행하라.
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

- snapshot backend: `wiki-markdown` CLI 또는 built-in fallback
- `SESSION_REVIEW_WIKI_CLI` override 유효성
- wiki vault의 존재·생성 가능 여부와 snapshot 경로
- Git executable, worktree root, branch, HEAD, dirty 여부

## 불변식

- config, vault, snapshot, branch, git index를 만들거나 변경하지 않는다.
- built-in snapshot backend는 지원되는 정상 상태다. wiki-markdown 미설치는 오류가 아니다.
- session-review 전용 persistent config를 만들지 않는다.
- review flow에 필요한 git worktree가 없거나 vault를 사용할 수 없으면 nonzero로 종료한다.
