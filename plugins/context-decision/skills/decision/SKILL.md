---
name: decision
description: 대화가 앞으로 따를 선택으로 수렴하거나 기존 결정을 바꾸려 할 때 Current DEC의 실제 본문을 먼저 비교해 동일·보강·취지 변경·충돌을 알리고, 명시적으로 확정·승인된 선택만 DEC owner result로 만들어 context-core coordinator에 전달한다.
---

# Decision

context-decision은 직접 설치된 context-core가 활성 상태일 때만 사용한다. 이 skill은 semantic owner이며 filesystem을 쓰지 않는다. `schema`/`capabilities`를 제외한 모든 CLI 호출은 host가 제공한 `--host`, `--core-inventory @file`, `--core-doctor @file`을 먼저 검증한다.

1. 대화가 선택으로 수렴하거나 기존 선택을 바꾸려는 시점에는 결론·기록 제안보다 먼저 `check --statement ... --scope ... --decision-key ...`를 실행한다. 결과에 포함된 Current DEC의 실제 `결정`·`취지`·`반려대안`을 읽고 각 후보 관계를 `new|same|supporting|rationale_changed|conflict` 중 하나로 판정한다. 문장 유사도나 hash는 의미 판정 근거가 아니다.
2. `same`이면 기존 DEC를 재사용하고 중복 기록하지 않는다. `supporting`이면 기존 DEC를 유지하며 새 근거가 오래 재사용될 때만 OBS 후보를 고려한다. `rationale_changed`나 `conflict`이면 결론 전에 무엇이 달라졌는지 알리고 기존 결정 유지·변경·supersede 중 사용자의 의도를 확인한다. `new`는 조회 범위 안의 판정일 뿐 전역 무충돌 증명이 아니다.
3. 현재 또는 미래 행동을 지배하는 명시적 선택, canonical scope와 commitment evidence가 모두 있을 때만 DEC를 claim한다. 대화가 이 상태에 도달하면 원래 답을 먼저 마친 뒤 자연스럽게 한 번만 기록 여부를 묻는다. 승인 전에는 persistent write를 제안 상태 이상으로 진행하지 않는다.
4. direct capture는 `candidate prepare --candidate-id ... --commitment-evidence ...`로 exact candidate를 먼저 만든다. 이 candidate를 본 owner skill이 claim/decline/clarification한 뒤 `capture --candidate @file --attestation @file` 또는 `--decline-reason`/`--needs-clarification-reason`으로 넘긴다. CLI가 evidence나 attestation을 자체 발명하지 않는다.
5. `batch validate`는 exact slot, scope overlap, acknowledgement와 ordered prior bundle overlay를 구조적으로 fail closed 한다. 의미상 동일·변경·충돌 판정은 `check`의 실제 본문을 읽은 agent가 담당한다.
6. ordinary evidence OBS는 DEC의 `relations.informed_by`로 남기며 retire하지 않는다. decision owner가 없어서 생성된 `kind_hint: decision` fallback OBS만 `import-fallback`으로 전환하며, source artifact의 id·path·SHA-256·실제 claim과 `same_claim` attestation을 검증한다.
7. complete final bundle과 exact digest 승인, index rebuild와 physical write는 모두 context-core가 소유한다. decision CLI의 write 수는 항상 0이다.
