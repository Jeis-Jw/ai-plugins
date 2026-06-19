# 방향 설계 초안 — wiki-markdown 운용 효율 개선 (문서 오버헤드 감소)

- **대상 task:** `wiki/task/TASK-2026-06-19-125723-wiki-markdown-운용-효율-개선-문서-오버헤드-감소.md`
- **버전:** wiki-markdown 0.9.0 → 범프 예정
- **영향 ssot:** [[wiki-lifecycle]], [[wiki-data-model]]
- **상태:** 작업자 초안 (리뷰 대기)

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

**구현.** incoming 2-pass(`2305-2320`)에서 첫 pass를 `all_active + done docs`로 확장. `iter_done_docs` 재사용. retired는 계속 제외.

**테스트.** DEC 생성 → task가 →DEC relation → task done 전이 → `refresh --check orphan` → DEC **미플래그**. 회귀: 백링크 0인 순수 고아는 여전히 플래그.

**리스크.** 낮음. 거짓 양성만 줄어듦(노이즈↓). 하위호환: 엄격히 완화 방향.

---

## Item 2 — snapshot save 부분 업데이트 (lifecycle)

**문제.** `snapshot_body_from_args`(`1190-1195`)가 7섹션 전체를 매번 재작성, 빠진 건 `""`로 덮어씀. → 라운드마다 전 섹션 재공급 강제.

**방향.** `--merge`(기본) vs `--replace`.

- **핵심 난점:** "플래그 생략" vs "빈 값 명시"를 구분해야 한다. 현재 argparse `default=""`(`2856-2863`)는 구분 불가 → 기본값을 `None`으로 변경. `None`=보존, `""`=명시적 비우기.
- **`--merge`:** 기존 스냅샷 본문 read → arg가 `None`이 아닌 섹션만 `apply_section_updates`로 갱신, 나머지 보존. 신규 파일(기존 없음)이면 전 헤더 스캐폴드 + 제공분만 채움.
- **`--replace`:** 현 동작(전체 덮어쓰기) — 리셋용·하위호환 탈출구.

**하위호환 주의.** 기본을 merge로 바꾸면 동작 변화. 단 전 플래그를 항상 주는 호출자는 merge==replace로 무영향. "생략→비움"에 의존하던 호출자만 영향 — 그게 바로 줄이려는 오버헤드. 문서화 필요. `created_at` 보존, `updated_at` 스탬프 유지.

**테스트.** 풀 저장 → `--decided`만 재저장 → 타 섹션 보존 확인. `--replace`는 생략 섹션 비움. 멱등성.

**리스크.** 중. 빈값/생략 의미가 핵심 — `None` 센티넬 + `--replace` 탈출구로 완화.

---

## Item 3 — capture 1콜화, 섹션별 명명 플래그 (lifecycle)

**문제.** capture가 빈 섹션만 스캐폴드(`1452-1456`) → read+채우기 별도 = 3스텝/노드.

**방향 (선택: 섹션별 명명 플래그).** 타입별 섹션이 다르므로(`TYPE_SPECS` 8타입) 섹션→ascii flag 매핑이 필요하다.

- `TYPE_SPECS`의 `sections` 튜플을 `(header, flag_key)` 쌍으로 확장(또는 병행 `SECTION_FLAGS` 맵). 예: decision → `--sec-decision`/`--sec-intent`/`--sec-background`/`--sec-alternatives`/`--sec-tradeoffs`/`--sec-reeval`. (한글 헤더→안정 ascii 키, 단일 테이블 정본.)
- capture 파서에 전 타입 union flag 등록(옵션). 런타임에 타입 확정 후 **그 타입 섹션에 속한 flag만 허용** — 외부 flag는 결정적 에러(exit nonzero).
- 제공된 flag는 스캐폴드에 `apply_section_updates`로 채운다. 생략 섹션은 빈 헤더 유지.

**하위호환.** 섹션 flag 없는 capture == 오늘과 동일.

**플래그 네이밍 — 리뷰어 결정 포인트.** `--sec-<key>` prefix 방식 제안. 키 매핑 테이블 1곳 집중. 대안(미채택): `--section KEY=VALUE` 반복 플래그(발견성↓, 사용자가 명명 플래그를 선택해 배제).

**테스트.** `capture decision --sec-decision "..." --sec-background "..."` → 해당 본문 채워짐, 타 섹션 빈 헤더, 단일 콜. 외부 flag(decision에 `--sec-procedure`) → exit nonzero. 회귀: flag 없는 capture 불변.

**리스크.** 중. 한글→ascii 매핑 스킴이 핵심. 테이블 단일화로 완화.

---

## Item 4 — 경량 capture `--lite` (data-model)

**문제 & 충돌.** `--lite` = 핵심 섹션만 본문, 나머지 헤더 유지·"해당 없음" 허용. **그러나** `_check_decision_quality`(`2102`)·`_check_task_quality`(`2118`)가 refresh 기본 체크(`ALL_REFRESH_CHECKS`)로 비핵심 섹션을 substantive 강제 → lite 문서는 FLAG 폭탄. "해당 없음"(~5자)은 `QUALITY_MIN_CHARS` 미만이라 통과 못 함.

**방향 (저리스크 안, 권장).**

- `TYPE_SPECS`에 `core_sections` 부분집합 정의.
- `--lite`는 프론트매터 마커 `lite: true` 기록 + 비핵심 섹션을 인식 토큰("해당 없음")으로 프리필.
- quality 게이트가 `lite: true` 문서의 비핵심 섹션을 **의도적 skip**으로 인정(통과). 핵심 섹션·relations 요구는 **유지**(품질 바닥 보존).
- `refresh --check decision-quality --strict`(opt-in)는 lite 마커를 무시하고 풀 기대치 재적용. → "quality FLAG는 풀 기대치(opt-in)" 충족.

**대안 (고리스크, 미권장).** quality 게이트 자체를 기본 완화. 133 테스트 중 quality 테스트 다수 깨짐 + 품질 바닥 하락. 배제.

**테스트.** `capture decision --lite --sec-decision ... --sec-intent ...` (핵심만) → `refresh` quality FLAG 0. `refresh --strict` → 비핵심 FLAG 재등장. 비-lite 문서 quality 동작 불변.

**리스크.** 중. `core_sections` 경계 + strict 플래그 추가가 작업량. quality 기본동작 보존이 핵심 안전장치.

**리뷰어 결정 포인트.** core_sections 경계(타입별 무엇이 핵심인가) + `lite:true` 마커 영속화 적절성.

---

## Item 5 — 캡처 임계 명문화 (정책, 코드 아님)

**방향.** `wiki-markdown:agent-policy` 스캐폴드 텍스트 + CLAUDE.md/AGENTS.md 재렌더.

- 작은/일회성 = observation + 커밋 메시지. DEC = 재방문/되돌리기 비용 있는 것만.
- refresh는 묶음 끝 1회(노드마다 아님).
- "리프 task 노드 금지" 강화.

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

**리뷰어 핵심 질의 3개:**

1. **Item 1** — done 포함이 의도적 제외(2195-2197 주석)와 충돌하는가? `incoming`만 확장하는 범위가 적절한가.
2. **Item 3** — `--sec-<key>` 플래그 네이밍 + 한글→ascii 매핑 스킴 승인?
3. **Item 4** — `lite:true` 마커 + quality 게이트 skip 방식 vs 기본 완화. core_sections 경계.
