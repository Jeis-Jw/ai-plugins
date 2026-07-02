---
title: task-github orchestration evidence reuse plan
created_at: 2026-07-03
summary: GitHub read boundary and child gate evidence reuse plan for task-github orchestration cost reduction.
tags: [task-github, orchestrate, ledger, evidence, workflow-efficiency]
type: snapshot
---
## 현재 논의

# task-github orchestration 비용 효율 개선 기획안

## 핵심 방향

이번 개선은 `task-github`의 기존 orchestrate v2와 merge-edge gear 결정을 되돌리지 않는다. 기존 `.task-github/orchestrate/{root}.json` ledger-first tick을 유지하고, ledger를 `v3` additive schema로 확장해 두 가지를 분리해서 기록한다.

- 실제 GitHub API/`gh` 호출 비용: `github_reads`
- ledger/cache를 써도 되는지에 대한 판단 흔적: `read_decisions`
- 자식 node가 부모에 합류했다는 사실: `merge_evidence`
- 자식 node에서 이미 통과한 wiki drift gate를 상위 node가 재사용할 수 있는지: `gate_evidence`

절감 대상은 GitHub SoT 자체가 아니라, 같은 tick 안의 read-after-write 재조회와 상위 merge 시점의 반복 `changed-path-stale` 대상이다. 상위/root merge에서 `wiki refresh --level integrity --strict --json`는 계속 전역 hard gate로 유지한다. Evidence reuse는 `changed-path-stale` scope 축소에만 적용한다.

## Self Review 반영

`session-review:request-review self co-design turnkey` 결과:

- 초안에서 `integrity strict`를 조건부로 줄인 부분은 회귀로 판단했다. 최종안은 global integrity hard gate를 유지한다.
- `github_reads`와 cache 판단을 분리한다. `cache_sufficient` 같은 판단은 `read_decisions`로 보내고, `github_reads.count`는 실제 GitHub 호출만 센다.
- `merge_evidence`와 `gate_evidence`를 분리한다. 기존 `child_merge_evidence`는 합류 증거이며, 새 gate 재사용 검증과 섞지 않는다.

`session-review:request-review self challenge turnkey` 결과:

- `changed-path-stale`는 코드 path뿐 아니라 현재 wiki 문서들의 `affects_paths`/`verified_at` 표면에 의존한다. 그래서 `gate_evidence`에는 `drift_surface_hash`를 넣고, 현재 surface와 다르면 full fallback한다.
- PR path에서는 gate 결과가 실제 merge head와 원자적으로 묶여야 한다. `headRefOid` pinning과 `gh pr merge --match-head-commit <headRefOid>` 또는 동등한 pre/post invariant가 필요하다.
- major PR path의 evidence producer는 문서 지시만으로 부족하다. `merge_preflight.py` 같은 executable wrapper를 두고, wiki gate 실행, gate evidence 기록, live pre-merge read, head pinning, closeout 실행 순서를 테스트 가능한 계약으로 만든다.

## 최종 설계

### 1. Ledger v3

`orchestrate_ledger.py`의 `_default()`를 v3로 확장한다. `load_ledger()`는 v2 ledger를 자동으로 v3 shape로 default-fill하며, 기존 `issues[N].ff_merged`는 계속 읽을 수 있어야 한다.

```json
{
  "version": 3,
  "spawned": [],
  "failed": [],
  "issues": {},
  "prs": {},
  "events": [],
  "github_reads": {
    "count": 0,
    "entries": []
  },
  "read_decisions": [],
  "evidence": {
    "by_issue": {}
  }
}
```

`github_reads.entries[]`는 실제 GitHub read만 기록한다.

```json
{
  "at": "2026-07-03T00:00:00Z",
  "reason": "pre_merge",
  "boundary": "merge",
  "command_kind": "gh_pr_view",
  "scope": "pr:123",
  "fields": ["mergeStateStatus", "statusCheckRollup", "reviewDecision", "headRefOid", "baseRefOid"],
  "caller": "merge_preflight",
  "result": "ok"
}
```

`read_decisions[]`는 API read가 아니라 orchestration 판단 log다.

```json
{
  "at": "2026-07-03T00:00:00Z",
  "caller": "ready_leaves",
  "decision": "ledger_used",
  "reason": "normal_tick",
  "cache_snapshot_at": "2026-07-03T00:00:00Z",
  "ledger_age_sec": 18,
  "cache_sufficient": true
}
```

`evidence.by_issue[N].merge_evidence`는 landing fact다.

```json
{
  "schema_version": 1,
  "producer": "done.ff",
  "merge_edge": "ff",
  "base_branch": "task/issue-81",
  "head_branch": "task/issue-82",
  "base_sha": "aaa",
  "head_sha": "bbb",
  "sha_range": "aaa..bbb",
  "recorded_at": "2026-07-03T00:00:00Z"
}
```

