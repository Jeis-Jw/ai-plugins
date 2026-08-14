---
title: context-decision 플러그인
created_at: 2026-08-13
summary: 결정·취지·반려대안을 하나의 권위 record로 보존하고 scope·decision key·conflict·supersede·withdraw·revisit와 결정 전용 recall을 소유하는 공개 제품의 구현 정본.
tags: [context-decision, plugin, decision, rationale, supersede, ssot]
verified_at: 2026-08-13
affects_paths: [plugins/context-decision/**]
---

## 현재 상태

`context-decision` v1은 **설계 확정, 구현 전**이다. 공개 제품의 전면은 범용 memory가 아니라 프로젝트·조직에서 “무엇을 왜 결정했고, 무엇을 반려했으며, 지금도 무엇을 따라야 하는가”를 복원하는 decision continuity다.

### 의존성과 소유 범위

`context-decision`은 [[context-core-plugin]]의 `context-common/v1` 저장·ID·index·recall 계약에 manual hard-depend한다. 요구 distribution identity는 `marketplace: jeis-ai-plugins`, `plugin: context-core`, selector `context-core@jeis-ai-plugins`, marketplace source `Jeis-Jw/ai-plugins`다. host-native dependency, 자동 설치·활성화·업데이트와 내장 core는 사용하지 않는다. exact core가 준비되지 않았거나 repository root가 초기화되지 않았으면 fail-closed하고 묵시적으로 다른 저장소를 만들지 않는다.

semantic 소유 범위:

- `context/decision/`과 `decision.index.md`
- decision candidate claim validator
- `context-decision/v1` schema
- `{결정 + 취지 + 반려대안}` 원자 단위
- `scope`, `decision_key`, current slot exclusivity
- conflict candidate, supersede, withdraw, revisit
- decision search, brief와 history
- decision artifact·index의 validated draft와 mutation plan

소유하지 않는 범위:

- transcript 전체 audit, grouped approval와 cross-area search — context-core
- SNAP·OBS schema와 lifecycle
- TASK/SSOT의 생성·상태·동기화
- 조직 approval workflow, 권한, audit queue와 cross-project conflict — PCMS

### 계획 source layout

```text
plugins/context-decision/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
├── README.md
├── rules/decision-policy.md
├── skills/
│   ├── init/SKILL.md
│   └── decision/SKILL.md
├── skills/decision/
│   ├── scripts/decision_cli.py
│   └── references/decision-protocol.md
├── templates/decision.md
└── tests/
    ├── test_decision_schema.py
    ├── test_decision_lifecycle.py
    ├── test_decision_conflicts.py
    ├── test_decision_recall.py
    ├── test_mutation_plan.py
    └── test_plugin_contract.py
```

decision CLI는 filesystem을 직접 쓰지 않는다. 자기 area와 허용된 fallback import의 semantic draft·plan을 만들고, [[context-storage-retrieval]]의 context-core coordinator가 유일한 physical writer로 적용한다. 공통 index row/schema fixture는 context-core protocol fixture와 parity test하며 core는 decision module을 import하지 않는다.

### Public skills

| skill | 역할 |
|---|---|
| `context-decision:init` | exact core를 확인하고 필요한 core bootstrap과 decision area/index를 한 호출로 멱등 등록 |
| `context-decision:decision` | candidate claim, capture, search/brief, conflict, supersede/withdraw/revisit |

직접 decision skill을 호출할 수 있지만, 일반 대화 closeout audit에서는 context-core가 만든 candidate만 받아 원문을 재판독하지 않는다.

### Manual dependency preflight

정적이고 filesystem-independent한 `schema`와 `capabilities`만 core 없이 호출할 수 있다. `context-decision:init`, `context-decision:decision` 및 repository/artifact에 접근하는 모든 operation은 작업 시작 전에 다음 순서의 read-only preflight를 통과해야 한다.

1. host의 plugin inventory에서 exact `marketplace=jeis-ai-plugins`, `plugin=context-core`를 찾는다. plugin cache path를 직접 탐색하거나 동명 plugin을 marketplace 구분 없이 수락하지 않는다.
2. exact plugin이 현재 scope에서 enabled/available인지 확인한다.
3. host가 노출한 core capability와 `context_cli.py doctor --json` receipt에서 `context-common/v1` 호환성을 확인한다.
4. repository state를 확인한다. 일반 operation은 `ready`를 요구하고, init은 `absent`를 installed core bootstrap-required state로 수락한다.

missing/source mismatch/disabled/incompatible/partial preflight 실패는 repository filesystem과 host configuration 모두 write 0이다. context-decision은 install, enable, update 또는 marketplace add를 실행하지 않는다. Exact compatible core가 installed/enabled이고 repository가 absent일 때만 그 core의 public bootstrap surface를 init orchestration으로 호출한다.

| code | 조건 | 안내 후 동작 |
|---|---|---|
| `core_missing` | exact `context-core@jeis-ai-plugins` 미설치 | provider marketplace `jeis-ai-plugins`의 plugin `context-core`를 사용자가 직접 설치 |
| `core_source_mismatch` | 다른 marketplace의 동명 core만 존재 | source `Jeis-Jw/ai-plugins`의 exact marketplace/plugin 좌표를 표시하고 중단 |
| `core_disabled` | exact core가 설치됐지만 현재 scope에서 비활성 | 사용자가 직접 올바른 scope에서 활성화 |
| `core_incompatible` | exact core가 `context-common/v1`을 제공하지 않음 | 사용자가 exact core를 호환 버전으로 직접 업데이트 |
| `core_uninitialized` | plugin은 준비됐지만 repository state가 `absent` | 같은 `context-decision:init` 호출에서 installed core bootstrap 뒤 area 등록 계속 |
| `partial_core_init` | repository state가 `partial` 또는 invalid | core doctor/repair 안내 후 중단; decision이 덮어쓰지 않음 |

모든 오류는 structured `required_plugin`을 포함한다.

```json
{
  "marketplace": "jeis-ai-plugins",
  "plugin": "context-core",
  "selector": "context-core@jeis-ai-plugins",
  "source": "Jeis-Jw/ai-plugins",
  "provider": "Jinwuk-Lee (Jeis-Jw)",
  "required_protocol": "context-common/v1"
}
```

missing/source mismatch/disabled/incompatible의 사람용 안내는 현재 host에 맞는 수동 설치·활성화·업데이트 방법, reload 또는 새 session, 마지막 `context-decision:init` 재실행 순서를 보여준다. scope는 사용자가 선택하며 command를 자동 실행 가능한 confirmation으로 제안하지 않는다. `core_uninitialized`는 host 설정을 바꾸지 않고 repository bootstrap phase로 진행한다.

### CLI surface

```text
decision_cli.py init [--json]
decision_cli.py schema [--json]
decision_cli.py capabilities [--json]
decision_cli.py draft --candidate @file|@- --attestation @file [--json]

decision_cli.py capture --title TEXT --summary TEXT --scope SCOPE --decision-key KEY
                        --captured-from conversation|workspace|manual|import
                        --attestation @file
                        --sec-decision BODY --sec-rationale BODY --sec-alternatives BODY
                        [--sec-constraints BODY] [--sec-tradeoffs BODY] [--sec-revisit BODY]
                        [--revisit-on YYYY-MM-DD] [--source-ref REF]... [--tag TAG]...
                        [--informed-by ID]...
                        [--ack-conflicts ID]... [--json]
decision_cli.py search [--query TEXT] [--scope SCOPE] [--decision-key KEY]
                       [--include-history] [--limit N] [--json]
decision_cli.py read --id ID [--section NAME]... [--max-bytes N] [--json]
decision_cli.py brief --query TEXT [--include-history] [--max-bytes N] [--json]
decision_cli.py brief --id ID [--id ID]... [--include-history] [--max-bytes N] [--json]
decision_cli.py conflicts --scope SCOPE --decision-key KEY [--candidate @file] [--json]
decision_cli.py supersede --id OLD --successor-candidate @file|@- --attestation @file
                          [--ack-conflicts ID]... [--json]
decision_cli.py import-fallback --id OBS --successor-result @file|@-
                                --lifecycle-input @file
                                --lifecycle-attestation @file
                                [--ack-conflicts ID]... [--json]
decision_cli.py withdraw --id ID --reason TEXT [--json]
decision_cli.py annotate --id ID [--title TEXT] [--summary TEXT]
                         [--tag TEXT]... [--search-term TEXT]... [--source-ref REF]...
                         [--clear tags|search_terms|source_refs] [--json]
decision_cli.py revisit [--due] [--id ID]... [--as-of YYYY-MM-DD] [--json]
decision_cli.py batch validate --owner-result @file|@-
                               [--prior-bundle @file]... [--json]
decision_cli.py plan validate --plan-bundle @file|@- [--json]
```

`init`은 owner descriptor와 decision area index seed를, `draft`·새 slot의 `capture`는 claim variant를, `supersede`·`import-fallback`·`withdraw`·`annotate`는 mutation variant의 complete `context-owner-result/v1`을 반환할 뿐 write하지 않는다. existing slot 대체는 `capture` option이 아니라 반드시 `supersede --id OLD`를 사용한다. context-decision init skill은 `decision_init.py` entrypoint 한 번으로 preflight 결과를 installed core의 public `context_cli.py bootstrap`에 넘겨 fixed core/area seed를 coordinator로 적용한다. 일반 mutation result와 `batch validate` receipt는 `context_cli.py transaction preview`에 넘겨 grouped approval에 포함하고 승인 뒤 `transaction apply`에 위임한다. rename·discard·index refresh는 decision owner의 plan validation을 거쳐 context-core 공통 명령을 사용한다. body `@file`/`@-`, JSON error와 exit code는 context-core 공통 계약을 따른다.

JSON success output은 context-core envelope을 따른다. owner skill과 `draft`·domain mutation이 합성한 결과는 discriminated `context-owner-result/v1`, `batch validate`는 `context-owner-validation-receipt/v1`, `search`는 index projection `items`, `read`는 exact DEC와 요청 section, `brief`는 bounded DEC core section projection, `conflicts/revisit`는 read-only candidate/warning 목록을 반환한다. final bundle/digest는 core `transaction preview`가 만든다. `[--flag VALUE]...`는 repeatable option이다.

### Capability와 claim rule

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
      "rule": "decision-like fallback OBS의 primary claim을 새 DEC가 같은 의미로 인수한다",
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

field type과 length semantics는 context-core capability 계약의 `string|string_list|enum|date`, Unicode codepoint 기준을 따른다. `date`는 Python `date.fromisoformat`이 수락하고 입력과 `YYYY-MM-DD` canonical output이 같은 실제 calendar date다. 실제 검토한 대안이 없으면 `rejected_alternatives` 한 항목을 `검토하지 않음: <이유>`로 채워 판단 상태를 명시한다.

다음을 모두 만족하면 decision claim이 될 수 있다.

1. 선택된 내용이 명시되어 있다.
2. 적용 대상 또는 scope를 정할 수 있다.
3. 현재 따르기로 합의했거나 결정 권한자의 확정 의사가 있다.

아이디어, 질문, 미합의 제안, 사실 발견, 단순 선호는 claim하지 않는다. 이들은 OBS 또는 skip 대상이다. 명시적 `requested_kind: decision`도 이 검증을 우회하지 않는다. 결정 후보의 근거가 부족하면 owner는 `decline`하거나 `needs_clarification`을 반환하고 권위 DEC를 만들지 않는다.

`context-decision:decision` skill이 candidate common fields와 `owner_inputs.decision`만 읽어 claim/decline/clarification과 semantic attestation을 만든다. common fields 중 `title,summary,captured_from,scope_hint,source_refs,tags,claim`이 DEC envelope·scope·fingerprint의 입력이다. `decision_cli.py draft`는 attestation과 field/schema를 결정적으로 검증해 exact candidate를 semantic input으로 embedded하고 DEC의 모든 필수 section, path/ID, conflict/lifecycle effect를 포함한 claim variant `context-owner-result/v1`을 render한다. ID와 `created_at`은 이 preview 때 한 번 생성되며 final bundle에 고정된다. skill과 CLI 모두 원문 transcript를 읽거나 승인 뒤 취지·반려대안을 보충할 수 없다.

direct `capture`도 flags를 complete `context-capture-candidate/v1`로 정규화한다. `requested_kind:"decision"`, `specialized_kinds:["decision"]`, `fallback_kind:null`, `claim_key:"direct"`, 새 candidate ID와 `owner_inputs.decision`을 사용해 exact object를 claim semantic input으로 embed한 뒤 `--attestation` pointer를 검증한다. raw CLI가 accepted choice 의미를 발명하지 않는다.

### DEC schema

```yaml
---
schema: "context-decision/v1"
id: "ctx_550e8400e29b41d4a716446655440000"
title: "인증 세션은 BFF가 소유한다"
summary: "OAuth callback과 cookie lifecycle을 BFF로 통합한다."
created_at: "2026-08-13T18:20:00+09:00"
captured_from: "conversation"
scope: "project/auth"
decision_key: "session-owner"
source_refs: ["file:src/auth/session.ts"]
tags: ["auth","BFF"]
search_terms: ["OAuth callback","session cookie"]
claim_fingerprint: "sha256:0123456789abcdef01234567"
revisit_when: ["브라우저가 first-party cookie도 차단할 때"]
revisit_on: "2027-02-01"
relations: {"informed_by":["ctx_..."]}
supersedes: ["ctx_..."]
---

## 결정

인증 세션은 BFF가 소유한다.

## 취지

브라우저별 cookie 차이를 서버 경계 안으로 모아 인증 흐름을 일관되게 한다.

## 반려대안

- SPA가 token을 직접 소유: XSS 노출과 callback 분기가 커져 반려.

## 근거와 제약

브라우저가 BFF의 first-party session cookie를 허용해야 한다.

## 트레이드오프

BFF가 callback, refresh와 logout 운영 책임을 추가로 가진다.

## 재평가 조건

주요 브라우저가 first-party cookie도 차단하면 재평가한다.
```

규칙:

- `scope`: `/`로 계층화한 canonical string, 필수
- `decision_key`: scope 안에서 안정적인 canonical topic slug, 필수
- 같은 `(scope, decision_key)`에는 current DEC가 최대 하나
- successor는 predecessor의 scope/key를 그대로 상속
- `결정`, `취지`는 substantive 필수
- `반려대안` section은 반드시 존재한다. 실제 대안이 없으면 `검토하지 않음: <이유>`를 기록한다.
- `근거와 제약`, `트레이드오프`, `재평가 조건`은 선택이지만 section 계약은 고정한다.
- `verified_at`과 공통 `status`는 금지한다.
- `relations.informed_by`는 OBS 같은 독립 evidence ID를 참조한다.
- `supersedes`는 같은 slot의 DEC 또는 [[context-artifact-lifecycle]]이 허용한 decision-like fallback OBS만 참조한다.

scope/key canonicalization은 다음 하나만 사용한다.

1. 입력 전체를 NFKC+casefold하고 trim한다. scope는 leading/trailing `/`를 제거한 뒤 `/`로 split한다. 내부 empty segment(`//`)는 오류다. decision key에 `/`는 오류다.
2. 각 segment/key에서 `str.isalnum()` codepoint는 보존하고 그 밖의 연속 run은 `-` 하나로 바꾼 뒤 양끝 `-`를 제거한다.
3. empty, `.`/`..`, segment 40 codepoint 초과, scope 8 segment/160 codepoint 초과, key 80 codepoint 초과는 exit 2다.
4. canonical value만 frontmatter/index/slot key에 쓴다. 예: `Project/Auth/`→`project/auth`, `session owner`와 `session_owner`→`session-owner`다.

scope ancestor는 canonical segment array의 **strict prefix**다. equality는 exact slot이고 문자열 prefix(`project/a` vs `project/auth`)는 ancestor가 아니다.

`supersede --id OLD`의 successor candidate는 canonical `scope_hint`와 `decision_key`가 OLD slot과 exact match해야 한다. omitted value를 CLI가 추론해 채우지 않고, 다르면 `successor_slot_mismatch`로 실패한다. fallback OBS import는 새 DEC가 명시한 slot을 사용하되 OBS에는 DEC slot exclusivity가 없으므로 같은-claim/active slot 검증을 별도로 통과해야 한다.

### Conflict contract

CLI가 결정할 수 있는 v1 conflict는 좁게 유지한다.

1. exact `(scope, decision_key)` current가 존재하면 hard conflict다. 새 `capture`는 항상 `decision_slot_conflict`로 실패하며 기존 DEC를 `supersede --id OLD`로 명시해야 한다.
2. 같은 `decision_key`이며 scope가 ancestor/descendant 관계면 `conflict_candidates`로 반환한다. apply에는 `--ack-conflicts` 또는 명시적 supersede가 필요하다. 승인 preview는 acknowledged ID를 표시하고 plan `read_preconditions`에 각 conflict의 exact current path/content digest를 넣는다. apply 시 하나라도 바뀌거나 새 overlap conflict가 생기면 `conflict_set_changed`로 재-preview를 요구한다.
3. fingerprint가 동일하면 `duplicate_claim`으로 새 capture를 막고 기존 DEC를 반환한다.
4. 다른 key 사이의 semantic contradiction은 CLI가 추측하지 않는다. owner skill이 index 검색 후보를 사용자에게 제시한다.

conflict 후보가 있다는 사실만으로 자동 supersede하지 않는다.

### Lifecycle

DEC의 의미 변경은 새 artifact 생성이다. 자세한 전이는 [[context-artifact-lifecycle]]이 정본이다.

- `supersede`: successor draft로 new current 생성, old를 deterministic history path로 이동, 양방향 ID edge를 한 mutation plan에 포함
- `withdraw`: successor 없이 old를 `retired/`, `retired_reason: withdrawn`
- `withdraw --reason`: free-text reason을 retired DEC의 `retirement_note`로 persist
- `revisit`: 조건 충족 가능성을 review proposal로 반환, 상태 변경 0
- `revisit_on`: optional canonical `YYYY-MM-DD`; capture/supersede owner input 또는 direct `--revisit-on`에서 설정하며 index projection으로 due를 계산
- TASK·SSOT 생성: DEC 유지
- metadata correction: 의미를 바꾸지 않는 범위에서 제자리 수정

core-only fallback OBS를 DEC로 import하려면 `kind_hint: decision`, OBS `source_claim_fingerprint`와 DEC fingerprint exact match, [[context-capture-routing]]의 bounded old/new lifecycle input에 대한 owner skill의 `same_claim` attestation과 별도 승인이 필수다. 먼저 DEC claim result를 만들고 core `lifecycle prepare --transition decision_fallback_import`로 exact input을 만든 뒤, 그 input을 decision owner skill의 `same_claim` operation에 전달한다. `import-fallback`은 DEC claim result, lifecycle input과 attestation을 검증해 mutation variant의 owner result를 만든다. 이 결과는 DEC candidate의 embedded `claim` input/attestation과 lifecycle `same_claim` input/attestation을 모두 포함한다. decision owner는 OBS after-content까지 직접 쓰지 않고 `decision_fallback_import` cross-owner plan을 만든다. core coordinator가 OBS retire와 DEC create를 root lock 아래 함께 적용한다. 일반 evidence OBS는 retire하지 않고 `informed_by`로 연결한다.

### Same-batch domain validation

`context-decision` capability는 `batch_validation_surface`를 필수로 선언한다. host는 routing이 끝난 뒤 decision owner result를 proposal 순서대로 하나씩 `batch validate`한다. 첫 result는 current `decision.index.md`, 이후 result는 current index 위에 앞서 finalize된 **같은 decision area** bundle들의 expected after-state를 순서대로 overlay한 virtual index를 사용한다. candidate transcript는 다시 읽지 않는다.

성공 receipt는 다음 fixed shape다.

```json
{
  "schema": "context-owner-validation-receipt/v1",
  "owner": "context-decision",
  "kind": "decision",
  "owner_result_digest": "sha256:...",
  "base_area_index_sha256": "sha256:...",
  "prior_same_area_bundle_digests": ["sha256:..."],
  "validated_facts": {"scope":"project/auth","decision_key":"session-owner","claim_fingerprint":"sha256:0123456789abcdef01234567","acknowledged_conflicts":[]},
  "status": "valid",
  "receipt_digest": "sha256:..."
}
```

`base_area_index_sha256`는 grouped preview 시작 시 physical `decision.index.md`의 exact digest이며 batch 내 모든 DEC receipt에서 같다. `prior_same_area_bundle_digests`를 그 base 위에 proposal order로 overlay해 이 result 직전 virtual Current set을 만든다. `receipt_digest`는 자기 field를 제외한 object의 canonical SHA-256이다. `validated_facts` key order는 예시 그대로이며 값은 owner result draft에서 다시 계산한다. validator는 virtual Current set에 exact slot·ancestor/descendant conflict·duplicate fingerprint·supersede predecessor 상태를 적용한다. exact slot 중복, 승인되지 않은 overlap, 이미 앞 bundle에서 retire된 predecessor면 receipt를 만들지 않고 domain error를 반환한다. core `transaction preview`는 capability가 이 surface를 선언한 owner result에 receipt를 필수로 요구하고 result digest, batch base index, 모든 앞선 same-area bundle digest의 **exact ordered list**와 receipt digest를 구조적으로 검증해 final plan에 포함한다. apply는 이를 approval material과 current/prior precondition으로 다시 검증한다. 따라서 같은 grouped approval 안의 두 DEC도 base filesystem만 보고 독립 통과할 수 없다.

### Decision recall

공통 search는 `decision.index.md`의 title·summary·terms·scope·decision_key·revisit_on으로 후보를 찾는다. `projection_fields`는 이 세 domain field다. decision plugin은 선택된 후보에만 domain projection을 추가한다. `revisit --due --as-of D`는 current row의 `revisit_on <= D`를 비교하며 `--as-of` 기본값은 repository timezone이 아니라 caller가 명시하지 않은 경우 local system date다; JSON 결과에 실제 `as_of`를 항상 반환한다.

`brief` 기본 출력:

- current DEC title/summary/scope/key
- `결정`, `취지`, `반려대안` bounded snippet
- predecessor/successor와 conflict warnings
- revisit due 여부
- `informed_by` OBS ID와 label; evidence 전문은 자동 로드하지 않음

기본은 current만 권위 있게 반환한다. history를 포함해도 retired DEC에는 `do_not_follow`와 lifecycle reason을 붙인다. 8 KiB budget을 넘으면 낮은 순위 artifact를 제외하고 전문 자동 로드를 금지한다.

### Init·packaging gate

`init`은 위 manual dependency preflight를 먼저 수행한다. missing/source mismatch/disabled/incompatible/partial이면 owner descriptor나 index seed를 만들지 않고 structured error와 수동 next action만 반환한다. exact core가 ready 또는 absent이면 owner descriptor와 complete `decision.index.md` seed를 생성하고 installed core의 public `bootstrap` surface에 전달한다. core coordinator가 absent core seed를 먼저 적용하고 `context/decision/`, decision index와 root area entry를 등록한다. 두 phase는 `applied|noop|failed`와 changed paths를 반환한다. coordinator가 남긴 exact canonical root-row prefix만 재시도에서 area index write를 계속하며, 동일 descriptor/index가 이미 valid면 noop이다. descriptor의 owner/authority/artifact_schema 등 canonical fields가 다르거나 임의 partial content/다른 owner claim이면 write 0 fail-closed다.

두 host의 `.claude-plugin/plugin.json`과 `.codex-plugin/plugin.json`에는 plugin dependency metadata를 넣지 않는다. marketplace entry도 context-decision 설치를 이유로 context-core를 `INSTALLED_BY_DEFAULT` 처리하지 않는다. README와 init error는 provider marketplace `jeis-ai-plugins`, plugin `context-core`, source `Jeis-Jw/ai-plugins`를 정확히 표시하되 marketplace 추가·plugin 설치·활성화·업데이트를 실행하지 않는다. host별 command/GUI 안내는 distribution adapter가 현재 host surface에 맞춰 render하며 scope 선택은 사용자에게 남긴다.

plugin cache path 추측이나 두 개의 독립 core 구현을 만들지 않는다. manual preflight와 양 host 안내의 검증이 공개 release gate다.

### v1 acceptance

- 핵심 3 section 누락·placeholder capture 실패
- idea/question/fact candidate claim 거부, accepted choice만 claim
- claim result가 핵심 3 section의 complete draft와 owner-result digest를 포함하고, core final bundle의 approval digest가 승인된 뒤 내용 생성 0
- 동일 slot의 current DEC 두 개 생성 불가
- exact slot supersede 시 old/new edge와 Current/History index 일치
- ancestor/descendant scope conflict가 proposal에 표시되고 ack 전 apply 실패
- withdraw가 successor 없이 history로 이동하고 current recall에서 제외
- revisit due가 warning만 만들고 filesystem diff 0
- core-only와 core+decision에서 동일 claim의 OBS/DEC 중복 제안 0
- fallback OBS import와 evidence OBS 참조가 서로 다른 lifecycle을 따름
- decision CLI physical write 0; init과 모든 mutation이 core coordinator를 통해서만 적용
- Stage 1에서 DEC 전문 read 0, brief에서 선택된 DEC만 read
- decision plugin 제거 후 기존 area는 core recall로 읽히되 새 DEC write owner로 간주되지 않음
- 양 host manifest와 marketplace entry의 dependency/implicit-install metadata 0
- exact core missing/source mismatch/disabled/incompatible이면 repository·host config write 0, 정확한 provider marketplace/plugin/source와 reload·재실행 안내
- core repository absent이면 `core_missing`이 아니라 `core_uninitialized`, installed core bootstrap으로 core+decision ready

## 취지

AI agent의 client-local memory와 달리 DEC는 repository에 남아 사람과 여러 agent가 공유한다. 결정·취지·반려대안을 원자화하고 current slot과 supersede를 관리해야 “무슨 결정을 따라야 하는가”를 짧은 context로 복원할 수 있다.

## 구성요소

- [[context-plugin-definition]] — 공통 불변식과 제품 경계
- [[context-storage-retrieval]] — decision index와 ID
- [[context-artifact-lifecycle]] — DEC 상태 전이와 OBS import
- [[context-capture-routing]] — candidate claim과 approval
- [[context-v1-implementation]] — 구현 및 release gate
- [[DEC-2026-08-13-233319-context-decision은-context-core를-사용자가-직접-설치한-뒤에만-동작한다]] — manual hard dependency와 정확한 distribution identity
