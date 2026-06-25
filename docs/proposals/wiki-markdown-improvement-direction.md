# wiki-markdown 개선 방향 — 분석 + 결정 (방향 확정 · locked)

- **대상**: wiki-markdown 0.12.0
- **작성자**: Claude (worker)
- **상태**: session-review **수렴 확정** (round 1·2·3 모두 approved · blocking 0 · reviewer lock). 구현 단계 이월 노트는 §8.
- **리뷰 목적**: 분석 정확성 + 우선순위 + 누락 아이디어 수렴. **구현 아님 — 방향 수렴 완료.**

---

## 0. 입력

Claude·Codex 두 에이전트 실사용 운용 피드백 2건(원본 섹션 부록 A). 둘 다 "지식 모델 탄탄, 마찰은 운용 표면"으로 수렴하나 **세션 종류가 달라 다른 표면을 침**: Claude=설계/캡처(명령 사용성), Codex=디버깅/구현(과호출).

---

## 1. 핵심 발견 (헤드라인)

1. **SKILL.md가 출시 CLI보다 뒤처져 있다 — drift 확정 3건.** `--sec-<key>`(본문 1-step), `--lite`(경량), `--level`(refresh integrity/hygiene tier) — 셋 다 CLI에 존재하나 SKILL 미문서. 특히 `--level`은 **task-github이 hard-gate로 의존**(`refresh --level integrity --strict`)하는데도 wiki SKILL은 "`--check all`=13 checks"라는 옛 표면을 설명. → 운용 마찰 본체 = **agent-facing 표면이 CLI 실체와 drift**.
2. **매뉴얼이 역설적**: 동시에 너무 길고(매트릭스 재인라인) 불완전(고가치 플래그 누락).
3. **진짜 mechanism 빈틈은 소수**: canonical `discard`, recall **projection**, snapshot/observation **stale 경고**, closeout(=complete/reopen payload 강화).
4. **일부는 mechanism 아니라 policy**: 과호출·mode·negative trigger는 호출 빈도/판단 → agent-policy + SKILL gate. 무상태 CLI에 상태머신 금지.

---

## 2. 피드백 × 실측 대조

> ✅구현됨(노출만) · 🟡부분 · ❌빈틈 · 🔁오진 · 🧭정책

| # | 항목 | 실측 | 판정 | 계층 |
|---|---|---|---|---|
| 1 | 매뉴얼 통째·무거움 | SKILL 236줄 재인라인. **+`--level` tier(`wiki_cli:2160,3095`) 미문서·task-github 의존 = drift #3** | ❌ | 표면 |
| 2 | capture 2-step | `--sec-<key>` 전 섹션 존재(`:2984`)·미기재 | ✅ | 문서 |
| 3 | 인덱스 자동 동기화 | `cmd_capture`→`refresh_all_indexes`(`:1579`) | ✅ | — |
| 4 | canonical discard 부재 | `snapshot discard`만(`:1966`). `context/*`는 `retire`뿐 | ❌ | mechanism |
| 5 | 인덱스 git 노이즈 | 커밋 산출물, capture마다 재작성 | 🟡 | 설계 |
| 6 | `--body-file`/STDIN | 없음. `--sec-*`도 인라인 문자열 | 🟡 | mechanism |
| 7 | recall `--json` 불투명 | 일관·`mode` 구분. 미문서 | ✅ | 문서 |
| 8 | `--lite` 경량 | 존재(`:2988`)·미문서 | ✅ | 문서 |
| 9 | recall 과호출 | 빈도제어 mechanism 없음 | 🧭 | 정책 |
| 10 | 디버깅중 wiki우선 | 모드 없음 | 🧭 | 정책 |
| 11 | snapshot recall 혼입 | wording=오진(이미 제외 `:777`) / symptom=실재(`snapshot load` authority 과신) | 🔁/🟡 | mechanism |
| 12 | `refresh --strict` 한계 | stale/quality opt-in 존재, stale-snapshot 부재 | 🟡 | 문서+mech |
| 13 | closeout 명령 | `complete`만. task-github `closeout.py` 별도 | ❌ | mechanism(경계) |
| 14 | recall context-pack | `--stage 1` 압축만, projection 없음 | 🟡 | mechanism |
| 15 | negative trigger | 양성 트리거만 | 🧭 | 정책/문서 |
| 16 | authority ranking | recall에 라벨 없음 | ❌/🧭 | mechanism or 가이드 |
| 17 | stale 경고 | 없음 | ❌ | mechanism |

---

## 3. 문제 지도 — 3계층

| 계층 | 정의 | 항목 |
|---|---|---|
| **L1 표면/문서** | 있는데 안 보이거나 너무 보임 | 1·2·7·8·12·15 + `--level` |
| **L2 mechanism 빈틈** | 실제 없는 기능 | 4·6·11(symptom)·13·14·16·17 |
| **L3 정책/행동** | 호출 빈도·판단 | 9·10·15(gate) |

