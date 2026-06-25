# wiki-markdown 개선 방향 — 분석 + 결정 초안 (리뷰용)

- **대상**: wiki-markdown 0.12.0
- **작성자**: Claude (작성자 역할, 실측 그라운딩 기반)
- **상태**: 초안 — session-review 수렴 대상
- **리뷰 목적**: (1) 분석 정확성 검증, (2) 개선방향 우선순위 도전, (3) 누락된 아이디어 발굴. **구현 아님 — 방향 수렴까지.**

---

## 0. 입력

두 에이전트가 **실제 작업 세션**에서 wiki-markdown을 쓰며 남긴 운용 효율 피드백 2건(Claude, Codex). 원본 섹션 목록 + 우선순위는 부록 참조. 둘 다 "지식 모델은 탄탄, 마찰은 운용 표면에 몰림"으로 수렴하나, **세션 종류가 달라 서로 다른 표면을 침**:

- **Claude** = 설계/캡처 세션 (snapshot save/load, capture decision/rejected/task). 마찰 = **명령 사용성**(왕복·토큰).
- **Codex** = 디버깅/구현 세션 (런타임 버그, DB, API). 마찰 = **실시간 작업 중 과호출**(호출빈도·신뢰도).

---

## 1. 핵심 발견 (헤드라인)

1. **가장 시끄러운 요청 다수가 이미 구현돼 있고, SKILL.md에 노출만 안 됨.** capture 본문 1-step(`--sec-<key>`), `--lite` 경량 캡처, capture 인덱스 자동 동기화, recall 압축(`--stage 1`), 일관된 recall `--json` 스키마 — **전부 코드에 존재**. → 1순위 레버는 **신규 기능이 아니라 문서/표면 재설계**.

2. **그래서 매뉴얼이 역설적이다**: 동시에 (a) **너무 길다**(exit-code 매트릭스·13개 refresh 체크·`--fix` whitelist를 본문에 재인라인) 그리고 (b) **불완전하다**(`--sec-*`·`--lite`·`mode` 스키마 누락). 잘못된 것을 인라인하고 고가치 ergonomic 플래그를 숨김. 두 에이전트가 서로 다른 각도에서 정확히 이 표면을 침.

3. **진짜 mechanism 빈틈은 소수다**: canonical 노드 `discard` 부재, recall 구조화 context-pack 부재, snapshot/observation **stale 경고** 부재, wiki-레벨 `closeout` 부재.

4. **일부 요청은 mechanism이 아니라 policy 계층 소관이다**: 과호출 억제, usage mode, negative trigger는 호출 *빈도/판단* 문제 → `CLAUDE.md`/`agent-policy`/SKILL "When NOT to use" 소관. **무상태 filesystem-primary CLI에 상태 머신(context-lock, 6개 mode)을 넣는 건 설계와 충돌하고 "ceremony∝blast-radius" 원칙에 반함.**

---

## 2. 피드백 × 실측 대조 (그라운딩)

> 판정 범례: ✅구현됨(노출만 필요) · 🟡부분 · ❌빈틈(신규) · 🔁오진 · 🧭정책계층