`evidence.by_issue[N].gate_evidence`는 gate reuse fact다.

```json
{
  "schema_version": 1,
  "producer": "done.ff",
  "gate_version": "task-github-quality-gates-v1",
  "tool_versions": {
    "task_github": "0.16.0",
    "wiki_markdown": "0.19.1"
  },
  "commit_head_sha": "bbb",
  "changed_paths": ["plugins/task-github/skills/done/SKILL.md"],
  "changed_paths_hash": "sha256:...",
  "drift_surface_hash": "sha256:...",
  "gate_results": {
    "changed_path_stale": {
      "ok": true,
      "issues": [],
      "checked_paths_hash": "sha256:...",
      "checked_at": "2026-07-03T00:00:00Z"
    }
  },
  "recorded_at": "2026-07-03T00:00:00Z"
}
```

### 2. GitHub Read Boundary

허용 reason enum:

- `session_start`
- `resume`
- `explicit_reconcile`
- `plain_container_compat`
- `long_wait`
- `ci_check`
- `mergeability`
- `review_decision`
- `pre_merge`
- `final_closeout`
- `failure_recovery`

`ready_leaves.py`는 다음 계약을 가진다.

- `--from-ledger`: normal tick 기본 path. GitHub read 0. `read_decisions`에 `ledger_used` 기록.
- `--reconcile-github`: GitHub read path. `--read-reason` 필수.
- plain `{container}` invocation: backward-compatible GitHub read path. `--read-reason plain_container_compat` 또는 명시 reason 필요.
- `--fixture-json`: 테스트 예외. GitHub read 기록하지 않음.
- output에 `source: ledger|github|fixture`, `read_decision`, `github_reads_summary` 포함.

`ready_leaves.github_fetch_page()`와 `_open_blockers()`는 1차 구현에서 먼저 instrumentation을 붙인다. GraphQL/REST batch 최적화는 별도 incremental task로 둔다. 이유는 safety contract와 cost 관측이 먼저 안정되어야 하기 때문이다.

### 3. Evidence Producer

micro/normal FF path는 `done` 절차 안에서 다음 순서를 원자적으로 묶는다.

1. `BASE_BRANCH...HEAD` changed paths canonical list 산출
2. `wiki refresh --check changed-path-stale --changed-path "$FILES" --json`
3. `compute_drift_surface_hash()` 산출
4. drift gate 통과 확인
5. local FF merge와 `SHA_RANGE` 산출
6. `record_event(ff_merged)`와 `record_gate_evidence` 기록
7. issue close

이 path에서 `SHA_RANGE`, canonical changed paths, drift JSON, drift surface hash, tool/gate version 중 하나라도 없으면 evidence 기록 실패로 보고 issue close 전에 STOP한다. 비용 절감 때문에 “증거 없는 close”가 생기면 안 된다.

major PR path는 `closeout.py`에 wiki 책임을 넣지 않는다. 대신 새 executable wrapper 또는 helper를 둔다.

- 후보 이름: `plugins/task-github/skills/merge/scripts/merge_preflight.py`
- 책임: PR diff path 산출, wiki integrity 실행, `changed-path-stale` 실행, drift surface hash 산출, live PR state read, required checks/review/mergeability 판단, `gate_evidence` 기록, closeout 호출 준비
- closeout.py 책임: merge facts only. `pr_merged`/`issue_closed` merge evidence 기록, branch cleanup warning-tier 처리

PR path는 head pinning을 강제한다. `merge_preflight.py`가 gate를 실행한 `headRefOid`와 merge 직전 live `headRefOid`가 다르면 STOP한다. 가능한 경우 `gh pr merge --match-head-commit <headRefOid>`를 사용하고, 사용할 수 없는 환경이면 closeout 내부에서 pre/post invariant를 검증한다.

### 4. Evidence Consumer

새 pure helper를 둔다.

```python
validate_gate_evidence(
    children,
    *,
    parent_changed_paths,
    current_gate_version,
    current_tool_versions,
    current_drift_surface_hash,
    expected_base,
    parent_range,
) -> {
    "ok": bool,
    "reusable_issues": [...],
    "fallback_paths": [...],
    "invalid": [{"issue": 82, "reason": "..."}],
}
```

상위/root merge gate는 항상 다음 순서다.

1. global `wiki refresh --level integrity --strict --json`
2. child `merge_evidence` 검증: 기존 `child_merge_evidence` 또는 v3 projection이 expected base landing을 증명해야 함
3. child `gate_evidence` 검증
4. `changed-path-stale` 대상 계산
5. scoped `changed-path-stale`
6. evidence가 불완전하면 full fallback

`changed-path-stale` target set:

```text
parent_changed_paths
+ evidence_missing_paths
+ invalid_evidence_paths
+ parent/child overlap paths
```

