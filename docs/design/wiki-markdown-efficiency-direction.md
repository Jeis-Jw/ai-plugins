# 방향 설계 초안 — wiki-markdown 운용 효율 개선 (문서 오버헤드 감소)

- **대상 task:** `wiki/task/TASK-2026-06-19-125723-wiki-markdown-운용-효율-개선-문서-오버헤드-감소.md`
- **버전:** wiki-markdown 0.9.0 → 범프 예정
- **영향 ssot:** [[wiki-lifecycle]], [[wiki-data-model]]
- **상태:** round 2 reviewer **approved**. round 2 non-blocking 3건(기어별 예산 / hard·hygiene gate 분리 / closeout 자동화) 반영. complete 대기(사용자 확인).

## 공통 원칙 (취지 보존 — 깨면 안 됨)

- 고정 섹션 헤더 유지 — 본문만 옵션화, 헤더 삭제 없음 (Stage-2 recall 전제).
- 결정성(같은 입력 → 같은 출력) + JSON/exit-code 계약 유지.
- 4계층 분리 + 비대칭(wiki는 task-github를 모름) 유지.
- 모든 신기능 opt-in 또는 하위호환 기본값. 회귀 0.
- **공유 헬퍼 `apply_section_updates(body, {header: value})` 신설** — `_replace_section`(`wiki_cli.py:902`) 래핑. Item 2·3 둘 다 사용 → 중복 제거, 단일 정본.

---

## Item 1 — orphan이 done-task 백링크 포함 (data-model, 버그픽스)

**문제.** orphan의 `incoming`은 `all_active`만 스캔(`wiki_cli.py:2305`). done task는 `all_retired`로 분류됨(`2198-2199`, 의도적). 그러나 `find_backlinks`는 done 포함(`966`). → done task가 DEC를 relation해도 orphan은 그 백링크를 못 봄 → DEC가 거짓 orphan. **recall은 백링크를 보여주는데 orphan은 고아라고 함** = 자기 불일치.

**방향.** 의도적 제외(라인 2195-2197 주석)를 통째 되돌리지 **않는다**. orphan의 `incoming` 계산에만 done docs를 추가한다 — done task의 relation은 "이 결정이 무슨 작업을 낳았나"의 유효 백링크이므로 `find_backlinks`와 의미를 일치시킨다. orphan **후보**는 여전히 active RECORD_TYPES만. `tasks` relation skip 유지(외부 GitHub ref).

