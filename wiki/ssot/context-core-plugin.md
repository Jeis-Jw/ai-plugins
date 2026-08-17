---
title: context-core 플러그인
created_at: 2026-08-13
summary: 대화에서 생긴 재사용 가치 있는 프로젝트 맥락을 index-first로 회수하고, semantic owner 비교와 사용자 승인 뒤에만 보관하는 가벼운 Git/Markdown 공통 runtime의 제품·구현·평가 정본.
tags: [context-core, plugin, snapshot, observation, recall, ssot]
verified_at: 2026-08-17
affects_paths: [plugins/context-core/**]
---

## 현재 상태

`context-core` 0.2.0은 구현되어 deterministic test와 교차 플러그인 fixture로 검증한다. 목적은 대화 전체를 기억하는 범용 memory가 아니라, 이후 판단을 바꿀 수 있는 프로젝트 맥락을 필요한 순간에 회수하고 보관 가치가 생긴 시점에 승인형 capture로 연결하는 것이다. 기존 `wiki-markdown`의 snapshot/observation/index/recall 경험을 참고하지만 별도 plugin과 storage root를 사용하며 자동 migration이나 호환성을 약속하지 않는다.

현재 제품 판정은 **source와 contract는 구현·검증됐고, 실제 host/consumer 운영성은 부분 검증**이다. 문서나 test가 존재한다는 이유만으로 운영 완료로 판정하지 않는다.

| 평가 축 | 현재 판정 | 확인 근거 | 남은 경계 |
|---|---|---|---|
| 제품 취지·domain 경계 | 확정 | 이 SSOT, [[context-plugin-definition]], [[context-capture-routing]], active fingerprint 제거 v2 결정 | 실제 사용에서 recall/capture 제안이 충분히 유용한지는 계속 관찰 필요 |
| core source·공개 계약 | 구현 | `plugins/context-core/**`, `context-common/v2`, 0.2.0 manifests | 0.1.x와 wire/storage 호환 없음 |
| deterministic 검증 | 통과 | 이 변경 worktree에서 `python3 -m unittest discover`로 `context-core` 75 tests, `context-v1` 26 tests, `context-decision` 34 tests를 실측했고 repo-root `pytest`로 decision 34 tests+14 subtests를 확인 | test는 실제 장기 대화의 의미 품질을 대신하지 않음 |
| index 효율성 | 구현·계측 | Stage 1 synthetic explicit/cross-area query에서 artifact open/read/stat와 artifact directory listing 0, bounded output 검증 | 대규모 실제 corpus의 recall precision/false negative는 별도 측정 필요 |
| Codex 설치본 실행 | 부분 운영 검증 | 현재 Codex skill catalog에서 0.2.0이 발견되고 `capabilities --json` 실행 성공 | client별 설치·reload·upgrade UX의 반복 검증은 부족 |
| Claude Code·Linux | 미확인 | static contract와 platform test만 존재 | 실제 host inventory와 live filesystem flow 필요 |
| legacy consumer data | 점진 정리 | 제거된 fingerprint field는 `schema_removed_field` warning으로 읽고, 해당 artifact의 다음 승인 write에서 lazy-clean한다. index drift도 warning이며 즉시 rebuild 가능 | artifact 본문·lifecycle은 자동 수정하지 않음 |
| GitHub 배포 표면 | source 공개 | 두 host manifest와 marketplace catalog가 0.2.0으로 정렬되고 `main@c98623a` push | tag·release artifact와 각 client UI 노출은 별도 상태 |

이 표의 판정은 `verified_at` 시점의 snapshot이다. 다른 세션은 아래 평가 규칙에 따라 현재 code/runtime evidence를 다시 확인하고, 확인하지 않은 항목을 `완료`로 승격하지 않는다.

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

### Source layout

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
| `context-core:init` | root/index/SNAP/OBS canonical seed를 한 호출로 멱등 적용·검증 |
| `context-core:context` | scoped recall, candidate route, grouped capture orchestration, refresh/schema |
| `context-core:snapshot` | explicit handoff save·merge·load·search·discard |
| `context-core:observation` | evidence capture·read·search·reverify·invalidate·supersede |

skill은 primary 사용자 요청을 먼저 수행한다. audit 결과가 없으면 capture 상태 메시지를 출력하지 않는다. 승인 없는 mutation 명령을 호출하지 않는다.

### CLI surface

```text
context_cli.py init --host codex|claude-code [--json]
context_cli.py bootstrap --descriptor @file --index-seed @file
                         --host codex|claude-code [--json]
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
                             [--search-term TERM]...
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
                                   [--search-term TERM]...
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
context_cli.py observation discard --id ID [--json]

context_cli.py rename --id ID --filename NAME [--json]
context_cli.py discard --id ID [--json]
context_cli.py refresh [--fix index] [--json]
```

repository root의 `context/`가 유일한 v1 storage root이며 CLI에 `--root`는 없다. core-owned domain mutation과 init/area/policy 명령은 내부 final `context-mutation-bundle/v1` 검증을 통과한다. 명시적 `init`과 addon init의 `bootstrap`만 fixed `core_init|area_register|policy_install` bundle을 coordinator로 즉시 적용하고, 나머지는 exact digest 승인 뒤 `transaction apply`한다. addon owner result는 명시적으로 `transaction preview`에 전달한다. create ID와 `created_at`은 owner/core preview에서 한 번 생성되고 final bundle에 고정된다. caller는 final **동일 bundle object**를 보관해 `transaction apply --plan-bundle @file --approved-digest DIGEST`에 넘긴다. JSON whitespace 재직렬화는 허용하지만 apply 시 timestamp/ID/path/artifact content를 재생성하지 않는다.

`snapshot save`는 create-only다. `snapshot update`는 기본 full replacement이므로 세 필수 section을 모두 요구하고, `--merge`일 때만 지정한 section·metadata를 부분 변경한다. repeatable list flag는 full replacement에서 해당 list 전체를 대체하고 merge에서 하나라도 주어졌을 때 전체를 대체한다. full replacement에서 생략한 optional list는 empty, merge에서 생략한 list는 unchanged다. list를 명시적으로 비우려면 `--clear anchors|tags|search_terms|source_refs`를 사용하며 required body list는 clear할 수 없다. `observation supersede`는 successor result를 검증해 new OBS create와 old OBS retirement를 하나의 plan으로 만든다. 이미 존재하는 successor ID만 연결하는 비원자 명령은 없다.

`--successor-result`는 observation owner skill+`context_cli.py draft --kind observation`이 만든 complete claim result를 받으며 새 ID와 created_at이 고정된 artifact draft를 포함해야 한다. 먼저 `lifecycle prepare`가 current old artifact와 successor result의 owner-validated projection만으로 exact `context-lifecycle-semantic-input/v1`을 만든다. host는 그 object를 observation owner skill의 `same_claim` operation에 그대로 전달한다. supersede 명령은 successor result의 embedded claim input/attestation, canonical-JSON으로 동등한 `--lifecycle-input`과 그 digest를 가리키는 `--lifecycle-attestation`을 검증해 두 lifecycle effect가 든 mutation variant를 내부 구성하고 `transaction preview`를 거친 final bundle을 반환한다. apply 전까지 세 단계 모두 filesystem write 0이다.

`lifecycle prepare`는 predecessor current bytes의 ID·path·SHA-256·실제 primary claim과 successor result의 같은 artifact identity·`semantic_projection`을 대조한다. 지원 transition 외에는 실패하고 semantic equality를 스스로 판정하지 않는다. 반환 input 전체가 attestation과 mutation result에 그대로 embedded되며 caller가 내용을 재작성하면 digest mismatch다.

`observation invalidate --reason`은 enum state `retired_reason:"invalidated"`와 free-text `retirement_note`로 분리해 persist한다.

direct `snapshot save`/`observation capture`는 CLI flags를 동일 complete `context-capture-candidate/v1` common fields+owner_inputs object로 먼저 정규화한다. `requested_kind`는 exact target kind, `specialized_kinds`는 그 kind 하나, `fallback_kind:null`, 새 transport-only candidate ID를 사용하고 그 object 전체를 claim semantic input으로 embed한다. `--attestation`의 JSON pointers를 그 exact object에 대해 검증한다. user-facing skill이 explicit 요청을 bounded candidate와 attestation으로 바꾸며 raw CLI가 semantic assertion을 발명하지 않는다.

CLI 표기의 `[--flag VALUE]...`는 repeatable option이다. `@file`은 UTF-8 file 전체, `@-`는 stdin 전체이며 두 입력은 command당 한 곳에서만 사용할 수 있다.

JSON success envelope은 `{"ok":true,"result":{...}}`다.

- `capabilities`: `context-owner-capabilities/v1` envelope 안의 SNAP·OBS `context-owner-capability/v1` 두 개
- `doctor`: read-only `context-core-doctor/v1`; supported protocol, repository state, blocking `issues`와 non-blocking `warnings`를 반환하고 filesystem을 변경하지 않음
- `draft`: owner skill의 attestation을 구조 검증하고 matching candidate와 input을 embedded해 render한 claim variant `context-owner-result/v1`; semantic claim/decline은 CLI가 수행하지 않음
- `list/search/recall`: `items`, `returned`, `omitted`, `truncated`, `index_fallback`, `warnings`
- `load/read`: index-first exact ID resolution, exact `artifact` metadata, 요청한 `sections`, authority/freshness, `warnings`와 실제 byte budget 기반 `truncated`; stale/missing lookup은 `index_lookup_fallback`
- `lifecycle prepare`: exact `context-lifecycle-semantic-input/v1`, input digest, `applied:false`
- `init`/`bootstrap`: `context-core-bootstrap-result/v1`, ordered `core_init|area_register|policy_install`의 `applied|noop` phase, changed paths, post-apply doctor와 host policy receipt
- 일반 core domain mutation/`area register`/policy와 `transaction preview`: complete final `bundle`, `approval_preview`, `approval_digest`, `applied:false`
- `refresh --fix index`: derived index만 root lock 아래 즉시 rebuild하고 `applied|noop`, `changed_paths`, 잔여 `issues|warnings`를 반환; approval bundle 없음
- `transaction apply`: `applied:true`, `plan_id`, `approval_digest`, `changed_paths`, `index_paths`, `warnings`

text mode는 사람이 읽는 projection일 뿐 host orchestration과 test는 JSON envelope만 계약으로 사용한다.

`snapshot load`와 `observation read`의 `--max-bytes`는 result object 기준 1..32768 bytes다. section을 prefix 단위로 줄여도 metadata envelope가 들어가지 않는 값은 usage error이며, 정상 truncation은 `truncated:true`와 `full_read_hint`를 반환한다. `rename`/`discard` preview도 index lookup fallback이 발생하면 top-level `warnings`에 같은 code를 노출한다.

공통 exit code:

| code | 의미 |
|---:|---|
| 0 | 성공 또는 정상 preview |
| 2 | usage/schema/filename 오류 |
| 3 | root/artifact not found |
| 5 | lifecycle/owner/path conflict |
| 6 | integrity/index failure |

error JSON은 `{"ok":false,"error":{"code":"...","message":"...","details":{...}}}` 형태다.

`doctor`의 fixed result는 다음과 같다.

```json
{
  "schema": "context-core-doctor/v1",
  "owner": "context-core",
  "supported_protocols": ["context-common/v2"],
  "repository_state": "ready",
  "root": "context/",
  "issues": [],
  "warnings": []
}
```

`repository_state` enum은 `absent|ready|partial|invalid`다. `absent`는 `context/` 자체가 없는 상태다. populated `context/`에서 root index만 없으면 `partial`+`index_missing` warning으로 판정하고 explicit init이 exact built-in SNAP/OBS area metadata로 root catalog를 복구한다. 미등록 area를 추측 등록하지 않는다. `ready`는 blocking issue가 없다는 뜻이며 legacy field·derived index drift warning을 포함할 수 있다. addon preflight는 exact core identity/protocol과 `absent`만 전역 검사하고, `partial|invalid` 진단은 실제 operation target과 겹칠 때 해당 command가 중단한다. Plugin의 marketplace/source/enabled 여부는 filesystem CLI가 주장하지 않고 host plugin inventory가 검증한다.

### SNAP schema

frontmatter는 공통 envelope에 `updated_at`, optional `anchors`를 추가한다. fixed body section은 다음과 같다.

- 필수: `현재 맥락`, `열린 항목`, `다음 단계`
- 선택: `정해진 것`, `참조`, `capture 후보`

SNAP의 lifecycle과 load authority는 [[context-artifact-lifecycle]]을 따른다. 여러 named SNAP을 허용하며 각 ID만 하나의 mutable chain이다. snapshot search는 기본 index metadata만 사용하고 `load`에서 선택한 본문만 연다.

### OBS schema

frontmatter는 공통 envelope에 optional `kind_hint`, `verified_at`, `affects_paths`, `relations.related`를 추가한다. `kind_hint: decision` fallback도 실제 `관찰` 본문과 source artifact identity로 비교하며 별도 claim 지문을 저장하지 않는다. fixed body section은 다음과 같다.

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

`context_cli.py init --host codex|claude-code`은 한 번의 명시적 호출에서 fixed `core_init`과 활성 host의 `policy_install`을 coordinator로 적용한다. repository에 `context/`가 전혀 없으면 directory 자체는 operation이 아니며 apply가 file parent를 `mkdir(mode=0755, parents=True, exist_ok=True)`로 만들고 built-in complete root/SNAP/OBS index seed material을 canonical generator에 전달한다. 생성 가능한 parent는 exact `context/`, `context/snapshot/`, `context/observation/`, `context/observation/retired/` allowlist뿐이고 non-directory/symlink 충돌은 실패한다. index file apply 전에 crash해 생긴 빈 allowlist directory는 재실행에서 absent와 동등하게 취급한다. populated repository에서 root index만 없으면 exact built-in SNAP/OBS descriptor만 root catalog로 즉시 rebuild한 뒤 계속하며, 미등록 addon/rogue area는 자동 claim하지 않는다. 세 built-in index descriptor가 일치하면 unrelated artifact warning/issue와 무관하게 core phase는 `noop`이고, incompatible schema/owner/path처럼 init target 자체를 안전하게 해석할 수 없는 경우만 `partial_core_init`으로 중단한다. schema major upgrade는 별도 migration 결정 없이는 수행하지 않는다.

1. repository root의 `context/`, SNAP, OBS area와 세 semantic index의 `index_rebuild(include_root:true)`를 preview한다.
2. 기존 사람 작성 index 설명과 일반 artifact를 보존한다.
3. 이미 root catalog에 등록된 addon area는 보존하되 addon 파일을 변경하지 않는다. 등록되지 않은 임의 폴더를 자동 claim하지 않는다.
4. 활성 host mapping은 `codex → AGENTS.md`, `claude-code → CLAUDE.md`로 고정하고 runtime hook, session ledger와 activity heuristic은 만들지 않는다.

user-facing `context-core:init`은 사용자의 명시적 init 의도를 fixed storage bootstrap과 canonical managed policy 설치 둘에 한정해 해석한다. policy target과 bytes를 storage write 전에 preflight하고 non-UTF-8, mixed newline, symlink, 비정상 marker는 structured write-zero error로 중단한다. core/area phase 후 policy bundle을 다시 계산해 noop TOCTOU를 막는다. 기존 target은 marker 밖 bytes와 file mode를 보존하고 신규 target은 `0644`로 생성한다.

`policy preview`는 exact repository-root basename 두 개만 받고 symlink는 거부한다. target이 없으면 `file_create`, 있으면 exact before digest의 `file_replace(role:"policy")` plan을 만든다. policy plan은 `transition: policy_install`, `owner_descriptor`는 built-in `context-core/policy` descriptor, effect action은 `install_policy`, `area`는 생략한다. marker는 정확히 한 쌍만 허용하고, marker 밖 UTF-8 bytes를 보존한다. 기존 file이 UTF-8이 아니거나 mixed newline이면 `policy_file_unsupported`로 실패해 수동 설치를 안내한다.

```markdown
<!-- BEGIN context-core-policy (managed by context-core) -->
## Durable context workflow

- Substantive work나 결정 수렴 전에 이전 맥락이 판단을 바꿀 수 있으면 Current context를 scoped index-first로 한 번 recall한다.
- 설치된 semantic owner가 있으면 후보와 관련 Current artifact의 실제 본문·scope·rationale를 비교한다. hash나 fingerprint로 의미 동일성 또는 충돌을 판정하지 않는다.
- capture 후보의 title·summary·search_terms에는 대화에서 쓰인 표현과 필요한 동의어를 bounded하게 남겨 이후 index recall을 돕되, index metadata를 의미 판정으로 사용하지 않는다.
- 기존 결정과의 conflict 또는 rationale change가 보이면 결론 전에 관련 artifact와 차이를 알리고 유지·수정·supersede 중 무엇인지 확인한다.
- Primary 요청과 답변을 먼저 끝낸다. semantic milestone 또는 closeout당 durable candidate audit은 최대 한 번 수행하고, 재사용 가치가 있는 후보가 있을 때만 grouped capture를 제안한다.
- Current DEC는 authoritative, OBS는 non-authoritative evidence, SNAP은 resume staging으로 취급한다.
- 사용자의 명시 승인 전에는 context artifact나 index를 쓰지 않는다.
<!-- END context-core-policy (managed by context-core) -->
```

marker가 없으면 file 끝에 blank line 두 개를 경계로 block을 append하고, 한 쌍이면 block bytes만 replace한다. 두 쌍 이상·unbalanced·END-before-BEGIN marker는 실패한다. approval preview는 target, action과 위 managed block 전체를 보여주고 final plan/material digest는 marker 밖 보존 bytes까지 결박한다. `transition: policy_install`만 `context/` 밖의 exact 두 target과 `role:"policy"`를 허용한다. rollback은 Git restore 또는 새 policy preview이며 apply 중 crash는 일반 file operation resume 규칙을 따른다.

addon init은 root index를 직접 수정하지 않는다. `context-decision:init`처럼 owner descriptor와 complete area index seed를 만든 뒤 public `bootstrap --descriptor --index-seed --host`를 호출한다. 이 surface는 `core_init`, fixed `area_register`, host `policy_install`을 coordinator로 순서대로 적용한다. seed bytes와 generated output digest는 final plan에 결박되며 absent index를 seed 없이 추측 생성하지 않는다. root row write 뒤 interruption은 exact descriptor/schema/owner/kind/artifact_schema/authority와 canonical generated bytes가 모두 일치할 때만 남은 area index write를 재개한다. existing descriptor/index metadata가 다르거나 임의 partial content가 있으면 write 0으로 실패한다.

### Coordinator와 승인 경계

semantic owner는 schema·domain lifecycle을 검증하고 fully rendered after-content, effect와 proposed plan을 반환한다. context-core preview가 current byte precondition과 index rebuild를 붙인 final bundle을 만들고 coordinator만 root lock 아래 document/index를 실제 변경한다. cross-owner transition은 protocol allowlist에 있는 plan만 허용하며 현재 계약에서는 `decision_fallback_import` 하나다.

capture audit의 claim result는 [[context-capture-routing]]의 complete artifact preview를 포함해야 한다. rename·annotate·reverify·invalidate·supersede·discard는 durable artifact mutation이므로 사용자가 현재 요청에서 exact action·target·새 값과 lifecycle effect를 모두 명시했거나 preview digest를 승인한 경우에만 `transaction apply`할 수 있다. `refresh --fix index`는 artifact를 정본으로 삼아 derived index만 즉시 rebuild하는 예외이며 artifact body·lifecycle bytes는 건드리지 않는다.

### Integrity 진단과 write 경계

항상 blocking인 write 경계:

- 대상 artifact CAS byte 일치
- 대상 area index before digest와 deterministic after material
- global duplicate ID
- path traversal·symlink·reserved filename guard
- exact approval digest, root lock, atomic replace와 replay 시 after-byte 재생성 0

검색 품질 warning:

- 제거된 legacy artifact field (`schema_removed_field`); 다음 승인 rewrite에서 lazy-clean
- derived index missing/ghost/wrong path·state/content와 root generated drift

`doctor`와 plain `refresh`는 진단만 하며 write 0이다. artifact schema/lifecycle/ref 문제는 corpus 진단의 `issues`와 `repository_state:invalid`로 남지만 addon preflight나 unrelated target write의 전역 gate로 사용하지 않는다. 검색 projection 문제는 `warnings`다. `refresh --fix index`만 approval 없이 derived entry와 기존 root의 generated display row를 rebuild하며 marker 밖 bytes와 authoritative root descriptor를 보존한다. area metadata mismatch와 미등록 area는 repair 대상이 아니고, lifecycle·본문·relation도 자동 수정하지 않는다.

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
- Stage 1 instrument 시 positive index match에서 directory listing과 artifact stat도 0; zero-match 또는 stale selected link만 area scan fallback
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

context-core는 범용 지식 시스템이 아니라 **session continuity, evidence capture, scoped recall과 승인형 보관을 위한 작은 공통 runtime**이다. transcript 판독·저장·검색을 addon마다 복제하지 않으면서도 domain 의미는 semantic owner에 남겨 token과 결합도를 줄인다.

### 해결하려는 문제

LLM과의 대화에는 이후 설계·구현 판단을 바꿀 수 있는 취지, 결정, 근거와 unfinished context가 생긴다. 이를 전부 transcript나 일반 memory에 맡기면 다음 문제가 반복된다.

- 보관할 가치가 있는 맥락과 일회성 대화가 섞인다.
- 새 판단 전에 관련 과거 맥락을 찾지 않아 취지 변경이나 충돌을 놓친다.
- 같은 의미인지 ID·hash·문장 정규화 같은 기계적 surrogate로 오판한다.
- addon마다 저장·검색·승인·index 갱신을 중복 구현한다.
- 자동 저장이 사용자의 repository와 지식 권한을 침범한다.

core가 제공해야 하는 결과는 “더 많이 기억함”이 아니라 다음 네 가지다.

1. **필요한 때 찾는다.** substantive 판단 전에 관련 Current context를 scoped index-first recall한다.
2. **실제 내용을 비교한다.** 의미 관계는 installed semantic owner가 실제 본문·scope·rationale를 읽고 attestation하며, core는 이를 기계적 동일성으로 가장하지 않는다.
3. **보관 가치를 제안한다.** semantic milestone에서 재사용 가치가 있는 후보만 한 번 묶어 제안한다.
4. **승인 뒤 안전하게 쓴다.** exact preview와 `approval_digest` 승인 뒤 coordinator만 document와 derived index를 원자적으로 변경한다.

### 추구 원칙

1. **Project context 우선** — 일반 개인 memory나 transcript archive보다 repository의 why, current state, evidence와 handoff continuity에 집중한다.
2. **내용이 의미의 정본** — `candidate_id`와 artifact ID는 식별·transport용이다. title·summary·tag·`search_terms`와 index는 탐색 후보를 줄이는 projection일 뿐 의미 동일성·충돌의 증거가 아니다. addon의 slot key도 authority 주소이지 semantic equality가 아니다.
3. **Recall before capture** — 보관부터 하지 않는다. 기존 Current context가 판단을 바꿀 수 있으면 먼저 회수·비교하고, 새로 남길 실익이 있을 때만 capture 후보를 만든다.
4. **제안은 자동, 영속화는 승인형** — agent는 자연스럽게 grouped capture를 제안할 수 있지만, 일반 artifact write는 사용자의 exact 승인 전까지 byte-for-byte no-op이어야 한다.
5. **Domain 의미는 owner가 소유** — core는 공통 envelope·index·transaction·approval을 담당하고, DEC 같은 domain 의미와 lifecycle은 specialized owner가 담당한다. owner가 없다고 권위 수준을 임의 승격하지 않는다.
6. **Index-first, document-authoritative** — Stage 1은 index만 읽고 후보를 좁히며, 최종 판단에는 선택된 artifact 본문을 읽는다. 검색 비용을 줄이되 index corruption이나 metadata를 truth로 취급하지 않는다.
7. **Local-first와 낮은 운영비** — Git/Markdown/Python stdlib만으로 기본 가치가 동작해야 한다. Obsidian, embedding DB, SaaS와 background daemon은 필수 의존성이 아니다.
8. **Fail-closed와 복구 가능성** — schema·owner·protocol·path·digest·marker가 모호하면 쓰지 않는다. mutation은 bounded preview, exact precondition, root lock, atomic replace와 Git history로 검증·복구 가능해야 한다.
9. **실익이 구현 형태보다 우선** — 이미 존재하는 field·key·flow라도 사용자 가치, 정확성 또는 운영 안전을 높이지 못하면 제거·축소한다. 확장성 명목의 추상화는 실제 addon·corpus·운영 증거가 생긴 뒤 도입한다.

### 명시적 비목표

- 모든 대화와 transcript의 자동 수집·보관
- hash, fingerprint, embedding, 정규화 문장만으로 semantic equality나 conflict를 확정
- 승인 없는 자동 DEC/OBS/SNAP 작성
- vector search, 조직 전체 cross-project search, cloud sync와 권한 queue의 기본 내장
- runtime hook, activity heuristic, session ledger와 항상 실행되는 background audit
- TASK, DEC, SSOT/runbook 등 addon domain schema를 core가 직접 소유
- 0.1.x legacy artifact의 묵시적 변환이나 손실 가능 auto-repair

이 비목표는 영구 금지가 아니라 현재 제품 경계를 뜻한다. 실제 recall 실패율, corpus 규모, 협업·감사 요구가 local index와 owner contract의 한계를 반복해서 증명할 때만 다음 계층을 검토한다.

### 객관적 평가 기준

다른 세션은 다음 질문에 code/runtime evidence로 답한다. 문서의 의도만 충족하고 실제 flow가 없으면 `기획됨`, source와 deterministic test만 있으면 `구현됨`, 실제 host와 consumer repository에서 재현되면 `운영 검증됨`으로 구분한다.

| 평가 항목 | 통과 기준 | 대표 실패 신호 |
|---|---|---|
| 맥락 회수 실익 | 관련 Current context가 bounded index query로 발견되고, 선택한 본문만 열어 판단에 사용 | 매번 전수 문서 읽기, 관련 결정을 놓침, history를 Current로 사용 |
| 의미 판정 정직성 | owner가 실제 primary claim·scope·rationale를 비교하고 근거와 관계를 반환 | ID/key/hash/embedding score를 같은 의미의 보장으로 사용 |
| 충돌·취지 변경 알림 | primary 결론 전에 관련 artifact ID와 실제 차이를 알리고 유지·수정·supersede를 확인 | 새 결정을 조용히 중복 작성하거나 과거 취지를 덮음 |
| capture 품질 | milestone당 audit 1회, durable value가 있을 때만 최대 8개 bounded 후보를 grouped proposal | 매 응답마다 저장 질문, transcript 덤프, addon 수만큼 audit 반복 |
| 승인 경계 | preview까지 write 0, exact approved bundle만 한 번 apply, 승인 뒤 ID/timestamp/content 재생성 0 | preview가 index를 바꿈, 승인과 다른 bytes를 apply |
| 저장 일관성 | 단일 coordinator, root lock, CAS/atomic replace, document와 derived index 동시 수렴 | owner 직접 write, lost index row, partial lifecycle |
| 검색 효율 | Stage 1 artifact I/O 0, output·pack·section byte budget 준수, query alias는 bounded metadata로 전달 | directory scan, corpus 크기만큼 artifact open, 의미 metadata 과적재 |
| 초기화 UX | 명시적 init 한 번으로 storage와 active-host policy를 설치, 재호출 diff 0, 사용자 bytes/mode 보존 | init과 policy 수동 다단계, partial state overwrite, marker 밖 변경 |
| 호환성·복구 | protocol mismatch와 신규 write의 removed field는 fail-closed하고, 저장된 legacy field는 warning+승인 rewrite 시 lazy-clean한다 | 혼합 버전을 ready로 오판, 구형 artifact 때문에 read/init을 막거나 조용히 변형 |
| 복잡도·비용 | stdlib/local default가 핵심 flow를 완결하고 새 abstraction은 측정된 병목을 해결 | 실사용 증거 없이 service/vector/runtime 계층 추가 |

### 평가 절차와 증거 우선순위

1. 현재 commit과 dirty state를 고정한다.
2. 실제 host inventory, installed version, `doctor`, representative init/recall/capture flow를 확인한다.
3. source·manifest·protocol과 deterministic suite를 확인한다.
4. wiki decision/SSOT로 의도와 rejected alternative를 확인한다.
5. 과거 session memory는 후보 근거로만 사용하고 현재 code/runtime과 충돌하면 폐기한다.

판정 보고에는 최소한 `기획`, `구현`, `운영 검증`, `배포`를 분리하고, 미확인 host·OS·migration·client UI를 명시한다. plain `refresh`의 `issues:[]`는 corpus 구조 진단 증거일 뿐 semantic freshness나 운영 readiness의 증거가 아니다.

### 개발 우선순위 판단

다음 개발은 현재 구조를 보존하는 것보다 실익을 높이는 순서로 평가한다.

1. 실제 장기 대화에서 recall 누락·오탐, conflict 알림 품질과 capture 제안 피로도를 측정한다.
2. legacy data가 사용을 막는 빈도와 손실 없는 migration 요구를 확인하고 upgrade UX를 결정한다.
3. Codex·Claude Code·macOS·Linux의 live install/init/reload 흐름을 반복 검증한다.
4. local index의 실제 한계가 측정될 때만 ranking, richer search 또는 외부 service를 검토한다.

새 기능이 이 우선순위와 직접 연결되지 않으면 기본 판정은 보류다. 단순한 schema 확장, 새 key, fingerprint, background mechanism은 그 자체로 진전이 아니다.

## 구성요소

- [[context-plugin-definition]] — 생태계 overview와 불변식
- [[context-storage-retrieval]] — 공통 저장/index/recall 계약
- [[context-artifact-lifecycle]] — SNAP·OBS lifecycle
- [[context-capture-routing]] — audit·owner·approval·budget
- [[context-v1-implementation]] — 구현 순서와 release gate
