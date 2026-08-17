---
title: 컨텍스트 capture routing과 bounded recall 계약
created_at: 2026-08-13
summary: 현재 대화를 milestone당 한 번 감사해 bounded ephemeral candidate를 만들고 설치된 semantic owner로 중복 없이 routing한 뒤 grouped approval 후에만 기록하는 provider-neutral v1 계약.
tags: [context-core, capture, routing, approval, recall, token-efficiency, ssot]
verified_at: 2026-08-17
affects_paths: [plugins/context-core/**, plugins/context-decision/**]
---

## 현재 상태

### Recall and compare before capture

Substantive 판단이나 결정 수렴에서 과거 맥락이 결론을 바꿀 수 있으면 capture audit보다 먼저 관련 Current context를 scoped recall한다. decision 후보는 `context-decision check`가 관련 Current DEC의 actual `결정`·`취지`·`반려대안`을 bounded input으로 만들고, owner agent가 `new|same|supporting|rationale_changed|conflict`를 판정한다. 취지 변경이나 충돌은 결론 전에 알린다. 같은 scope에서는 recall 결과를 재사용하고 scope·evidence·anchor가 바뀔 때만 갱신한다.

### Audit timing

capture audit는 다음 조건에서만 실행한다.

- 사용자가 명시적으로 기록·정리·handoff를 요청했다.
- 의미 있는 결정 또는 상태 변화가 확정된 semantic milestone이다.
- 긴 작업의 closeout이며 재사용 가능한 claim이 생겼을 가능성이 있다.

같은 semantic milestone 또는 closeout에서는 최대 한 번만 수행한다. primary 작업과 답변을 먼저 완료하고 이미 대화 context에 존재하는 내용으로 감사한다. runtime hook, edit/commit activity heuristic, transcript ledger로 audit를 강제하지 않는다.

SNAP은 durable candidate의 기본 fallback이 아니다. 사용자가 세션 handoff를 요청했거나 unfinished context의 저장 제안을 승인한 경우에만 생성한다.

### Candidate envelope

candidate는 한 audit batch 안에서만 존재하고 파일이나 ledger에 영속화하지 않는다.

auditor는 host agent의 bounded semantic extraction 단계다. candidate 생성 자체는 stdlib CLI가 수행하지 않으며, 그 출력은 아래 schema·capability constraints로 deterministic validation된다.

```json
{
  "schema": "context-capture-candidate/v1",
  "candidate_id": "cand_550e8400e29b41d4a716446655440000",
  "title": "인증 세션 소유권",
  "claim": "인증 세션은 BFF가 소유한다",
  "summary": "OAuth callback과 cookie boundary를 BFF로 통합하기로 합의했다.",
  "captured_from": "conversation",
  "requested_kind": null,
  "kind_hint": "decision",
  "specialized_kinds": ["decision"],
  "fallback_kind": "observation",
  "scope_hint": "project/auth",
  "source_refs": ["conversation:codex/<task-id>"],
  "evidence": ["사용자가 최종 합의로 명시한 문장"],
  "tags": ["auth"],
  "search_terms": ["인증 주체", "세션 owner", "로그인 상태 소유권"],
  "owner_inputs": {
    "decision": {
      "decision": "인증 세션은 BFF가 소유한다.",
      "rationale": "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
      "rejected_alternatives": ["SPA token 소유: XSS 노출과 callback 분기가 커져 반려"],
      "decision_key": "session-owner"
    },
    "observation": {
      "observation": "대화에서 인증 세션을 BFF가 소유하기로 합의했다는 진술이 있었다.",
      "evidence": ["사용자가 최종 합의로 명시한 문장"]
    }
  }
}
```

필수 필드는 `schema`, `candidate_id`, `title`, `claim`, `summary`, `captured_from`, `specialized_kinds`, `fallback_kind`, `owner_inputs`다.

- `candidate_id`: `cand_`+32 lowercase hex의 batch-local transport ID. owner result와 route를 연결할 뿐 의미 동일성·중복·lifecycle을 보장하지 않는다.
- `requested_kind`: 사용자가 명시한 저장 type; 있으면 routing 최우선. 필드는 항상 존재하고 absent 의미는 JSON null이다.
- `kind_hint`: auditor의 비권위 분류 힌트. optional이며 absent는 key 생략, OBS fallback에서만 frontmatter로 복사한다.
- `captured_from`: `conversation | workspace | manual | import`; audit caller가 provenance를 알고 명시하며 owner가 추측하지 않는다.
- `specialized_kinds`: 현재 capability inventory에서 이 claim을 검증할 전문 kind, 우선순위 순 최대 2개. addon 전체 broadcast 금지
- `fallback_kind`: `observation | snapshot | null`. specialized owner가 모두 decline/부재한 뒤 호출할 core kind이며 auditor가 해당 owner input을 함께 제공한다.
- `scope_hint`: owner가 검증·정규화할 입력. decision specialized kind에서는 필수, 그 밖에는 생략한다.
- `evidence`: 분류에 필요한 짧은 근거만 포함; transcript 전체 금지
- `search_terms`: title·summary에 없는 동의어·과거 표현을 최대 12개까지 넣는 recall hint. 의미 동일성의 증명이나 capture gate가 아니다.
- `owner_inputs`: capability가 선언한 `draft_fields`만 담는 bounded opaque map. core router는 내용을 해석하지 않고 해당 owner에게만 전달한다.

auditor는 capability를 먼저 읽고 현재 대화를 **한 번만** 판독해 owner draft에 필요한 내용을 candidate에 넣는다. DEC의 결정·취지·반려대안, SNAP의 현재 맥락·열린 항목·다음 단계처럼 영속 문서의 핵심 section을 candidate 밖에서 승인 후 새로 만들 수 없다. owner가 필수 input이 부족하다고 판단하면 `decline` 또는 `needs_clarification`을 반환하며 transcript를 다시 읽지 않는다.

`owner_inputs`는 candidate당 2 KiB다. candidate batch의 canonical compact JSON UTF-8 합계는 16 KiB를 넘을 수 없다. 선언되지 않은 key와 원문 transcript blob은 거부한다. v1 값은 capability의 plain string/list/date/enum뿐이므로 별도 executable type은 존재하지 않으며 content를 shell/template로 평가하지 않는다.

한 발언에 사실·선택·실행 항목이 함께 있어도 OBS·DEC·TASK candidate를 각각 만들 수 있다. router는 ID나 문자열 정규화로 candidate 사이의 의미 동일성을 추정하지 않는다. 저장된 artifact와 중복되는지는 index로 후보를 좁힌 뒤 actual body를 읽은 semantic owner가 판정한다.

### Lifecycle semantic input

`same_claim`은 capture candidate에 대한 assertion이 아니라 predecessor와 successor가 같은 의미 자리를 인수하는지 판정하는 별도 operation이다. core가 current artifact와 complete successor draft에서 아래 bounded input을 만들며 owner는 transcript나 workspace를 다시 읽지 않는다.

```json
{
  "schema": "context-lifecycle-semantic-input/v1",
  "operation": "same_claim",
  "transition": "decision_fallback_import",
  "owner": "context-decision",
  "predecessor": {
    "id": "ctx_old",
    "kind": "observation",
    "path": "context/observation/합의-기록.md",
    "primary_claim": "인증 세션은 BFF가 소유하기로 합의했다.",
    "artifact_sha256": "sha256:...",
    "supporting_context": ["사용자가 최종 합의로 명시한 문장"]
  },
  "successor": {
    "id": "ctx_new",
    "kind": "decision",
    "path": "context/decision/인증-세션은-bff가-소유한다.md",
    "primary_claim": "인증 세션은 BFF가 소유한다.",
    "artifact_sha256": "sha256:...",
    "supporting_context": ["브라우저별 cookie 차이를 서버 경계 안으로 모은다."]
  },
  "source_candidate_digest": "sha256:..."
}
```

필수 key는 예시와 같고 `source_candidate_digest`만 manual lifecycle에서 JSON null일 수 있다. successor가 claim result에서 왔으면 이 값은 embedded `operation:"claim"` input digest와 exact match해야 한다. `transition`은 `observation_supersede | decision_fallback_import`다. `primary_claim`은 OBS의 `## 관찰`, DEC의 `## 결정` 전문이며 `artifact_sha256`은 해당 exact artifact bytes를 결박한다. `supporting_context`는 owner가 정한 핵심 근거/취지 projection 최대 4개·각 500 codepoint다. 전체 canonical JSON은 4 KiB 이하이며 path는 repository-relative canonical path다. core/owner CLI가 artifact ID·kind·path·SHA-256·actual claim과 successor result의 owner-validated semantic projection 일치를 구조적으로 검증한 뒤 owner skill에 전달한다.

### Semantic owner capability

storage에 area가 있다는 사실과 현재 host에서 write owner를 호출할 수 있다는 사실을 구분한다.

- `context.index.md`: 기존 artifact를 읽기 위한 storage discovery
- host가 노출한 installed skill inventory 또는 caller가 전달한 descriptor: 현재 write/claim capability discovery
- plugin cache directory 직접 탐색: 금지

owner는 transcript가 아닌 candidate만 받아 다음 descriptor와 결과를 제공한다. `batch_validation_surface`는 area-wide uniqueness/conflict invariant가 있는 addon에서 필수이고, 없는 owner는 생략한다. 이 surface는 semantic transcript가 아니라 current area index, selected owner result와 앞 same-area final bundle만 받는다.

```json
{
  "schema": "context-owner-capability/v1",
  "owner": "context-decision",
  "kind": "decision",
  "artifact_schema": "context-decision/v1",
  "authority": "authoritative",
  "claim_surface": {"type":"agent_skill","name":"context-decision:decision","operation":"claim"},
  "batch_validation_surface": {"type":"cli","command":"decision_cli.py batch validate"},
  "claim_rule": "현재 또는 미래 행동을 지배하는 명시적 선택이며 scope와 따를 의사가 있다",
  "claim_assertions": ["explicit_choice","scope_identified","commitment_present"],
  "lifecycle_operations": {
    "same_claim": {
      "surface": {"type":"agent_skill","name":"context-decision:decision","operation":"same_claim"},
      "rule": "decision-like OBS의 primary claim을 DEC가 같은 의미로 인수한다",
      "assertions": ["same_semantic_claim"]
    }
  },
  "draft_fields": {
    "required": {
      "decision": {"type":"string","min_chars":1,"max_chars":1200},
      "rationale": {"type":"string","min_chars":1,"max_chars":1200},
      "rejected_alternatives": {"type":"string_list","min_items":1,"max_items":8,"max_item_chars":500},
      "decision_key": {"type":"string","min_chars":1,"max_chars":80}
    },
    "optional": {
      "constraints": {"type":"string_list","max_items":8,"max_item_chars":240},
      "tradeoffs": {"type":"string_list","max_items":8,"max_item_chars":240},
      "revisit_when": {"type":"string_list","max_items":8,"max_item_chars":240},
      "revisit_on": {"type":"date"}
    }
  }
}
```

```json
{
  "schema": "context-owner-result/v1",
  "result_type": "claim",
  "transition": "capture",
  "owner": "context-decision",
  "target_kind": "decision",
  "candidate_id": "cand_550e8400e29b41d4a716446655440000",
  "decision": "claim",
  "reason": "explicit accepted choice",
  "capability_digest": "sha256:...",
  "semantic_inputs": [
    {
      "operation": "claim",
      "input_schema": "context-capture-candidate/v1",
      "input_digest": "sha256:...",
      "value": {
        "schema": "context-capture-candidate/v1",
        "candidate_id": "cand_550e8400e29b41d4a716446655440000",
        "title": "인증 세션 소유권",
        "claim": "인증 세션은 BFF가 소유한다",
        "summary": "OAuth callback과 cookie boundary를 BFF로 통합하기로 합의했다.",
        "captured_from": "conversation",
        "requested_kind": null,
        "kind_hint": "decision",
        "specialized_kinds": ["decision"],
        "fallback_kind": "observation",
        "scope_hint": "project/auth",
        "source_refs": ["conversation:codex/<task-id>"],
        "evidence": ["사용자가 최종 합의로 명시한 문장"],
        "tags": ["auth"],
        "search_terms": ["인증 주체", "세션 owner", "로그인 상태 소유권"],
        "owner_inputs": {
          "decision": {
            "decision": "인증 세션은 BFF가 소유한다.",
            "rationale": "브라우저별 cookie 차이를 서버 경계 안으로 모은다.",
            "rejected_alternatives": ["SPA token 소유: XSS 노출과 callback 분기가 커져 반려"],
            "decision_key": "session-owner"
          },
          "observation": {
            "observation": "대화에서 인증 세션을 BFF가 소유하기로 합의했다는 진술이 있었다.",
            "evidence": ["사용자가 최종 합의로 명시한 문장"]
          }
        }
      }
    }
  ],
  "semantic_attestations": [
    {
      "schema": "context-semantic-attestation/v1",
      "operation": "claim",
      "input_schema": "context-capture-candidate/v1",
      "input_digest": "sha256:...",
      "assertions": [
        {"name":"explicit_choice","value":true,"evidence_pointers":["/owner_inputs/decision/decision"]},
        {"name":"scope_identified","value":true,"evidence_pointers":["/scope_hint"]},
        {"name":"commitment_present","value":true,"evidence_pointers":["/evidence/0"]}
      ]
    }
  ],
  "artifact_drafts": [
    {
      "effect_id":"effect_create_dec",
      "path":"context/decision/인증-세션은-bff가-소유한다.md",
      "content":"---\nschema: \"context-decision/v1\"\n...\n---\n\n## 결정\n...",
      "semantic_projection":{"kind":"decision","primary_claim":"인증 세션은 BFF가 소유한다.","supporting_context":["브라우저별 cookie 차이를 서버 경계 안으로 모은다."]}
    }
  ],
  "effects": [
    {"effect_id":"effect_create_dec","action":"create","area":"decision","id":"ctx_...","state":"current"}
  ],
  "proposed_plan": {"schema":"context-owner-plan/v1","transition":"capture","operations":[{"op":"create","effect_id":"effect_create_dec","area":"decision","path":"context/decision/인증-세션은-bff가-소유한다.md"}]}
}
```

`context-owner-result/v1`은 `result_type`으로 구분하는 유일한 owner output envelope다.

- `result_type:"claim"`: `transition:"capture"`, `candidate_id`, `decision: claim|decline|needs_clarification`, reason, capability digest와 embedded claim input을 가진다. `claim`만 draft/effect/plan을 가질 수 있다. decline/clarification은 그것들을 금지한다.
- `result_type:"mutation"`: `decision`, `candidate_id`를 금지하고 domain transition, normalized `mutation_request` input, 필요한 predecessor/successor input과 complete after-content/effect/plan을 가진다. `snapshot_update`, `observation_annotate|reverify|invalidate|supersede`, `decision_annotate|supersede|withdraw`, `decision_fallback_import`, `rename`, `discard`만 v1 transition이다.
- 모든 result는 `owner,target_kind,capability_digest,semantic_inputs,semantic_attestations,artifact_drafts,effects,proposed_plan` key를 가진다. absent collection은 빈 array다. result의 canonical digest를 `owner_result_digest`라 부르며 object 안에는 넣지 않는다.

`mutation_request` input value는 `context-domain-mutation-input/v1`이며 `transition,owner,target_kind,requested_changes,targets,successor_owner_result_digest,successor_artifact_sha256`를 fixed key로 가진다. `targets`는 `{id,path,sha256}`의 path ASC array, `requested_changes`는 CLI가 정규화한 bounded JSON object, successor가 없으면 두 successor 값은 null이다. 전체는 8 KiB 이하이고 현재 artifact exact bytes 및 explicit user values와 대조한다. 이 input은 의미 attestation을 요구하지 않지만 승인 뒤 target/action/value를 바꿀 수 없게 owner result에 결박한다.

각 artifact draft는 `effect_id,path,content,semantic_projection`을 가진다. projection은 `kind,primary_claim,supporting_context` fixed shape이며 supporting context는 최대 4개·각 500 codepoint다. domain owner CLI는 projection과 자기 draft schema/body 일치를 검증한다. core는 exact artifact bytes/path와 projection shape를 검증하되 addon section 의미를 추측하지 않는다. `lifecycle prepare`는 actual primary claim과 이 projection 외의 addon body를 읽지 않는다.

v1 capture 최종 분류는 `claim | decline | needs_clarification`이다. semantic 판단은 descriptor의 `claim_surface` 또는 `lifecycle_operations.<operation>.surface`인 **owner agent skill**이 bounded input만 보고 수행한다. stdlib-only CLI는 attestation의 schema·input digest·JSON pointer 존재·required assertion이 모두 true인지 검증하고 document를 render할 뿐 idea와 accepted choice 또는 same-claim 의미를 스스로 판정하지 않는다. confidence score 경쟁, generic registry framework와 owner가 transcript를 다시 읽는 호출은 넣지 않는다.

`semantic_inputs`는 operation별 최대 하나이며 `{operation,input_schema,input_digest,value}` fixed shape다. `input_digest`는 `value` 전체의 canonical SHA-256이고 `value.schema == input_schema`여야 한다. capture는 `claim`, OBS supersede는 successor의 `claim`+lifecycle `same_claim`+`mutation_request`, DEC supersede는 successor `claim`+`mutation_request`, `decision_fallback_import`는 DEC `claim`+lifecycle `same_claim`+`mutation_request`를 요구한다. 그 밖의 허용 mutation은 `mutation_request`만 요구한다. claim result의 embedded candidate는 route batch의 같은 candidate와 canonical deep equality여야 한다.

`semantic_attestations`는 attestation 대상 operation별 최대 한 개다. attestation의 `operation:"claim"`은 `input_schema:"context-capture-candidate/v1"`와 capability `claim_assertions` exact set을, `operation:"same_claim"`은 `input_schema:"context-lifecycle-semantic-input/v1"`와 `lifecycle_operations.same_claim.assertions` exact set을 사용한다. 각 attestation `input_digest`는 같은 operation의 embedded semantic input digest와 같아야 한다. `mutation_request`에는 attestation을 붙이지 않는다.

각 attestation assertion name은 unique하고 모든 value는 JSON `true`다. `evidence_pointers`는 해당 attestation input 안의 RFC 6901 JSON Pointer 1~4개이며 각 target은 non-empty string/list여야 한다. `same_claim` pointer는 predecessor와 successor의 `primary_claim`을 각각 하나 이상 가리켜야 한다. CLI가 검증하는 것은 이 구조와 연결이지 의미적 진실이 아니다. owner skill의 판단과 사용자가 보는 complete preview가 의미적 gate다. descriptor에 없는 lifecycle operation, attestation 누락·중복·extra assertion은 실패한다.

semantic input digest와 `capability_digest`는 [[context-storage-retrieval]]의 approval canonical JSON 규칙을 각각 input value와 capability object 전체에 적용해 계산한다. result object 자신은 input digest에 포함되지 않는다.

`context-owner-validation-receipt/v1`의 공통 key는 `schema,owner,kind,owner_result_digest,base_area_index_sha256,prior_same_area_bundle_digests,validated_facts,status,receipt_digest`다. status는 성공 receipt에서 `valid` 하나뿐이다. prior list는 proposal order를 보존하고 result보다 앞서 finalize됐으며 같은 area를 touch한 모든 bundle digest와 exact match해야 한다. `validated_facts`는 owner-defined bounded one-level object이고 final plan에 그대로 포함한다. receipt digest는 자기 field를 제외한 전체 object의 canonical SHA-256이다. core는 이 구조·digest·coverage를 검증하지만 domain facts의 의미를 재판정하지 않는다. context-decision의 exact facts와 conflict algorithm은 [[context-decision-plugin]]이 정본이다.

### Host orchestration contract

router가 owner binary를 발견하거나 실행하지 않는다. host skill이 다음 호출 순서를 소유한다.

1. host installed skill inventory 또는 caller input에서 capability descriptor를 수집한다.
2. auditor가 descriptor의 `draft_fields`를 보고 candidate batch를 한 번 만든다.
3. host는 `requested_kind`가 있으면 그 owner skill 하나만 호출한다. 없으면 `specialized_kinds`의 owner skill을 순서대로 최대 2회 호출한다. addon 전체를 broadcast하지 않는다.
4. specialized result 중 claim이 있으면 fallback을 호출하지 않는다. 모두 `decline` 또는 owner 부재이고 `fallback_kind`가 있으면 해당 core owner skill을 한 번 호출한다. 하나라도 `needs_clarification`이면 fallback하지 않고 질문으로 종료한다. requested kind에는 어떤 fallback도 없다.
5. host는 candidate batch, 사용한 capability descriptor와 모든 claim result를 `context_cli.py candidate route --batch @file --capabilities @file --claim-results @file --json`에 전달한다.
6. router는 schema, candidate ID 중복, embedded candidate canonical equality, owner/kind, capability digest와 routing priority를 결정적으로 검증한다. owner를 호출하거나 candidate 간 의미 동일성을 판정하거나 semantic body를 생성하지 않는다.
7. 선택된 result를 proposal 순서대로 처리한다. capability가 `batch_validation_surface`를 선언하면 host는 current area index와 앞서 finalize된 **same-area** bundle을 해당 owner validator에 전달해 `context-owner-validation-receipt/v1`을 먼저 받는다. context-core built-in owner는 같은 검사를 coordinator library에서 직접 수행한다.
8. host는 result, optional validation receipt와 앞 bundle들을 `context_cli.py transaction preview --owner-result @file [--owner-validation @file] [--prior-bundle @file]... --json`에 전달한다. core는 앞 bundle expected after-state를 virtual precondition으로 사용하고, validation receipt가 요구되면 ordered same-area digest coverage를 확인한 뒤 final bundle화한다.
9. 실제 content/lifecycle effect와 final plan을 한 grouped approval로 제시하고, 승인된 `approval_digest`와 **동일 final bundle object**만 context-core coordinator의 `transaction apply`에 전달한다.

embedded candidate/capability digest가 달라지면 `claim_result_mismatch`로 실패한다. core는 addon body 의미를 비교하지 않으므로 owner가 candidate 외 입력을 사용하지 않았는지는 owner protocol test와 host call isolation으로 검증하고, 생성된 전체 내용은 approval preview에 노출한다. semantic claim owner 호출은 candidate당 specialized 최대 2회+fallback 최대 1회다. batch validator는 selected result당 최대 한 번 추가되지만 transcript를 읽지 않고 index+draft projection만 본다. 이 계약으로 addon 수가 늘어도 transcript 판독과 semantic claim 호출 수가 addon 전체 개수에 비례하지 않는다.

route JSON success result는 다음 fixed projection이다.

```json
{
  "schema":"context-route-result/v1",
  "routes":[
    {"candidate_id":"cand_...","status":"proposed","owner":"context-decision","target_kind":"decision","authority":"authoritative","reason":"specialized_owner","owner_result_digest":"sha256:..."}
  ],
  "conflicts":[],
  "skipped":[]
}
```

`status`는 `proposed | needs_clarification | owner_unavailable | owner_conflict | skipped`다. proposed만 exact owner-result digest를 가지며 이 digest는 `context-owner-result/v1` 전체의 canonical JSON SHA-256이다. host는 digest가 맞는 claim variant만 transaction preview로 넘긴다. 같은 candidate ID는 routes/conflicts/skipped 전체에서 정확히 한 번만 나타난다.

### Routing priority

```text
1. requested_kind가 있음
   ├─ owner available + claim → 그 owner만 제안
   ├─ owner available + decline/clarification → 오류/질문, 다른 type fallback 금지
   └─ owner unavailable → owner_unavailable, 조용한 OBS fallback 금지
2. installed specialized owner가 claim
   └─ primary owner 하나, core OBS fallback 억제
3. specialized owner가 없고 재사용 가능한 사실·근거
   └─ context-core OBS 제안
4. session resume/handoff 자체
   └─ SNAP 제안
5. durable value 없음
   └─ skipped, 기록 제안 없음
```

둘 이상의 specialized owner가 같은 candidate를 claim하면 파일을 쓰지 않고 `owner_conflict`로 사용자에게 type 선택을 요청한다. router가 기계적으로 검증하는 candidate 동일성은 중복 `candidate_id`뿐이며, 그 ID는 의미를 갖지 않는다. candidate끼리 또는 저장된 artifact와 의미가 같은지는 actual body comparison 결과 `same`이면 owner가 기존 문서를 제시하고 새 capture를 만들지 않는다. top-level `kind_hint`가 fallback OBS frontmatter의 유일한 정본이며 `owner_inputs.observation` 안에는 같은 field를 둘 수 없다.

`requested_kind`는 owner 선택을 강제할 뿐 schema·semantic validation을 우회하지 않는다. 예를 들어 사용자가 fact를 DEC로 요청해도 decision owner가 accepted choice로 검증하지 못하면 권위 DEC를 만들지 않는다.

core-only에서 decision-like candidate를 보존할 때는 다음처럼 **결정 자체가 아니라 결정으로 보이는 발언이 있었다는 observation**으로 바꿔 제안한다.

```text
target: observation
authority: non_authoritative
kind_hint: decision
claim: 대화에서 인증 세션을 BFF가 소유하기로 합의했다는 진술이 있었다.
```

`context-decision`이 설치된 경우 같은 claim은 DEC로만 제안한다.

### Grouped approval

route 결과는 사용자에게 한 번의 grouped proposal로 제시한다. 제목 목록만으로 승인받지 않고, 각 항목의 실제 draft와 lifecycle effect를 함께 보여준다.

```text
기록 후보 3개
1. [DEC] context/decision/인증-세션은-bff가-소유한다.md — authoritative
   결정: 인증 세션은 BFF가 소유한다.
   취지: 브라우저별 cookie 차이를 서버 경계 안으로 모은다.
   반려대안: SPA token 소유 — XSS 노출과 callback 분기가 커져 반려.
   lifecycle: create current DEC
   approval_digest: sha256:...
2. [OBS] ... — complete draft + lifecycle + digest
3. [SNAP] ... — complete draft + lifecycle + digest
```

계약:

- audit와 route는 filesystem byte를 변경하지 않는다.
- 사용자의 명시적 “이 내용을 기록해”는 그 요청에 모든 필수 semantic section과 lifecycle target이 이미 들어 있고 preview가 lossless formatting만 한 경우 해당 digest의 승인으로 인정한다. owner가 취지·반려대안·근거·후속 항목을 새로 추론하거나 보충했다면 반드시 complete preview를 먼저 보여주고 별도 승인을 받는다.
- grouped proposal의 canonical semantic preview는 target path, authority, 전체 artifact frontmatter/body section, predecessor/retire·conflict effect와 final plan summary, `approval_digest`를 포함한다. UI가 접어서 보여줄 수는 있지만 semantic 내용을 생략하거나 승인 뒤 생성할 수 없다. derived index와 policy marker 밖 기존 bytes는 path+before/after digest로 표시하고 final bundle hash로 봉인한다.
- grouped proposal에서는 사용자가 승인한 **approval digest**만 coordinator에 전달한다. 승인 뒤 owner가 draft·plan을 재생성하거나 변경하면 apply가 실패하고 새 승인을 받아야 한다.
- 사용자가 앞 item을 거절하고 그 digest를 `prior_bundle_digests`로 참조한 뒤 item만 승인하면 뒤 item을 현재 state에서 재-preview한다. dependency 없는 item은 prior chain을 만들지 않도록 area/path별 독립 chain으로 preview할 수 있다.
- domain mutation CLI는 complete bundle preview만 반환한다. 실제 write는 같은 bundle을 받은 `transaction apply --plan-bundle @file --approved-digest sha256:...`만 수행하며, approved digest는 caller가 승인을 확보했다는 assertion이지 CLI가 대화를 재판정한다는 뜻이 아니다.
- type 변경·권위 상승·OBS fallback→DEC import는 각각 명시 승인이 필요하다.
- 거절·보류 candidate를 영속 ledger에 저장하지 않는다. 같은 세션에서는 새 근거 없이 재제안하지 않는다.
- grouped approval은 UX 단위이지 multi-artifact atomic transaction이 아니다. final bundle은 proposal 순서와 `prior_bundle_digests`를 plan에 결박한다. 승인된 bundle을 같은 순서로 `transaction apply`하고 각 apply가 자기 root lock/precondition을 가진다. batch receipt는 item별 `applied|failed|not_attempted`, plan ID, changed paths를 묶는다. 한 item 실패 뒤 나머지는 실행하지 않으며 이미 성공한 item은 rollback하지 않는다. 남은 item은 current state에서 새 preview/digest가 필요하다. owner는 filesystem을 직접 쓰지 않는다.
- capture뿐 아니라 rename, metadata annotate, reverify, invalidate/withdraw, supersede, discard와 index fix도 durable mutation이다. 사용자가 현재 요청에서 exact target·action·모든 새 값/lifecycle effect를 명시하면 그 범위의 승인으로 인정할 수 있고, 그렇지 않으면 preview digest 승인이 필요하다. autonomous audit/maintenance는 `transaction apply`를 호출할 수 없다.
- complete preview가 32 KiB를 넘으면 핵심 section을 truncate하지 않고 `approval_preview_too_large`로 실패시켜 candidate를 나눈다.

### Recall budget

provider tokenizer에 종속되지 않도록 UTF-8 byte hard cap을 사용한다. 이 문서의 `1 KiB`는 1,024 bytes다.

| surface | default | hard rule |
|---|---:|---|
| audit candidates | 8개 | claim 320자, evidence 2개×240자, owner input 2 KiB/item, batch 16 KiB |
| grouped approval preview | 32 KiB | semantic section 또는 artifact 중간 절단 금지; 초과 시 재분할 |
| recall Stage 1 | 4 KiB | 기본 top 8, 최대 20 |
| section item | 2 KiB | 절단 시 `…`와 full-read hint |
| section/pack 합계 | 8 KiB | 낮은 순위 item부터 제외 |
| snapshot load brief | 4 KiB | 전문은 명시 read |
| user `--max-bytes` | 최대 32 KiB | 초과 인자 거부 |

budget을 넘으면 완전한 낮은 순위 record부터 제외하고 `truncated`, `returned`, `omitted`, narrowing hint를 반환한다. index 전체, 검색되지 않은 `search_terms`, transcript 원문을 model output에 포함하지 않는다.

### Recall output

공통 recall은 [[context-storage-retrieval]]의 index-first 후보 검색을 수행하고 domain authority를 다음 정도만 투영한다.

- SNAP: `authority=staging`, `use_as=resume_context`
- OBS: `authority=evidence`, `use_as=investigate_or_support`
- DEC current: `authority=authoritative`, `use_as=follow_decision`
- DEC/OBS history: lifecycle reason과 successor warning

core는 decision body를 해석하지 않는다. `decision brief`, conflict와 revisit는 `context-decision`이 선택된 DEC를 대상으로 수행한다.

## 취지

one auditor-many semantic owners는 addon 수에 따라 transcript 판독·token·제안 횟수가 증가하는 문제를 막는다. approval gate는 evidence에서 authority로의 오염을 막고, index-first bounded recall은 필요한 문서만 context에 넣는다.

## 구성요소

- [[context-plugin-definition]] — 공통 불변식과 owner 경계
- [[context-storage-retrieval]] — index-first 검색과 ID
- [[context-artifact-lifecycle]] — 승인 후 artifact 상태 전이
- [[context-core-plugin]] — auditor/router와 OBS fallback owner
- [[context-decision-plugin]] — decision claim validator
- [[DEC-2026-08-13-180535-capture-audit는-milestone-단위-단일-판독과-승인형-write를-지킨다]] — 본 계약의 결정 근거
