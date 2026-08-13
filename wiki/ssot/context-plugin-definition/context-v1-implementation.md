---
title: context-core와 context-decision v1 구현 계획과 acceptance
created_at: 2026-08-13
summary: 구현 순서, source 단위, CLI·fixture·통합 테스트, token/I-O 계측, host packaging과 공개 release gate를 정의한 context plugin v1 실행 청사진.
tags: [context-core, context-decision, implementation, acceptance, release, ssot]
verified_at: 2026-08-13
affects_paths: [plugins/context-core/**, plugins/context-decision/**]
---

## 현재 상태

이 문서는 [[context-storage-retrieval]], [[context-artifact-lifecycle]], [[context-capture-routing]], [[context-core-plugin]], [[context-decision-plugin]]을 코드로 옮기는 순서와 완료 조건이다. 현재 구현은 시작되지 않았다.

### v1 기술 제약

- filesystem·Markdown primary
- Python 3.11+ stdlib-only CLI, Git 2.39+, macOS 13+/Linux (`fcntl` required); Windows/non-Git directory 미지원
- provider-neutral JSON I/O
- network, database, daemon, vector/embedding 없음
- runtime hook과 transcript/session ledger 없음
- Obsidian dependency 0; standard wikilink 호환만 제공
- semantic owner는 complete draft/effect/proposed plan만 생성하고 context-core가 final bundle로 봉인하며 coordinator만 physical write
- mutation 기본 preview, 동일 bundle과 exact approved digest를 받은 `transaction apply`에서만 write
- storage root는 `git rev-parse --show-toplevel`의 Git worktree root 아래 `context/`로 고정; `--root`와 repository 밖 storage 없음
- 기존 `wiki/` 자동 migration 없음

### 구현 단위

### 선택 가능한 구현 cut line

기획 전체를 한 번에 출시할 필요는 없다. 동일 계약에서 다음 cut line을 선택한다.

| cut | 포함 | 판정 |
|---|---|---|
| A — storage kernel | Phase 0~2의 index/recall/SNAP/OBS direct surface | 내부 dogfood 가능, decision 제품 공개에는 부족 |
| B — decision wedge | A + Phase 3의 explicit DEC capture/brief/supersede | 첫 private beta 권장; 사용자가 명시 호출하고 자동 audit/routing은 아직 없음 |
| C — integrated context | B + Phase 4 audit/routing/grouped approval + policy | public v1 기능 완성 |
| D — distribution proof | C + Phase 5 양 host packaging/demo | marketplace/커뮤니티 공개 gate |

어떤 cut도 schema/index/lifecycle을 축약한 별도 구현을 만들지 않는다. 뒤 기능을 비활성화할 뿐 같은 fixture와 storage를 사용한다. 이렇게 해야 가볍게 검증하면서도 beta 문서를 다시 migrate하지 않는다.

#### Phase 0 — 위험 spike

목표는 product invariant를 바꾸지 않고 host·filesystem mechanism을 검증하는 것이다.

1. Codex와 Claude Code에서 설치된 semantic owner skill을 식별하거나 caller descriptor를 전달하고 host가 owner semantic attestation+draft 결과를 수집하는 경로를 확인한다.
2. 양 host의 plugin inventory가 `marketplace=jeis-ai-plugins`, `plugin=context-core`, enabled 상태를 구분하는 경로와 core doctor/protocol handshake를 확인한다. 설치 정책은 이미 manual hard dependency로 확정됐으며 native dependency·자동 install/enable/update는 검토 대상이 아니다.
3. `*.index.md` generated row parser/serializer와 Obsidian graph link를 fixture repo에서 확인한다.
4. Unicode filename·NFC/NFD, 파일명 공백, rename과 path collision을 macOS/Linux fixture에서 확인한다.
5. `fcntl` advisory lock, exact byte digest precondition, same-directory temp+replace와 changed-move의 destination-prepare/source-unlink resume를 parallel capture/강제 crash fixture로 검증한다.

Phase 0가 막혀도 semantic index 이름, immutable ID, lifecycle, approval gate와 manual dependency 정책을 바꾸지 않는다. host inventory/capability probe와 안내 renderer 구현만 조정한다.

#### Phase 1 — context-common storage/index

`context-core` 안에 다음 thin unit을 구현한다.

```text
model       narrow YAML/frontmatter, ID, schema, section parser
paths       root containment, reserved names, NFC, exact resolver
index       root/area generated block parser·serializer·scorer
storage     advisory lock, preview diff, temp write·replace, repair result
coordinator owner/area authorization, plan/digest/precondition, cross-owner allowlist
recall      index-first Stage 1, selected read/section/pack, byte budget
integrity   schema/ref/lifecycle/index checks and index-only fix
cli         argparse dispatch, JSON/text output, exit codes
```

처음부터 generic addon framework로 만들지 않는다. 공통 code는 SNAP·OBS와 decision fixture가 실제 공유하는 만큼만 둔다.

완료 조건:

- `schema`가 root 없이 계약을 출력
- `init` idempotent
- reserved index와 자유 filename/immutable ID 동작
- index parse/regenerate byte-deterministic
- Stage 1 artifact open·directory listing·artifact stat count 0
- index fallback/strict-index 분기
- owner descriptor+hashed complete index seed 기반 area register와 승인 digest 불일치/seed 누락 fail-closed

#### Phase 2 — SNAP·OBS owner

SNAP save/update/merge/load/search/discard와 OBS capture/read/search/annotate/reverify/invalidate/supersede/discard를 coordinator 내부 owner+writer fixture로 구현한다.

완료 조건:

- SNAP created_at 보존·updated_at 변경·retired 0
- 여러 named SNAP 허용, save=create-only, update full-replace와 merge partial-update 구분
- anchor freshness label
- OBS claim/evidence validation
- metadata correction과 semantic supersede 분리
- successor create+predecessor retire가 하나인 OBS supersede plan
- embedded successor claim input과 prepared old/new lifecycle input의 `same_claim` attestation 재검증
- invalidated/superseded History row에 reason/time/successor projection
- destructive operation exact ref+dry-run+backlink guard

#### Phase 3 — context-decision owner

DEC schema, claim/draft validator, slot conflict, capture/search/read/brief, supersede/withdraw/revisit와 decision area registration plan을 구현한다. decision CLI는 physical write를 하지 않는다.

완료 조건:

- accepted choice만 claim
- 핵심 3 section validation
- exact slot exclusivity
- scope overlap conflict acknowledgement
- ordered prior same-area bundle을 overlay한 batch validator receipt와 same-batch slot exclusivity
- current/history와 reciprocal lifecycle edge
- repeated same-title supersede의 deterministic history filename
- init/root 등록과 fallback OBS import가 core coordinator를 경유

#### Phase 4 — audit·routing·approval integration

agent skill과 deterministic router를 연결한다.

- host가 capability descriptor를 수집하고 skill이 현재 context에서 owner input을 포함한 candidate를 한 번 추출
- host가 matching owner skill을 호출해 claim/decline attestation과 complete draft/proposed plan을 수집하고, lifecycle은 core prepare input에 대한 operation-bound attestation을 받은 뒤 core가 final bundle로 봉인
- CLI는 candidate+descriptor+claim result를 검증하고 route하며 owner binary를 직접 호출하지 않음
- selected addon result는 owner batch validator가 current+prior same-area virtual state에서 검증하고 receipt를 final plan에 결박
- user explicit type, owner claim, OBS fallback, SNAP handoff, skip 우선순위
- actual artifact content와 lifecycle effect를 포함한 one grouped preview
- 승인된 final bundle digest만 core coordinator apply
- batch receipt에 proposal/created/skipped/error를 묶음
- init의 AGENTS.md/CLAUDE.md policy preview·managed block·sequential receipt

완료 조건:

- audit/route 자체 filesystem diff 0
- owner가 transcript를 다시 읽는 호출 0
- owner conflict·unavailable·duplicate가 fail-closed
- embedded semantic input/attestation digest·pointer·transition set 불일치 fail-closed
- requested kind가 owner semantic validation을 우회하지 않음
- 승인 뒤 owner draft 재생성 0, digest mismatch apply 0
- candidate와 approval preview byte budget; 핵심 section 절단 0
- core-only OBS fallback과 core+decision DEC routing 통합 fixture
- policy marker 밖 bytes 보존과 idempotent second init

#### Phase 5 — agent policy·distribution·public proof

- 두 host용 manifest와 skill path portability test
- 두 manifest의 plugin dependency metadata 부재와 marketplace implicit-install 부재 검사
- exact `context-core@jeis-ai-plugins` missing/source-mismatch/disabled/incompatible 및 repository-uninitialized preflight demo
- provider marketplace source `Jeis-Jw/ai-plugins`, 수동 scope 선택, reload/new-session과 init 재시도 안내 검증; install/enable/update 실행 0
- context-core standalone demo
- context-decision 설치 조합 demo
- README에서 decision continuity를 전면 가치로 설명
- existing wiki와의 차이·migration 없음·PCMS 경계 명시
- version 0.1.0 package validation

### Cross-plugin protocol fixture

두 plugin은 다음 fixture를 공유해야 한다.

- common document envelope valid/invalid cases
- `ctx_<uuidhex>` ID와 exact ref
- root/area index frontmatter와 canonical JSON row
- candidate/capability/semantic-attestation/owner-result/route JSON
- complete approval material(preview+plan), exact byte digest와 final mutation bundle
- frontmatter JSON-compatible YAML subset valid/invalid corpus와 canonical rewrite
- preview/apply transaction result와 error envelope
- exit code table
- manual dependency requirement/error envelope과 host inventory fixture
- UTF-8 byte budget/truncation

하나의 host-independent fixture directory를 source of truth로 두고 두 plugin test가 같은 fixture를 실행한다. 두 개의 독립적인 protocol 해석을 만들지 않는다. 실제 packaging에서 shared source를 import할 수 없는 경우 generated vendoring을 허용하되 build가 source digest parity를 검증해야 한다.

### Acceptance matrix

| # | fixture | expected |
|---:|---|---|
| 1 | init 두 번 | 두 번째 diff 0, 사람 작성 설명 보존 |
| 2 | decision plugin이 먼저 init | `core_missing`, exact provider marketplace/plugin/source와 수동 next action, repository·host config write 0 |
| 3 | 자연 filename capture | prefix/timestamp 0, valid immutable ID |
| 4 | path collision | overwrite/suffix 없이 `path_exists` |
| 5 | rename | ID·relations 유지, index path만 변경 |
| 6 | malformed/reserved path | root escape와 `*.index.md` artifact 거부 |
| 7 | index generation | repeated refresh byte-identical, self-entry 0 |
| 8 | Stage 1 search | root/area index만 read, artifact read/list/stat 0 |
| 9 | broken index/selected link | normal은 해당 area scan fallback+warning, strict-index exit 6 |
| 10 | output limit | 완전한 item만 반환, truncated/omitted 정확 |
| 11 | named SNAP | 둘 이상 독립 생성 가능; save collision 실패; 각 ID만 갱신 |
| 12 | SNAP update/merge | full update는 필수 section 전체 요구, merge는 omitted section·created_at 보존 |
| 13 | SNAP discard | file/index 제거, retired artifact 0 |
| 14 | OBS invalidate | History로 이동, reason/time이 index에 투영 |
| 15 | OBS supersede | embedded claim+same_claim inputs/attestations을 재검증하고 한 plan에서 successor create+old retire, reciprocal edge와 index 일치 |
| 16 | repeated supersede | 같은 natural filename 3세대에서 history path collision 0 |
| 17 | decision-like fallback | core-only는 labeled OBS 하나, DEC authority 0 |
| 18 | owner installed | 같은 claim은 DEC 하나, OBS fallback 억제 |
| 19 | explicit unavailable type | owner_unavailable, silent downgrade 0 |
| 20 | explicit invalid type | requested DEC라도 fact이면 owner decline, authority 상승 0 |
| 21 | independent fact+choice | 서로 다른 claim_key로 OBS+DEC 허용 |
| 22 | owner call contract | host 수집 claim result만 router 입력, router owner process 실행 0 |
| 23 | approval preview | 실제 필수 section·path·lifecycle·plan·digest 노출, 승인 뒤 생성/변경 0 |
| 24 | approval digest | preview+plan·owner-result material 변조, hidden operation, 불일치 digest, autonomous maintenance apply 모두 실패 |
| 25 | DEC core sections | 결정/취지/반려대안 누락·placeholder 거부 |
| 26 | duplicate slot | filesystem current 또는 앞 same-batch virtual current를 supersede하지 않은 second current 거부 |
| 27 | scope overlap | current와 앞 same-batch virtual DEC 모두 conflict 후보로 노출, ordered validation receipt/ack 전 apply 거부 |
| 28 | DEC supersede | old History, new Current, 같은 slot과 양방향 edge |
| 29 | DEC withdraw | successor 없이 History, current recall 제외 |
| 30 | revisit due | warning/proposal만, filesystem diff 0 |
| 31 | evidence OBS→DEC | OBS active, DEC.informed_by 연결 |
| 32 | fallback OBS→DEC | prepared lifecycle input과 claim+same_claim attestation, 승인된 single coordinator plan으로 OBS superseded |
| 33 | addon init | decision이 root를 직접 쓰지 않고 hashed area index seed를 참조한 area register index rebuild 사용 |
| 34 | policy install | AGENTS/CLAUDE marker 밖 bytes 보존, plan digest와 allowlist 검증 |
| 35 | frontmatter grammar | colon/comma/quote/unknown field canonical round-trip, duplicate/unsupported fail |
| 36 | scope/key normalization | case/slash/space variants canonical slot·segment ancestor 일치 |
| 37 | parallel capture | duplicate ID/lost index entry 0 |
| 38 | crash between writes | changed move start/prepared/final 각 지점에서 exact bundle resume, doc 정본 보존, index_stale와 repair 성공 |
| 39 | strict refresh | out-of-band 신규/rename/frontmatter drift 전수 검출 |
| 40 | Obsidian graph | repository root vault에서 context.index→area index→artifact hub 구분 |
| 41 | wrong-source/disabled/incompatible core | 각각 `core_source_mismatch|core_disabled|core_incompatible`, install/enable/update 자동 실행과 repository·host config write 0 |
| 42 | exact core, repository absent | `core_uninitialized`, `context-core:init` 수동 안내, decision seed/descriptor와 filesystem write 0 |
| 43 | distribution manifests | Claude/Codex manifest dependency field 0, context-decision 때문에 core를 implicit/default install하는 marketplace policy 0 |

### Integrity release gate

`refresh --level integrity --strict`가 다음을 모두 잡아야 한다.

- missing/wrong reserved index, marker와 canonical JSON 오류
- schema/area/path mismatch와 required field/section 오류
- duplicate ID, broken internal ref
- active/history path와 retired metadata 불일치
- supersede missing reciprocal edge, cycle와 illegal cross-kind predecessor
- duplicate current decision slot
- index missing/ghost/duplicate/wrong-state entry
- duplicate area/claim owner
- symlink/path traversal root escape

hygiene warning은 release를 막지 않는다. auto-fix는 derived index 외 금지한다.

### Token·I/O evidence

release 전에 synthetic fixture를 만든다.

- SNAP 100, OBS 2,000, DEC 2,000, history 1,000
- explicit area query와 cross-area query 각각 100회
- Stage 1의 opened artifact count, read bytes, output bytes 기록
- pack이 실제로 연 artifact 수와 returned/omitted 기록
- candidate 0/1/8/9개 batch에서 budget behavior 기록

통과 기준:

- Stage 1 artifact file open = 0
- Stage 1 artifact directory listing/stat = 0
- pack artifact open ≤ 반환된 top-K
- default Stage 1 ≤4 KiB, pack/section batch ≤8 KiB
- candidate 기본 최대 8개·batch ≤16 KiB, owner input ≤2 KiB/item
- grouped approval preview ≤32 KiB; 초과 candidate는 핵심 section을 자르지 않고 분할 요구
- addon 수와 transcript 재판독 횟수가 비례하지 않음

wall-clock 절대 수치는 Phase 0 fixture에서 baseline을 잡은 후 release note에 기록한다. 측정 전 임의 latency 목표를 계약으로 만들지 않는다.

### Product release gate

무료 공개 v1은 다음 사용자 흐름이 plugin 없이 수작업하는 것보다 분명히 짧아야 한다.

1. 대화 중 결정 확정
2. 한 번의 grouped proposal 승인
3. 자연스러운 filename의 DEC 생성
4. 다른 agent/session에서 query 한 번으로 현재 결정·취지·반려대안 복원
5. 새 결정으로 supersede 후 이전 agent도 old DEC를 따르지 않음

README/demo는 generic context framework보다 이 흐름을 먼저 보여준다. PCMS는 local plugin 기능을 제한해 판매하지 않고 조직 규모의 권한·승인 workflow·cross-project search·policy·audit·conflict queue·운영 지표를 유료 경계로 둔다.

### v1 이후로 미루는 항목

- existing wiki importer와 자동 migration
- nested topic folders와 index sharding
- BM25/vector/embedding/SQLite cache
- custom Git merge driver
- generic addon registry/SDK
- 자동 semantic conflict 판정
- Git 없는 저장소용 SNAP archive
- PCMS sync/control plane

## 취지

구현을 storage framework부터 크게 만드는 대신, 사용자 가치가 보이는 core+decision vertical slice와 측정 가능한 token/I-O gate를 먼저 완성한다. 설치 정책은 양 host 공통 manual hard dependency로 고정하고, host별로 남은 차이는 exact inventory probe와 안내 표현만 Phase 0에서 검증한다.

## 구성요소

- [[context-plugin-definition]] — 전체 구현 scope
- [[context-core-plugin]] — core public surface
- [[context-decision-plugin]] — decision public surface
- [[context-storage-retrieval]] — Phase 1 contract
- [[context-artifact-lifecycle]] — Phase 2·3 contract
- [[context-capture-routing]] — Phase 4 contract
