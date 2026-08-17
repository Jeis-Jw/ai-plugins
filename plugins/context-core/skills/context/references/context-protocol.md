# context-common/v2 storage kernel

이 문서는 `context-core` Phase 1 구현이 제공하는 host-independent 경계를 요약한다. 제품 의미와 lifecycle의 정본은 repository의 승인된 context v1 SSOT이며, 이 파일은 CLI 근처의 구현 참조다.

## 정본과 ID

- Git worktree root의 `context/`만 storage root다. `--root` override는 없다.
- Markdown artifact가 정본이고 `context.index.md`와 `<area>.index.md`는 deterministic projection이다.
- artifact ID는 `ctx_` + lowercase UUIDv4 hex 32자다. filename, title, path와 lifecycle이 ID를 바꾸지 않는다.
- frontmatter는 `KEY: JSON_VALUE` 한 줄 형식의 JSON-compatible YAML subset이고, document body는 schema별 fixed H2 section 순서를 사용한다.
- `claim_fingerprint`, `source_claim_fingerprint`와 capture candidate의 `claim_key`는 protocol에서 제거됐다. 신규 artifact와 semantic projection은 fingerprint를 출력하거나 요구하지 않고, candidate ID는 transport reference로만 사용한다. legacy artifact field는 `schema_removed_field` warning으로 읽고 다음 승인 rewrite에서 lazy-clean하며, 신규 candidate/draft에서는 fail-closed한다.

## Read 경계

- healthy Stage 1 recall은 root index와 선택된 area index만 연다. artifact open/list/stat은 0이다.
- broken area index, 선택된 missing link 또는 non-empty query zero-match는 해당 area scan으로만 fallback하고 warning을 반환한다.
- `--strict-index`는 fallback 없이 exit 6 `index_stale`로 실패한다.
- root index가 없으면 storage error `context_root_missing`이며 plugin dependency error와 다르다.

## Write 경계

- semantic owner는 complete `context-owner-result/v1`의 draft/effect/proposed plan만 만든다.
- `transaction preview`는 exact on-disk precondition, complete material, derived index rebuild와 owner/area authorization을 `context-mutation-bundle/v1`로 봉인한다.
- `approval_digest`는 canonical `approval_material` 전체의 SHA-256이다. apply는 동일 bundle object와 exact digest만 받는다.
- context-core coordinator만 repository-realpath root lock 아래 atomic file operation과 deterministic index rebuild를 수행한다.
- hidden operation, seed 누락, material/digest 불일치, changed precondition, path escape와 symlink segment는 write 전에 fail-closed한다.

## CLI envelope

- success: `{"ok":true,"result":{...}}`
- error: `{"ok":false,"error":{"code":"...","message":"...","details":{...}}}`
- exit 2 usage/schema/filename, 3 root/artifact/input missing, 5 owner/path/lifecycle conflict, 6 integrity/index failure
- `schema`와 `capabilities`는 repository root 없이 동작한다.

`init --host codex|claude-code`은 명시적 호출 하나로 absent root의 canonical root/SNAP/OBS index seed와 활성 host의 관리형 policy block을 적용한다. host mapping은 `codex → AGENTS.md`, `claude-code → CLAUDE.md`다. policy target과 marker를 storage write 전에 preflight하고 managed marker 밖 bytes를 보존한다. valid descriptor와 최신 block이면 unrelated corpus 진단과 무관하게 `core_init`과 `policy_install`이 noop이다. populated repository에서 root index만 없으면 exact built-in SNAP/OBS metadata만 rebuild하고 미등록 area는 자동 claim하지 않으며, init target의 incompatible schema/owner/path만 `partial_core_init`으로 중단한다. 결과는 structured phase와 post-apply doctor receipt를 포함한다.

`bootstrap --descriptor @file --index-seed @file --host codex|claude-code`은 addon init용 public surface다. 같은 호출에서 core init을 먼저 완료한 뒤 empty area seed를 `area_register`로 적용하고 동일한 host policy를 설치한다. 중간 실패는 완료/실패 phase를 반환하며, root area row만 쓴 exact descriptor-bound prefix는 재시도에서 남은 area index를 적용해 수렴한다. descriptor schema/owner/kind/artifact_schema/authority 또는 existing area index metadata가 다르면 noop이 아니라 write 0 fail-closed다. 이 explicit-init authority는 fixed `core_init|area_register|policy_install` transition에만 허용되고 일반 artifact/index mutation에는 사용할 수 없다.

Lifecycle semantic input은 predecessor와 successor의 실제 primary claim, bounded supporting context, artifact SHA-256, path/id와 source candidate digest를 포함한다. `same_claim` attestation은 두 primary claim을 직접 가리켜야 하며 hash-derived claim identity를 대신 사용하지 않는다.
