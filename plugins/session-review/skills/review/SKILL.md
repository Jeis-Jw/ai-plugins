---
name: review
description: Reviewer inspects a session-review snapshot and target, writes approved or changes-requested feedback, and commits the handoff. Use when the user says "리뷰해", "n라운드 리뷰요청 왔어", "session-review 검토해".
---

# review

Reviewer 전용. 작업 산출물을 검토하고 `approved` 또는
`changes-requested`로 결정적 판정을 남긴다. 사용자의 정책 판단이나 완료
확인은 요청하지 않는다.

## 절차

1. snapshot 로드
   ```bash
   python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py snapshot load <snapshot> --json
   ```
2. status/lock gate
   ```bash
   python3 plugins/session-review/scripts/session_review.py validate-turn \
     --file <loaded-snapshot-path> --actor reviewer --phase awaiting-review
   ```
   `phase`는 `awaiting-review`여야 한다. target이 없거나 모드가 불명확하면
   `blocked`로 넘기고 worker가 사용자에게 묻게 한다.
3. 대상 검토
   - `target_mode=diff`: `git diff <base_ref>..HEAD`와 관련 테스트/문서를 본다.
   - `target_mode=document`: `target_ref` 문서를 정본으로 읽고 관계 문서를 필요한 만큼 확인한다.
   - `review_strength`에 따라 깊이를 조정한다.
     - `fast`: critical/sanity 중심
     - `normal`: 정확성 + 주요 설계
     - `hard`: edge, 일관성, 반려 대안 회귀까지 적대적으로 확인
4. 피드백 작성
   - severity는 `blocking` / `non-blocking` / `nit` 중 하나를 붙인다.
   - `hard`여도 순수 스타일 nit은 nit로 둔다.
   - blocking 0이면 `phase: "approved"`, 있으면 `phase: "changes-requested"`.
   - `next_actor: "worker"`, `active_actor: "none"`, `lock_since: null`.
5. 같은 snapshot slug를 `wiki snapshot save`로 갱신하고 commit
   ```bash
   git add wiki/snapshot
   git commit -m "review: feedback — <approved|changes-requested>, <요지>"
   ```

## 불변식

- 사용자에게 판단 질문이나 완료 확인을 직접 요청하지 않는다.
- 커밋 메시지 bare `review: feedback`는 금지다. 판정과 요지를 붙인다.
- status 정본은 snapshot status block이다. 커밋 마커는 handoff discovery용이다.
