---
name: complete
description: Worker completes an approved session-review loop only after briefing the user and receiving explicit confirmation, then squash-merges the review branch and discards the wiki snapshot. Use when the user says "완료해", "리뷰 승인됐으니 합쳐", "session-review 마무리".
---

# complete

Worker 전용. `approved`는 완료가 아니다. 현재 세션에서 사용자의 명시적
확인이 있어야 squash merge와 snapshot discard를 진행한다.

## 절차

1. snapshot 로드 및 gate
   ```bash
   python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py snapshot load <snapshot> --json
   python3 plugins/session-review/scripts/session_review.py validate-complete \
     --file <loaded-snapshot-path> --user-confirmed
   ```
   사용자의 명시적 확인이 없으면 `--user-confirmed`를 주지 말고 중단한다.
2. worker 브리핑 확인
   - reviewer가 지적한 쟁점
   - worker가 해결/반박한 방식
   - 최종 판정과 남은 non-blocking/nit
   - 승격할 wiki decision/observation/trial_error 후보 또는 `none`
3. 머지 전 확인
   ```bash
   git status --short
   git branch --show-current
   git merge-base --is-ancestor <base_ref> HEAD
   ```
   working tree가 더럽거나 base 추적이 안 되면 중단한다.
4. squash merge
   ```bash
   REVIEW=$(git branch --show-current)
   WORKER=<worker-branch>
   git switch "$WORKER"
   git merge --squash "$REVIEW"
   git commit -m "review: complete — <리뷰 결과 요약>"
   git branch -d "$REVIEW"
   ```
5. 핸드셰이크 discard
   ```bash
   python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py snapshot discard <snapshot>
   git add wiki/snapshot
   git commit -m "review: discard handshake — <snapshot>"
   ```

## 불변식

- `phase`는 `approved` 또는 `awaiting-user-confirmation`이어야 한다.
- 현재 세션에 사용자 명시 확인이 없으면 squash merge 금지다.
- 완료 후 장기 상태는 squash commit, 필요한 wiki 승격 기록, git history에 남기고 snapshot은 버린다.
