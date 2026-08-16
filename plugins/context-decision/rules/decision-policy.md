# Decision capture policy

대화가 선택으로 수렴하거나 기존 결정을 바꾸려 하면 결론과 capture 전에 Current DEC의 실제 `결정`·`취지`·`반려대안`을 조회해 비교한다. 관계는 `new|same|supporting|rationale_changed|conflict`로 판정하며 문장 유사도나 hash를 의미 동일성의 근거로 사용하지 않는다. 취지 변화나 충돌은 결론 전에 사용자에게 알린다.

명시적 선택·scope·따를 의사가 모두 있는 후보만 context-decision owner에 전달한다. semantic milestone에서는 원래 답을 먼저 마친 뒤 기록 여부를 한 번 묻고, 승인 전에는 persistent write를 수행하지 않는다. evidence OBS와 DEC 관계는 `informed_by`로 보존한다. fallback OBS import는 source artifact의 exact id·path·SHA-256·actual claim, same-claim attestation과 reciprocal lifecycle edge가 모두 일치할 때만 제안한다.

context-decision은 draft와 validation receipt만 반환한다. 승인 또는 filesystem write를 수행하지 않는다.
