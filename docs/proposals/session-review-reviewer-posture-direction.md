# session-review reviewer posture 개선 방향 — 최종 수렴안

- **대상**: session-review 0.2.1
- **작성자**: Codex (worker)
- **상태**: session-review 3라운드 리뷰 수렴 완료
- **목적**: 코드 검증 리뷰와 아이디어/방향 수렴 리뷰를 같은 프로토콜에서 다루되, reviewer 역할을 더 정확히 지정해 불필요한 steering과 라운드 낭비를 줄인다.

---

## 0. 배경

최근 `wiki-markdown` 개선 방향을 Claude(worker)와 Codex(reviewer)가 3라운드로 수렴했다. 프로토콜 자체는 잘 작동했다. snapshot status block, review branch, `approved`/`changes-requested`, `review_strength=hard`는 충분히 안정적이었다.

다만 라운드 초반에 사용자 steering이 한 번 필요했다.

> 이건 방향을 고도화하는 일이니, 검증만 하지 말고 의견도 적극적으로 내면 좋겠다.

이 말은 현재 session-review의 빈틈을 드러낸다. 지금 프로토콜은 reviewer의 **검토 깊이**(`review_strength`)는 표현하지만, reviewer의 **참여 태도**와 **라운드 목적**은 충분히 표현하지 않는다. 코드 diff 검증과 아이디어 수렴은 둘 다 review지만, reviewer가 해야 할 일은 다르다.

reviewer feedback의 핵심은 타당했다. `target_nature`, `round_type`, `review_posture`를 모두 독립 입력으로 두면 조합 폭이 불필요하게 커진다. 이 문서는 그 피드백을 반영해 `target_nature + round_type`을 주 입력으로 두고, reviewer posture는 파생값과 override로 낮춘다.

---

## 1. 문제

### 1.1 `review_strength`가 너무 많은 의미를 떠안는다

현재 `fast|normal|hard`는 깊이와 blocking bar를 조절한다. 그러나 아래 질문에는 답하지 못한다.

- reviewer는 오류만 찾는가, 대안도 내야 하는가?
- 방향성 문서에서 reviewer는 co-designer인가, verifier인가?
- `approved`가 "의견 없음"인가, "blocking 없음"인가?
- confirmation 라운드에서 새 아이디어를 더 내야 하는가, lock 가능성만 봐야 하는가?

이번 케이스에서는 `hard`였지만 실제 기대는 `co-design`에 가까웠다.

### 1.2 3개 독립 축은 과하다

초안 round 1은 `target_nature`, `round_type`, `review_posture`를 모두 독립 선택 필드로 제안했다. 그러나 대부분의 `review_posture`는 앞의 두 값에서 자연스럽게 결정된다.

- `code + review/converge/confirm`이면 보통 `verify`
- `direction/process + explore`이면 보통 `co-design`
- `direction/process + converge`이면 보통 `challenge`
- `* + confirm`이면 새 아이디어보다 lock 가능성 확인이 우선

따라서 `review_posture`를 필수 입력으로 두면 "code diff에 co-design explore" 같은 낮은 가치 조합까지 공식 표면에 올린다.

### 1.3 feedback severity가 수렴 의도를 충분히 표현하지 못한다

현재 공식 severity는 `blocking` / `non-blocking` / `nit`에 가깝다. 방향 수렴에서는 `non-blocking` 안에 서로 다른 성격이 섞인다.

- 구현 전에 반영해야 하는 강한 권고
- 방향 품질을 높이는 제안
- 나중에 해도 되는 아이디어
- 단순 문구 수정

이 구분이 없으면 `approved`가 "다 끝났다"처럼 오해될 수 있다.

### 1.4 approved 이후 권고가 구현으로 이월되지 않을 수 있다

`approved + blocking_count=0`은 merge/complete gate에는 충분하다. 하지만 co-design 리뷰에서는 `[should-reflect-before-implementation]` 같은 강한 권고가 남을 수 있다. 이 항목이 complete 단계에서 구현 task, issue, wiki task, handoff로 이월되지 않으면 "승인됐으니 끝"으로 소실될 위험이 있다.

