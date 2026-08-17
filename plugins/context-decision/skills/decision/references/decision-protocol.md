# context-decision v1 owner protocol

`decision_cli.py`는 `context-decision/v1`의 semantic owner다. complete DEC draft, lifecycle effect, `context-owner-plan/v1`, `context-owner-validation-receipt/v1`과 bounded recall만 만든다. filesystem write, directory 생성, index 갱신, lock, final approval digest 생성과 apply는 하지 않는다. physical writer는 `context-core` coordinator 하나다.

## Dependency boundary

- marketplace: `jeis-ai-plugins`
- plugin: `context-core`
- selector: `context-core@jeis-ai-plugins`
- source: `Jeis-Jw/ai-plugins`
- protocol: `context-common/v2`

`schema`와 `capabilities`만 core 없이 호출할 수 있다. host는 다른 operation에 `--host`, `--core-inventory @file`, `--core-doctor @file`을 넘긴다. production CLI가 repository root를 탐색하기 전 exact identity, source, enabled state와 protocol을 read-only로 확인한다. `doctor.repository_state=absent`는 bootstrap-required state이고 partial/invalid diagnostics는 전역 차단하지 않는다. decision owner는 install, enable, update, marketplace add, cache probing 또는 embedded core를 수행하지 않는다.

## Semantic claim gate

DEC는 현재 또는 미래 행동을 지배하는 명시적 선택이며 다음 assertion 전부가 exact candidate에 결박돼야 한다.

- `explicit_choice` → `/owner_inputs/decision/decision`
- `scope_identified` → `/scope_hint`
- `commitment_present` → `/evidence/*`

idea, question, fact, preference와 미합의 제안은 `decline` 또는 `needs_clarification`이다. `requested_kind:"decision"`은 owner 선택만 고정하며 이 gate를 우회하지 않는다. CLI는 agent skill의 의미 판단을 대신하지 않고 assertion set, input digest와 RFC 6901 pointer만 fail-closed 검증한다.

Direct surface는 2단계다. `candidate prepare`는 caller가 명시한 `cand_`+32 lowercase hex transport ID, commitment evidence와 bounded search terms를 포함한 exact candidate만 정규화한다. candidate ID와 search metadata는 의미 동일성을 보장하지 않는다. owner skill이 그 object를 판독한 뒤 `capture --candidate @file --attestation @file`로 claim하거나 `--decline-reason`/`--needs-clarification-reason`으로 권위 draft 없이 종료한다. random candidate 생성, 상수 commitment evidence, CLI 자체 attestation은 금지다.

## DEC schema와 slot

필수 section은 `결정`, `취지`, `반려대안`이다. 세 section의 누락, 빈 값과 literal `...|TODO|TBD|해당 없음`은 실패한다. 실제 검토한 대안이 없으면 `검토하지 않음: <이유>`를 쓴다. 선택 section은 `근거와 제약`, `트레이드오프`, `재평가 조건`이다. `verified_at`과 공통 `status`는 금지한다.

`scope`는 trim → NFKC+casefold → leading/trailing slash 제거 → segment별 non-alnum run을 `-`로 변환한다. empty segment, `.`/`..`, segment 40자 초과, 8 segment 초과와 전체 160자 초과는 실패한다. `decision_key`는 같은 변환을 사용하고 `/`, empty와 80자 초과를 거부한다. ancestor는 canonical segment 배열의 strict prefix이며 문자열 prefix나 equality가 아니다.

Current에는 `(scope, decision_key)`당 DEC가 최대 하나다. 같은 key의 ancestor/descendant scope는 overlap conflict이며 모든 conflict ID에 대한 acknowledgement와 `{id,path,sha256}` exact read precondition이 있어야 한다. 의미상 동일한 결정은 fingerprint로 판정하지 않는다. 사전 `check`가 제공한 실제 본문을 agent가 비교하고 `same`이면 기존 DEC를 재사용한다.

## Owner result와 lifecycle

capture는 one current draft/effect/create operation을 반환한다. ID와 `created_at`은 draft 시 한 번 만들고 embedded candidate, claim attestation, complete content와 semantic projection에 결박한다.

