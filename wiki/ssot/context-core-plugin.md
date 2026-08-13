---
title: context-core 플러그인
created_at: 2026-08-13
summary: session handoff SNAP, 비권위 evidence OBS, semantic area catalog, index-first recall, 단일 capture audit·routing·grouped approval을 소유하는 가벼운 공통 context runtime의 구현 정본.
tags: [context-core, plugin, snapshot, observation, recall, ssot]
verified_at: 2026-08-13
affects_paths: [plugins/context-core/**]
---

## 현재 상태

`context-core` v1은 **설계 확정, 구현 전**이다. 기존 `wiki-markdown`의 snapshot/observation/index/recall 경험을 참고하지만 별도 plugin과 storage root로 새로 구현하며 자동 migration이나 호환성을 약속하지 않는다.

### 소유 범위

`context-core`가 소유한다.

- `context/context.index.md` area catalog
- `context/snapshot/`과 `snapshot.index.md`
- `context/observation/`과 `observation.index.md`
- 공통 document envelope·immutable ID·internal ref
- semantic index 문법, root/area search와 bounded recall
- 한 번의 capture audit에서 나온 candidate의 deterministic routing
- owner가 만든 complete draft의 grouped proposal/approval workflow
- semantic owner의 validated mutation plan을 적용하는 유일한 physical storage coordinator
- root area registration, cross-owner allowlist, 공통 advisory lock, filename/path guard와 integrity 검사
- agent policy scaffold: semantic milestone audit, approval 전 write 금지

소유하지 않는다.

- DEC의 본문·scope·conflict·supersede/revisit 의미 — [[context-decision-plugin]]
- TASK 실행·검증·lifecycle — 작업 plugin
- SSOT/runbook/knowledge의 domain schema
- 조직 권한·승인 queue·cross-project search·감사 — PCMS
- host transcript 수집, runtime hook, vector/embedding search

OBS는 core의 generic 미분류 쓰레기통이 아니라 **발견·근거라는 자체 의미를 가진 built-in semantic owner**다. core는 addon schema를 import하지 않는다.

### 계획 source layout

```text
plugins/context-core/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
├── README.md
├── rules/context-policy.md
├── skills/
│   ├── init/SKILL.md
│   ├── context/SKILL.md
│   ├── snapshot/SKILL.md
│   └── observation/SKILL.md
├── skills/context/
│   ├── scripts/context_cli.py
│   └── references/context-protocol.md
├── templates/
│   ├── snapshot.md
│   └── observation.md
└── tests/
    ├── test_storage_index.py
    ├── test_snapshot.py
    ├── test_observation.py
    ├── test_routing_recall.py
    ├── test_transaction_coordinator.py
    └── test_plugin_contract.py
```

Python stdlib-only 단일 CLI를 기준으로 한다. skill은 agent-facing contract이고 CLI는 deterministic filesystem operation과 JSON output을 담당한다.

### Public skills

| skill | 역할 |
|---|---|
| `context-core:init` | root/index/SNAP/OBS 구조와 auto-loaded agent policy를 멱등 설치·검증 |
| `context-core:context` | scoped recall, candidate route, grouped capture orchestration, refresh/schema |
| `context-core:snapshot` | explicit handoff save·merge·load·search·discard |
| `context-core:observation` | evidence capture·read·search·reverify·invalidate·supersede |

skill은 primary 사용자 요청을 먼저 수행한다. audit 결과가 없으면 capture 상태 메시지를 출력하지 않는다. 승인 없는 mutation 명령을 호출하지 않는다.

### CLI surface

```text
context_cli.py init [--json]
context_cli.py doctor [--json]
context_cli.py schema [--json]
context_cli.py capabilities [--json]
context_cli.py draft --kind snapshot|observation --candidate @file|@- --attestation @file [--json]
context_cli.py area register --descriptor @file --index-seed @file
                             [--json]
context_cli.py policy preview --target AGENTS.md|CLAUDE.md [--json]
context_cli.py lifecycle prepare --transition observation_supersede|decision_fallback_import
                                 --predecessor ID --successor-result @file|@- [--json]
context_cli.py transaction preview --owner-result @file|@-
                                   [--owner-validation @file]
                                   [--prior-bundle @file]... [--json]
context_cli.py transaction apply --plan-bundle @file --approved-digest SHA256 [--json]

context_cli.py candidate route --batch @file|@- --capabilities @file
                               --claim-results @file [--json]
context_cli.py recall [--query TEXT] [--area AREA]... [--include-history]
                      [--facet KEY=VALUE]... [--limit N] [--pack]
                      [--section NAME]... [--read ID]...
                      [--strict-index] [--max-bytes N] [--json]

context_cli.py snapshot save --title TEXT --summary TEXT [--filename NAME]
                             --captured-from conversation|workspace|manual|import
                             --attestation @file
                             --sec-context BODY --sec-open-items BODY --sec-next-steps BODY
                             [--sec-decided BODY] [--sec-refs BODY] [--sec-candidates BODY]
                             [--anchor ID]... [--source-ref REF]... [--tag TAG]...
                             [--json]
context_cli.py snapshot update --id ID [--title TEXT] [--summary TEXT]
                               [--merge] [--sec-context BODY] [--sec-open-items BODY]
                               [--sec-next-steps BODY] [--sec-decided BODY]
                               [--sec-refs BODY] [--sec-candidates BODY]
                               [--anchor ID]... [--source-ref REF]...
                               [--tag TAG]... [--search-term TERM]...
                               [--clear anchors|tags|search_terms|source_refs]
                               [--json]
context_cli.py snapshot list [--limit N] [--json]
context_cli.py snapshot search --query TEXT [--limit N] [--json]
context_cli.py snapshot load --id ID [--section NAME]... [--max-bytes N] [--json]
context_cli.py snapshot discard --id ID [--json]

context_cli.py observation capture --title TEXT --summary TEXT [--filename NAME]
                                   --captured-from conversation|workspace|manual|import
                                   --attestation @file
                                   --sec-observation BODY --sec-evidence BODY
                                   [--sec-impact BODY] [--sec-handling BODY] [--sec-followup BODY]
                                   [--kind-hint KIND] [--source-ref REF]... [--tag TAG]...
                                   [--json]
context_cli.py observation read --id ID [--section NAME]... [--max-bytes N] [--json]
context_cli.py observation search --query TEXT [--include-history] [--limit N] [--json]
context_cli.py observation annotate --id ID [--title TEXT] [--summary TEXT]
                                    [--tag TAG]... [--search-term TERM]... [--source-ref REF]...
                                    [--related ID]...
                                    [--clear tags|search_terms|source_refs|related]
                                    [--json]
context_cli.py observation reverify --id ID --verified-at RFC3339 --evidence-ref REF
                                    [--json]
context_cli.py observation invalidate --id ID --reason TEXT
                                      [--json]
context_cli.py observation supersede --id OLD --successor-result @file|@-
                                     --lifecycle-input @file
                                     --lifecycle-attestation @file [--json]

context_cli.py rename --id ID --filename NAME [--json]
context_cli.py discard --id ID [--json]
context_cli.py refresh [--level integrity|hygiene|all] [--strict]
                       [--fix index] [--json]
```

repository root의 `context/`가 유일한 v1 storage root이며 CLI에 `--root`는 없다. core-owned domain mutation과 init/area/policy 명령은 내부 `transaction preview`를 거쳐 final `context-mutation-bundle/v1`을 반환한다. addon owner result는 명시적으로 `transaction preview`에 전달한다. create ID와 `created_at`은 owner/core preview에서 한 번 생성되고 final bundle에 고정된다. caller는 final **동일 bundle object**를 보관해 `transaction apply --plan-bundle @file --approved-digest DIGEST`에 넘긴다. JSON whitespace 재직렬화는 허용하지만 apply 시 timestamp/ID/path/artifact content를 재생성하지 않는다.

`snapshot save`는 create-only다. `snapshot update`는 기본 full replacement이므로 세 필수 section을 모두 요구하고, `--merge`일 때만 지정한 section·metadata를 부분 변경한다. repeatable list flag는 full replacement에서 해당 list 전체를 대체하고 merge에서 하나라도 주어졌을 때 전체를 대체한다. full replacement에서 생략한 optional list는 empty, merge에서 생략한 list는 unchanged다. list를 명시적으로 비우려면 `--clear anchors|tags|search_terms|source_refs`를 사용하며 required body list는 clear할 수 없다. `observation supersede`는 successor result를 검증해 new OBS create와 old OBS retirement를 하나의 plan으로 만든다. 이미 존재하는 successor ID만 연결하는 비원자 명령은 없다.

`--successor-result`는 observation owner skill+`context_cli.py draft --kind observation`이 만든 complete claim result를 받으며 새 ID와 created_at이 고정된 artifact draft를 포함해야 한다. 먼저 `lifecycle prepare`가 current old artifact와 successor result의 owner-validated projection만으로 exact `context-lifecycle-semantic-input/v1`을 만든다. host는 그 object를 observation owner skill의 `same_claim` operation에 그대로 전달한다. supersede 명령은 successor result의 embedded claim input/attestation, byte-identical `--lifecycle-input`과 그 digest를 가리키는 `--lifecycle-attestation`을 검증해 두 lifecycle effect가 든 mutation variant를 내부 구성하고 `transaction preview`를 거친 final bundle을 반환한다. apply 전까지 세 단계 모두 filesystem write 0이다.

`lifecycle prepare`는 predecessor current bytes의 ID·path·primary claim/fingerprint와 successor result의 `semantic_projection`을 대조한다. 지원 transition 외에는 실패하고 semantic equality를 스스로 판정하지 않는다. 반환 input 전체가 attestation과 mutation result에 그대로 embedded되며 caller가 내용을 재작성하면 digest mismatch다.

`observation invalidate --reason`은 enum state `retired_reason:"invalidated"`와 free-text `retirement_note`로 분리해 persist한다.

direct `snapshot save`/`observation capture`는 CLI flags를 동일 complete `context-capture-candidate/v1` common fields+owner_inputs object로 먼저 정규화한다. `requested_kind`는 exact target kind, `specialized_kinds`는 그 kind 하나, `fallback_kind:null`, `claim_key:"direct"`, 새 candidate ID를 사용하고 그 object 전체를 claim semantic input으로 embed한다. `--attestation`의 JSON pointers를 그 exact object에 대해 검증한다. user-facing skill이 explicit 요청을 bounded candidate와 attestation으로 바꾸며 raw CLI가 semantic assertion을 발명하지 않는다.

CLI 표기의 `[--flag VALUE]...`는 repeatable option이다. `@file`은 UTF-8 file 전체, `@-`는 stdin 전체이며 두 입력은 command당 한 곳에서만 사용할 수 있다.

JSON success envelope은 `{"ok":true,"result":{...}}`다.

- `capabilities`: `context-owner-capabilities/v1` envelope 안의 SNAP·OBS `context-owner-capability/v1` 두 개
- `draft`: owner skill의 attestation을 구조 검증하고 matching candidate와 input을 embedded해 render한 claim variant `context-owner-result/v1`; semantic claim/decline은 CLI가 수행하지 않음
- `list/search/recall`: `items`, `returned`, `omitted`, `truncated`, `index_fallback`, `warnings`
- `load/read`: exact `artifact` metadata, 요청한 `sections`, authority/freshness와 `truncated`
- `lifecycle prepare`: exact `context-lifecycle-semantic-input/v1`, input digest, `applied:false`
- core domain mutation/`init`/`area register`/policy/index fix와 `transaction preview`: complete final `bundle`, `approval_preview`, `approval_digest`, `applied:false`
- `transaction apply`: `applied:true`, `plan_id`, `approval_digest`, `changed_paths`, `index_paths`, `warnings`

text mode는 사람이 읽는 projection일 뿐 host orchestration과 test는 JSON envelope만 계약으로 사용한다.

공통 exit code:

| code | 의미 |
|---:|---|
| 0 | 성공 또는 정상 preview |
| 2 | usage/schema/filename 오류 |
| 3 | root/artifact not found |
| 4 | read용 fuzzy ref가 ambiguous |
| 5 | lifecycle/owner/path conflict |
| 6 | integrity/index failure |

error JSON은 `{"ok":false,"error":{"code":"...","message":"...","details":{...}}}` 형태다.

### SNAP schema

frontmatter는 공통 envelope에 `updated_at`, optional `anchors`를 추가한다. fixed body section은 다음과 같다.

- 필수: `현재 맥락`, `열린 항목`, `다음 단계`
- 선택: `정해진 것`, `참조`, `capture 후보`

SNAP의 lifecycle과 load authority는 [[context-artifact-lifecycle]]을 따른다. 여러 named SNAP을 허용하며 각 ID만 하나의 mutable chain이다. snapshot search는 기본 index metadata만 사용하고 `load`에서 선택한 본문만 연다.

### OBS schema

frontmatter는 공통 envelope에 optional `kind_hint`, `source_claim_fingerprint`, `verified_at`, `affects_paths`, `relations.related`, `claim_fingerprint`를 추가한다. `kind_hint: decision` fallback은 candidate의 original decision-like claim fingerprint를 `source_claim_fingerprint`에 복사하고 OBS 자체의 진술 fingerprint와 구분한다. fixed body section은 다음과 같다.

- 필수: `관찰`, `근거`
- 선택: `영향`, `현재 처리`, `후속 조건`

OBS capture는 claim/evidence가 placeholder 또는 비어 있으면 실패한다. authority는 항상 `evidence/non_authoritative`다. core-only decision fallback은 `kind_hint: decision`을 가진 OBS일 뿐 DEC가 아니다.

### Built-in capability와 claim

`capabilities --json`은 다음 두 descriptor를 고정 순서로 반환한다.

```json
{
  "schema": "context-owner-capabilities/v1",
  "owners": [
    {
      "schema": "context-owner-capability/v1",
      "owner": "context-core",
      "kind": "snapshot",
      "artifact_schema": "context-snapshot/v1",
      "authority": "staging",
      "claim_surface": {"type":"agent_skill","name":"context-core:snapshot","operation":"claim"},
      "claim_rule": "사용자가 재개할 unfinished session handoff를 명시적으로 저장하려 한다",
      "claim_assertions": ["handoff_requested","unfinished_context_present"],
      "draft_fields": {
        "required": {
          "current_context": {"type":"string","min_chars":1,"max_chars":1200},
          "open_items": {"type":"string_list","min_items":1,"max_items":8,"max_item_chars":240},
          "next_steps": {"type":"string_list","min_items":1,"max_items":8,"max_item_chars":240}
        },
        "optional": {
          "decided": {"type":"string_list","max_items":8,"max_item_chars":240},
          "refs": {"type":"string_list","max_items":8,"max_item_chars":500},
          "capture_candidates": {"type":"string_list","max_items":8,"max_item_chars":240},
          "anchors": {"type":"string_list","format":"context_id","max_items":12,"max_item_chars":36}
        }
      }
    },
    {
      "schema": "context-owner-capability/v1",
      "owner": "context-core",
      "kind": "observation",
      "artifact_schema": "context-observation/v1",
      "authority": "evidence",
      "claim_surface": {"type":"agent_skill","name":"context-core:observation","operation":"claim"},
      "claim_rule": "나중에 조사·판단에 재사용할 수 있는 발견 또는 근거다",
      "claim_assertions": ["reusable_observation","evidence_present"],
      "lifecycle_operations": {
        "same_claim": {
          "surface": {"type":"agent_skill","name":"context-core:observation","operation":"same_claim"},
          "rule": "successor OBS가 predecessor OBS의 같은 관찰 claim을 교정하거나 더 정확히 인수한다",
          "assertions": ["same_semantic_claim"]
        }
      },
      "draft_fields": {
        "required": {
          "observation": {"type":"string","min_chars":1,"max_chars":1200},
          "evidence": {"type":"string_list","min_items":1,"max_items":4,"max_item_chars":500}
        },
        "optional": {
          "impact": {"type":"string","max_chars":800},
          "current_handling": {"type":"string","max_chars":800},
          "followup_conditions": {"type":"string_list","max_items":8,"max_item_chars":240}
        }
      }
    }
  ]
}
```

허용 field type은 `string`, `string_list`, `enum`, `date` 네 가지뿐이며 `required/optional` 외 key는 없다. optional `format:"context_id"`는 각 item이 `ctx_`+32 lowercase UUIDv4 hex인지 추가 검증한다. max는 Unicode codepoint 기준이고 candidate당 2 KiB hard cap이 더 작으면 hard cap을 우선한다. core snapshot/observation **agent skill**이 bounded candidate만 보고 claim attestation을 만들고, OBS supersede에서는 별도 bounded lifecycle input으로 `same_claim` attestation을 만든다. `draft --kind`는 해당 common candidate+`owner_inputs.<kind>`만 구조 검증·render한다. common `captured_from,title,summary,source_refs,tags`가 envelope 입력이고 top-level `kind_hint`만 OBS hint 정본이다. SNAP skill은 explicit handoff/resume intent가 없으면 decline하고, OBS skill은 재사용 가능한 claim+근거가 없으면 decline한다. attestation schema와 operation별 exact assertion 규칙은 [[context-capture-routing]]이 정본이다.

### Init과 policy

raw `context_cli.py init`은 storage-only `transition: core_init` final bundle을 만든다. repository에 `context/`가 전혀 없으면 directory 자체는 operation이 아니며 apply가 file parent를 `mkdir(mode=0755, parents=True, exist_ok=True)`로 만들고 built-in complete root/SNAP/OBS index seed material을 canonical generator에 전달한다. 생성 가능한 parent는 exact `context/`, `context/snapshot/`, `context/observation/`, `context/observation/retired/` allowlist뿐이고 non-directory/symlink 충돌은 실패한다. index file apply 전에 crash해 생긴 빈 allowlist directory는 재실행에서 absent와 동등하게 취급한다. 세 index가 모두 valid v1이면 `noop:true`로 끝난다. 일부 index만 있거나 schema/owner가 다르면 `partial_core_init`로 실패해 doctor 결과와 수동/승인 repair를 요구하며 임의 overwrite하지 않는다. schema major upgrade는 별도 migration 결정 없이는 수행하지 않는다.

1. repository root의 `context/`, SNAP, OBS area와 세 semantic index의 `index_rebuild(include_root:true)`를 preview한다.
2. 기존 사람 작성 index 설명과 일반 artifact를 보존한다.
3. 이미 root catalog에 등록된 addon area는 보존하되 addon 파일을 변경하지 않는다. 등록되지 않은 임의 폴더를 자동 claim하지 않는다.
4. runtime hook, session ledger와 activity heuristic은 만들지 않는다.

user-facing `context-core:init` skill은 storage bundle과 현재 host의 auto-loaded entry target을 위한 별도 policy bundle을 차례로 preview한다. Codex target은 repository root `AGENTS.md`, Claude Code target은 `CLAUDE.md`다. 같은 요청에서 두 host 지원을 명시하면 두 target을 각각 preview한다. grouped approval은 한 번 받을 수 있지만 apply는 bundle별 순차 transaction이며 partial success를 receipt에 표시한다.

`policy preview`는 exact repository-root basename 두 개만 받고 symlink는 거부한다. target이 없으면 `file_create`, 있으면 exact before digest의 `file_replace(role:"policy")` plan을 만든다. policy plan은 `transition: policy_install`, `owner_descriptor`는 built-in `context-core/policy` descriptor, effect action은 `install_policy`, `area`는 생략한다. marker는 정확히 한 쌍만 허용하고, marker 밖 UTF-8 bytes를 보존한다. 기존 file이 UTF-8이 아니거나 mixed newline이면 `policy_file_unsupported`로 실패해 수동 설치를 안내한다.

```markdown
<!-- BEGIN context-core-policy (managed by context-core) -->
## Shared context policy

- Substantive work에서 이전 결정·관찰·handoff가 판단을 바꿀 수 있으면 scoped index-first recall을 한 번 수행한다.
- Primary 요청과 답변을 먼저 끝낸다. semantic milestone 또는 closeout당 durable candidate audit은 최대 한 번만 수행한다.
- Candidate가 있을 때만 complete artifact preview를 한 grouped proposal로 보여준다. 승인 전에는 context artifact나 index를 쓰지 않는다.
- Current DEC는 authoritative, OBS는 non-authoritative evidence, SNAP은 resume staging으로 취급한다.
<!-- END context-core-policy (managed by context-core) -->
```

marker가 없으면 file 끝에 blank line 두 개를 경계로 block을 append하고, 한 쌍이면 block bytes만 replace한다. 두 쌍 이상·unbalanced marker는 실패한다. approval preview는 target, action과 위 managed block 전체를 보여주고 final plan/material digest는 marker 밖 보존 bytes까지 결박한다. `transition: policy_install`만 `context/` 밖의 exact 두 target과 `role:"policy"`를 허용한다. rollback은 Git restore 또는 새 policy preview이며 apply 중 crash는 일반 file operation resume 규칙을 따른다.

addon init은 root index를 직접 수정하지 않는다. `context-decision:init`처럼 owner descriptor와 complete area index seed를 만든 뒤 `area register --index-seed` preview를 호출하고, 승인된 plan만 coordinator가 seed material에서 새 area index를 만들고 root index에 등록한다. seed bytes와 generated output digest는 final plan에 결박되며 absent index를 seed 없이 추측 생성하지 않는다.

### Coordinator와 승인 경계

semantic owner는 schema·domain lifecycle을 검증하고 fully rendered after-content, effect와 proposed plan을 반환한다. context-core preview가 current byte precondition과 index rebuild를 붙인 final bundle을 만들고 coordinator만 root lock 아래 document/index를 실제 변경한다. cross-owner transition은 protocol allowlist에 있는 plan만 허용하며 v1에서는 `decision_fallback_import` 하나다.

capture audit의 claim result는 [[context-capture-routing]]의 complete artifact preview를 포함해야 한다. rename·annotate·reverify·invalidate·supersede·discard·index fix도 durable mutation이므로 사용자가 현재 요청에서 exact action·target·새 값과 lifecycle effect를 모두 명시했거나 preview digest를 승인한 경우에만 `transaction apply`할 수 있다. agent의 autonomous maintenance는 preview까지만 허용한다.

### Integrity/hygiene

blocking integrity:

- 예약 index 존재·schema·marker와 area/path 일치
- global duplicate ID
- artifact schema/필수 field/date/section
- path traversal, symlink root escape, reserved filename
- active/history path와 retired field 불일치
- internal ref 누락, supersede reciprocal edge/cycle
- index entry 누락·중복·wrong path/state
- root area/owner/claim 중복

non-blocking hygiene:

- stale SNAP
- OBS verified_at age 또는 changed affects_path
- missing/changed anchor
- 지나치게 긴 body, 검색 metadata 부족

auto-fix는 derived index만 허용한다. lifecycle, 본문과 relation은 자동 수정하지 않는다.

### Core-only behavior

| 입력 | 결과 |
|---|---|
| explicit handoff | SNAP preview/proposal |
| reusable fact/evidence | OBS preview/proposal |
| decision-like claim, decision owner 없음 | `kind_hint: decision` 비권위 OBS로 명시 제안 |
| explicit DEC 요청, decision owner 없음 | `owner_unavailable`; OBS downgrade 금지 |
| durable value 없음 | skip; 사용자-facing capture 문구 없음 |

### v1 acceptance

- init 두 번 실행 시 두 번째 filesystem diff 0
- prefix/timestamp 없는 filename과 immutable `ctx_*` ID 생성
- rename 뒤 ID/ref 보존, index path만 변경
- Stage 1 instrument 시 root/area index 외 artifact read 0
- Stage 1 instrument 시 directory listing과 artifact stat도 0; 전수 drift 검사는 strict refresh에서만 수행
- SNAP save→merge→load→discard에서 created_at 보존·retired 생성 0
- SNAP 여러 개를 독립 생성할 수 있고 각 ID만 update-in-place
- OBS supersede 한 plan에서 successor 생성과 predecessor history 이동, 반복 supersede history path 충돌 0
- core-only decision candidate가 DEC로 오인되지 않음
- owner claim→complete preview→digest 승인→coordinator apply에서 승인 뒤 draft 재생성 0
- route/capture와 모든 maintenance mutation이 승인 및 exact digest 전 byte-for-byte no-op
- addon area register와 fallback OBS→DEC가 root lock의 단일 coordinator를 우회하지 않음
- 누락/파손 index에서 area-only fallback과 strict-index fail 분리
- 두 병렬 mutation 뒤 duplicate ID와 lost index entry 0
- Obsidian 없이 기능 전체 동작, graph에서는 `context.index`→area index→artifact link가 보임

## 취지

context-core는 범용 지식 시스템이 아니라 session continuity와 evidence capture의 작은 공통 runtime이다. transcript 판독·저장·검색을 addon마다 복제하지 않으면서도 domain 의미는 semantic owner에 남겨 token과 결합도를 줄인다.

## 구성요소

- [[context-plugin-definition]] — 생태계 overview와 불변식
- [[context-storage-retrieval]] — 공통 저장/index/recall 계약
- [[context-artifact-lifecycle]] — SNAP·OBS lifecycle
- [[context-capture-routing]] — audit·owner·approval·budget
- [[context-v1-implementation]] — 구현 순서와 release gate