---

## 2. 원칙

1. **상태머신은 늘리지 않는다.** `phase`는 지금처럼 유지한다.
2. **기존 `review_strength`는 유지한다.** 깊이와 blocking bar의 축으로 남긴다.
3. **입력 축은 최소화한다.** primary input은 `target_nature`와 `round_type` 둘로 둔다.
4. **posture는 파생값이다.** `review_posture`는 기본 입력이 아니라 derived default이며, 필요할 때만 override한다.
5. **기계 검증 필드는 최소화한다.** status block은 handoff 안정성에 필요한 enum만 검증한다.
6. **아이디어 수렴 리뷰는 approved + 강한 non-blocking이 정상이다.** approved는 blocking 없음이지 의견 없음이 아니다.
7. **completion은 worker + 사용자 확인이다.** reviewer가 완료 판단을 사용자에게 직접 요청하지 않는다.
8. **co-design의 최종 synthesis는 worker 소유다.** reviewer는 대안과 수렴안을 추천하지만, 최종 프레임을 작성하거나 잠그지 않는다.

---

## 3. 제안

### 3.1 primary input: `target_nature`

`target_mode`와 별개로 대상 성격을 표현한다.

| target_nature | 예 | reviewer checklist |
|---|---|---|
| `code` | diff, tests | correctness, regression, security, test gaps |
| `spec` | 구현 설계 | requirement fit, API/schema, migration, testability |
| `direction` | 개선 방향, 제품 판단 | framing, priority, alternatives, scope |
| `process` | workflow/protocol | roles, state transitions, failure modes, handoff cost |
| `general` | 성격이 애매한 문서 | target 성격 확인, 과도한 checklist 적용 회피 |

default는 보수적으로 둔다.

- `target_mode=diff`이면 `target_nature=code`
- `target_mode=document`이면 자동으로 `spec`을 추측하지 않는다.
- document target에서 명시값이 없으면 `general`로 보고, `request-review` skill은 가능하면 사용자 또는 worker에게 `target_nature` 명시를 요구한다. `general`은 fallback이지 편한 기본값이 아니다.

예:

```yaml
target_mode: "document"
target_nature: "process"
```

### 3.2 primary input: `round_type`

라운드의 목적을 표현한다.

| round_type | 목적 | reviewer 기대 |
|---|---|---|
| `explore` | 아이디어 확장 | 누락 대안 적극 제시 |
| `converge` | 쟁점 좁히기 | 과한 범위 줄이고 우선순위 정리 |
| `confirm` | lock 확인 | 새 범위 확장 자제, 잔여 이견만 확인 |
| `review` | 일반 리뷰 | 기존 동작 |

이번 wiki-markdown 흐름은 `explore -> converge -> confirm`에 가까웠다. round 3에서 `confirm`이 명시됐다면 reviewer가 "새 아이디어를 더 내야 하나?"를 덜 고민했을 것이다.

### 3.3 derived default: `effective_review_posture`

`review_posture`는 독립 필수 입력이 아니다. `target_nature + round_type`으로 `effective_review_posture`를 계산하고, 드문 예외만 `review_posture` override로 명시한다.

posture 값은 3개만 둔다. `confirm`은 posture가 아니라 `round_type`이다.

| effective_review_posture | 목적 | reviewer 행동 | blocking 기준 |
|---|---|---|---|
| `verify` | 목표 충족/회귀 검증 | 증거 기반 결함 탐지 | 오류, 회귀, 요구사항 누락 |
| `challenge` | 전제·우선순위 도전 | 반례, edge, rejected alternative 점검 | 방향을 틀리게 만드는 판단 |
| `co-design` | 검증 + 보강 아이디어 | 대안 제시, scope 절단, 수렴안 추천 | 치명적 오류만 blocking, 제안은 별도 label |

초기 default table:

| target_nature | explore | converge | confirm | review |
|---|---|---|---|---|
| `code` | `verify` | `verify` | `verify` | `verify` |
| `spec` | `co-design` | `challenge` | `verify` | `challenge` |
| `direction` | `co-design` | `challenge` | `verify` | `challenge` |
| `process` | `co-design` | `challenge` | `verify` | `challenge` |
| `general` | `challenge` | `challenge` | `verify` | `verify` |

