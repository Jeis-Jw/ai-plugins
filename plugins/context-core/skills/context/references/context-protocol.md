# context-common/v1 storage kernel

이 문서는 `context-core` Phase 1 구현이 제공하는 host-independent 경계를 요약한다. 제품 의미와 lifecycle의 정본은 repository의 승인된 context v1 SSOT이며, 이 파일은 CLI 근처의 구현 참조다.

## 정본과 ID

- Git worktree root의 `context/`만 storage root다. `--root` override는 없다.
- Markdown artifact가 정본이고 `context.index.md`와 `<area>.index.md`는 deterministic projection이다.
- artifact ID는 `ctx_` + lowercase UUIDv4 hex 32자다. filename, title, path와 lifecycle이 ID를 바꾸지 않는다.
- frontmatter는 `KEY: JSON_VALUE` 한 줄 형식의 JSON-compatible YAML subset이고, document body는 schema별 fixed H2 section 순서를 사용한다.

## Read 경계

- healthy Stage 1 recall은 root index와 선택된 area index만 연다. artifact open/list/stat은 0이다.
- broken area index 또는 선택된 missing link는 해당 area scan으로만 fallback하고 warning을 반환한다.
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
- exit 2 usage/schema/filename, 3 root/artifact missing, 4 ambiguous read, 5 owner/path/lifecycle conflict, 6 integrity/index failure
- `schema`와 `capabilities`는 repository root 없이 동작한다.

`init`은 명시적 호출 하나로 absent root의 canonical root/SNAP/OBS index seed를 final bundle에 고정하고 core coordinator로 적용한다. valid root면 `phases[core_init].status=noop`이고 filesystem diff는 0이다. 직전 fixed init bundle이 write 순서대로 남긴 exact canonical prefix만 같은 bundle의 남은 index를 재개하며, 그 밖의 partial 또는 invalid root는 overwrite하지 않고 `partial_core_init`으로 중단한다. 결과는 structured phase와 post-apply doctor receipt를 포함한다.

`bootstrap --descriptor @file --index-seed @file`은 addon init용 public surface다. 같은 호출에서 core init을 먼저 완료한 뒤 empty area seed를 `area_register`로 적용한다. 중간 실패는 완료/실패 phase를 반환하며, root area row만 쓴 exact descriptor-bound prefix는 재시도에서 남은 area index를 적용해 수렴한다. descriptor schema/owner/kind/artifact_schema/authority 또는 existing area index metadata가 다르면 noop이 아니라 write 0 fail-closed다. 이 explicit-init authority는 `core_init|area_register` transition에만 허용되고 일반 artifact/index/policy mutation에는 사용할 수 없다. agent policy는 별도 `policy preview`와 exact digest approval 없이는 설치하지 않는다.
