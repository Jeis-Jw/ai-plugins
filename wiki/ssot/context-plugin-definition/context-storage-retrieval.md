---
title: 컨텍스트 저장소와 semantic index 조회 계약
created_at: 2026-08-13
summary: 자유로운 Markdown 파일명과 immutable ID를 분리하고 context.index.md 및 영역별 semantic index를 문서에서 파생해 index-first·document-authoritative recall을 수행하는 v1 계약.
tags: [context-core, storage, index, recall, obsidian, ssot]
verified_at: 2026-08-17
affects_paths: [plugins/context-core/**, plugins/context-decision/**]
---

## 현재 상태

### 저장 구조와 예약 경로

consumer repository의 root는 v1에서 Git worktree 최상위의 `context/`로 고정한다. CLI는 현재 working directory에서 `git rev-parse --show-toplevel`을 실행하고 stdout의 absolute path를 `realpath`로 정규화한다. cwd는 worktree 하위 어디여도 되며 linked worktree의 top-level이 해당 실행의 repository root다. 명령 실패·빈 출력·cwd가 반환 root 밖이면 exit 3 `repository_not_found`로 실패한다. non-Git directory, `--root` override와 repository 밖 저장은 v1에서 지원하지 않는다. 임의 nested topic 폴더도 지원하지 않는다.

```text
context/
├── context.index.md
├── snapshot/
│   ├── snapshot.index.md
│   └── <free-filename>.md
├── observation/
│   ├── observation.index.md
│   ├── <free-filename>.md
│   └── retired/
│       └── <free-filename>.md
└── decision/
    ├── decision.index.md
    ├── <free-filename>.md
    └── retired/
        └── <free-filename>.md
```

다음 네 파일명은 정확한 예약 이름이다.

- `context/context.index.md`
- `context/snapshot/snapshot.index.md`
- `context/observation/observation.index.md`
- `context/decision/decision.index.md`

일반 artifact 파일은 `*.index.md`로 끝날 수 없다. index 판별은 basename만 보지 않고 예약 경로와 `schema`를 함께 검사한다.

### 파일명과 정체성

- 일반 문서명에 type prefix나 timestamp를 붙이지 않는다.
- CLI 기본 파일명은 title에서 만든 Unicode NFC slug다. 알고리즘은 trim→NFC→각 codepoint 중 `str.isalnum()` 또는 `-_.`만 보존→그 밖의 연속 구간을 `-` 하나로 치환→양끝 `-._` 제거→`.md` 추가 순서다. ASCII case는 바꾸지 않는다. 결과가 비거나 basename 120 codepoint/UTF-8 240 byte를 넘으면 자동 절단하지 않고 `filename_required`로 실패한다.
- `--filename`은 area 안의 basename만 받으며 `.md`는 생략하거나 정확히 한 번 붙일 수 있다. 다른 extension, path separator, 빈 stem, basename 120 codepoint/UTF-8 240 byte 초과는 거부한다.
- `/`, `\\`, ASCII control/NUL, `.`/`..`, `< > : " | ? * [ ] # ^`, trailing space/dot, Windows reserved stem `CON|PRN|AUX|NUL|COM1..9|LPT1..9`, marker를 깨는 `<!--`·`-->`, `*.index.md`는 NFKC+casefold 검사로 거부한다.
- 같은 폴더에서 basename의 Unicode NFKC+casefold collision key가 기존 파일과 같으면 `path_exists`로 실패한다. 묵시적 overwrite나 `-2` suffix를 만들지 않는다.
- active OBS·DEC를 history로 옮길 때는 원래 stem에 ID의 UUID hex 앞 12자를 붙인 `<stem>--<id12>.md`를 사용한다. 이 deterministic history 이름이 충돌하면 duplicate ID/integrity 오류로 실패한다. 따라서 같은 자연 filename을 여러 current generation에서 재사용할 수 있다.
- title 변경은 파일 rename을 강제하지 않는다. rename은 별도 명령으로 수행한다.
- type은 area path와 `schema`의 일치로 검증한다.
- 정체성의 정본은 frontmatter의 `id`다. 파일명·title·path는 바뀔 수 있다.

v1 ID는 외부 dependency 없이 생성 가능한 `ctx_` + lowercase UUIDv4 hex 32자로 고정한다.

```yaml
id: "ctx_550e8400e29b41d4a716446655440000"
```

ID는 vault 전체에서 유일하고 생성 뒤 불변이다. 내부 relation, supersede edge와 mutation target은 exact ID를 사용한다. 파괴적 mutation은 exact ID 또는 exact root-relative path만 받으며 fuzzy title은 read/search에만 허용한다.

### 공통 document envelope

모든 artifact는 다음 필드를 공통으로 사용한다.

```yaml
---
schema: "context-observation/v1"
id: "ctx_550e8400e29b41d4a716446655440000"
title: "Safari에서 third-party cookie가 차단된다"
summary: "Safari 환경에서 인증 cookie 전달이 차단되는 조건을 재현했다."
created_at: "2026-08-13T18:20:00+09:00"
captured_from: "workspace"
source_refs: ["file:src/auth/session.ts"]
tags: ["auth","safari"]
search_terms: ["ITP","third-party cookie"]
---
```

필수 필드는 `schema`, `id`, `title`, `summary`, `created_at`, `captured_from`이다.

- `title`: 줄바꿈 없는 1~120자
- `summary`: 독립적으로 의미가 통하는 한 줄, 1~280자
- `created_at`: timezone을 포함한 RFC3339
- `captured_from`: `conversation | workspace | manual | import`
- `tags`, `search_terms`: 선택, 각각 최대 12개·항목당 40자
- `source_refs`: 선택, opaque URI-like string 목록·항목당 최대 500자
- `kind`와 `status`는 공통 frontmatter에 반복 저장하지 않는다. kind는 area, active/retired는 path가 정본이다.

CLI가 timestamp를 생성할 때는 preview 시점의 `datetime.now().astimezone().isoformat(timespec="seconds")`을 사용하고 final bundle에 고정한다. apply 시각으로 다시 만들지 않는다. 입력 timestamp는 Python `datetime.fromisoformat`으로 parse되고 timezone offset 필수, canonical output은 seconds precision ISO string이다. `updated_at`/`retired_at`도 같은 규칙이며 document의 기존 `created_at`보다 이르면 clock error로 실패한다.

#### Frontmatter lexical grammar

v1은 일반 YAML 전체가 아니라 JSON-compatible YAML subset만 지원한다.

- file은 UTF-8 without BOM이다. reader는 LF 또는 일관된 CRLF를 받지만 mixed newline은 거부한다. writer는 LF와 file 끝의 정확히 한 newline로 canonicalize한다.
- 첫 줄과 closing delimiter는 정확히 `---`다. frontmatter 안에 blank line, comment, YAML tag/anchor/alias, multiline scalar는 허용하지 않는다.
- 각 field는 한 줄 `KEY: JSON_VALUE`다. `KEY`는 `[a-z][a-z0-9_]*`이며 duplicate key는 오류다.
- `JSON_VALUE`는 compact JSON의 string, `true|false|null`, string array 또는 한 단계 object다. object value는 string, boolean, null 또는 string array만 허용한다. number와 중첩 object/array는 금지한다.
- string escaping과 parsing은 Python `json.loads`/`json.dumps(ensure_ascii=False, separators=(",", ":"))` 의미를 그대로 따른다. 따라서 `:`·`,`·`#`가 든 값도 JSON string으로만 쓴다.
- writer의 key 순서는 각 schema가 선언한 known-field order 뒤에 unknown key Unicode codepoint ASC다. 공통 prefix는 `schema,id,title,summary,created_at,updated_at,captured_from,source_refs,tags,search_terms`다. SNAP additive order는 `anchors`; OBS는 `kind_hint,verified_at,affects_paths,relations,supersedes,superseded_by,retired_at,retired_reason,retirement_note`; DEC는 `scope,decision_key,revisit_when,revisit_on,relations,supersedes,superseded_by,retired_at,retired_reason,retirement_note`다. lifecycle key는 current 문서에서는 absent다.
- 같은 schema major의 unknown additive field는 위 value grammar 안에서 semantic value를 보존하고 canonical rewrite한다. unknown key는 domain schema validation에는 쓰지 않지만 rename/index refresh 같은 common rewrite에서도 삭제하지 않는다. raw whitespace·quote style·frontmatter comment 보존은 약속하지 않는다. grammar 밖 unknown field는 mutation 전에 `frontmatter_unsupported`로 실패한다.
- closing delimiter 뒤에는 blank line 하나와 Markdown body가 온다. body는 schema가 선언한 H2 section만 canonical order로 각 최대 한 번 허용하고 첫 section 전에는 blank line만 허용한다. required section은 substantive non-whitespace content가 있어야 하며 literal `...`, `TODO`, `TBD`, `해당 없음` 하나만 있는 값은 placeholder로 거부한다. H3 이하 heading은 section content다. fixed section heading은 line 전체가 정확히 `## <schema-defined name>`일 때만 인식하며 CommonMark backtick/tilde fenced code 안 heading은 무시한다. unknown/duplicate/out-of-order H2는 `section_schema_error`다.

OBS·DEC의 의미 동일성은 저장 필드나 hash로 판정하지 않는다. owner가 bounded recall로 가져온 actual primary claim·supporting section·scope를 비교한다. exact file SHA-256은 승인 뒤 bytes가 바뀌지 않았음을 보장하는 artifact identity/precondition일 뿐 semantic identity가 아니다. 제거된 legacy claim 지문 field가 남은 artifact는 `schema_removed_field` warning과 함께 읽고, 해당 artifact의 다음 승인 rewrite가 canonical render하면서 field를 제거한다. 신규 artifact/candidate에는 계속 허용하지 않는다.

### Root index

`context.index.md`는 개별 artifact를 수록하지 않고 초기화된 area index만 연결한다. Root/area index frontmatter도 위 JSON-compatible subset을 사용한다. `index: true`는 JSON boolean이다.

```markdown
---
schema: "context-root-index/v1"
index: true
owner: "context-core"
summary: "프로젝트의 공유 context 영역 catalog"
---

# Context

## Areas
<!-- BEGIN CONTEXT GENERATED:areas -->
- [[context/snapshot/snapshot.index]] — Snapshot: session handoff staging <!-- context-area {"area":"snapshot","path":"context/snapshot/snapshot.index.md","owner":"context-core","claims":["snapshot"],"artifact_schema":"context-snapshot/v1","authority":"staging"} -->
- [[context/observation/observation.index]] — Observation: 비권위 발견과 근거 <!-- context-area {"area":"observation","path":"context/observation/observation.index.md","owner":"context-core","claims":["observation"],"artifact_schema":"context-observation/v1","authority":"evidence"} -->
- [[context/decision/decision.index]] — Decision: 결정·취지·반려대안 <!-- context-area {"area":"decision","path":"context/decision/decision.index.md","owner":"context-decision","claims":["decision"],"artifact_schema":"context-decision/v1","authority":"authoritative"} -->
<!-- END CONTEXT GENERATED:areas -->
```

root index는 area install/remove 시에만 바뀐다. v1 area는 정확히 같은 이름의 claim 하나만 선언한다. 같은 area 또는 claim kind를 두 owner가 등록하면 integrity error다. generated area row는 `area ASC` 정렬, JSON key order `area,path,owner,claims,artifact_schema,authority`로 고정하고 같은 compact JSON/Markdown escape 규칙을 쓴다. 사람용 area label/설명은 등록 시 hashed area-index seed의 H1과 frontmatter summary에서, 이후 root rebuild에서는 현재 area index의 같은 marker-external metadata에서 결정적으로 가져온다. area index가 없고 승인된 seed도 없으면 root row를 추측하지 않고 `index_seed_required`다. area가 남아 있어도 해당 plugin이 현재 host에서 호출 가능하다는 뜻은 아니다. storage discovery와 write capability discovery를 구분한다.

### Area index

각 area index는 사람이 읽는 설명과 완전히 파생 가능한 generated block을 함께 가진다.

```markdown
---
schema: "context-area-index/v1"
index: true
area: "decision"
owner: "context-decision"
artifact_schema: "context-decision/v1"
authority: "authoritative"
summary: "결정·취지·반려대안과 현재 유효성을 관리한다."
search_terms: ["결정","rationale","rejected alternative"]
projection_fields: ["scope","decision_key","revisit_on"]
---

# Decision

## Current
<!-- BEGIN CONTEXT GENERATED:current -->
- [[context/decision/인증-세션은-bff가-소유한다]] — 인증 세션은 BFF가 소유한다 — OAuth callback과 cookie lifecycle을 BFF로 통합한다. <!-- context-entry {"id":"ctx_...","path":"context/decision/인증-세션은-bff가-소유한다.md","title":"인증 세션은 BFF가 소유한다","summary":"OAuth callback과 cookie lifecycle을 BFF로 통합한다.","state":"current","created_at":"2026-08-13T18:20:00+09:00","terms":["auth","BFF","oauth"],"scope":"project/auth","decision_key":"session-owner"} -->
<!-- END CONTEXT GENERATED:current -->

## History
<!-- BEGIN CONTEXT GENERATED:history -->
<!-- END CONTEXT GENERATED:history -->
```

계약:

- entry는 한 artifact당 한 줄이며 Obsidian graph를 위한 root-relative wikilink를 포함한다.
- 기계 필드는 HTML comment 안의 canonical compact JSON이다. key order를 고정한다.
- 사람용 title·summary는 `\\`, `` ` ``, `*`, `_`, `{}`, `[]`, `<>`, `#`, `|` 앞에 backslash를 붙여 Markdown inline 문법을 escape한다. CLI 검색은 표시 문자열을 재파싱하지 않고 JSON의 `path`·`title`·`summary`를 사용한다.
- `generated_at`을 쓰지 않는다. 실제 내용이 같으면 byte-identical해야 한다.
- generated marker 밖의 사람 작성 설명은 refresh가 보존한다.
- SNAP에는 `Current`만 있고 `History`가 없다.
- OBS·DEC에는 `Current`와 `History`가 있다. 기본 recall은 Current만 읽는다.
- 정렬은 `created_at ASC`, 동률이면 `id ASC`다.
- index entry에는 검색·routing에 필요한 공통 projection만 둔다. 본문, 근거, 반려대안 전문은 넣지 않는다.
- semantic owner는 자기 area 문서의 schema·draft·mutation plan을 검증하고, context-core storage coordinator만 실제 문서·index를 쓴다. core는 domain-specific field 의미를 해석하지 않고 보존한다.
- `projection_fields`는 owner가 index에 복사할 추가 frontmatter string/string-array key를 최대 4개 선언한다. key는 `[a-z][a-z0-9_]*`이고 공통 row key `id,path,title,summary,state,created_at,updated_at,terms,retired_at,retired_reason,superseded_by,kind,authority`와 충돌할 수 없다. core는 의미를 해석하지 않고 복사·보존하며 owner가 값의 domain validation을 담당한다.
- 공통 entry `state`는 artifact 종류와 무관하게 `current | history` 두 값만 사용한다. History entry에는 `retired_at`, `retired_reason`, optional `superseded_by`를 반드시 투영한다.
- canonical JSON key order는 `id,path,title,summary,state,created_at,updated_at,terms,retired_at,retired_reason,superseded_by` 뒤에 `projection_fields` 선언 순서다. 값이 없는 optional key는 생략한다.
- JSON은 UTF-8, `ensure_ascii=false`, 공백 없는 separators로 serialize한다. `terms`는 tags+search_terms를 합쳐 NFC trim하고 NFKC+casefold 기준으로 dedupe한 뒤 normalized value와 원문을 tie-break로 정렬한다.

### Index-first recall

기본 알고리즘:

1. `context.index.md`에서 초기화된 area index 경로를 읽는다.
2. 명시적 `--area`/`--kind`가 없으면 모든 area index를 검색한다. root summary만으로 area를 미리 제외하지 않는다.
3. 기본은 `Current`, `--include-history`일 때만 `History` entry를 포함한다.
4. index metadata의 title·summary·terms·path로 lexical score와 query token coverage를 계산한다. `--facet key=value`는 area가 선언한 `projection_fields`에 대한 exact filter이며 core는 field 의미를 알지 않는다. scalar는 NFKC+casefold exact equality, string array는 normalized element membership이다. 여러 facet은 AND이고 같은 key를 반복하면 그 값도 모두 포함해야 한다.
5. bounded top-K Stage 1 결과만 반환한다. 이 단계에서는 artifact 파일을 열지 않는다.
6. `--pack`, `--section`, `--read`가 선택한 artifact만 연다.

query는 Unicode NFKC+casefold 후 공백·구두점 token으로 나누고 중복 token을 제거한다. stemming, embedding, vector DB를 사용하지 않는다. v1 deterministic score는 다음과 같다.

| match | score |
|---|---:|
| exact ID | 100 |
| title 전체 phrase | 40 |
| exact tag/search term | 12 |
| summary phrase | 10 |
| query token별 가장 강한 match | title substring 8, term substring 6, summary substring 3, path substring 1 |
| 모든 query token 포함 | +10 |

non-empty query는 unique query token의 `min(2, ceil(N/2))` 이상을 match해야 한다. 긴 자연어 query의 filler token 때문에 강한 2-token match를 버리지 않으면서 단일 우연 match는 줄이는 bounded cutoff다. strong match(title·term·summary)가 하나라도 있으면 path-only 후보는 cutoff한다. 그 뒤 tie-break는 `score DESC → created_at DESC → id ASC`다. query가 없으면 모든 filter 통과 item의 score는 0이므로 최신순 listing이 된다. 기본 `limit=8`, 최대 20이다.

Stage 1은 `id, kind, state, title, summary, path, authority`와 owner가 명시한 작은 facet만 반환한다. decision plugin은 `--facet scope=... --facet decision_key=...`를 사용하고 필요하면 후보 안에서 domain ranking을 적용한다. `search_terms` 전체와 index 원문을 model prompt에 노출하지 않는다.

exact ID read도 root→area index의 `id→path`를 먼저 사용한다. healthy index의 `snapshot load`와 `observation read`는 선택한 artifact 본문 하나만 parse하며 SNAP anchor freshness도 다른 본문 대신 index state/path로 계산한다. stale anchor index만 scan fallback한다. `rename`과 `discard`도 같은 resolver로 target을 고르고, write 경계의 duplicate ID 검사는 다른 artifact의 frontmatter ID만 확인한다. index가 unreadable하거나 ID/path/schema가 어긋나면 그때만 canonical area를 scan하고 결과에 `index_lookup_fallback` warning을 붙인다. `discard`의 inbound relation 검사는 별도 write safety scan이므로 유지한다.

`snapshot load`와 `observation read`의 `--max-bytes`는 1..32768 범위에서 complete result object를 제한한다. metadata envelope를 보존한 뒤 section을 순서대로 채우고 마지막 section prefix만 UTF-8 JSON byte budget에 맞춰 자른다. 잘리면 `truncated:true`, `full_read_hint`를 반환한다. metadata envelope 자체보다 작은 budget은 잘못된 usage로 거부한다.

### Drift와 fallback

normal read path는 다음 상태만 즉시 stale index로 판정한다.

- root index는 존재하지만 area index 누락 또는 schema/marker/JSON parse 실패
- 선택된 index entry가 가리키는 파일 누락

healthy-index Stage 1의 positive match는 root index와 area index 외에 directory listing, artifact stat/open을 수행하지 않는다. area index 자체가 파손됐거나 선택된 entry load에서 누락이 확인되거나 non-empty query가 zero-match이면 그때만 해당 area directory를 frontmatter scan해 fallback하고 `index_fallback: true`와 원인을 반환한다. zero-match fallback은 out-of-band missing row를 회수하기 위한 bounded 예외다. root index 자체가 없으면 storage-level `context_root_missing`이며 recall이 임의 folder scan으로 root catalog를 추측하지 않는다. read operation은 index를 자동 수정하지 않는다. `--strict-index`는 fallback 없이 exit 6으로 실패한다. out-of-band 신규·rename·frontmatter 변경과 전체 path-set 불일치는 plain `refresh`가 전수 진단한다. addon user-facing preflight는 exact core plugin identity/protocol과 repository `absent`만 전역 gate로 쓰며 partial/invalid 진단은 실제 operation target과 겹칠 때 해당 command가 중단한다.

`refresh --fix index`는 root lock 아래 문서를 정본으로 derived area entry와 기존 root의 generated display row를 즉시 rebuild한다. 기존 root descriptor와 marker 밖 사람 bytes를 보존하고, area metadata mismatch·미등록 area를 root authority로 승격하지 않는다. root가 유실된 populated core는 exact built-in SNAP/OBS descriptor만 복구하며 addon 등록을 추측하지 않는다. approval bundle이나 `transaction apply`는 사용하지 않는다. 승인된 capture/mutation transaction도 자기 target area index의 exact before/after material만 갱신하고, target root descriptor와 area metadata가 어긋나면 중단한다. 어떤 경로도 artifact 본문·lifecycle을 index로 덮어쓰지 않는다.

### 단일 writer와 mutation plan

semantic owner는 filesystem을 직접 변경하지 않고 discriminated `context-owner-result/v1`의 complete `artifact_drafts`, semantic `effects`와 `context-owner-plan/v1`을 반환한다. capture/lifecycle variant와 embedded semantic input·attestation 계약은 [[context-capture-routing]]이 정본이다. owner plan operation은 `create(effect_id,area,path)`, `replace(effect_id,area,id,path)`, `move(effect_id,area,id,from_path,to_path)`, `delete(effect_id,area,id,path)` 네 discriminated shape만 쓰며 hash, material, index operation을 넣지 않는다. delete 외 operation은 같은 effect ID의 destination draft가 정확히 하나 있어야 한다.

context-core의 `transaction preview`가 owner/capability, target ID/path, embedded semantic evidence, optional owner validation receipt와 draft를 검증하고 current exact bytes, material IDs, read precondition과 `index_rebuild`를 붙여 final `context-mutation-bundle/v1`을 만든다. owner plan은 승인·apply 대상이 아니며 finalization 뒤 폐기한다. grouped approval에는 반드시 **final bundle**을 사용하고 context-core storage coordinator만 이를 apply한다.

```json
{
  "schema": "context-mutation-bundle/v1",
  "approval_material": {
    "preview": {
      "schema": "context-approval-preview/v1",
      "owner": "context-decision",
      "candidate_id": "cand_...",
      "artifacts": [
        {"effect_id":"effect_create_dec","path":"context/decision/인증-세션은-bff가-소유한다.md","content":"---\n...complete DEC Markdown..."},
        {"effect_id":"effect_retire_obs","path":"context/observation/retired/합의-기록--abc123def456.md","content":"---\n...complete retired OBS Markdown..."}
      ],
      "effects": [
        {"effect_id":"effect_create_dec","action":"create","area":"decision","id":"ctx_new","state":"current"},
        {"effect_id":"effect_retire_obs","action":"retire","area":"observation","id":"ctx_old","reason":"superseded","successor":"ctx_new"}
      ]
    },
    "plan": {
      "schema": "context-mutation-plan/v1",
      "plan_id": "plan_550e8400e29b41d4a716446655440000",
      "owner": "context-decision",
      "source_type": "owner_result",
      "owner_result_digest": "sha256:...",
      "owner_result_material": "material_owner_result",
      "capability_digest": "sha256:...",
      "transition": "decision_fallback_import",
      "owner_descriptor": {"owner":"context-decision","kind":"decision","artifact_schema":"context-decision/v1"},
      "owner_validation": {"schema":"context-owner-validation-receipt/v1","owner":"context-decision","kind":"decision","owner_result_digest":"sha256:...","base_area_index_sha256":"sha256:...","prior_same_area_bundle_digests":[],"validated_facts":{"scope":"project/auth","decision_key":"session-owner","primary_claim":"인증 세션은 BFF가 소유한다.","rationale":"cookie lifecycle을 서버 경계로 모은다.","acknowledged_conflicts":[]},"status":"valid","receipt_digest":"sha256:..."},
      "prior_bundle_digests": [],
      "read_preconditions": [],
      "operations": [
        {"op":"file_create","effect_id":"effect_create_dec","role":"artifact","area":"decision","path":"context/decision/인증-세션은-bff가-소유한다.md","before_sha256":null,"after_sha256":"sha256:...","material":"material_dec"},
        {"op":"file_move","effect_id":"effect_retire_obs","role":"artifact","area":"observation","id":"ctx_old","from_path":"context/observation/합의-기록.md","to_path":"context/observation/retired/합의-기록--abc123def456.md","before_sha256":"sha256:...","destination_before_sha256":null,"after_sha256":"sha256:...","material":"material_obs_retired"},
        {"op":"index_rebuild","derived_from":["effect_create_dec","effect_retire_obs"],"areas":["decision","observation"],"include_root":false,"before_sha256":{"context/decision/decision.index.md":"sha256:...","context/observation/observation.index.md":"sha256:..."},"after_sha256":{"context/decision/decision.index.md":"sha256:...","context/observation/observation.index.md":"sha256:..."}}
      ]
    }
  },
  "approval_digest": "sha256:...",
  "materials": [
    {"material_id":"material_owner_result","path":null,"content":"{...canonical complete context-owner-result/v1 JSON...}"},
    {"material_id":"material_dec","path":"context/decision/인증-세션은-bff가-소유한다.md","content":"---\n...same complete DEC Markdown..."},
    {"material_id":"material_obs_retired","path":"context/observation/retired/합의-기록--abc123def456.md","content":"---\n...same complete retired OBS Markdown..."}
  ]
}
```

#### Approval material과 bytes

- owner는 schema·본문·domain lifecycle을 검증하고 fully rendered semantic content와 effect를 제공한다. core preview가 precondition과 `index_rebuild`를 확정한 뒤부터 bundle은 immutable이다.
- `approval_digest`는 `approval_material` **전체(preview+plan)** 에 canonical JSON 규칙을 적용한 UTF-8 bytes의 SHA-256이다. canonical JSON은 모든 string/key를 NFC로 정규화하고 object key를 Unicode codepoint ASC로 재귀 정렬한 뒤 `json.dumps(ensure_ascii=False, separators=(",", ":"))`한다. contract scalar는 string·boolean·null 또는 0~2^53-1 정수만 허용하고 float/negative integer는 금지한다. array 순서는 보존한다. digest 자신과 `materials`는 제외되지만 plan의 `after_sha256`이 material bytes를 결박한다.
- artifact effect의 complete semantic content는 preview와 material에 byte-equivalent하게 한 번씩 존재한다. generated index 전체와 policy file의 무관한 기존 본문은 사람이 보는 preview projection에서 생략할 수 있지만 plan/material hash에는 포함한다. preview는 해당 omitted path와 before/after digest를 반드시 표시한다. 숨은 semantic section은 금지한다.
- owner-result material은 apply 재검증용 ephemeral bundle payload다. model recall이나 사용자 preview에 중복 노출하지 않고 apply receipt 이후 별도 ledger/file로 저장하지 않는다. 사용자에게는 그 result에서 나온 artifact content·effect·attestation label만 한 번 보여준다.
- `before_sha256`는 mutation 전 **exact on-disk bytes**의 lowercase SHA-256에 `sha256:`를 붙인다. artifact/index-seed `after_sha256`는 material string을 LF, UTF-8 without BOM, file 끝 정확히 한 newline로 encode한 bytes에서 계산한다. `role:"policy"` material은 policy preview가 만든 UTF-8 string을 newline 재정규화 없이 encode한다. `path:null`인 owner-result material은 complete `context-owner-result/v1`의 canonical JSON string 자체이며 trailing newline을 붙이지 않는다. 그 raw UTF-8 SHA-256은 plan의 `owner_result_digest`와 같아야 한다. apply는 material content를 다시 render하지 않고 이 bytes를 쓴다.
- requested mutation을 canonical render한 bytes가 before와 같으면 timestamp를 올리지 않고 `noop:true`, bundle 없음으로 반환한다. noop은 durable write approval이 필요 없고 index rebuild도 만들지 않는다.
- `approval_digest`, candidate/capability digest와 file digest는 모두 lowercase 64 hex다.

#### Operation discriminated schema

plan operation은 아래 다섯 개만 허용한다. 모든 path는 repository-relative POSIX path이며 symlink segment를 거부한다.

file operation은 destination parent가 이미 존재하는 directory여야 한다. 예외는 `core_init`과 `area_register`뿐이며, 이때 coordinator가 descriptor에서 결정된 exact allowlist parent를 mode 0755로 생성할 수 있다. arbitrary directory create/remove는 v1 operation이 아니다.

| op | required fields | precondition / resume |
|---|---|---|
| `file_create` | `effect_id,role,area?,path,before_sha256:null,after_sha256,material` | path absent; path가 already after면 completed |
| `file_replace` | `effect_id,role,area?,path,before_sha256,after_sha256,material` | current=before; current=after면 completed |
| `file_move` | `effect_id,role:"artifact",area,id,from_path,to_path,before_sha256,destination_before_sha256:null,after_sha256,material?` | 아래 rename/changed-move state machine. material 생략은 after=before인 byte-identical rename만 허용 |
| `file_delete` | `effect_id,role:"artifact",area,id,path,before_sha256,inbound_refs:[]` | current=before; absent면 completed. inbound internal ref가 있으면 plan 생성 자체를 거부 |
| `index_rebuild` | `derived_from,areas,include_root,before_sha256,after_sha256,seed_materials?` | 각 reserved index가 before/null; after면 해당 path completed. core의 canonical generator만 output content 생성 |

`role`은 `artifact | policy`다. `area`는 artifact role에서 필수, policy role에서 금지한다. `policy`는 [[context-core-plugin]]의 exact repository-entry allowlist에서만 허용한다. 모든 plan에는 canonical `owner_descriptor` 전체가 있다.

- domain artifact transition은 `source_type:"owner_result"`, `owner_result_digest`, `owner_result_material`과 optional `owner_validation` receipt를 가진다. owner-result material은 `path:null`이며 complete canonical owner result를 담는다. plan digest가 material ID와 owner-result digest를 결박하고 apply가 full result를 parse해 semantic input digest·JSON pointer·transition별 required set, draft/effect/owner-plan과 final operation/material의 대응을 다시 검증한다. capability가 `batch_validation_surface`를 선언하면 domain plan의 validation receipt는 필수다.
- `core_init | area_register | policy_install`은 `source_type:"core_control"`, canonical `control_input`을 plan 안에 직접 가진다. control input은 각 명령의 normalized explicit args, target paths, descriptor/seed or marker digest만 포함하고 semantic attestation은 금지한다. 이 세 transition에는 owner-result fields와 validation receipt가 없어야 한다.

artifact `area`는 root catalog의 owner claim과 일치해야 한다. `transition: area_register`의 아직 미등록 new area는 control input의 descriptor `owner,kind,artifact_schema`, seed frontmatter와 root row가 일치하는지를 대신 검증한다.

- `plan_id`는 `plan_`+lowercase UUIDv4 hex 32자다. `effect_id`와 `material_id`는 bundle-local `[a-z][a-z0-9_]{0,79}`다.
- `prior_bundle_digests`는 grouped preview 앞 item들의 approval digest를 순서대로 담는다. core preview는 prior bundle의 validated expected after-state를 현재 filesystem 위에 overlay해 before/index digest를 계산한다. apply는 각 prior digest가 같은 batch receipt에서 성공했는지 확인할 수 없으므로 caller 순서와 exact filesystem precondition 둘 다 필요하며, precondition만으로 우회 실행해도 안전하지만 순서가 다르면 보통 실패한다.
- optional `read_preconditions`는 `{id,path,sha256}` object의 path ASC array다. operation target이 아니지만 conflict/authority 판단에 사용한 current artifact를 결박하며 apply가 exact bytes와 ID를 재검증한다. decision scope acknowledgement는 acknowledged conflict 전부를 preview effect와 이 배열에 넣는다. plan의 decision `index_rebuild.before_sha256`도 current index 전체를 결박하므로 새 overlap artifact가 생기면 domain 의미를 core가 해석하지 않아도 precondition이 실패한다. 모든 lifecycle mutation은 target area index before digest를 가지므로 index 변경 뒤 재-preview가 필요하다. owner validation receipt의 `base_area_index_sha256`는 grouped preview 시작 전 physical index digest이고, receipt의 ordered prior same-area digests를 그 base에 overlay한 expected digest가 현재 plan의 area-index `before_sha256`와 exact match해야 한다.
- `effect_id`, material ID, operation은 bundle 안에서 유일하다. 모든 non-index operation은 preview effect 하나와 exact `effect_id`로 1:1 대응하고 action·area·id·source/destination path가 일치해야 한다. 모든 non-delete destination은 같은 path의 material 하나를 참조하며 content digest가 `after_sha256`과 일치한다.
- `index_rebuild.derived_from`은 같은 plan의 effect ID를 중복 없이 가리킨다. 일반 artifact transition에서 `areas`는 그 effects가 touch한 area의 sorted set과 정확히 같고 `include_root:false`다. `transition: area_register|core_init`은 등록/init effect ID를 derived_from에 넣고 `include_root:true`를 요구한다. 다른 hidden operation/effect는 `plan_preview_mismatch`다.
- `rename`은 byte-identical `file_move`, retire/supersede는 changed material을 가진 `file_move`, annotate/update는 `file_replace`, discard는 `file_delete`로 표현한다. index-only repair는 mutation plan 밖의 `refresh --fix index`가 담당한다.
- area 등록은 별도 multi-output op가 아니다. `transition: area_register`, hashed owner descriptor와 `index_rebuild(areas:[new_area], include_root:true)` 하나로 root index와 새 area index 두 projection을 생성한다. preview effect는 `register_area`이고 index operation이 그 effect ID를 `derived_from`으로 가진다. 이 transition에서만 exact area root를 생성하며, validated seed가 `History` generated marker를 가진 area면 `<area>/retired/`도 생성하고 Current-only seed면 생성하지 않는다. 임의 child directory는 만들지 않는다.
- `seed_materials`는 repository-relative index path→material ID의 path ASC object다. `area_register`에서는 absent인 새 area index 하나를, `core_init`에서는 absent인 root/SNAP/OBS index를 정확히 seed하며 그 밖의 transition에서는 금지한다. 각 seed material은 자기 index path를 가지며 complete index Markdown content를 담는다. reserved frontmatter, 사람이 작성한 title/summary/search terms/projection fields, empty generated markers가 필수다. core는 seed와 owner descriptor를 검증하고 canonical generator로 generated block/root area row를 채운 output이 `after_sha256`와 같은지 확인한다. seed material content의 canonical file bytes digest도 `control_input.seed_digests`에 path ASC로 들어가 approval digest에 결박된다. seed material이 없으면 이미 존재하는 index의 marker 밖 bytes를 보존해 rebuild한다. 대상 index가 absent인데 허용된 seed가 없으면 `index_seed_required`로 실패하며 설명 metadata를 추측하지 않는다.
- coordinator는 owner/area 권한, root containment, exact precondition, common envelope/ref/lifecycle, effect↔operation 완전 대응과 approval digest를 재검증한다.
- 일반 plan의 artifact area는 owner descriptor claim과 같아야 한다. v1의 유일한 cross-owner transition은 `decision_fallback_import`이며 exact decision create+observation retire effects, `kind_hint: decision`, predecessor/successor의 exact id·path·artifact SHA-256·actual primary claim, [[context-capture-routing]]의 operation-bound owner `same_claim` attestation과 reciprocal edge를 요구한다.
- apply는 caller의 `--approved-digest`가 bundle의 digest와 정확히 일치할 때만 실행한다. owner가 승인 뒤 preview, plan 또는 material을 재생성하면 실패한다.

#### `file_move` crash-resume state machine

byte-identical rename과 content-changing retire move는 다른 write 순서를 쓴다.

- rename(`material` absent, after=before): start `source=before,destination=absent`에서 같은 filesystem의 `os.replace(source,destination)` 한 번만 수행한다. resume 허용 상태는 start 또는 final `source=absent,destination=after`뿐이다.
- changed move(`material` present, after!=before): **destination prepare → source unlink** 순서만 허용한다. 먼저 after material을 destination parent의 temp file에 durable write/fsync하고 `os.replace(temp,destination)`한다. parent를 가능한 platform에서 fsync한 뒤 source가 아직 exact before인지 다시 확인하고 `os.unlink(source)`한 뒤 source parent를 fsync한다.
- changed move resume 허용 상태는 정확히 세 개다: start `source=before,destination=absent`; prepared `source=before,destination=after`; final `source=absent,destination=after`. prepared에서는 material을 다시 쓰지 않고 source exact before를 unlink한다. 그 외 `source/destination` 조합이나 제3의 digest는 `precondition_changed`다.
- coordinator는 non-index operation을 plan array 순서로 처리하고 각 operation이 final state가 된 뒤 다음으로 간다. 모든 file operation이 final일 때만 index rebuild를 시작한다. crash로 prepared/partial document state가 보이면 strict integrity가 duplicate ID/slot/edge drift를 보고하지만 같은 approved bundle 재실행은 위 state machine으로 결정적으로 수렴한다.

### 동시성·write consistency

- coordinator는 `tempfile.gettempdir()/context-core-locks/<sha256(repo-realpath)>`의 lock file에 `fcntl.flock(LOCK_EX)`를 잡는다. parent는 mode 0700, file은 `os.open(O_CREAT|O_RDWR, 0o600)` 후 실제 mode가 group/other writable이면 실패한다. symlink lock file은 `O_NOFOLLOW` 사용 가능 platform에서 거부하고, 없으면 `lstat`/`fstat` inode 일치를 검증한다. lock은 apply에서만 만들며 project filesystem preview를 변경하지 않는다. 따라서 v1 runtime은 Python 3.11+, Git 2.39+, `fcntl`·atomic same-filesystem `os.replace`를 제공하는 macOS 13+와 Linux를 지원하고 Windows는 지원하지 않는다.
- lock 안에서 approval/plan/precondition validate→모든 after-content 검증→plan 순서의 file operation→계획된 index regenerate/replace 순서로 수행한다. create/replace와 changed-move destination temp는 target parent의 `tempfile.mkstemp`, mode 0600으로 만들고 flush+`os.fsync` 후 replace한다. directory fsync 지원 platform에서는 parent도 fsync한다. `file_move`는 바로 위 전용 state machine이 우선한다.
- 개별 파일 replace는 atomic이지만 여러 파일 전체가 crash-atomic하다고 주장하지 않는다.
- 중간 실패 뒤 같은 bundle을 재실행하면 각 operation 표와 changed-move의 명시적 start/prepared/final 상태만 허용해 남은 operation을 완료한다. 제3의 content나 허용되지 않은 source/destination 조합이면 `precondition_changed`로 중단한다.
- process crash나 index write 실패 후 document가 남으면 문서를 정본으로 유지한다. 다음 `doctor`/plain `refresh`가 edge/index drift를 진단하고, caller가 보관한 bundle 재실행 또는 `refresh --fix index`로 복구한다. selected stale link의 strict read는 exit 6 `index_stale`과 affected path를 반환한다.
- root index는 area install/remove 때만 쓰고 artifact capture hot path에서는 건드리지 않는다.
- 각 domain bundle은 target area index의 exact before digest와 approved after material을 결박한다. root lock 아래 첫 apply 뒤 stale한 병렬 bundle은 `precondition_changed`로 실패하고 re-preview해야 하므로 lost entry를 막는다.
- supported Obsidian view는 repository root를 vault root로 연 경우다. v1 root-relative wikilink는 이 조건에서 graph hub를 구성하며 `context/`만 별도 vault로 여는 구성은 지원하지 않는다.

## 취지

의미가 드러나는 `*.index.md`는 파일 검색과 Obsidian graph에서 영역 hub로 보인다. 자유 파일명은 사람이 문서를 다루는 비용을 줄이고 immutable ID는 rename과 cross-plugin relation을 안전하게 만든다. index-first 검색은 모든 문서 frontmatter를 여는 기존 wiki 방식보다 실제 I/O와 model context를 줄이되, 문서를 정본으로 남겨 repair 가능성을 유지한다.

## 구성요소

- [[context-plugin-definition]] — 전체 경계와 공통 불변식
- [[context-artifact-lifecycle]] — path와 lifecycle field 규칙
- [[context-capture-routing]] — candidate와 recall budget
- [[context-core-plugin]] — root/snapshot/observation owner
- [[context-decision-plugin]] — decision area owner
- [[DEC-2026-08-13-180256-컨텍스트-저장소는-semantic-index와-파일명-독립-id를-사용한다]] — 본 계약의 결정 근거