이 표에서 `confirm -> verify`는 evidence posture만 뜻한다. `round_type=confirm`에는 별도 lock-check behavior가 있으며, 단순 verify checklist로 대체하지 않는다.

override는 가능하지만 예외 처리다.

```yaml
target_nature: "process"
round_type: "explore"
review_posture: "co-design" # optional override; same as derived default here
```

해석 규칙:

- `review_posture`가 없으면 derived default를 쓴다.
- `review_posture`가 있으면 `verify|challenge|co-design`만 허용한다.
- `review_posture=confirm`은 허용하지 않는다. confirmation은 `round_type=confirm`으로만 표현한다.
- 구현체가 내부 출력에 `effective_review_posture`를 표시하는 것은 가능하지만, status handoff의 필수 입력으로 요구하지 않는다.

### 3.4 feedback taxonomy 확장

기존 `phase` semantics는 유지하되, 방향/설계 리뷰에서 다음 label을 공식 허용한다.

| label | 판정 규칙 | phase 영향 | 예 |
|---|---|---|---|
| `[blocking]` | 반영 전에는 승인 불가 | `changes-requested` | 요구사항 누락, 코드 회귀, 프로토콜 불변식 위반 |
| `[should-reflect-before-implementation]` | 방향은 승인 가능하지만 구현 전 수용/보류 결정을 남겨야 함 | `approved` 가능 | 설계 축 축소, handoff 누락 방지, default 변경 |
| `[directional]` | 수렴 품질을 높이는 관점이지만 구현 시작을 막지는 않음 | `approved` 가능 | 성공기준 추가, 우선순위 재정렬 |
| `[nice-to-have]` | 후순위 개선 | `approved` 가능 | 문서 예시 추가, CLI 출력 편의 |
| `[nit]` | 문구/형식 | `approved` 가능 | 이름, 오탈자, 표기 통일 |

`blocking_count`는 `[blocking]`만 센다. `approved`와 `[should-reflect-before-implementation]`은 양립한다.

### 3.5 approval meaning은 protocol-level contract로 둔다

`approval_meaning`을 status field로 추가하지 않는다. 기계 상태는 `phase`와 `blocking_count`로 충분하다.

대신 SKILL/SSOT에 다음 계약을 한 번 둔다.

```text
approved means blocking_count=0, not "no further ideas".
For co-design or challenge reviews, approved feedback may still include
should-reflect, directional, nice-to-have, or nit items.
```

snapshot에는 request-review가 필요 시 템플릿 문구를 넣을 수 있지만, free-form 상태 정본처럼 반복 작성하지 않는다.

### 3.6 should-reflect carryover

`[should-reflect-before-implementation]`은 승인 가능하지만 소실되면 안 되는 항목이다. 따라서 complete/handoff 경로에 다음 규칙을 추가한다.

- reviewer는 `[should-reflect-before-implementation]`을 구현 전 결정이 필요한 권고로만 사용한다.
- worker는 address-feedback에서 각 항목을 `accepted`, `deferred`, `rejected-with-rationale` 중 하나로 정리한다.
- `complete` skill은 최신 approved feedback과 worker synthesis에서 미해결 should-reflect를 찾아 final briefing에 표시하도록 worker에게 지시한다.
- 구현 task/issue/wiki task가 이어지면 complete 또는 worker synthesis가 해당 항목을 handoff checklist로 이월한다.
- 이어지는 구현이 없으면 complete가 "implementation carryover 없음"을 명시해 누락과 의도적 종료를 구분한다.

이 규칙은 `approved` semantics를 바꾸지 않는다. approved는 여전히 blocking 없음이다. 다만 co-design 리뷰의 강한 권고가 다음 실행 단위로 넘어가도록 만든다.

첫 구현은 CLI 자동 파싱이 아니라 skill policy로 충분하다. label은 prose이므로 `validate-complete`가 자동 검출한다고 가정하지 않는다.

