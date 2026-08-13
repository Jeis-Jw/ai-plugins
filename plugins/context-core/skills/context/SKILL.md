---
name: context
description: 한 번 추출한 durable-context 후보를 설치된 owner capability에 route하고, owner 결과를 한 grouped approval bundle로 조정한다.
---

# Context

milestone마다 candidate audit은 최대 한 번만 수행한다. 원 답변을 먼저 완성하고, 재사용 가치가 있는 후보가 있을 때만 한 번의 capability-first 추출로 최대 8개 candidate를 만든다.

1. `context_cli.py capabilities --json`과 host가 이미 발견한 addon capability만 사용한다. router는 owner process를 실행하거나 plugin cache·대체 runtime을 탐색하지 않는다.
2. candidate batch는 16 KiB, 각 owner input은 2 KiB 이하다. host가 target owner skill을 호출하며 router에는 complete `context-owner-result/v1`만 돌려준다.
3. route 우선순위는 explicit request, specialized owner, observation fallback, handoff, skip이다. invalid request, unavailable owner, conflict, duplicate, malformed result와 clarification은 fail closed 한다.
4. 같은 claim은 decision owner가 있으면 DEC 하나, 없으면 `kind_hint: decision` OBS 하나다. 독립 evidence OBS와 그 evidence를 `informed_by`로 인용하는 DEC는 서로 다른 claim으로 유지한다.
5. owner별 batch validation receipt를 받은 뒤 context-core가 ordered overlay를 반영해 complete final bundle을 만든다. preview는 32 KiB를 넘기거나 semantic content를 자르지 않는다.
6. 사용자가 exact `approval_digest`를 승인한 뒤에만 `transaction apply`를 한 번 호출한다. 승인 뒤 candidate, attestation, timestamp, path, plan 또는 content를 다시 생성하지 않는다.

audit, route, claim, draft, validation, preview와 거절된 apply는 repository와 host policy bytes를 변경하지 않는다. 물리 write는 context-core coordinator만 수행한다.