| # | 피드백 항목 | 실측 (코드 근거) | 판정 | 계층 |
|---|---|---|---|---|
| 1 | Claude 2.1 / Codex 6 — 매뉴얼 통째 로드·SKILL 무거움 | SKILL.md 237줄. CLI 계약표·13체크·`--fix` whitelist·slug팁을 본문에 재인라인. `references/wiki-protocol.md` 있는데 중복 | ❌ | 표면/문서 |
| 2 | Claude 2.2 — capture 2-step(스켈레톤→수기 본문) | `--sec-<key>` 플래그가 **모든 섹션키에 존재** (`wiki_cli.py:2984`). Quick start·CLI 계약표에 **미기재** | ✅ | 문서 |
| 3 | Claude 2.3a — capture 인덱스 자동 동기화 원함 | `cmd_capture`가 쓰기 후 `refresh_all_indexes(vault)` **자동 호출** (`:1579`) | ✅ | — |
| 4 | Claude 2.3b — canonical 노드 discard 부재 | `snapshot discard`만 파일 삭제(`:1966`). `context/*`는 `retire`(파일 유지·`retired/`로 이동)뿐. 삭제 서브커맨드 없음 | ❌ | mechanism |
| 5 | Claude 2.3c — 인덱스 git 노이즈(파생화 검토) | 인덱스 = 커밋 산출물, capture마다 재작성 → diff 노이즈 사실 | 🟡 | 설계결정 |
| 6 | Claude 2.4 — `--body-file`/STDIN (셸 이스케이프) | `--*-file`/STDIN 입력 **없음**. `--sec-*`·`--discussion`도 인라인 문자열 인자 | 🟡 | mechanism |
| 7 | Claude 2.5 — recall `--json` 스키마 불투명 | 스키마 일관·`mode`로 구분(`stage1/2/3/read/backlinks`, `:2083~2121`). SKILL에 **미문서** | ✅ | 문서 |
| 8 | Claude 2.6 — `--lite` 경량 캡처 원함 | `--lite` 플래그 **존재** (`:2988`): 핵심 섹션만, 나머지 `해당 없음` 프리필 + quality 체크 skip 표식. **미문서** | ✅ | 문서 |
| 9 | Codex 1 — recall 과호출 / 세션 락 | 호출빈도 제어 mechanism 없음(CLI는 빈도 제어 못 함). 에이전트 *행동* 문제 | 🧭 | 정책 |
| 10 | Codex 2 — 디버깅 중 wiki 우선 / usage mode | 모드 없음. 호출 *판단* 문제 | 🧭 | 정책 |
| 11 | Codex 3 — snapshot이 recall에서 truth로 혼입 | snapshot은 recall에서 **이미 제외** (`iter_every_md:777` — `snapshot/` skip). 명시적 `snapshot load` 필요. observation엔 일부 적용 가능 | 🔁 snapshot / 🟡 observation | mechanism |
| 12 | Codex 4 — `refresh --strict` 의미검증 한계 | 구조검증 외 `stale`·`changed-path-stale`·`*-quality` 존재(opt-in). 단 **stale-snapshot 체크는 부재**(snapshot은 refresh서 제외) | 🟡 | 문서+mechanism |
| 13 | Codex 5/F — closeout 고수준 통합 명령 | wiki엔 `complete`(task→done)만. task-github `closeout.py`가 별도로 존재 | ❌ | mechanism(경계) |
| 14 | Codex 7 — recall 결과를 context-pack으로 | `--stage 1`(frontmatter only ~2KB) 압축 존재. **구조화 pack**(task+decisions+constraints)은 없음 | 🟡 | mechanism |
| 15 | Codex 8 — negative trigger("언제 쓰지 마") | SKILL "When to use"는 **양성 트리거만** | 🧭 | 정책/문서 |
| 16 | Codex D — authority ranking(타입별 신뢰도) | recall 출력에 신뢰도/freshness 라벨 없음 | ❌ 또는 🧭 | mechanism or 가이드 |
| 17 | Codex E — stale 경고 강화 | snapshot/observation이 최신 decision보다 오래됐을 때 경고 없음 | ❌ | mechanism |

**요약**: 17개 중 ✅이미구현 4 · 🟡부분 4 · ❌신규빈틈 4 · 🔁오진 1 · 🧭정책 3 · (5는 설계결정). **시끄러운 P1급 요청(capture 1-step, --lite, recall 압축)이 ✅에 몰려 있음** = 표면 문제.

---

## 3. 문제 지도 — 3계층

| 계층 | 정의 | 해당 항목 |
|---|---|---|
| **L1 표면/문서** (mechanism-doc) | 기능은 있는데 안 보이거나, 너무 많이 보임 | 1·2·7·8·12(한계명시)·15 |
| **L2 mechanism 빈틈** (신규 CLI) | 실제로 없는 기능 | 4·6·13·14·16·17 |
| **L3 정책/행동** (CLI 아님) | 호출 빈도·판단 — agent-policy/SKILL 가이드 소관 | 9·10·16(가이드안) |

이 구분이 핵심: **L1만으로 두 피드백의 체감 마찰 대부분이 해소**된다(신규 코드 거의 0). L2는 소수 정밀 추가. L3는 wiki CLI를 건드리지 않고 정책/가이드로.

---

## 4. 제안 방향 + 우선순위

### P0 — 표면/문서 단일 작업 (최대 ROI, 신규코드 ≈0)
SKILL.md를 **progressive disclosure**로 재설계:
- 본문 = **compact 런타임 cheat-sheet** (Quick start + 타입 결정표 + CLI 1줄 요약 + "When NOT to use"). 목표 ~1.5k 토큰.
- 전체 계약(exit-code 매트릭스·13체크 상세·whitelist·slug 규칙)은 `references/wiki-protocol.md`로 이관, 필요 시 fetch.
- **동시에 숨은 고가치 플래그를 cheat-sheet에 노출**: `--sec-<key>`(capture 1-step), `--lite`, recall `--stage`, `snapshot save --merge`, recall `--json`의 `mode` 스키마.
- "When NOT to use" 음성 트리거 섹션 추가 (Codex 8/15).
- `refresh --strict` 출력/문서에 **"구조 무결성만 검증, 의미 freshness 아님"** 한계 1줄 (Codex 4).

근거: 두 에이전트 **공통 불만** + **이미-구현 기능 미사용**을 한 작업으로 동시 해소. 가장 싸고 가장 큼.

### P1 — 소수 진짜 mechanism 빈틈
- **canonical `discard` 서브커맨드** — `snapshot discard`와 대칭, 실수 취소용, 인덱스 자동정리 포함 (Claude 2.3b). `retire`(deprecated/superseded, 파일유지)와 의미 구분.
- **stale 경고** — snapshot/observation이 최신 관련 decision보다 오래되면 recall/load 출력에 경고 (Codex E). authority 혼동(11·16)의 실질 해법.
- **recall context-pack 출력 모드** — `--stage 1`을 넘어 task+decisions+constraints+next를 구조화 JSON으로 (Codex 7/14). *단 §5 긴장점 참조 — mechanism vs policy 결정 필요.*

