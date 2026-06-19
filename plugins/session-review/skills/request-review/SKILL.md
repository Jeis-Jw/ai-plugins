---
name: request-review
description: Worker starts or resumes a session-review loop by forking a review branch, choosing flow mode and review strength, and saving the handshake through wiki snapshot. Use when the user says "리뷰 요청해", "session-review 시작", "이 작업 리뷰브랜치로 넘겨".
---

# request-review

Worker 전용. 리뷰 루프를 시작하거나 재요청한다. 핸드셰이크는 snapshot으로
다루고, 별도 파일포맷이나 전용 handoff 디렉터리를 만들지 않는다.

## 헬퍼 위치 (Claude Code · Codex 공통)

모든 연산은 이 플러그인의 `scripts/session_review.py`(이하 `SR`) **하나로** 한다.
wiki_cli를 직접 호출하지 않는다.

- 해석 순서: `SR="${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}"`.
  - `SESSION_REVIEW_CLI`(명시 경로)가 있으면 그것, 없으면 Claude Code의
    `$CLAUDE_PLUGIN_ROOT/scripts/session_review.py`.
  - Codex 등 `$CLAUDE_PLUGIN_ROOT`가 없는 하니스: 이 스킬이 로드된 위치의 플러그인
    루트 아래 `scripts/session_review.py` 경로로 `SR`(또는 `SESSION_REVIEW_CLI`)을 지정한다.
- 스냅샷 백엔드는 하이브리드: wiki-markdown이 있으면 자동 위임, 없으면 내장
  fallback(동일 포맷)으로 동작. `SESSION_REVIEW_WIKI_CLI`로 위치 지정/비활성.

## 입력

```
$ARGUMENTS:
  --target-mode diff|document
  --target-ref <branch-or-file>
  --flow-mode self|separate        # 기본: separate; 서브에이전트 가능하면 self 선택 가능
  --review-strength fast|normal|hard # 기본: normal
  --snapshot <slug>                # 기본: session-review-<target slug>
```

## 절차

1. 대상 확정
   - `target_mode=diff`: 현재 작업브랜치의 `HEAD`를 `base_ref`로 기록하고
     `<current>-review` 형태의 리뷰브랜치를 만든다.
   - `target_mode=document`: 대상 문서 경로를 `target_ref`로 기록한다.
   - 대상/모드가 불명확하면 추론하지 말고 중단한다.
2. 리뷰브랜치 생성
   ```bash
   git status --short
   BASE=$(git rev-parse HEAD)
   CURRENT=$(git branch --show-current)
   REVIEW="${CURRENT}-review"
   git switch -c "$REVIEW"
   ```
   이미 리뷰브랜치가 있으면 `python3 "$SR" snapshot-load --slug <snapshot>` 후
   status block을 읽어 `base_ref`와 `target_ref`가 같은지 확인한다.
3. status block 생성
   - `phase: "awaiting-review"`
   - `active_actor: "none"`
   - `lock_since: null`
   - `next_actor: "reviewer"`
   - `target_mode`, `target_ref`, `base_ref`, `responding_to`, `flow_mode`,
     `review_strength`는 모두 quoted string으로 저장한다.
   - `round`만 integer다.
   `blocking_count: 0`을 포함한다(초기엔 0). helper로 렌더링한다:
   ```bash
   STATUS=$(python3 "$SR" render \
     --status-json '{"phase":"awaiting-review","active_actor":"none","lock_since":null,"next_actor":"reviewer","target_mode":"diff","target_ref":"task/issue-10-review","base_ref":"<BASE>","responding_to":"<BASE>","round":1,"flow_mode":"separate","review_strength":"normal","blocking_count":0}')
   ```
4. snapshot 저장 (facade — 백엔드 자동 선택)
   ```bash
   python3 "$SR" snapshot-save \
     --slug "$SNAPSHOT" \
     --title "session-review: $target_ref" \
     --summary "Review handoff for $target_ref" \
     --tags session-review,review \
     --discussion "$(printf '```yaml\n%s\n```\n\n%s\n' "$STATUS" "$REQUEST")" \
     --background "target_mode=$target_mode, target_ref=$target_ref, base_ref=$BASE, review_branch=$REVIEW" \
     --next "reviewer가 snapshot-load 후 review skill을 실행한다." \
     --references "$target_ref"
   ```
5. 핸드오프 커밋
   ```bash
   git add wiki/snapshot
   git commit -m "review: request — <무엇을 왜 봐달라는지>"
   ```

## self / separate

- `separate`: 사용자 운영 릴레이를 전제로 독립 reviewer 세션이 `review`를 실행한다.
- `self`: 작업자가 핸드셰이크 저장 직후 **fresh 서브에이전트 reviewer**를 띄워
  `review` 스킬을 실행시킨다(독립 세션 릴레이 대신). snapshot, review branch,
  status block, 완료 게이트는 separate와 동일하다.

## 불변식

- status 정본은 snapshot body의 `## 현재 논의` 첫 fenced `yaml` block이다.
- `review: request`는 discovery marker일 뿐 상태 정본이 아니다.
- 완료는 여기서 수행하지 않는다. `complete`가 reviewer approval과 사용자 확인을 gate 한다.
