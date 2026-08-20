---
name: context
description: 중앙 대화 audit에서 durable-context 신호가 생겼거나 이전 맥락이 판단을 바꿀 때, Current context를 metadata-first로 recall하고 성숙한 후보를 owner capability에 route한다.
---

# Context

각 user turn에서 새로 추가된 의미만 같은 응답 pass에서 내부 audit한다. 별도 model·tool 호출을 만들지 않으며 durable signal이 없으면 audit 상태나 capture 질문 없이 원래 대화를 계속한다. 이 audit은 context-core가 delta당 한 번만 수행하고 addon별로 반복하지 않는다.

host 또는 model session 안에 작은 ephemeral ledger만 유지한다: 현재 scope·anchor, 이미 읽은 Current `{id,sha256}`, pending 후보의 짧은 참조·성숙도, dismissed/deferred 참조와 evidence anchor. 실제 본문을 복제하거나 repository에 쓰지 않는다. scope, evidence, anchor, index 또는 artifact SHA가 바뀌거나 본문이 session context에서 사라지면 관련 항목만 무효화하고, 새 근거가 없으면 dismissed/deferred 후보를 다시 제안하지 않는다.

1. 이전 맥락이 판단을 바꿀 신호가 있을 때만 `recall`로 index metadata를 먼저 조회한다. 실제 의미 비교가 필요한 관련 item만 `--read`하고, 좁게 선택된 묶음에만 `--pack`을 사용한다. 같은 scope와 `{id,sha256}`는 ledger에서 재사용한다.
2. 설치된 semantic owner가 후보와 관련 artifact의 실제 primary claim, supporting sections, scope와 rationale를 비교한다. hash, fingerprint, ID와 index metadata는 의미 판정 근거가 아니다. conflict 또는 rationale change는 primary 결론 전에 관련 ID와 차이를 알리고 유지·수정·supersede 여부를 확인한다.
3. 그 외에는 원 답변을 먼저 완성한다. 현재·미래 판단에 재사용될 후보가 충분히 성숙했을 때만 semantic milestone당 한 번, 최대 8개를 capability-first로 추출해 grouped capture를 제안한다.
4. `context_cli.py capabilities --json`과 host가 이미 발견한 addon capability만 사용한다. router는 owner process, plugin cache 또는 대체 runtime을 탐색하지 않는다. route 우선순위는 explicit request, specialized owner, observation fallback, handoff, skip이다.
5. candidate batch는 16 KiB, 각 owner input은 2 KiB 이하다. `candidate_id`는 result 연결용 transport ID일 뿐이다. owner별 validation 뒤 context-core가 ordered overlay와 complete final bundle을 만들며 preview는 semantic content를 자르지 않는다.
6. 사용자가 exact `approval_digest`를 승인한 뒤에만 `transaction apply`를 한 번 호출한다. 승인 뒤 candidate, attestation, timestamp, path, plan 또는 content를 다시 생성하지 않는다.

audit, route, claim, draft, validation, preview와 거절된 apply는 repository와 host policy bytes를 변경하지 않는다. 물리 write는 context-core coordinator만 수행한다.
