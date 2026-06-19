---
name: request-review
description: Worker starts or resumes a session-review loop by forking a review branch, choosing flow mode and review strength, and saving the handshake through wiki snapshot. Use when the user says "리뷰 요청해", "session-review 시작", "이 작업 리뷰브랜치로 넘겨".
---

# request-review

Worker 전용. 리뷰 루프를 시작하거나 재요청한다. 핸드셰이크는 반드시
`wiki snapshot save/load`로 다루고, 별도 파일포맷이나 전용 handoff
디렉터리를 만들지 않는다.

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
   이미 리뷰브랜치가 있으면 `wiki snapshot load <snapshot>` 후 status block을
   읽어 `base_ref`와 `target_ref`가 같은지 확인한다.
3. status block 생성
   - `phase: "awaiting-review"`
   - `active_actor: "none"`
   - `lock_since: null`
   - `next_actor: "reviewer"`
   - `target_mode`, `target_ref`, `base_ref`, `responding_to`, `flow_mode`,
     `review_strength`는 모두 quoted string으로 저장한다.
   - `round`만 integer다.
   helper로 렌더링한다:
   ```bash
   python3 plugins/session-review/scripts/session_review.py render \
     --status-json '{"phase":"awaiting-review","active_actor":"none","lock_since":null,"next_actor":"reviewer","target_mode":"diff","target_ref":"task/issue-10-review","base_ref":"<BASE>","responding_to":"<BASE>","round":1,"flow_mode":"separate","review_strength":"normal"}'
   ```
4. wiki snapshot 저장
   ```bash
   python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py snapshot save \
     --slug "$SNAPSHOT" \
     --title "session-review: $target_ref" \
     --summary "Review handoff for $target_ref" \
     --tags session-review,review \
     --discussion "$(printf '```yaml\n%s```\n\n%s\n' "$STATUS" "$REQUEST")" \
     --background "target_mode=$target_mode, target_ref=$target_ref, base_ref=$BASE, review_branch=$REVIEW" \
     --next-steps "reviewer가 snapshot load 후 review skill을 실행한다." \
     --references "$target_ref"
   ```
5. 핸드오프 커밋
   ```bash
   git add wiki/snapshot
   git commit -m "review: request — <무엇을 왜 봐달라는지>"
   ```

## self / separate

- `separate`: 사용자 운영 릴레이를 전제로 독립 reviewer 세션이 `review`를 실행한다.
- `self`: 작업자가 fresh subagent reviewer를 띄울 수 있을 때만 사용한다. 그래도
  snapshot, review branch, status block, 완료 게이트는 동일하다.

## 불변식

- status 정본은 snapshot body의 `## 현재 논의` 첫 fenced `yaml` block이다.
- `review: request`는 discovery marker일 뿐 상태 정본이 아니다.
- 완료는 여기서 수행하지 않는다. `complete`가 reviewer approval과 사용자 확인을 gate 한다.
