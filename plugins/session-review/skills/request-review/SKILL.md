---
name: request-review
description: Worker starts or resumes a session-review loop, choosing separate/self flow and self-mode automation/recording profile. Use when the user says "리뷰 요청해", "session-review 시작", "이 작업 리뷰브랜치로 넘겨".
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
  --target-nature code|spec|direction|process|general # diff 기본 code; document는 명시 요구
  --round-type explore|converge|confirm|review        # 기본: review
  --review-posture verify|challenge|co-design         # optional override only
  --flow-mode self|separate        # 기본: separate; 서브에이전트 가능하면 self 선택 가능
  --self-automation manual|auto-rounds|turnkey # self 전용; 기본 manual
  --recording-mode audit|fast      # 기본 audit; self+turnkey는 fast 강제
  --review-strength fast|normal|hard # 기본: normal
  --snapshot <slug>                # 기본: session-review-<target slug>
```

## 절차

1. 대상 및 profile 확정
   - `target_mode=diff`: 현재 작업브랜치의 `HEAD`를 `base_ref`로 기록한다.
     `target_nature` 기본값은 `code`.
   - `target_mode=document`: 대상 문서 경로를 `target_ref`로 기록한다. 이때
     `target_nature`를 worker/user에게 명시하게 한다. 불명확하면 `general` fallback을
     쓰되, `general`은 편한 기본값이 아니라 성격 미확정 표시다.
   - 대상/모드가 불명확하면 추론하지 말고 중단한다.
   - `round_type`은 라운드 목적이다: `explore`(아이디어 확장),
     `converge`(쟁점 축소), `confirm`(lock 확인), `review`(일반 리뷰).
   - `review_posture`는 필수가 아니다. helper가 `target_nature + round_type`으로
     `effective_review_posture`를 계산한다. override가 필요할 때만
     `verify|challenge|co-design` 중 하나를 쓴다. `confirm`은 posture가 아니라
     `round_type`으로만 표현한다.
   - `flow_mode=separate`는 항상 `recording_mode=audit`이다.
   - `flow_mode=self` 기본은 `self_automation=manual`, `recording_mode=audit`이다.
   - `self_automation=auto-rounds`는 리뷰/수정 라운드만 자동 진행하고, complete는
     사용자 승인을 기다린다.
   - `self_automation=turnkey`는 complete까지 자동 진행하며 `recording_mode=fast`만 허용한다.
   - `recording_mode=fast`는 self 전용이다. snapshot/review branch/round commit만
     생략하고, reviewer 분리는 유지한다.
2. 리뷰브랜치 생성
   `recording_mode=fast`면 이 단계와 4~5단계를 생략한다.
   audit mode에서는 `<current>-review` 형태의 리뷰브랜치를 만든다.
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
     `review_strength`, `target_nature`, `round_type`, optional `review_posture`,
     self일 때 `self_automation`, `recording_mode`는 모두 quoted string으로 저장한다.
   - `round`만 integer다.
   `blocking_count: 0`을 포함한다(초기엔 0). `--fenced`로 ```yaml 펜스째 렌더한다:
   ```bash
   STATUS=$(python3 "$SR" render --fenced \
     --status-json '{"phase":"awaiting-review","active_actor":"none","lock_since":null,"next_actor":"reviewer","target_mode":"diff","target_nature":"code","target_ref":"task/issue-10-review","base_ref":"<BASE>","responding_to":"<BASE>","round":1,"round_type":"review","flow_mode":"self","self_automation":"auto-rounds","recording_mode":"audit","review_strength":"normal","blocking_count":0}')
   ```
   상태를 확인하면 helper가 파생값을 함께 보여준다.
   ```bash
   python3 "$SR" status --slug "$SNAPSHOT"
   ```
4. snapshot 저장 (facade — 백엔드 자동 선택)
   ```bash
   python3 "$SR" snapshot-save \
     --slug "$SNAPSHOT" \
     --title "session-review: $target_ref" \
     --summary "Review handoff for $target_ref" \
     --tags session-review,review \
     --discussion "$(printf '%s\n\n%s\n' "$STATUS" "$REQUEST")" \
     --background "target_mode=$target_mode, target_ref=$target_ref, base_ref=$BASE, review_branch=$REVIEW" \
     --next "reviewer가 snapshot-load 후 review skill을 실행한다." \
     --references "$target_ref"
   ```
   `effective_review_posture`가 `co-design` 또는 `challenge`인 요청에는 다음 계약을
   요청문에 노출한다: approved는 `blocking_count=0`이지 "의견 없음"이 아니다.
   승인 feedback에도 `[should-reflect-before-implementation]`, `[directional]`,
   `[nice-to-have]`, `[nit]`가 남을 수 있다.
5. 핸드오프 커밋
   ```bash
   git add wiki/snapshot
   git commit -m "review: request — <무엇을 왜 봐달라는지>"
   ```

## self / separate

- `separate`: 사용자 운영 릴레이를 전제로 독립 reviewer 세션이 `review`를 실행한다.
- `self`: 작업자가 핸드셰이크 저장 직후 **fresh 서브에이전트 reviewer**를 띄워
  `review` 스킬을 실행시킨다(독립 세션 릴레이 대신).
- `self + audit`: snapshot, review branch, status block, round commit을 유지한다.
- `self + fast`: snapshot, review branch, round commit을 생략하지만 **fresh reviewer
  subagent는 필수**다. same-agent self-check는 session-review가 아니다. 최종 commit
  message에 subagent verdict, resolved findings, test 요약을 남긴다.

## 불변식

- status 정본은 snapshot body의 `## 현재 논의` 첫 fenced `yaml` block이다.
- `review: request`는 discovery marker일 뿐 상태 정본이 아니다.
- 완료는 여기서 수행하지 않는다. `complete`가 reviewer approval과 사용자 확인을 gate 한다.
