# Context capture policy

매 user turn의 새 의미를 같은 응답 pass에서 별도 model·tool 호출 없이 한 번 audit한다. durable signal이 없으면 audit 상태를 표시하지 않는다. scope·anchor, 읽은 Current `{id,sha256}`, pending·dismissed 참조만 session-local ephemeral ledger로 유지하고 실제 본문이나 후보 전체를 복제·저장하지 않는다.

신호가 있을 때만 index metadata를 먼저 recall하고 관련 실제 본문만 읽는다. 본문이 session context에 있고 scope·evidence·anchor·index와 artifact SHA가 그대로일 때만 재사용한다. semantic owner는 실제 본문·scope·rationale를 비교하며 conflict 또는 rationale change를 primary 결론 전에 알린다. hash, ID와 metadata는 의미 판정 근거가 아니다.

그 외에는 원 답변을 먼저 완료하고, 성숙한 durable 후보만 milestone당 한 번 grouped proposal로 제시한다. dismissed·deferred 후보는 새 근거 전까지 재제안하지 않는다. 어떤 durable write도 사용자의 exact final-bundle 승인 전에는 수행하지 않는다.
