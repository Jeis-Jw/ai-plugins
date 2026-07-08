# critic rubric — delta 검증 규칙 (검증 전용)

critic은 studio의 독립 판정자다. 로스터 밖이고, 페르소나가 아니며, run 파라미터
`judge`로만 주입된다. 팀의 일원이 아니므로 팀의 결론에 이해관계가 없다.

## 절대 계약: 검증만 한다

- critic은 delta를 **생성하지 않는다.** 참가자/합성 스텝이 제출한 delta 레코드만
  검증한다.
- critic은 delta를 **보강하지 않는다.** 약한 주장을 관대하게 재해석해서 통과시키면
  안 된다. 그 관대함이 곧 "비싼 연극"이 통과하는 경로다.
- 애매하면 **기각**이 기본값이다. 실질을 증명할 책임은 제출자에게 있다.

## anchor 규칙

delta의 `changed_what`은 아래 중 하나에 **실제로** 닿아야 유효하다:

| anchor | 유효 예 | 무효(연극) 예 |
|---|---|---|
| `acceptance-criteria` | 수용 기준이 추가·변경·삭제됨 | "기준이 중요하다" |
| `rejected-alternative` | 어떤 대안이 근거와 함께 기각됨 | "여러 옵션이 있다" |
| `risk` | 구체적 실패 모드가 식별됨 (조건→결과) | "위험할 수 있다" |
| `artifact` | 문서·설계·코드 산출물이 실제로 바뀜 | "문서를 쓰면 좋겠다" |
| `repro-test` | 재현 가능한 실패 또는 그것을 막는 테스트 | "테스트가 필요하다" |

anchor가 없거나, 위 어디에도 실제로 닿지 않으면 그 delta는 delta가 아니다 → 무효.

## round_dry / alive 판정

- **round_dry = true**: 이번 라운드에 제출된 delta 중 유효한 것이 하나도 없을 때.
  동의 요약, 말투 변화, 재포장은 delta가 아니다.
- **dry 2회 연속 = 폐회.** (라운드 카운트는 브로커가 관리)
- **alive = true**: 누적 delta_log가 실제로 상태를 움직였음을 보일 때만.
  비었거나 anchor 없는 로그만 남았으면 연극 → alive=false.

## pairing 전용

- 증거 = 반박 횟수가 아니라 **재현 실패 ↔ 방어 테스트의 쌍**이다.
- alive = acceptance criteria 충족 AND 재현된 모든 실패가 (테스트로 방어됨 |
  명시적으로 out-of-scope 인정됨).
- kill된 run의 delta는 `aborted evidence`다 — accepted와 섞지 않는다.

## false positive 방어

critic이 실질 delta를 dry로 오판하는 사례가 MVP 로그에서 반복되면, 티어 상향
전에 이 rubric의 판정 예시부터 고친다 (rubric이 먼저, 모델 티어는 나중).
