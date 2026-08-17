---
title: context-core 무결성 게이트 단순화와 index-first read 보강
created_at: 2026-08-17
summary: corpus-wide 차단을 target write 경계로 좁히고 dead CLI 표면·문서 drift를 제거하며 index 기반 read와 bounded lexical recall을 보강한다.
tags: [context-core, context-decision, integrity, index, task-worker]
search_terms: [legacy field, index repair, target-scoped write, read index, max-bytes]
relations:
  ssot: [context-core-plugin, context-decision-plugin, context-storage-retrieval]
  decisions: [DEC-2026-08-17-222516-context-무결성은-검색-경고와-대상-write-경계로-분리한다]
  tasks: [task-worker:context-core-simplification-20260817]
---

## 개요

독립 감사에서 확인된 context-core의 과도한 corpus-wide 무결성 게이트를 제거하고, fail-closed를 실제 write 안전 경계로 되돌린다. 동시에 dead CLI 표면과 문서 drift를 제거하고, 기존 index를 read 경로에서 활용하며 lexical recall 변별력과 bounded load/read를 가볍게 보강한다.

코드는 task-worker가 만든 격리 branch/worktree에서 변경하고, 방향 DEC와 root TASK만 정책대로 main에 먼저 기록한다. GitHub Issue projection, push, publish와 release는 이 작업에 포함하지 않는다.

## 근거

legacy `claim_fingerprint` field 잔재가 `repository_state=invalid`를 만들어 init 전체를 차단했지만 보호한 write는 없었다. derived index drift도 user artifact mutation과 같은 approval ceremony를 요구하고, root index missing 상태에서 doctor와 init 판정이 모순됐다. 반면 recall은 이미 index fallback+warning과 `--strict-index` opt-in으로 가용성과 엄격성을 분리한다.

이번 작업은 이 검증 결과와 새 fail-closed 경계 DEC를 구현 정본에 반영한다. CAS, duplicate ID, path traversal·symlink guard, atomic replace, root lock, exact approval digest 1회 사용은 완화하지 않는다.

## 범위와 완료 기준

Unit 1은 같은 rollback 단위로 A와 B를 수행한다. `schema_removed_field`를 warning으로 내리고, index-only drift를 approval 없는 `refresh --fix index` 즉시 rebuild로 수리하며, write validation과 addon preflight를 target-scoped로 좁힌다. doctor/init의 absent·partial 모순을 제거한다. `EXIT_AMBIGUOUS`, 미사용 refresh `--level`/`--strict`, 미구현 hygiene 약속을 CLI·schema·문서에서 제거하고 `@missing` 입력을 structured ContextError envelope으로 통일한다.

Unit 2는 C와 D를 수행한다. snapshot load, observation read, rename, discard의 id→path lookup에 index를 우선 사용하고 실패할 때만 scan fallback+warning을 반환한다. recall은 term match 기반의 가벼운 순위와 cutoff를 적용한다. snapshot load와 observation read는 recall budget 기계를 재사용한 `--max-bytes`와 정확한 `truncated`를 제공한다. decision test sibling import를 repo root 표준 pytest invocation에서 고친다.

정본 `wiki/ssot/context-core-plugin.md`와 `wiki/ssot/context-plugin-definition/*.md`는 flag, exit code, doctor/refresh/preflight, canonical-JSON lifecycle equality, 실제 test count와 새 read/index 계약까지 코드와 일치시킨다. 필요한 `context-decision-plugin.md` drift도 함께 수정한다.

완료 기준은 다음과 같다. (1) 기존 suite green과 A/B/C/D 회귀 test 추가: legacy warning, index one-call repair, unrelated dirty artifact 아래 target write 성공, indexed read path, lexical ranking, max-bytes, missing @file envelope. (2) temp repo의 legacy field corpus에서 init·recall·capture가 모두 동작. (3) `python3 -m pytest plugins/context-decision/tests -q`가 repo root에서 green. (4) preview write 0, wrong digest 거부, apply 재생성 0과 CAS/path/lock/approval 경계 유지. (5) `wiki/ssot/context-core-plugin.md`와 구현의 flag·exit·동작 drift 제거. (6) focused suites, context-v1 integration, diff check, wiki integrity와 독립 hard review 및 fresh integration QA 통과.

범위 밖은 capture ceremony 단계 병합, wiki-markdown과 context 저장소 통합, superseded import 데이터 수습, 승인 게이트 완화, Stage 1 index-first 포기, 새 schema·식별자·embedding·daemon 도입, GitHub delivery, push, publish와 release다.
