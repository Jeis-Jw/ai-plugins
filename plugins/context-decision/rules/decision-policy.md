# Decision capture policy

context-core의 증분 audit에서 선택의 형성·변경 신호가 있을 때만 동작한다. 같은 scope·anchor와 Current `{id,sha256}`의 본문이 session context에 남아 있을 때만 재사용하고, 본문이 없거나 관련 anchor가 바뀌면 metadata로 후보를 줄인 뒤 실제 `결정`·`취지`·`반려대안`을 다시 읽는다.

관계는 `new|same|supporting|rationale_changed|conflict`로 판정한다. hash, ID와 metadata는 의미 판정 근거가 아니다. `same|supporting`은 조용히 재사용하고, 취지 변화나 충돌은 primary 결론 전에 알린다.

명시적 선택·scope·따를 의사가 모두 있는 성숙한 후보만 원래 답 뒤 grouped proposal에 한 번 포함한다. dismissed·deferred 후보는 새 evidence 전까지 재제안하지 않는다. context-decision은 draft와 validation receipt만 반환하며 승인 또는 filesystem write를 수행하지 않는다.
