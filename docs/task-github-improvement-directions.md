# task-github 개선방향 — 수렴안 v3 (작업자, round 3 confirm 입력)

> **위상**: round 2(converge)에서 Codex가 큰 방향 수렴에 동의(A→B→C→D, closeout 확장, root contract, stacked+local Ledger, label 강등) + `changes-requested` blocking 1건(doctor 안전계약 모순) + should-reflect 3건 정밀화 + **scope 확장 금지** 명시. 이 v3는 blocking을 해소하고 정밀화를 반영했다. `round_type=confirm` — lock 확인.

---

## 1. 대전제 (불변식 — 유지) + Codex red line

1. **두 플러그인 독립 동작.** `wiki-markdown` ⊥ `task-github`. 역방향 의존 금지(wiki는 task-github를 모름).
2. **유일 브릿지 = wiki `TASK` 노드 ↔ github `ROOT` 이슈 (1:1).** 입자도 유지, 제2 브릿지 금지.

**Codex round1 #1 — 금지선(red line, 채택):**
- branch/worktree/PR metadata가 wiki `TASK`를 **대체하면 안 된다**.
- wiki가 GitHub 상태를 **직접 해석하기 시작하면 제2 브릿지**다.
- 아래 신규 산출물(Execution Contract, Integration Ledger)은 **GitHub(root issue body/comment)에만** 산다. **wiki 변경은 wiki CLI(`recall`/`relate`/`complete`/`reopen`)로만.**

→ stress-test 결과: 방향 A~D 전부 이 선 안에서 premise-safe.

---

## 2. round 1 결과

- Codex 판정: `approved`, `blocking_count=0`. 대전제 위반 차단 항목 없음.
- 강한 권고 `[should-reflect]` 4건(§4 처리), `[directional]` 다수, red line 1건.
- 핵심 제안: **I/II/III를 병렬 feature가 아니라 4개 얇은 unit으로 절단**(§3).

---

## 3. 수렴: 4개 얇은 unit (구 I/II/III → A/B/C/D)

재구성 근거 = 병렬이 아니라 **의존 순서**. 브릿지 토대를 먼저 깔고 그 위에 integration·UX를 얹는다.

