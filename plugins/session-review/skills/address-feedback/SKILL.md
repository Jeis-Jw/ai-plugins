---
name: address-feedback
description: Worker addresses reviewer feedback in a session-review loop, using snapshot gates for audit mode or context-only handoff for fast self-mode. Use when the user says "피드백 왔어", "review feedback 반영해", "재리뷰 요청해".
---

# address-feedback

Worker 전용. reviewer의 `changes-requested` 피드백을 처리하고 다시
`awaiting-review`로 넘긴다.

## 헬퍼 위치 (Claude Code · Codex 공통)

모든 연산은 이 플러그인의 `scripts/session_review.py`(이하 `SR`) **하나로** 한다.
해석 순서: `SR="${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}"`.
Codex 등 `$CLAUDE_PLUGIN_ROOT`가 없으면 이 스킬 로드 위치의 플러그인 루트 아래
`scripts/session_review.py`로 `SR`(또는 `SESSION_REVIEW_CLI`)을 지정한다. 백엔드는
하이브리드(wiki 있으면 위임, 없으면 내장).

## 절차

1. snapshot 로드
   `recording_mode=fast` self-review면 snapshot이 없으므로 1~2단계를 생략하고 현재
   context의 reviewer feedback을 바로 처리한다.
   ```bash
   python3 "$SR" snapshot-load --slug <snapshot> --json
   ```
2. status/lock gate
   ```bash
   python3 "$SR" validate-turn --slug <snapshot> --actor worker --phase changes-requested
   ```
   `phase`는 `changes-requested`여야 한다. `active_actor`가 reviewer면 중단한다.
3. 피드백 처리
   - blocking 항목은 수용 또는 근거 있는 반박으로 처리한다.
   - `[should-reflect-before-implementation]` 항목은 구현 전 소실되면 안 되는 권고다.
     각 항목을 `accepted`, `deferred`, `rejected-with-rationale` 중 하나로 정리해
     snapshot의 `정해진 것` 또는 `열린 질문`에 남긴다.
   - `[directional]`, `[nice-to-have]`, `[nit]`은 스코프 안에서만 처리하고,
     미처리 항목은 이유를 snapshot에 남긴다.
   - target이 `diff`면 리뷰브랜치에서 수정 커밋을 만든다. `document`면 해당 문서를 수정한다.
4. status 갱신 — `set-status`로 status block만 제자리 교체(나머지 섹션 보존)
   - `phase:"awaiting-review"`, `active_actor:"none"`, `lock_since:null`,
     `next_actor:"reviewer"`, `responding_to:<직전 review:feedback SHA>`, `round`:+1,
     `blocking_count:0`(재요청 시 리셋).
   - 라운드 목적이 바뀌면 `round_type`을 갱신한다. 예: 아이디어 확장 후 수렴은
     `explore -> converge`, 마지막 확인은 `confirm`.
   ```bash
   python3 "$SR" set-status --slug <snapshot> \
     --status-json '{"phase":"awaiting-review","active_actor":"none","lock_since":null,"next_actor":"reviewer","target_mode":"diff","target_nature":"code","target_ref":"<ref>","base_ref":"<BASE>","responding_to":"<FEEDBACK_SHA>","round":<n+1>,"round_type":"converge","flow_mode":"<self|separate>","review_strength":"<...>","blocking_count":0}'
   ```
   미처리 반박은 `snapshot-save --merge --decided`/`--open-questions`로 남긴다.
5. 커밋
   `recording_mode=fast` self-review면 라운드별 커밋을 생략한다. 최종 complete
   커밋에 resolved findings와 검증 결과를 남긴다.
   ```bash
   git add <target files> wiki/snapshot
   git commit -m "review: request — feedback 반영 후 재검토 요청"
   ```

## 불변식

- owner가 worker가 아니면 처리하지 않는다.
- 피드백을 맹목 수용하지 않는다. 반박은 snapshot의 `정해진 것` 또는 `열린 질문`에 남긴다.
- `[should-reflect-before-implementation]`은 accepted/deferred/rejected-with-rationale 중
  하나로 정리한다. deferred는 complete/handoff에서 이월 대상이다.
- status block 외 자유문을 상태 정본으로 삼지 않는다.
