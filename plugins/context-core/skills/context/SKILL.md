---
name: context
description: substantive 판단 전에 관련 Current context를 scoped recall하고, milestone에서 추출한 durable-context 후보를 설치된 owner capability에 route해 한 grouped approval bundle로 조정한다.
---

# Context

Substantive work나 결정 수렴에서 이전 맥락이 판단을 바꿀 수 있으면 먼저 `recall --pack`으로 관련 Current context를 scoped index-first 조회한다. 같은 scope에서는 결과를 재사용하고 scope, evidence 또는 anchor가 바뀔 때만 다시 조회한다.

설치된 semantic owner가 있으면 후보와 관련 artifact의 실제 primary claim, supporting sections, scope와 rationale를 비교하게 한다. 같은 문장인지 계산하는 hash는 사용하지 않는다. conflict 또는 rationale change가 있으면 primary 결론 전에 관련 ID와 차이를 알리고 유지·수정·supersede 여부를 확인한다.

milestone마다 candidate audit은 최대 한 번만 수행한다. 원 답변을 먼저 완성하고, 재사용 가치가 있는 후보가 있을 때만 한 번의 capability-first 추출로 최대 8개 candidate를 만든다.

1. `context_cli.py capabilities --json`과 host가 이미 발견한 addon capability만 사용한다. router는 owner process를 실행하거나 plugin cache·대체 runtime을 탐색하지 않는다.
2. candidate batch는 16 KiB, 각 owner input은 2 KiB 이하다. host가 target owner skill을 호출하며 router에는 complete `context-owner-result/v1`만 돌려준다.
3. route 우선순위는 explicit request, specialized owner, observation fallback, handoff, skip이다. invalid request, unavailable owner, conflict, duplicate, malformed result와 clarification은 fail closed 한다.
4. 같은 의미인지 여부는 owner가 실제 본문을 비교해 attestation한다. decision owner가 있으면 DEC 하나, 없으면 `kind_hint: decision` OBS 하나다. 독립 evidence OBS와 그 evidence를 `informed_by`로 인용하는 DEC는 서로 다른 claim으로 유지한다.
5. owner별 batch validation receipt를 받은 뒤 context-core가 ordered overlay를 반영해 complete final bundle을 만든다. preview는 32 KiB를 넘기거나 semantic content를 자르지 않는다.
6. 사용자가 exact `approval_digest`를 승인한 뒤에만 `transaction apply`를 한 번 호출한다. 승인 뒤 candidate, attestation, timestamp, path, plan 또는 content를 다시 생성하지 않는다.

audit, route, claim, draft, validation, preview와 거절된 apply는 repository와 host policy bytes를 변경하지 않는다. 물리 write는 context-core coordinator만 수행한다.
