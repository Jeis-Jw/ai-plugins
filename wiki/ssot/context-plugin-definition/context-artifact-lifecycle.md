---
title: SNAP OBS DEC artifact lifecycle 계약
created_at: 2026-08-13
summary: SNAP은 현재 handoff staging으로 제자리 갱신 후 discard하고, OBS와 DEC는 의미 불변 record로서 domain별 retire reason과 supersede edge를 갖는 v1 상태 전이 계약.
tags: [context-core, context-decision, snapshot, observation, decision, lifecycle, ssot]
verified_at: 2026-08-13
affects_paths: [plugins/context-core/**, plugins/context-decision/**]
---

## 현재 상태

artifact가 생성됐다는 이유로 그 원천 artifact를 자동 종료하지 않는다. successor가 **같은 semantic claim**을 인수할 때만 supersede한다. evidence와 choice, handoff와 durable record처럼 의미가 다르면 관계로 공존한다.

### 공통 상태 표현

- SNAP은 파일 존재 여부만 갖고 retired 상태가 없다.
- OBS·DEC의 active 상태는 area root, historical 상태는 `retired/` path가 정본이다.
- active/current를 frontmatter `status`로 중복 저장하지 않는다.
- retired artifact만 timezone 포함 RFC3339 `retired_at`과 owner가 허용한 `retired_reason`을 가진다.
- invalidated/withdrawn에는 사용자가 제공한 줄바꿈 없는 1~500자 `retirement_note`가 필수다. superseded는 successor relation 자체가 이유이므로 optional이다.
- successor가 있는 `superseded`만 `superseded_by`가 필수다.
- successor는 top-level `supersedes`로 predecessor ID를 보유한다.
- stale, anchor_changed, revisit_due는 조회 시 계산되는 warning이지 lifecycle 상태가 아니다.

### SNAP — mutable staging

SNAP은 여러 개의 named handoff를 가질 수 있다. 각 SNAP ID는 하나의 현재 handoff chain이며, vault 전체 singleton이나 세션당 singleton 제약은 두지 않는다.

```text
absent ──save(create)──> present ──update/merge──> present ──discard──> absent
```

frontmatter:

```yaml
schema: "context-snapshot/v1"
id: "ctx_..."
title: "인증 리팩터링 handoff"
summary: "BFF 세션 소유권 논의의 현재 상태와 열린 항목"
created_at: "2026-08-13T18:20:00+09:00"
updated_at: "2026-08-13T19:10:00+09:00"
captured_from: "conversation"
anchors: ["ctx_..."]
tags: ["auth"]
search_terms: ["BFF","OAuth callback"]
```

body section:

- 필수: `## 현재 맥락`, `## 열린 항목`, `## 다음 단계`
- 선택: `## 정해진 것`, `## 참조`, `## capture 후보`

mutation 규칙:

- `save`는 create-only다. 같은 path가 있으면 `path_exists`, 같은 ID가 있으면 `duplicate_id`로 실패한다. `현재 맥락`, `열린 항목`, `다음 단계`를 모두 받아야 한다.
- 같은 SNAP 갱신은 exact ID로 수행하고 파일과 ID를 유지한다.
- `update --id`의 기본은 전체 replace이며 필수 세 section을 모두 받아야 한다. `update --id --merge`만 전달된 section·metadata를 부분 갱신하고 생략된 값은 보존한다.
- `created_at`은 보존하고 `updated_at`은 실제 내용 변경 때만 갱신한다.
- title·summary·tags·search_terms도 갱신할 수 있다.
- `archive`, `promoted`, `retired`, `verified_at`을 두지 않는다.
- DEC·OBS·TASK·SSOT 생성만으로 자동 discard하지 않는다.
- 열린 항목이 모두 처리됐거나 사용자가 버리기로 했을 때 exact ID/path로 discard한다.
- durable artifact는 삭제 가능한 SNAP ID를 무결성 필수 relation으로 사용하지 않는다. 필요하면 SNAP의 source_refs를 복사하고 provenance hint만 남긴다.

load label:

- `authority: staging`
- `use_as: resume_context`
- anchors 전부 active면 `freshness: anchored`
- anchor가 missing/retired/superseded면 `freshness: anchor_changed`와 warning
- anchor가 없으면 `freshness: authority_unknown`
- configured `snapshot_stale_days` 초과는 hygiene warning이며 자동 삭제하지 않는다.

### OBS — immutable evidence claim

OBS는 발견 당시의 claim과 근거를 보존하는 비권위 record다.

```text
active
 ├─ invalidate ─────────────> retired(invalidated)
 └─ successor가 같은 claim 인수 ─> retired(superseded)
```

frontmatter additive field:

```yaml
schema: "context-observation/v1"
kind_hint: "decision"
verified_at: "2026-08-13T18:30:00+09:00"
affects_paths: ["src/auth/**"]
relations: {"related":["ctx_..."]}
```

body section:

- 필수: `## 관찰`, `## 근거`
- 선택: `## 영향`, `## 현재 처리`, `## 후속 조건`

mutation 규칙:

- 관찰 claim 또는 evidence의 의미가 바뀌면 새 OBS를 만들고 기존 OBS를 supersede한다. successor create와 predecessor retire는 [[context-capture-routing]]의 bounded old/new input에 대한 owner skill의 `same_claim` attestation 및 하나의 승인된 mutation plan에서 수행하며 이미 존재하는 successor ID를 사후 연결하는 명령은 제공하지 않는다.
- typo, title, summary, tags, search_terms, source_refs 교정은 제자리 수정할 수 있다.
- 실제 근거를 다시 확인한 경우에만 `verified_at`을 갱신할 수 있다.
- 반증됐거나 전제가 사라져 더는 성립하지 않으면 `invalidate`한다. persisted `retired_reason`은 `invalidated`다.
- 같은 claim을 더 정확한 OBS 또는 허용된 다른 owner artifact가 인수하면 `retired_reason: superseded`와 `superseded_by`를 기록한다.
- 오래됐거나 `verified_at`이 없다는 이유만으로 retire하지 않는다. recall에서 `stale` 또는 `authority_unknown`으로 낮춰 보여준다.
- authority는 active 여부와 관계없이 `evidence/non_authoritative`다.

### DEC — immutable authoritative choice

DEC는 `{결정 + 취지 + 반려대안}`을 하나의 의미 단위로 보존한다.

```text
current
 ├─ withdraw ───────────────> retired(withdrawn)
 └─ 새 DEC가 같은 slot 대체 ───> retired(superseded) + new current
```

frontmatter additive field:

```yaml
schema: "context-decision/v1"
scope: "project/auth"
decision_key: "session-owner"
revisit_when: ["브라우저가 first-party cookie도 차단할 때"]
relations: {"informed_by":["ctx_..."]}
supersedes: ["ctx_..."]
```

body section:

- 필수 substantive: `## 결정`, `## 취지`
- 필수 존재: `## 반려대안`; 대안이 없으면 `검토하지 않음: <이유>`를 명시한다.
- 선택: `## 근거와 제약`, `## 트레이드오프`, `## 재평가 조건`

mutation 규칙:

- 결정·취지·반려대안 중 하나의 의미가 바뀌면 새 DEC를 만든다.
- typo, title, summary, tags, search_terms, source_refs 교정은 제자리 수정할 수 있다.
- DEC는 `verified_at`을 갖지 않는다. 현재 유효성은 active path와 lifecycle edge가 정한다.
- 같은 `(scope, decision_key)`에는 current DEC가 최대 하나다.
- successor는 predecessor의 slot을 상속하고 `supersedes`/`superseded_by` 양쪽 edge를 기록한다.
- successor 없이 결정을 명시적으로 철회하면 persisted `retired_reason`은 `withdrawn`이다.
- revisit 조건 충족은 review proposal만 만들며 자동 withdraw/supersede하지 않는다.
- TASK·SSOT·OBS 생성은 DEC 종료 조건이 아니다.

### Cross-artifact 전이

| source → output | source lifecycle | 관계 |
|---|---|---|
| SNAP → OBS/DEC/TASK/SSOT | 열린 항목이 남으면 유지, 모두 흡수되면 승인 후 discard | output은 SNAP의 외부 source_refs를 복사; SNAP ID는 soft provenance만 허용 |
| OBS evidence → DEC choice | OBS 유지 | `DEC.relations.informed_by += OBS.id` |
| core-only decision-like OBS → 승인된 DEC | 동일 claim일 때 OBS superseded | DEC가 OBS를 `supersedes`; OBS는 `superseded_by: DEC.id`; core coordinator가 한 plan으로 적용 |
| DEC → TASK/SSOT | DEC 유지 | output이 DEC ID를 근거로 참조 |
| OBS → 더 정확한 OBS | old OBS superseded | 양방향 supersede edge |
| DEC → 새 DEC | old DEC superseded | 같은 scope/key, 양방향 supersede edge |

core-only fallback OBS에서 DEC로 넘어갈 때 다음 조건을 모두 만족해야 cross-kind supersede를 허용한다.

1. OBS에 `kind_hint: decision`이 있다.
2. DEC capture가 별도 사용자 승인을 받았다.
3. OBS `source_claim_fingerprint`와 새 DEC의 `claim_fingerprint`가 exact match하고 [[context-capture-routing]]의 bounded old/new input에 대한 owner skill의 `same_claim` attestation 및 preview 승인이 있다.
4. 새 DEC가 원 OBS를 predecessor로 기록한다.

전환의 semantic 검증과 DEC draft 생성은 context-decision owner가 수행한다. OBS retire를 포함한 물리적 변경은 [[context-storage-retrieval]]의 context-core coordinator가 root lock 아래 하나의 `decision_fallback_import` plan으로 적용한다. owner가 서로의 파일을 직접 수정하지 않는다.

일반 evidence OBS를 DEC가 사용한 경우에는 위 조건을 적용하지 않고 OBS를 active로 둔다.

### Discard — mistake undo

- SNAP discard는 정상 종료가 될 수 있다.
- OBS·DEC discard는 잘못 생성한 duplicate/오류를 되돌리는 용도다. 당시 유효했으나 바뀐 기록은 retire한다.
- 파괴적 discard는 exact ID/path만 허용하고 preview에서 inbound relation과 lifecycle edge를 보여준다.
- inbound internal reference가 하나라도 있으면 v1에서는 항상 거부한다. 참조 owner의 명시적 annotate로 edge를 먼저 제거하고 integrity를 통과한 뒤 별도 discard approval을 받아야 한다. broken graph를 만드는 `--force`와 cross-owner auto-detach는 제공하지 않는다.
- Git repository에서는 Git이 물리적 이력을 보유한다. Git이 없는 저장소의 archive 요구는 v1 범위 밖이다.

### Index 반영

- active OBS·DEC는 area index `Current`, retired는 `History` generated block에 투영한다.
- SNAP은 존재하는 문서만 `Current`에 투영하고 discard 시 entry를 제거한다.
- default recall은 Current만, `--include-history`에서만 History를 검색한다.
- 반복 supersede에서 자연 filename 충돌을 피하기 위해 history path는 [[context-storage-retrieval]]의 `<stem>--<id12>.md` 규칙을 사용한다.
- History row는 artifact open 없이 안내할 수 있도록 `retired_at`, `retired_reason`, optional `superseded_by`를 포함한다.
- lifecycle mutation 성공 결과는 `changed_paths`, `index_paths`, `warnings`를 반환한다.

## 취지

SNAP·OBS·DEC는 임시성, 권위와 변경 의미가 다르다. 하나의 공통 status enum에 맞추면 snapshot archive, observation promotion, decision completion 같은 의미 없는 상태가 생긴다. owner별 lifecycle을 유지하면 core가 domain 의미를 침범하지 않으면서도 공통 index와 relation integrity를 제공할 수 있다.

## 구성요소

- [[context-storage-retrieval]] — path·ID·index가 상태를 표현하는 방식
- [[context-capture-routing]] — 승인 전 candidate와 cross-owner routing
- [[context-core-plugin]] — SNAP·OBS mutation owner
- [[context-decision-plugin]] — DEC mutation owner
- [[DEC-2026-08-13-180257-snap-obs-dec는-각-의미에-맞는-독립-lifecycle을-갖는다]] — 본 계약의 결정 근거