valid 조건:

- child merge evidence가 expected base에 landed
- child `sha_range` 또는 `head_sha`가 parent PR/FF range ancestry에 포함
- child changed paths와 parent changed paths가 overlap하지 않음
- `gate_version`과 `tool_versions` match
- `drift_surface_hash`가 현재 hash와 match
- `gate_results.changed_path_stale.ok == true`
- `gate_results.changed_path_stale.issues == []`
- `checked_paths_hash == changed_paths_hash`
- canonical path list 존재
- PR path에서는 `commit_head_sha == live headRefOid`였음이 preflight evidence에 남아 있음

하나라도 모호하면 해당 path는 skip하지 않고 fallback 대상에 넣는다.

### 5. Tests / Fixture

필수 fixture와 regression test:

- v2 ledger load: `issues[N].ff_merged`가 v3 `merge_evidence` projection으로 계속 소비됨
- `record_snapshot()`이 root snapshot을 갱신해도 `evidence`, `github_reads`, `read_decisions`를 보존
- `--from-ledger` normal tick은 `github_reads.count` 증가 없음
- `--reconcile-github --read-reason session_start`는 GitHub read entry 기록
- `--reconcile-github` reason 누락은 fixture mode가 아니면 실패
- valid child gate evidence는 child paths를 상위 `changed-path-stale` 대상에서 제외
- parent가 같은 path를 수정하면 overlap fallback
- wiki `affects_paths`/`verified_at` surface 변경 시 drift surface hash mismatch로 full fallback
- PR head가 gate 이후 바뀌면 STOP
- missing gate evidence, missing changed path hash, missing drift surface hash, tool/gate version drift는 fallback
- no-code close는 path 없음으로 처리하되 merge evidence만 있어도 parent path 계산이 깨지지 않음
- `merge_preflight.py`가 gate evidence를 기록하기 전에는 closeout 실행 준비 상태가 되지 않음
- cost fixture: old full target set 대비 scoped target set 감소, invalid cases에서는 감소하지 않고 full fallback

## 수용 기준

- GitHub 조회 boundary와 reason enum이 orchestrate/merge 문서에 명시되어 있다.
- ledger에 `github_reads`와 `read_decisions`가 분리되어 기록된다.
- ledger에 `merge_evidence`와 `gate_evidence`가 분리되어 기록된다.
- `changed-path-stale` scope 축소는 valid evidence에만 적용된다.
- global integrity strict, pre-merge mergeability/checks/review/blocker live read는 생략되지 않는다.
- wiki drift surface hash mismatch, PR head mismatch, parent path overlap, version drift, missing evidence는 full fallback 또는 STOP으로 간다.
- 기존 v2 ledger fixture가 계속 통과한다.
- fixture로 GitHub read 수와 changed-path-stale 대상 path 수 감소 근거를 남긴다.

## 배경

Issue tree #81 orchestration에서 leaf/container/root를 모두 PR 기반으로 처리하면서 `gh pr view`, `gh pr list`, `gh pr diff`, `gh pr checks`, `ready_leaves --reconcile-github`, `closeout.py` 내부 재조회가 반복됐다.

현재 코드/문서 상태:

- `plugins/task-github/skills/orchestrate/SKILL.md`는 이미 ledger-first tick과 GitHub read boundary를 선언한다.
- `plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py`는 `version: 2`, `spawned`, `failed`, `issues`, `prs`, `events`를 가진다. `ff_merged` evidence는 있지만 GitHub read counter나 gate evidence는 없다.
- `plugins/task-github/skills/orchestrate/scripts/ready_leaves.py`는 `--from-ledger`에서 GitHub read를 하지 않고, `--reconcile-github` 또는 plain container 실행에서 GitHub를 읽는다. read reason 기록은 없다.
- `plugins/task-github/skills/merge/scripts/closeout.py`는 PR path merge facts를 처리하지만 wiki gate는 모른다. 이는 유지할 경계다.
- `plugins/task-github/rules/quality-gates.md`는 `integrity strict`와 `changed-path-stale`를 hard gate로 둔다. `changed-path-stale`는 hygiene tier이지만 task-github에서는 drift hard gate다.
- `plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py`의 `changed-path-stale`는 active wiki 문서의 `affects_paths`와 `verified_at` frontmatter를 기준으로 path match를 수행한다.

보존해야 할 결정:

- `DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml`
- `DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거`
- `DEC-2026-07-02-224910-orchestrate-세리머니를-merge-edge-gear로-이동-분해를-payoff-원리로-재정의`

Memory-derived baseline:

- 기존 orchestration critique에서도 read-after-write GitHub polling, `ready_leaves.py`의 GitHub rebuild, `closeout.py`의 성공/cleanup 경계 혼합이 주요 cost center로 확인됐다.
- 개선 방향은 GitHub SoT를 유지하되, 실행 중 write-through ledger를 더 적극적으로 사용하고 reconcile boundary를 제한하는 쪽이었다.

