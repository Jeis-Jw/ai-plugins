---
name: decision
description: 대화의 증분 audit에서 선택 신호가 생길 때만 관련 Current DEC 실제 본문을 비교해 동일·보강·취지 변경·충돌을 알리고, 확정·승인된 선택만 DEC owner result로 만든다.
---

# Decision

context-decision은 직접 설치된 context-core가 활성 상태일 때만 사용한다. 이 skill은 대화 전체를 따로 audit하지 않는 semantic owner이며 filesystem을 쓰지 않는다. `schema`/`capabilities`를 제외한 CLI 호출은 host의 `--host`, `--core-inventory @file`, `--core-doctor @file`을 먼저 검증한다.

1. context-core의 증분 audit이 선택의 형성·변경 신호를 감지한 경우에만 동작한다. ledger의 같은 scope·anchor와 Current `{id,sha256}` 본문이 session context에도 남아 있으면 재사용한다. 본문이 없거나 scope·evidence·anchor·index 또는 artifact SHA가 바뀌었으면 결론·기록 제안 전에 `check --statement ... --scope ... --decision-key ...`를 실행한다.
2. `check`는 metadata로 후보를 줄인 뒤 관련 Current DEC의 실제 `결정`·`취지`·`반려대안`만 반환한다. 이를 읽고 `new|same|supporting|rationale_changed|conflict` 중 하나로 판정한다. 문장 유사도, hash, ID와 metadata는 의미 판정 근거가 아니다.
3. `same`은 기존 DEC를 조용히 재사용한다. `supporting`은 DEC를 유지하고 오래 재사용될 새 근거만 OBS 후보로 본다. `rationale_changed|conflict`는 primary 결론 전에 차이를 알리고 유지·변경·supersede 의도를 확인한다. `new`는 조회 범위 안의 판정일 뿐 전역 무충돌 증명이 아니다.
4. 현재 또는 미래 행동을 지배하는 명시적 선택, canonical scope와 commitment evidence가 모두 있을 때만 DEC를 claim한다. 원래 답을 먼저 마친 뒤 성숙한 후보를 grouped proposal에 한 번 포함한다. dismissed·deferred 후보는 새 evidence 전까지 다시 제안하지 않는다.
5. direct capture는 `candidate prepare --candidate-id ... --commitment-evidence ...`로 exact candidate를 고정한다. owner가 판독한 뒤 `capture --candidate @file --attestation @file` 또는 `--decline-reason`/`--needs-clarification-reason`으로 넘긴다. CLI가 evidence나 attestation을 발명하지 않는다.
6. `batch validate`는 exact slot, scope overlap, acknowledgement와 ordered prior bundle overlay를 구조적으로 검증한다. ordinary evidence OBS는 DEC의 `relations.informed_by`로 유지한다.
7. complete final bundle, exact digest 승인, index rebuild와 physical write는 context-core만 소유한다. decision CLI의 write 수는 항상 0이다.
