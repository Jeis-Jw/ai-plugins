# Decision capture policy

명시적 선택·scope·따를 의사가 모두 있는 후보만 context-decision owner에 전달한다. evidence OBS와 DEC 관계는 `informed_by`로 보존한다. fallback OBS import는 exact `source_claim_fingerprint`, same-claim attestation과 reciprocal lifecycle edge가 모두 일치할 때만 제안한다.

context-decision은 draft와 validation receipt만 반환한다. 승인 또는 filesystem write를 수행하지 않는다.