### P2 — 큰 결정/경계 합의 필요
- **wiki `closeout` 고수준 명령** — done 이동+인덱스+downstream+targeted refresh+git-paths를 compact JSON으로 (Codex 5/F). **단 task-github `closeout.py`와 경계 합의 선행 — 중복 금지** (메모리: task-github C2가 이미 git/gh 머지 closeout 담당).
- **audit 체크 추가** — `stale-snapshot`·`empty-observation` 등 (Codex 4 후속).
- **인덱스 파생화 (2.3c)** — commit-artifact→read-derived. git 노이즈 제거하나 모델 변경 → **별도 DEC 필요**, 빠른 수정 아님.

### 신중/기각 후보
- **6개 stateful usage mode**(Codex A) + **context-lock CLI 상태**(Codex B/C) — 무상태·filesystem-primary 설계(Claude가 칭찬한 바로 그것)와 충돌, "ceremony∝blast-radius" 위반. **대체**: 모드는 SKILL "When to / When NOT to use" 서술 + agent-policy 가이드로, CLI 기계장치 없이.

---

## 5. 긴장점 / 미해결 — 리뷰 집중 요청

1. **context-pack을 어느 계층에?** recall이 구조화 pack을 *출력*(mechanism)할지, 아니면 에이전트가 recall 결과를 압축(policy/행동)할지. CLI가 "작업 context"를 안다고 가정하는 게 무상태 설계와 맞나?
2. **authority ranking — 강제 vs 가이드?** recall이 타입별 신뢰도를 *정렬/라벨*로 강제할지(16=mechanism), SKILL 서술로 둘지(16=정책). 강제 시 recall 출력 계약이 무거워짐.
3. **closeout 경계** — wiki closeout vs task-github closeout.py. 누가 무엇을? 중복/충돌 회피선.
4. **호출빈도는 mechanism이 도울 수 없다** — CLI는 자기가 몇 번 불리는지 모름. Codex의 P0(과호출 억제)는 본질상 100% policy/행동. 이걸 플러그인 개선으로 분류하는 게 맞나, 아니면 agent-policy 작업으로 분리하나?
5. **`--sec-*`로 Claude 2.4가 충분한가?** 왕복은 해소되나 `--sec-*`도 인라인 문자열 → 긴/백틱/`$` 본문엔 셸 이스케이프 잔존. `--body-file`/STDIN 여전히 필요한가, 과한가?
6. **오진(11) 처리** — snapshot이 recall서 이미 제외인데 Codex가 truth 혼입을 우려 = 에이전트가 `snapshot load` 결과를 과신했다는 *행동* 신호. mechanism 수정 불필요, 가이드 신호로만?

---

## 6. 리뷰어에게 (요청 사항)

- **§2 판정표 오류**를 코드로 반박해 달라 (특히 ✅/🔁 판정 — 정말 노출/오진인지).
- **§4 우선순위 재배치** 제안 — P0이 정말 최대 ROI인가? 빠진 P0 후보는?
- **누락된 개선 아이디어** — 두 피드백/이 분석이 놓친 것.
- **§5 긴장점**에 입장 — 특히 1·2·4(계층 귀속)와 6(오진 처리).
- ✅"이미 구현됨" 항목이 **노출만으로 충분한지**, 아니면 UX 추가가 필요한지 (예: capture가 --sec-* 없이 불릴 때 JSON에 섹션 헤더 목록을 반환해 Read 생략 — Claude 2.2 후속).

---

## 부록: 원본 피드백 섹션 + 우선순위 (커버리지 감사용)

### Claude 피드백 — 섹션
- 1 잘 작동(유지): 결정그래프 / snapshot staging / friendly-ref+NFC / 결정적 CLI / refresh --fix whitelist
- 2.1 매뉴얼 통째 로드 · 2.2 capture 2-step · 2.3 인덱스 드리프트+canonical 취소 부재 · 2.4 셸 이스케이프 · 2.5 recall --json 스키마 · 2.6 품질게이트 vs 경량
- 우선순위: **P1** progressive disclosure / P1 capture 1-step · **P2** canonical discard+인덱스 동기화 / P2 --body-file·STDIN · **P3** recall 스키마 문서화 / P3 --lite

### Codex 피드백 — 섹션
- 1 recall 과호출 · 2 디버깅 중 wiki 우선 · 3 snapshot/observation 신뢰도 · 4 refresh --strict 과대해석 · 5 closeout 무거움 · 6 SKILL 무거움 · 7 recall→context-pack · 8 negative trigger
- 제안 A usage mode · B context-lock · C recall budget · D authority ranking · E stale warning · F closeout 통합 · G "code 먼저" guardrail
- 우선순위: **P0** recall compact / 반복 recall 방지 / debug-mode recall 억제 · **P1** stale warning / authority ranking / closeout 통합 · **P2** refresh 한계 안내 / context-lock / skill quick·full 분리
