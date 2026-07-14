# Native execution control

실제 명령, capability probe, 외부 mutation, closeout이 있는 run에서만 읽는다. Studio는
control plane만 소유하고 명령·provider API를 직접 실행하지 않는다.

## Canonical artifact

- schema: `studio-verification-contract-set/v1`
- digest: `sha256:7df570d1faaba445865c74fd6dffff73178f0102cd3a5728183abf6791ce2b65`
- default: repo 최상위 `tests/fixtures/studio-verification-contract-v1.json`
- leaf QA override: `STUDIO_VERIFICATION_CONTRACT=/absolute/path/to/exact-artifact.json`

시작할 때 `execution contract`로 schema, canonical root digest, 10개 golden case를 검증한다.
축약 fixture나 소비자별 재직렬화 복제본을 만들지 않는다.

## Dispatch

1. 실제 executable/args/cwd/environment를 exact `command-profile/v1`으로 허용한다.
2. head, command/environment digest, tool version, purpose, criteria/impact, run cap,
   telemetry policy를 `execution-permit/v1`에 고정한다.
3. final 독립 판단, integration-full, release-artifact, device-check,
   production-preflight는 새 `fresh_requirement_id`를 요구한다.
4. required capability는 `(mission_id, capability_id, environment_digest)` cache를 먼저 본다.
   unavailable snapshot이 있으면 probe를 반복하지 않고 STOP한다.
5. external mutation은 passed `preflight-receipt/v1`을 요구한다. 비용이 있으면 exact mutation
   request와 owner-approved authorization을 permit에 pin한다.
6. `execution dispatch --json @request.json`의 `action=claim` 뒤에만 executor를 호출한다.
   `reuse-evidence`, `reject`, `pause`, `probe-capability`, `block-dispatch`는 물리 실행을 시작하지 않는다.

physical key는 `head + command_digest + environment_digest + tool_version + purpose`이며 fresh
실행만 `fresh_requirement_id`를 추가한다. cycle/unit/target으로 duplicate identity를 갈라놓지 않는다.

## Result와 evidence

- executor는 exact claim의 `command-receipt/v1`을 반환한다. receipt의 profile, purpose, head,
  command/environment/tool/fresh binding이 permit과 다르면 받지 않는다.
- `telemetry_policy=fail-closed`는 `tokens:null`, `unavailable`, estimated coverage를 pause한다.
  `report-only`만 미측정 run을 명시적으로 기록하며 summary에서 unmeasured로 센다.
- 새 native evidence는 passing receipt를 `source_receipt_id`로 참조해야 한다. criteria,
  covered_paths, surface, impact, purpose, independence가 맞는 `verification-evidence/v1`만 기록한다.
- invalidation은 criteria/path/surface 변화와 timestamp를 넣은 새 canonical evidence로 한 번
  기록한다. invalidated evidence를 valid로 되돌리지 않는다.
- paid mutation은 authorization quota를 mutation 전에 atomic claim한다. command result는 최종
  consumption digest를 가리키는 `external-mutation-receipt/v1`을 함께 반환하고, consumption은
  mutation receipt ref를 역참조한다.

## Closeout과 summary

`closeout-receipt/v1`은 integration HEAD에 적용 가능한 track result, verification evidence,
review lease, delivery, mutation, cleanup, preserved-user-change ref와 zero open finding을 가져야 한다.
누락·stale ref가 있으면 closeout을 진행하지 않는다.

`execution summary --mission-id <id>`는 read-only다. logical checks, physical runs, full/delta QA,
evidence reuse, duplicate prevention, capability probe/failure reuse, token coverage, owner intervention,
external spend만 집계한다. 미측정 token을 0이나 exact로 바꾸지 않는다.
