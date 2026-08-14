---
name: decision
description: 사용자가 앞으로 따를 선택과 scope를 명시적으로 확정해 rationale·rejected alternatives까지 보존해야 할 때 DEC owner result로 만들고 context-core coordinator에 전달한다. 임시 선호나 미확정 논의에는 사용하지 않는다.
---

# Decision

context-decision은 직접 설치된 context-core가 활성 상태일 때만 사용한다. 이 skill은 semantic owner이며 filesystem을 쓰지 않는다. `schema`/`capabilities`를 제외한 모든 CLI 호출은 host가 제공한 `--host`, `--core-inventory @file`, `--core-doctor @file`을 먼저 검증한다.

1. 현재 또는 미래 행동을 지배하는 명시적 선택, canonical scope와 commitment evidence가 모두 있을 때만 DEC를 claim한다.
2. direct capture는 `candidate prepare --candidate-id ... --commitment-evidence ...`로 exact candidate를 먼저 만든다. 이 candidate를 본 owner skill이 claim/decline/clarification한 뒤 `capture --candidate @file --attestation @file` 또는 `--decline-reason`/`--needs-clarification-reason`으로 넘긴다. CLI가 evidence나 attestation을 자체 발명하지 않는다.
3. conflict와 duplicate 검사는 `batch validate`에서 current DEC와 ordered prior bundle overlay를 기준으로 fail closed 한다.
4. ordinary evidence OBS는 DEC의 `relations.informed_by`로 남기며 retire하지 않는다.
5. decision owner가 없어서 생성된 `kind_hint: decision` fallback OBS만 `import-fallback`으로 전환한다. core가 준비한 exact fingerprint/same_claim input을 검증하고 OBS History 이동과 DEC create를 한 coordinator plan으로 제안한다.
6. complete final bundle과 exact digest 승인, index rebuild와 physical write는 모두 context-core가 소유한다. decision CLI의 write 수는 항상 0이다.
