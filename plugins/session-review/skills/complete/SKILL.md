---
name: complete
description: Worker completes an approved session-review loop, respecting self-mode automation profile, then lands review changes and removes transient snapshot state. Use when the user says "완료해", "리뷰 승인됐으니 합쳐", "session-review 마무리".
---

# complete

Worker 전용. `approved`는 완료가 아니다. 현재 세션에서 사용자의 명시적
확인이 있어야 squash merge와 snapshot discard를 진행한다. 단,
`flow_mode=self`, `self_automation=turnkey`로 시작한 fast self-review는 최초
요청이 complete 승인까지 포함한 것으로 보고 추가 확인 없이 완료할 수 있다.

## 헬퍼 위치 (Claude Code · Codex 공통)

모든 연산은 이 플러그인의 `scripts/session_review.py`(이하 `SR`) **하나로** 한다.
해석 순서: `SR="${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}"`.
Codex 등 `$CLAUDE_PLUGIN_ROOT`가 없으면 이 스킬 로드 위치의 플러그인 루트 아래
`scripts/session_review.py`로 `SR`(또는 `SESSION_REVIEW_CLI`)을 지정한다. 백엔드는
하이브리드(wiki 있으면 위임, 없으면 내장).

## 절차

1. snapshot 로드 및 gate
   ```bash
   python3 "$SR" snapshot-load --slug <snapshot> --json
   python3 "$SR" validate-complete --slug <snapshot> --user-confirmed
   ```
   사용자의 명시적 확인이 없으면 `--user-confirmed`를 주지 말고 중단한다.
   `self_automation=turnkey` status는 `--user-confirmed` 없이 통과할 수 있다.
2. worker 브리핑 확인
   - reviewer가 지적한 쟁점
   - worker가 해결/반박한 방식
   - 최종 판정과 남은 `[directional]`, `[nice-to-have]`, `[nit]`
   - 최신 approved feedback과 worker synthesis의 미해결
     `[should-reflect-before-implementation]`
   - 승격할 wiki decision/observation/trial_error 후보 또는 `none`
   - 다음 구현 task/issue/wiki task로 넘길 carryover checklist. 이어지는 구현이 없으면
     `implementation carryover 없음`을 명시해 누락과 의도적 종료를 구분한다.
   첫 구현 단계에서는 should-reflect를 CLI가 자동 파싱한다고 가정하지 않는다. worker가
   최신 approved feedback과 synthesis를 직접 확인해 final briefing에 포함한다.
3. 머지 전 확인
   ```bash
   git status --short
   git branch --show-current
   git merge-base --is-ancestor <base_ref> HEAD
   ```
   working tree가 더럽거나 base 추적이 안 되면 중단한다.
4. squash merge + snapshot discard 단일 커밋
   ```bash
    REVIEW=$(git branch --show-current)
    WORKER=<worker-branch>
    git switch "$WORKER"
    git merge --squash "$REVIEW"
    python3 "$SR" snapshot-discard --slug <snapshot>
    git add wiki/snapshot
    git commit -m "review: complete — <리뷰 결과 요약>"
    git branch -d "$REVIEW"
   ```
   commit message에는 snapshot slug, round 수, resolved blocking 요약, 남은
   `[directional]`/`[nice-to-have]`/`[nit]` 요약을 포함한다.
5. fast self-review 완료
   `recording_mode=fast`는 snapshot/review branch가 없으므로 squash/discard를 하지 않는다.
   단, reviewer는 반드시 fresh subagent여야 한다. 현재 작업트리에 최종 변경만 남긴 뒤
   `review: complete — ...` 단일 커밋에 subagent verdict, blocking_count, resolved
   findings, 검증 결과를 포함한다.

## 불변식

- `phase`는 `approved` 또는 `awaiting-user-confirmation`이어야 한다.
- `approved`는 `blocking_count=0`만 뜻한다. co-design/challenge review의 강한 권고가
  사라졌다는 뜻이 아니다.
- 완료 gate는 `blocking_count` 누락이나 0이 아닌 값을 거부한다.
- 현재 세션에 사용자 명시 확인이 없으면 squash merge 금지다. 단, self turnkey는 예외다.
- self turnkey도 same-agent self-check로 완료할 수 없다. fresh reviewer subagent의
  `approved`와 `blocking_count:0`이 필요하다.
- 완료 후 장기 상태는 complete commit, 필요한 wiki 승격 기록, git history에 남기고 snapshot은 버린다.