### 3.7 co-design boundary

`co-design` reviewer는 적극적으로 아이디어를 낸다. 하지만 frame과 최종 synthesis는 worker 책임이다.

reviewer가 할 수 있는 일:

- factual 오류를 검증한다.
- 핵심 framing이 맞는지 도전한다.
- 더 나은 대안과 scope 절단을 제안한다.
- 자신의 추천 수렴안을 명시한다.
- blocking과 should-reflect를 구분한다.

reviewer가 하지 않는 일:

- 최종 수렴 문서를 직접 authoring하지 않는다.
- worker의 frame ownership을 대체하지 않는다.
- approved를 이유로 사용자 completion 확인을 직접 요청하지 않는다.

### 3.8 flow mode guidance

`effective_review_posture`는 flow 선택에도 영향을 준다.

| effective_review_posture | 기본 flow guidance |
|---|---|
| `verify` | self-flow도 충분한 경우가 많다. code diff, 작은 변경, 명확한 acceptance criteria에 적합 |
| `challenge` | blast radius가 크거나 전제 검증이 중요하면 separate 권장 |
| `co-design` | 비상관 관점이 가치의 본체이므로 separate/cross-model 권장 |

`review_strength=hard`의 의미도 posture에 따라 다르게 해석한다.

- `verify + hard`: 더 깊은 증거 확인, 회귀/테스트 gap 탐지
- `challenge + hard`: 더 강한 반례와 rejected alternative 점검
- `co-design + hard`: 더 가혹한 말투가 아니라 **서로 구별되는 여러 lens**를 요구

---

## 4. 동작 플로우

### 4.1 request-review

worker는 request-review 때 대상 성격과 라운드 목적을 명시한다.

```yaml
target_mode: "document"
target_nature: "process"
round_type: "explore"
review_strength: "hard"
```

derived posture는 `co-design`이다. 필요하면 override를 명시한다.

요청 문구에는 다음을 포함한다.

- 초안의 핵심 주장
- reviewer가 적극적으로 도전해야 할 지점
- 아이디어 제안을 원하는 영역
- 이번 round의 수렴 목표

### 4.2 review

reviewer는 `target_nature + round_type`으로 `effective_review_posture`를 계산하고 checklist를 고른다.

`round_type=confirm`이면 posture와 별개로 lock-check 경로를 따른다.

- 이전 round의 agreed feedback이 반영됐는지 확인한다.
- 남은 이견이 lock을 막는지 판단한다.
- 새 scope를 넓히지 않는다.
- blocking은 lock을 막는 미해결 쟁점에만 쓴다.

confirm이 아니면 posture별 checklist를 따른다.

`co-design`이면 대안을 적극 제안한다. `challenge`이면 과한 범위와 취약한 전제를 줄인다. `verify`이면 acceptance criteria, 회귀, 증거 gap을 본다.

feedback은 label을 붙여 작성한다. `phase=changes-requested`는 `[blocking]`이 있을 때만 사용한다.

### 4.3 address-feedback

worker는 피드백을 맹목 수용하지 않는다. 각 핵심 항목을 수용하거나, 보류하거나, 근거 있게 반박한다.

round가 계속되면 `round_type`을 갱신한다.

```yaml
round_type: "converge"
```

마지막 확인은 posture override 없이 표현한다.

```yaml
round_type: "confirm"
```

### 4.4 complete

complete는 blocking gate만 확인하고 끝내지 않는다. co-design/challenge 리뷰였고 `[should-reflect-before-implementation]`이 있었다면, complete skill 지시에 따라 worker가 synthesis 또는 최신 approved feedback에서 carryover 항목을 final briefing과 다음 구현 단위에 이월한다.

---

## 5. 구현 범위

### Unit A — status field와 derivation

- status block 선택 필드 추가:
  - `target_nature`
  - `round_type`
  - `review_posture` optional override
- enum 검증:
  - `target_nature`: `code|spec|direction|process|general`
  - `round_type`: `explore|converge|confirm|review`
  - `review_posture`: `verify|challenge|co-design`