L1만으로 체감 마찰 대부분 해소 — **신규코드 최소, 주효과는 표면 재정렬**(capture payload만 소량 신규).

---

## 4. 방향 + 우선순위

### P0-선행 — bounded drift audit
범위 **한정**: `wiki_cli --help`/parser · wiki SKILL · wiki reference · task-github rules/skills의 **command surface만** 대조. 산출 = **정본 command surface 표 + drift 목록**. (`--level` 1건 확정.) **repo-wide 문서정리로 확장 금지 — P0가 다시 ceremony 됨.**

### P0 — agent-facing runtime contract 재설계 (= 구현 Unit A)
문제는 길이만이 아니라 기본 Quick start가 `capture skeleton→read/edit`를 정답처럼 안내하는 것. 산출물:
1. **compact SKILL** — 런타임 cheat-sheet, 전체계약 `references/`.
2. **기본 예제 교체** — `--sec-*`/`--lite`/`--stage`/`--level` 중심.
3. **command별 `--json` payload 예시** (capture·recall `mode`).
4. **`capture --json` payload 확장** — `sections`/`filled_sections`/`empty_sections`/`section_flags`/`index_changed`(+optional `index_paths` touched list). **additive only — command가 이미 계산하는 파생 metadata만**(신규 introspection 명령 아님). read-back 직접 제거.
5. **negative trigger "When NOT to use"** — SKILL 상세 + **agent-policy gate 1줄** 이중배치.
6. **`--level` tier 문서화** (drift 수정).

**완료기준 — baseline 가설표(지금 남김) + 실측은 구현단계** (추정치):

| 시나리오 | before cmd/read/edit | after | 절감 |
|---|---|---|---|
| capture 3건(dec/rej/task) | 3 / 3 / 3 | 3 / 0 / 0 | `--sec-*`로 read·edit 제거 |
| snapshot save→load 재개 | 2 / 0~1 / 0 | 2 / 0 / 0 | ~동일(이미 1-step) |
| active task closeout | 2~3 / 1~2 / 0 | 1~2 / 0 / 0 | complete payload로 read 제거 |
| SKILL 1회 로드 | ~6k tok(40~50% 사용) | ~1.5k cheat-sheet | 상시 ~3k↓ |

표 숫자는 `expected baseline`(추정) — 구현 후 실제 count·JSON bytes로 채움. `snapshot save→load`은 절감 아닌 **control row**; `active task closeout` 절감은 payload가 `suggested_git_paths`/`updated_indexes` 제공 시만 성립. 실측(토큰·JSON bytes)은 구현 뒤. **debug-no-wiki는 CLI benchmark 아니라 policy acceptance** — negative trigger가 agent-policy에 들어갔는지 + SKILL When-NOT-to-use와 같은 문구로 정렬됐는지로 판정(harness trace 없는 자동검증은 과함).

### P1 — 구현 Unit B (write UX) + Unit C (read/authority UX)
**Unit B (write UX):**
- **canonical `discard`** — 가드: exact basename only · backlinks/relations 있으면 기본 거부 · `--dry-run` first-class · `--force` 명시 · affected JSON. `retire`와 의미경계 명문화.
- **`--body-file`/STDIN** — `@file` 값 convention 또는 단일 입력. 섹션별 `--sec-<key>-file`로 넓히지 말 것.

**Unit C (read/authority UX):**
- **recall projection** — stateless `recall --pack --json`. **deterministic 경계 명시**: frontmatter·relations·fixed-section snippet·task body 정해진 header에서만 추출, **prose 추론 금지**. 추론 필요분은 `candidate_*`/`source_summaries` 같은 낮은확신 이름. lock 아님.
- **authority/stale 라벨 (additive)** — `authority`/`freshness`/`use_as`/`warnings` 필드를 `snapshot load`·`recall --pack`·observation 결과에 부착. **강한 ranking/sorting은 `--pack` 내부에서만**, 기본 stage1 recall은 최소변경(안정성).
- **stale 경고는 relation-aware** — 단순 날짜비교 금지(오탐). observation은 `relations.decisions/ssot/tasks` 축으로, snapshot은 `references`/`search_terms` 있을 때만 관련 decision과 비교. anchor 없으면 `possibly_stale` 아니라 `authority_unknown`.
- machine-discoverability(`wiki schema/help --json`, `capture --dry-run --json`)도 여기 — payload로 못 덮는 introspection.