- `supersede`: successor candidate가 predecessor의 canonical scope/key를 명시적으로 그대로 가져야 한다. 한 owner result에 old changed-move History draft와 new Current create draft를 포함하고 `old.superseded_by == new.id`, `new.supersedes == [old.id]`를 지킨다. History path는 `<stem>--<old-id12>.md`다.
- `withdraw`: old를 `retired_reason:"withdrawn"`과 `retirement_note`가 있는 History draft로 만들며 successor가 없다.
- `annotate`: title, summary, tags, search terms, source refs만 제자리 correction하고 결정 section, slot과 ID는 보존한다.
- `revisit`: due warning과 review proposal만 반환하며 state를 바꾸지 않는다.

일반 evidence OBS는 active인 채 DEC `relations.informed_by`로 연결한다. decision-like fallback OBS import는 `kind_hint:decision`, source artifact의 exact id·path·SHA-256·actual claim, `same_claim` attestation과 cross-owner single coordinator plan을 요구하며 일반 evidence relation과 혼용하지 않는다.

## Same-batch validation

`batch validate`는 physical `decision.index.md`의 exact SHA-256를 base로 사용한다. 전달된 prior same-area final bundle을 proposal order대로 overlay한다. 각 bundle의 `plan.prior_bundle_digests`는 앞선 exact digest 목록과 같아야 한다. virtual Current에 slot, overlap acknowledgement/read precondition과 lifecycle predecessor current 여부를 적용한다.

성공 receipt는 다음을 결박한다.

- `owner_result_digest`
- `base_area_index_sha256`
- ordered `prior_same_area_bundle_digests`
- canonical `scope`, `decision_key`, actual `primary_claim`, `rationale`, acknowledged conflicts
- 자기 field를 제외한 `receipt_digest`

Receipt 없는 final owner plan이나 altered receipt는 `plan validate`에서 실패한다.

## Recall과 init

`search`는 `decision.index.md` metadata만 읽는다. `read`와 `brief`는 선택된 DEC만 연다. brief는 `결정`, `취지`, `반려대안`만 포함하고 최대 8 KiB다. 낮은 순위 item을 통째로 제외하며 section 중간 절단은 하지 않는다. History에는 항상 `do_not_follow:true`와 lifecycle reason을 붙인다.

`check --statement ... --scope ... --decision-key ...`는 새 선택을 확정하거나 기록하기 전에 사용한다. exact slot과 scope overlap은 반드시 포함하고, 나머지는 bounded ranking으로 선택해 실제 Current DEC의 세 핵심 section과 `{id,path,sha256}`를 `context-decision-comparison-input/v1`으로 반환한다. comparison input은 24 KiB, 전체 result는 32 KiB이며 omitted ID는 최대 8개 sample과 exact count만 반환한다. agent는 `new|same|supporting|rationale_changed|conflict` 중 하나와 근거·관련 ID를 제시한다. `new`는 반환된 집합 안의 판정이며 전역 무충돌 증명이 아니다. 이 operation은 read-only이고 지문·문장 유사도로 의미를 확정하지 않는다.

`init`은 exact core identity/source/enabled/protocol이 맞으면 `repository_state`가 ready/partial/invalid인 경우에도 `context-owner-descriptor/v1`, complete empty decision index seed, descriptor/seed digest와 installed core `bootstrap` 요청을 반환한다. `absent`도 bootstrap-required로 허용한다. Init skill은 `decision_init.py` entrypoint 한 번으로 preflight와 active installed core의 public `context_cli.py bootstrap --host <host>` 호출을 순서대로 수행한다. core surface가 필요한 root 복구, decision area registration과 host별 managed operating policy installation을 coordinator로 적용하며 phase result를 반환한다. decision CLI 자체는 root/area/index/policy를 만들거나 수정하지 않는다.

`claim_fingerprint`, `source_claim_fingerprint`와 capture candidate의 `claim_key`는 schema에서 제거됐다. candidate ID는 transport reference로만 사용한다. legacy artifact field는 읽고 다음 승인 rewrite에서 제거하며, 신규 candidate/draft의 제거된 field는 `schema_removed_field`로 실패한다.

## Output and errors

JSON success는 `{"ok":true,"result":...}`, error는 `{"ok":false,"error":{"code":...,"message":...,"details":...}}`다. exit code는 usage/schema 2, not found 3, conflict 5, integrity/index 6이다. 모든 operation은 실행 전후 repository filesystem bytes가 같아야 한다.
