---
name: review
description: Reviewer inspects a session-review target in audit or fast self-mode, writes approved or changes-requested feedback, and records it according to the chosen profile. Use when the user says "리뷰해", "n라운드 리뷰요청 왔어", "session-review 검토해".
---

# review

Reviewer 전용. 작업 산출물을 검토하고 `approved` 또는
`changes-requested`로 결정적 판정을 남긴다. 사용자의 정책 판단이나 완료
확인은 요청하지 않는다.

## 헬퍼 위치 (Claude Code · Codex 공통)

모든 연산은 이 플러그인의 `scripts/session_review.py`(이하 `SR`) **하나로** 한다.
wiki_cli를 직접 호출하지 않는다.

- 해석 순서: `SR="${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}"`.
  Codex 등 `$CLAUDE_PLUGIN_ROOT`가 없으면 이 스킬 로드 위치의 플러그인 루트 아래
  `scripts/session_review.py`로 `SR`(또는 `SESSION_REVIEW_CLI`)을 지정한다.
- 스냅샷 백엔드는 하이브리드(wiki 있으면 위임, 없으면 내장).

## 절차

1. snapshot 로드
   `recording_mode=fast` self-review면 snapshot이 없으므로 1~2단계를 생략하고 현재
   worker context의 target을 lease가 선택한 분리 reviewer가 바로 검토한다. 같은 agent가
   스스로 재검토하는 것은 session-review가 아니다.
   ```bash
   python3 "$SR" snapshot-load --slug <snapshot> --json
   ```
2. status/lock gate (slug만 주면 경로는 내부 해석)
   ```bash
   python3 "$SR" validate-turn --slug <snapshot> --actor reviewer --phase awaiting-review
   python3 "$SR" status --slug <snapshot>
   ```
   `phase`는 `awaiting-review`여야 한다. target이 없거나 모드가 불명확하면
   `blocked`로 넘기고 worker가 사용자에게 묻게 한다. `status` 출력의
   `effective_review_posture`와 `confirm_lock_check`를 기준으로 리뷰 렌즈를 고른다.
   전달된 lease decision이 `fresh`면 새 reviewer 세션이어야 하고, `reuse`면
   `reviewer_ref`와 현재 reviewer가 같아야 한다. 불일치하거나 reviewer를 다시 address할
   수 없으면 worker에게 `harness_unaddressable` fresh fallback을 요청한다.
3. 대상 검토
   - `target_mode=diff`: `git diff <base_ref>..HEAD`와 관련 테스트/문서를 본다.
   - `target_mode=document`: `target_ref` 문서를 정본으로 읽고 관계 문서를 필요한 만큼 확인한다.
   - `target_nature`는 `code|spec|direction|process|general`이다. document target에서
     `general`이면 성격 미확정 fallback으로 보고 과도한 checklist 적용을 피한다.
   - `round_type=confirm`이면 derived posture가 `verify`여도 별도 lock-check 경로를 따른다.
     - 이전 round의 agreed feedback이 반영됐는지 확인한다.
     - 남은 이견이 lock을 막는지 판단한다.
     - 새 scope를 넓히지 않는다.
     - `[blocking]`은 lock을 막는 미해결 쟁점에만 쓴다.
   - confirm이 아니면 `effective_review_posture`별 checklist를 따른다.
     - `verify`: acceptance criteria, 회귀, 증거 gap, 요구사항 누락.
     - `challenge`: 취약한 전제, 우선순위, edge case, 반려 대안 회귀.
     - `co-design`: 검증에 더해 대안, scope 절단, 추천 수렴안. 단 frame과 최종
       synthesis ownership은 worker에게 남긴다.
   - `review_strength`에 따라 깊이를 조정한다.
     - `fast`: critical/sanity 중심
     - `normal`: 정확성 + 주요 설계
     - `hard`: edge, 일관성, 반려 대안 회귀까지 적대적으로 확인