### P2 — closeout (별도, Unit C에 넣지 않음)
**새 `wiki closeout` 명령 만들지 않음.** 대신 기존 `complete`/`reopen` JSON payload 강화: `moved_from`·`moved_to`·`updated_indexes`·`suggested_git_paths`·optional `refresh_summary`. targeted refresh는 별도 또는 opt-in `--refresh`만. **GitHub/branch/label/root-close 감지는 task-github `closeout.py` 소관**(비대칭 결합). 그 외 P2: audit 체크(stale-snapshot·empty-observation), 인덱스 파생화(별도 DEC).

### 기각 / 신중
stateful usage mode(6종)·context-lock CLI 상태 — 무상태·filesystem-primary 충돌, "ceremony∝blast" 위반. 대체: 모드 = SKILL/agent-policy 서술.

### 구현 단위 (gear/PR 묶음)
- **Unit A** — surface drift/P0: `--level` 문서화, compact SKILL, examples 교체, capture payload.
- **Unit B** — write UX: `discard` 가드, body-file/STDIN.
- **Unit C** — read/authority UX: `recall --pack`, stale/authority 라벨.
- **closeout** — 별도 P2 후보(task-github 경계). C에 미포함.

---

## 5. 긴장점 — 전부 해소

- ✅**1** — context-pack은 **projection(무상태)** 채택, lock 기각. deterministic 추출 경계 명시.
- ✅**2** — authority는 **additive label**부터(authority/freshness/use_as/warnings), 기본 recall 강제 sort 안 함, 강 ranking은 `--pack` 내부만.
- ✅**3** — closeout은 **complete/reopen payload 강화**, 새 명령 아님. targeted refresh opt-in. GitHub은 task-github.
- ✅**4** — 호출빈도는 mechanism 불가 → agent-policy gate.
- ✅**6** — Codex 오진(11)은 wording-오진/symptom-실재. 대응 = relation-aware stale 경고.

**잔여 미해결 긴장 없음.**

---

## 6. 수렴 로그

- **round 1→2**: reviewer 13건 → 수용 11·부분반박 2(benchmark 범위·discoverability 분할). `--level` drift 신규 확정.
- **round 2→3**: reviewer 9건 = 내 질문 답변 + refine, **전부 수용(반박 0)**. 반영: P0-선행 bounded scope, capture payload additive 제약, baseline 가설표 추가, authority additive label(긴장2 해소), relation-aware stale, **closeout = complete/reopen payload 강화로 재설계(긴장3 해소, 새 명령 폐기)**, deterministic projection 경계, debug-no-wiki = policy acceptance, **구현 3-unit(A/B/C) 분해**, nit(신규코드 최소).

---

## 7. round 3 리뷰 요청 (confirmation)

round-2 가이드 통합 확인 위주. 잔여 이견 0이면 수렴 확정(lock).
1. round-2 9건 통합이 **충실**한가? (특히 closeout 재설계·authority additive·projection 경계·3-unit 분해)
2. baseline 가설표 숫자가 합리적인가?
3. **Codex**: 이 수렴안에 남은 이견? 없으면 lock.

---

## 8. 구현 단계 반영 노트 (round 3 reviewer)

방향 lock 후 **구현 task로 이월**할 제약 (방향 변경 아님):
- **Unit A 범위 고정** — "surface + additive payload"만. behavior semantics 섞지 말 것(P0 비대화). 성공기준 = 기존 command 의미 불변 + hidden CLI surface 제거 + read-back 감소.
- **baseline = expected baseline(추정)** — 구현 후 실측으로 채움. `snapshot save→load`=control row, `closeout` 절감은 payload가 git-paths/indexes 제공 시만.
- **Unit C stale/authority = relation-aware 테스트 케이스 고정** — anchor 없는 snapshot/observation엔 `possibly_stale` 금지 → `authority_unknown`/무경고. 관련 decision 찾을 때만 stale 경고.
- **capture payload 필드** — `index_changed: true` + optional `index_paths`(touched list)가 boolean보다 agent-friendly.
- **body-file/STDIN = capture + snapshot 함께** — 원 pain은 `snapshot save --discussion`에도 있었음. `@file`/stdin 단일 통일, 섹션별 file flag 폭발 금지.
- **구현 순서** — A → (B or C) → closeout. closeout-first는 task-github 경계와 재엮임.

## 부록 A — 원본 피드백 섹션

**Claude**: 2.1 매뉴얼 · 2.2 capture 2-step · 2.3 드리프트+취소 · 2.4 셸 · 2.5 스키마 · 2.6 경량. P1(disclosure·1-step)·P2(discard·body-file)·P3(스키마·lite).
**Codex**: 1 과호출 · 2 디버깅 wiki · 3 snapshot 신뢰 · 4 refresh 한계 · 5 closeout · 6 SKILL · 7 context-pack · 8 negative trigger. 제안 A mode·B lock·C budget·D authority·E stale·F closeout·G code-first. P0(compact·반복방지·debug억제)·P1(stale·authority·closeout)·P2(refresh한계·lock·분리).