**구현 (리뷰 #3 승인 + 팁).** incoming 2-pass(`2305-2320`)에서 첫 pass 소스를 `incoming_sources = all_active + [d for d in all_docs if d.done]`처럼 **done task만 명시 포함**. retired record는 계속 제외 → 2195-2197 주석 의도와 충돌 없음. `iter_done_docs` 재사용.

**테스트.** DEC 생성 → task가 →DEC relation → task done 전이 → `refresh --check orphan` → DEC **미플래그**. 회귀: 백링크 0인 순수 고아는 여전히 플래그.

**리스크.** 낮음. 거짓 양성만 줄어듦(노이즈↓). 하위호환: 엄격히 완화 방향.

---

## Item 2 — snapshot save 부분 업데이트 (lifecycle)

**문제.** `snapshot_body_from_args`(`1190-1195`)가 7섹션 전체를 매번 재작성, 빠진 건 `""`로 덮어씀. → 라운드마다 전 섹션 재공급 강제.

**방향 (리뷰 round 1 반영 — default flip 철회).** `--merge`를 **명시 opt-in**으로 추가, **기본은 현 replace semantics 유지**.

- **핵심 난점:** "플래그 생략" vs "빈 값 명시"를 구분해야 한다. 현재 argparse `default=""`(`2856-2863`)는 구분 불가 → 기본값을 `None`으로 변경. `None`=("미지정"), `""`=명시적 비우기. (이 구분은 merge 모드에서만 의미 발생; replace 모드는 종전대로 None→"" 취급.)
- **`--merge` (opt-in):** 기존 스냅샷 본문 read → arg가 `None`이 아닌 섹션만 `apply_section_updates`로 갱신, 나머지 보존. 신규 파일(기존 없음)이면 전 헤더 스캐폴드 + 제공분만 채움.
- **기본 (replace, 현 동작):** 7섹션 전체 재작성, 생략 섹션 `""`. 기존 호출자 의미 불변.

**하위호환 (리뷰 #1 blocking 반영).** 공통 원칙 "신기능 opt-in 또는 하위호환 기본값" 준수를 위해 **0.9.x에서 default flip 안 함**. `--replace` 탈출구가 있어도 기본값을 merge로 바꾸면 기존 호출자 의미가 바뀌어 하위호환 기본값이 아니다. default merge로의 전환은 사용 경험 축적 후 별도 breaking-change 또는 major에서 재검토. `created_at` 보존, `updated_at` 스탬프 유지.

**테스트.** 풀 저장 → `--merge --decided`만 재저장 → 타 섹션 보존 확인. 기본(merge 미지정) 저장 → 생략 섹션 비워짐(현 동작 회귀). 멱등성.

**리스크.** 낮~중으로 하향(default 불변). 빈값/생략 의미가 merge 모드 한정 — `None` 센티넬로 처리.

---

## Item 3 — capture 1콜화, 섹션별 명명 플래그 (lifecycle)

**문제.** capture가 빈 섹션만 스캐폴드(`1452-1456`) → read+채우기 별도 = 3스텝/노드.

**방향 (선택: 섹션별 명명 플래그).** 타입별 섹션이 다르므로(`TYPE_SPECS` 8타입) 섹션→ascii flag 매핑이 필요하다.

- **(리뷰 #4 승인 + 팁)** `TYPE_SPECS.sections` tuple shape를 바꾸면 기존 테스트/헬퍼 영향이 넓다. **초기 구현은 병행 테이블 `SECTION_FLAGS = {doc_type: {flag_key: header}}`로 분리**하고, 안정화 뒤 TypeSpec으로 합친다(리스크↓). 예: decision → `--sec-decision`/`--sec-intent`/`--sec-background`/`--sec-alternatives`/`--sec-tradeoffs`/`--sec-reeval`. (한글 헤더→안정 ascii 키, 단일 테이블 정본.)
- capture 파서에 전 타입 union flag 등록(옵션). 런타임에 타입 확정 후 **그 타입 섹션에 속한 flag만 허용** — 외부 flag는 결정적 에러(exit nonzero).
- 제공된 flag는 스캐폴드에 `apply_section_updates`로 채운다. 생략 섹션은 빈 헤더 유지.

**하위호환.** 섹션 flag 없는 capture == 오늘과 동일.

**플래그 네이밍 — 리뷰어 결정 포인트.** `--sec-<key>` prefix 방식 제안. 키 매핑 테이블 1곳 집중. 대안(미채택): `--section KEY=VALUE` 반복 플래그(발견성↓, 사용자가 명명 플래그를 선택해 배제).

**테스트.** `capture decision --sec-decision "..." --sec-background "..."` → 해당 본문 채워짐, 타 섹션 빈 헤더, 단일 콜. 외부 flag(decision에 `--sec-procedure`) → exit nonzero. 회귀: flag 없는 capture 불변.

**리스크.** 중. 한글→ascii 매핑 스킴이 핵심. 테이블 단일화로 완화.

---

## Item 4 — 경량 capture `--lite` (data-model)

**문제 (리뷰 #2 blocking 반영 — 진단 수정).** quality 체크(`_check_decision_quality` `2102`·`_check_task_quality` `2118`)는 `QUALITY_REFRESH_CHECKS`(`2020-2021`)에 속하며 **기본 `ALL_REFRESH_CHECKS`에 없다**(`2013-2019`). 즉 기본 `refresh`는 quality를 실행하지 않고, `--check decision-quality`처럼 **명시 opt-in**일 때만 돈다. 따라서 "기본 체크라 lite 문서가 FLAG 폭탄"은 **부정확** — 정정. 실제 문제는: **quality check를 명시 실행할 때 lite 문서의 비핵심 섹션을 어떻게 평가할 것인가**. ("해당 없음" ~5자 < `QUALITY_MIN_CHARS`=20이라, 평가 대상이 되면 여전히 미달.)

**방향 (좁힌 범위, 권장).**

- `TYPE_SPECS`(또는 병행 테이블)에 `core_sections` 부분집합 정의.
- `--lite`는 프론트매터 마커 `lite: true` 기록 + 비핵심 섹션을 인식 토큰("해당 없음")으로 프리필.
- **opt-in quality check 내부 동작으로** `lite: true` 문서의 비핵심 섹션을 의도적 skip 처리(통과). 핵심 섹션·relations 요구는 **유지**(품질 바닥 보존). 기본 refresh는 quality를 안 돌리므로 lite는 기본 흐름에 무영향.
- `refresh --strict`와의 관계는 "선택된 quality check를 strict exit(비0 종료)로 승격" 수준으로 재서술. lite skip은 strict 여부와 독립; strict는 선택된 check의 FLAG를 에러로 올릴 뿐.

**대안 (고리스크, 미권장).** quality 게이트 로직 자체를 완화. quality 테스트 영향 + 품질 바닥 하락. 배제.

**테스트.** `capture decision --lite --sec-decision ... --sec-intent ...` (핵심만) → `refresh --check decision-quality` quality FLAG 0(lite skip). 비-lite 문서 `--check decision-quality` 동작 불변. 기본 `refresh`는 lite/비-lite 모두 quality 미실행 확인.

**리스크.** 중. `core_sections` 경계 + lite skip을 quality check 내부에 한정하는 게 핵심 안전장치.

**리뷰어 결정 포인트.** core_sections 경계(타입별 무엇이 핵심인가) + `lite:true` 마커 영속화 적절성.

---

## Item 5 — 캡처 임계 명문화 (정책, 코드 아님)

**방향.** `wiki-markdown:agent-policy` 스캐폴드 텍스트 + CLAUDE.md/AGENTS.md 재렌더.

- 작은/일회성 = observation + 커밋 메시지. DEC = 재방문/되돌리기 비용 있는 것만.
- refresh는 묶음 끝 1회(노드마다 아님).
- "리프 task 노드 금지" 강화.
- **(리뷰 round 2 #3) 기어별 문서 예산 명문화.** 모든 작업을 같은 문서 강도로 처리하지 않게 하는 안전장치. 예:
  - `gear:micro` — wiki task 생략 / 감사 캡처 none 기본.
  - `gear:normal` — 후보 있을 때만 capture(observation 우선).
  - `gear:major`(+workflow) — task + DEC/SSOT 유지.
  위키 취지는 살리되 강도는 기어에 비례.

**테스트.** `test_agent_policy_scaffold.py` 갱신. 재렌더 결과 확인.

**리스크.** 낮음.

---

## 시퀀싱 & 횡단 사항

**권장 순서:** 1 (격리·즉효) → 2 → 3 → 4 (3의 section-fill 기반) → 5. Item 2·3은 `apply_section_updates` 공유 → 2에서 헬퍼 신설, 3에서 재사용.

**횡단 사항:**

- 각 item은 task 노드 방침대로 doc-first `define`으로 독립 단위 분해(필요 시 GitHub 이슈 트리).
- item별 `refresh --strict` 영향 확인.
- 버전 범프: `.claude-plugin/plugin.json` + `.codex-plugin/plugin.json` 양쪽.
- 회귀 0: 기존 capture/snapshot/refresh 호출처 호환 — 전 신기능 opt-in/하위호환 기본값으로 보장.

**후속 후보 (이번 0.9.x 범위 밖, 리뷰 round 2 제안):**

- **(#1) integrity-hard vs hygiene-warn check 분리.** refresh check를 2등급으로: `integrity-hard`(schema, broken-rel, duplicate-basename, task-ref — merge/done hard gate가 막아야 할 무결성) vs `hygiene-warn`(orphan, stale, quality, changed-path-stale 일부 — 경고만). 운영 오버헤드 완화 취지를 선명하게. task-github merge/done gate가 어느 등급까지 막을지 별도 설계.
- **(#2) task-github merge/done closeout 자동화.** wiki-markdown 범위 밖(task-github 쪽). 실제 운영에서 PR merge 후 `wiki complete → refresh → closeout commit/push → branch cleanup`가 수동 연쇄 — 체감 오버헤드의 핵심. 자동화 후속 item.

**리뷰 round 1 결과 (반영 완료):**

1. **Item 1** — ✅ 승인. done만 명시 포함(`all_active + done`), retired 제외 → 주석 의도와 충돌 없음.
2. **Item 3** — ✅ 승인. `SECTION_FLAGS` 병행 테이블로 초기 구현, 추후 TypeSpec 합류.
3. **Item 4** — 🔧 진단 정정. quality check는 opt-in(`QUALITY_REFRESH_CHECKS`), 기본 refresh 미실행. lite skip은 opt-in quality check 내부 동작으로 설계.
4. **Item 2** — 🔧 default flip 철회. 기본 replace 유지, `--merge` opt-in.