4. 피드백 작성
   - label은 `[blocking]`, `[should-reflect-before-implementation]`, `[directional]`,
     `[nice-to-have]`, `[nit]` 중 하나를 붙인다.
   - `[should-reflect-before-implementation]`은 구현 전 결정이 필요한 강한 권고지만
     approval과 양립 가능하다. `approved`는 `blocking_count=0`이지 "의견 없음"이
     아니다.
   - `hard`여도 순수 스타일 문제는 `[nit]`로 둔다.
   - **`[blocking]` 개수만 센다.** canonical feedback text의 digest와 실제 검토한
     commit/document ref를 각각 `finding_digest`, `reviewed_ref`에 함께 기록하고
     `lease_updated_at`을 갱신한다. 둘 중 하나만 기록하면 helper validation이 거부한다.
     reuse handoff도 이전 round evidence가 비워진 상태이므로 새 검토 결과를 반드시 기록한다.
   - 새 STATUS를 렌더한다: blocking 0이면
     `phase:"approved"`+`blocking_count:0`, 있으면 `phase:"changes-requested"`+
     `blocking_count:<n>`. 공통으로 `next_actor:"worker"`, `active_actor:"none"`,
     `lock_since:null`.
   ```bash
   STATUS=$(python3 "$SR" render --fenced --status-json '{...,"phase":"approved","next_actor":"worker","active_actor":"none","lock_since":null,"blocking_count":0}')
   ```
   `{...}`는 현재 status의 lease 필드 전체를 보존한다는 뜻이며 실제 JSON 문법이 아니다.
   - `--fenced`는 status를 ```yaml 펜스째 출력하므로 그대로 discussion에 넣는다.
   - 피드백은 `### 리뷰 피드백 (round N)` **하위 헤딩**으로 둬서 `## 현재 논의` 안에
     머물게 한다(sibling `## ...` 금지 — `--merge`가 discussion을 매 라운드 통째
     교체하므로 누적되지 않는다). `--merge`라 `--title/--summary/--tags`는 생략 가능:
   ```bash
   python3 "$SR" snapshot-save --slug <snapshot> --merge \
     --discussion "$(printf '%s\n\n### 리뷰 피드백 (round %s)\n%s\n' "$STATUS" "$ROUND" "$FEEDBACK")"
   ```
5. 일관성 검증 후 commit
   `recording_mode=fast` self-review면 snapshot 저장과 commit을 생략한다. 판정,
   blocking_count, 주요 finding, 갱신된 lease status JSON을 reviewer 응답으로 worker에게
   전달하고 worker가 바로 반영한다. 전달 전
   `python3 "$SR" validate-status --status-json '<status JSON>'`으로 판정 일관성을
   검증한다.
   ```bash
   python3 "$SR" validate-status --slug <snapshot>   # approved ⇒ blocking_count==0 강제
   git add wiki/snapshot
   git commit -m "review: feedback — <approved|changes-requested>, <요지>"
   ```

## 불변식

- 사용자에게 판단 질문이나 완료 확인을 직접 요청하지 않는다.
- fast self-review에서도 reviewer 분리는 유지한다. lease가 fresh면 새 reviewer,
  reuse면 addressable한 동일 reviewer를 쓴다. same-agent self-check는 금지다.
- 커밋 메시지 bare `review: feedback`는 금지다. 판정과 요지를 붙인다.
- status 정본은 snapshot status block이다. 커밋 마커는 handoff discovery용이다.
- `phase:"approved"`는 `blocking_count:0`과만 양립한다(`validate-status`가 강제).
- `review_posture=confirm`은 금지다. confirm은 `round_type=confirm`으로만 표현하고,
  lock-check behavior는 derived posture와 별도로 수행한다.
- co-design reviewer는 대안을 제안할 수 있지만, worker의 frame/synthesis ownership을
  가져오지 않는다.