- parser default:
  - `target_mode=diff` -> `target_nature=code`
  - document target에서 누락 -> `general`
  - `round_type` 누락 -> `review`
- helper 출력에서 `effective_review_posture`를 계산해 보여줄 수 있다.
- `round_type=confirm`의 lock-check behavior는 derived posture와 별도로 노출한다.
- 기존 phase 전이는 변경하지 않는다.

### Unit B — skill behavior와 taxonomy

- `request-review`:
  - document target에서는 `target_nature` 명시를 요청하고, 불명확할 때만 `general` fallback 사용
  - `target_nature`/`round_type` 입력 설명 추가
  - direction/process 예시 추가
  - derived posture와 flow guidance 안내
- `review`:
  - posture별 checklist 추가
  - `round_type=confirm` lock-check checklist 추가
  - feedback taxonomy 확장
  - `approved != no opinion`을 protocol-level contract로 명시
  - `co-design` boundary 명시
- `address-feedback`:
  - `[should-reflect-before-implementation]` 수용/보류/반박 규칙 추가
  - `round_type` 갱신 예시 추가

### Unit C — complete carryover policy, SSOT, dogfooding

- `complete`:
  - approved feedback의 should-reflect carryover를 final briefing과 다음 구현 단위에 이월하도록 skill policy 추가
  - 구현 이월이 없으면 명시적으로 없음 처리
  - 첫 단계에서는 CLI 자동 파싱을 요구하지 않는다.
- `wiki/ssot/session-review-plugin.md`와 README에 short contract 반영
- parser/validator test는 enum과 derivation을 검증한다.
- policy behavior는 unit test만으로 충분하지 않으므로 dogfooding 시나리오로 검증한다.

---

## 6. 비범위

- 새 phase 추가 없음
- reviewer가 사용자에게 완료 확인 요청하는 경로 없음
- `approved` semantics 변경 없음 (`blocking_count=0`만 의미)
- `approval_meaning` status field 추가 없음
- LLM judge 또는 자동 품질 판정 없음
- 리뷰 결과 자동 merge 없음
- 모든 review를 co-design으로 기본화하지 않음
- `review_posture=confirm` 없음
- should-reflect label의 CLI 자동 파싱 없음

---

## 7. 성공 기준

- 사용자가 "검증만 하지 말고 적극 의견도 내라"고 별도 steering하지 않아도 request-review contract만 보고 reviewer가 기대 역할을 이해한다.
- code review는 기존처럼 검증 중심으로 유지된다.
- direction/process review는 reviewer가 대안·scope 절단·수렴안을 적극 제안한다.
- `approved`가 의견 없음으로 오해되지 않는다.
- `[should-reflect-before-implementation]`이 approved 이후 구현 단위로 이월된다.
- self mode와 separate mode 모두 같은 status block으로 동작한다.
- cross-model/separate 리뷰가 같은 abstraction에 독립 수렴했는지를 co-design 성공 신호로 볼 수 있다.

---

## 8. 최종 수렴 요약

3라운드 리뷰 결과, blocking 0과 잔여 이견 없음으로 lock 가능 판정을 받았다. 최종 수렴안은 다음과 같다.

- `target_nature + round_type`을 primary input으로 둔다.
- `review_posture`는 derived default + optional override로 낮춘다.
- `confirm`은 posture가 아니라 `round_type`으로만 표현한다.
- 단, `round_type=confirm`은 derived posture와 별개로 lock-check behavior를 가진다.
- `approval_meaning`은 status field가 아니라 protocol-level contract로 둔다.
- `[should-reflect-before-implementation]`은 complete/handoff로 이월하되, 첫 구현은 CLI 자동 파싱이 아니라 skill policy로 둔다.
- co-design synthesis는 worker-owned로 명확히 한다.

구현 전 확인할 carryover:

1. `round_type=confirm` lock-check behavior는 derived posture와 별도 분기로 구현한다.
2. should-reflect carryover는 첫 단계에서 CLI 자동 파싱이 아니라 skill policy로 구현한다.
3. document target은 `target_nature`를 묻고, `general`은 fallback으로만 사용한다.
