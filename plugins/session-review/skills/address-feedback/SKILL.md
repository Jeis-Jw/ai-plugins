---
name: address-feedback
description: Worker addresses reviewer feedback in a session-review loop, enforcing snapshot phase and lock before editing, then re-requests review. Use when the user says "피드백 왔어", "review feedback 반영해", "재리뷰 요청해".
---

# address-feedback

Worker 전용. reviewer의 `changes-requested` 피드백을 처리하고 다시
`awaiting-review`로 넘긴다.

## 절차

1. snapshot 로드
   ```bash
   python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py snapshot load <snapshot> --json
   ```
2. status/lock gate
   ```bash
   python3 plugins/session-review/scripts/session_review.py validate-turn \
     --file <loaded-snapshot-path> --actor worker --phase changes-requested
   ```
   `phase`는 `changes-requested`여야 한다. `active_actor`가 reviewer면 중단한다.
3. 피드백 처리
   - blocking 항목은 수용 또는 근거 있는 반박으로 처리한다.
   - nit/non-blocking은 스코프 안에서만 처리하고, 미처리 항목은 이유를 snapshot에 남긴다.
   - target이 `diff`면 리뷰브랜치에서 수정 커밋을 만든다. `document`면 해당 문서를 수정한다.
4. status 갱신
   - `phase: "awaiting-review"`
   - `active_actor: "none"`
   - `lock_since: null`
   - `next_actor: "reviewer"`
   - `responding_to`: 직전 `review: feedback` 커밋 SHA
   - `round`: +1
5. wiki snapshot save로 같은 slug를 갱신하고 commit
   ```bash
   git add <target files> wiki/snapshot
   git commit -m "review: request — feedback 반영 후 재검토 요청"
   ```

## 불변식

- owner가 worker가 아니면 처리하지 않는다.
- 피드백을 맹목 수용하지 않는다. 반박은 snapshot의 `정해진 것` 또는 `열린 질문`에 남긴다.
- status block 외 자유문을 상태 정본으로 삼지 않는다.