## 정해진 것

정해진 방향:

1. 기존 ledger-first orchestrate를 유지하고 v3 additive schema로 확장한다.
2. `github_reads`는 실제 GitHub 호출만 센다.
3. cache/ledger 사용 판단은 `read_decisions`로 별도 기록한다.
4. `merge_evidence`와 `gate_evidence`를 분리한다.
5. 상위/root merge의 global `integrity strict`는 항상 유지한다.
6. Evidence reuse는 `changed-path-stale` scope 축소에만 적용한다.
7. `gate_evidence`는 `changed_paths_hash`뿐 아니라 `drift_surface_hash`를 포함한다.
8. PR path는 gate를 실행한 `headRefOid`와 merge 직전 `headRefOid`를 pinning한다.
9. `closeout.py`는 wiki-free merge facts only 경계를 유지한다.
10. major PR path의 gate evidence 기록은 문서 지시가 아니라 executable `merge_preflight.py` 또는 동등 helper로 강제한다.
11. evidence가 불완전하거나 애매하면 full verification fallback 또는 STOP한다.

## 아직 열린 질문

아직 구현 중 확정해야 할 세부:

- `drift_surface_hash` helper를 task-github 안에 둘지, wiki-markdown CLI에 read-only projection으로 추가할지. 1차 구현은 task-github helper가 active wiki markdown frontmatter를 canonical projection하는 방식이 가장 작다.
- `gh pr merge --match-head-commit` 사용 가능성을 현재 지원 gh 버전에서 확인할지, 아니면 closeout 내부 pre/post invariant로 먼저 구현할지.
- `tool_versions` 값을 어디서 읽을지. plugin manifest/package metadata가 있으면 그 값을 쓰고, 없으면 `unknown`을 invalidation 대상으로 취급할지 결정해야 한다.
- GraphQL/REST batch 최적화를 같은 PR에 넣을지. 안전 contract가 먼저라 1차 구현에서는 instrumentation과 boundary 제한을 우선하는 것이 낫다.

## 다음에 볼 것

구현 slicing:

1. `orchestrate_ledger.py` v3 defaults, v2 projection, `record_github_read`, `record_read_decision`, `record_merge_evidence`, `record_gate_evidence` 추가.
2. `ready_leaves.py`에 `--read-reason`, `source`, read instrumentation 추가. `--from-ledger` read count 0 fixture 작성.
3. `orchestrator_ops.py`에 `validate_gate_evidence`, scoped changed-path target 계산 helper, drift surface hash 비교 helper 추가.
4. `done/SKILL.md`의 micro/normal FF path를 evidence producer contract로 갱신.
5. `merge/scripts/merge_preflight.py` 추가. wiki gate, live PR state read, head pinning, gate evidence 기록을 closeout 전에 강제.
6. `closeout.py`는 merge facts만 확장해 `merge_evidence`를 기록한다. wiki gate 책임은 넣지 않는다.
7. `orchestrate/SKILL.md`, `merge/SKILL.md`, `rules/quality-gates.md`, `README.md`에 boundary table, invalidation/fallback 조건, cost-proof fixture 설명을 반영한다.
8. Unit/fixture tests를 추가하고 `python3 -m unittest plugins/task-github/tests/test_orchestrate_ready_leaves.py plugins/task-github/tests/test_orchestrator_ops.py plugins/task-github/tests/test_closeout.py` 및 신규 테스트를 실행한다.
9. 구현 후 `wiki refresh --level integrity --strict --json`와 `git diff --check`로 마무리 검증한다.

## 관련 파일/문서

- plugins/task-github/skills/orchestrate/SKILL.md
- plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py
- plugins/task-github/skills/orchestrate/scripts/ready_leaves.py
- plugins/task-github/skills/orchestrate/scripts/orchestrator_ops.py
- plugins/task-github/skills/done/SKILL.md
- plugins/task-github/skills/merge/SKILL.md
- plugins/task-github/skills/merge/scripts/closeout.py
- plugins/task-github/rules/quality-gates.md
- plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py
- wiki/context/decision/DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml.md
- wiki/context/decision/DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거.md
- wiki/context/decision/DEC-2026-07-02-224910-orchestrate-세리머니를-merge-edge-gear로-이동-분해를-payoff-원리로-재정의.md

## 승격 후보

- 구현 후 DEC 후보: `task-github ledger v3 evidence reuse boundary` - GitHub read boundary, gate evidence reuse, full fallback 조건이 실제 구현으로 확정될 때 승격.
- 구현 중 OBS 후보: `changed-path-stale depends on wiki drift surface` - affects_paths/verified_at surface hash 필요성이 구현에서 확인되면 observation으로 남길 수 있음.