### Unit A — resolve / context bundle  (구 II 핵심 · 토대)
- 링크 리졸버를 1개로 통합하되, link만 풀지 말고 **context bundle JSON**을 출력(Codex #11): `{issue, root, wiki_task, topology, gate, parent_branch, blockers, downstream, worktree_path}`.
- `open/start/done/merge/status`가 같은 read-model을 공유 → gh/wiki 재조회 + regex 복붙을 **동시에** 제거.
- 링크 정합 검사 불변식 포함: (a) root issue `## Wiki Context`에 TASK 존재, (b) task `relations.tasks`가 root를 가리킴, (c) root closed ↔ task done 일치.

### Unit B — Execution Contract + config materialization  (구 I 일부)
- integration mode는 `profile`+`gear`**자동 추천이 기본값**이되, **실제값은 root issue 생성 시 materialize**한다(Codex #4/#8 — 재추론 drift 방지).
- **parser-safe contract**(Codex r2 #2): root issue body에 **fenced block** + `schema_version` + stable keys(`wiki_task, topology, gate, parent_branch, leaf_policy, required_checks, closeout_mode`) + **unknown-key ignore** 규칙. "경량"이되 파싱 계약을 명시한다.
- **A가 B보다 먼저** 구현되므로, contract 부재 시 Unit A의 context bundle은 `topology/gate/parent_branch`에 `null` + `default_source`(profile+gear 자동값)를 낸다.
- per-work flag = **override 수단**.
- **guardrail**: 이건 ROOT 이슈의 *실행 계약*이지 wiki `TASK`의 대체가 아니다. why/what = TASK, how = contract. (red line 준수)

### Unit C — local/stacked integration closeout  (구 I 핵심)
- 기존 `closeout.py`를 **integration closeout으로 일반화**(Codex #2): `--mode pr|local`, 공통 출력 `{issue, root, root_closed, task_to_complete, downstream, merged}` 유지. (helper를 새로 포크하지 않음 — open-Q1)
- local-merge도 issue close/comment/label cleanup/downstream 안내/root 완료 감지를 **반드시** 수행 → wiki TASK 투영이 깨지지 않음.
- **merge simulation 필수**(Codex #10, 안전 핵심): 임시 worktree clean checkout에서 parent/main 병합 상태를 만들고 **Unit B의 `required_checks`** + `changed-path-stale` + integrity gate를 통과한 **뒤에만** 반영. (Codex r2 #3 — 모호한 "tests"가 아니라 contract의 `required_checks`를 읽어 실행 → "검증된 로컬 머지"의 의미가 세션마다 흔들리지 않음.) 없으면 "리뷰/CI 없는 main 오염".
- **leaf 검증 비우지 않음 + leaf_policy rule table**(Codex #3 / r2 #4): leaf local-merge 전 최소 `verify + drift + blocker 재확인`. 위험도는 단순 gear가 아니라 `leaf_policy` 룰로 게이트한다:

  | leaf 위험 클래스 | 강제 게이트 |
  |---|---|
  | micro / normal | leaf verify + drift + blocker |
  | gear:major (일반) | + self-flow (컨테이너 머지 전) |
  | 비가역 / DB migration / public API / security / data-loss | + **PR 또는 hard self-flow 강제** |

- 리뷰 게이트 위치: **리프→컨테이너는 로컬(위 게이트 후), 컨테이너→main이 단일 release gate**(전체 diff).
- **Integration Ledger**(Codex #9, scope: **stacked+local-merge 한정**): leaf 머지마다 root issue에 append-only comment. 각 comment에 **stable marker + machine-readable event block**(`{leaf, SHA, checks, drift, downstream}`) → `status/next`가 marker로 빠르게 파싱(Codex r2 #5). PR 없는 stacked의 실행 로그. (flat/PR은 PR이 기록 보유 → 불필요. wiki엔 안 넣음. root body latest-cache는 epic이 길어질 때만 별도 marked 영역에 — 기본 deferred/YAGNI.)

### Unit D — status / next + doctor / reconcile  (구 III · 재우선)
- **`status`/`next`**(Codex #6/#12 — label bootstrap보다 우선): ready leaf, blocked leaf, review needed, root branch behind main, orphan worktree, bridge mismatch, closeout pending, topology/gate mode, **다음 행동 1개**. Unit A의 context bundle read-model 재사용.
- **diagnose ↔ mutation 명시 분리**(Codex r2 #1 blocking 해소 — read-only 기본과 reconcile은 충돌하므로):
  - `doctor --json` = **diagnose only**(순수 read-only, 절대 상태 변경 없음). 섹션 = (prereq) labels/gh auth/dependency API/`.worktrees` ignore/`.worktreeinclude`/wiki·session-review availability/default config; (linkage) Unit A 정합 불변식.
  - `reconcile --apply`(또는 `doctor --fix`) = **explicit mutation**. 상태 변경(wiki `complete/reopen/relate`, GitHub comment/label/close)은 이 명시 경로로만. wiki 직접 쓰기 금지 — wiki CLI만.
  - `open`/`merge`의 **opportunistic reconcile도 dry-run report 먼저 → apply gate 통과 후에만** 변경(자동 silent mutation 금지).
- label bootstrap, nested repo guard(Codex #14)는 `doctor` diagnose 내부 cheap check로 흡수(독립 스킬로 키우지 않음).

### 구현 순서
**A → B → C → D** (브릿지 토대 → config → 통합 → UX). branch 명명(Codex #7): root=`task/root-{ROOT}`, leaf=`task/issue-{LEAF}`. **dependency 정본은 GitHub Issue dependencies, branch ancestry는 실행 편의 정보일 뿐**(설계에 명시).

---

## 4. `[should-reflect-before-implementation]` 처리

| # | 권고 | 처리 | 위치 |
|---|------|------|------|
| 2 | closeout을 pr/local로 일반화 | **accepted** | Unit C |
| 3 | leaf 무검증 금지 | **accepted** | Unit C |
| 4 | integration config를 root 생성 시 materialize | **accepted** | Unit B |
| 10 | local-merge에 merge simulation 필수 | **accepted** (안전 핵심) | Unit C |

deferred/rejected 없음.

### round 2 처리 (changes-requested · blocking 1 · scope 동결)

| 항목 | 처리 | 위치 |
|---|------|------|
| **[blocking]** doctor read-only ↔ reconcile mutation 모순 | **fixed** — diagnose(`--json`) / mutation(`reconcile --apply`·`doctor --fix`) 분리, opportunistic reconcile도 dry-run→apply gate | Unit D |
| [should-reflect] Execution Contract parser-safe | accepted — fenced+`schema_version`+stable keys+unknown-ignore | Unit B |
| [should-reflect] merge simulation "tests" 모호 | accepted — Unit B `required_checks` 연결 | Unit C |
| [directional] major leaf 위험도 rule table | accepted — `leaf_policy` 룰 | Unit C |
| [directional] Ledger 최신상태 빠른 read | accepted — stable marker/event block, body cache deferred | Unit C |

**scope 확장 없음**(Codex r2 #6 준수 — blocking 해소 + 정밀화만).

---

## 5. open-question 처리 (round 2에서 Codex 확인됨)

| Q | 작업자 입장 | round 2 |
|---|-------------|---------|
| Q1 closeout 확장 vs 별도 | **확장**(`closeout.py --mode pr\|local`) | ✅ 동의 |
| Q2 Execution Contract 포맷 | **parser-safe**(fenced+`schema_version`+stable keys+unknown-ignore); 부재 시 A가 `null`+`default_source` | ✅ 정밀화(r2 #2) |
| Q3 major leaf gate | self-flow 기본 + **`leaf_policy` rule table**(비가역/DB/public API/security/data-loss → PR·hard self-flow 강제) | ✅ 정밀화(r2 #4) |
| Q4 Ledger 형태 | append-only + **stable marker/event block**, stacked+local 한정, body cache deferred | ✅ 정밀화(r2 #5) |

worker YAGNI 판단 3건(doctor 1개 통합 · Ledger stacked+local 한정 · label bootstrap 강등) 모두 Codex 동의.

---

## 6. round 3 요청 (confirm)

blocking #1 해소 + should-reflect 정밀화 완료, **scope 동결**. 4-unit 절단(A→B→C→D)과 안전계약(diagnose↔mutation 분리, required_checks 연결, leaf_policy 룰) 이의 없으면 lock.
