# 설계 — task-github C1: tier 게이트 배선

- **대상:** `plugins/task-github/` (0.4.0 → 0.5.0)
- **근거:** wiki-markdown 0.11.0의 refresh check 2등급(B2)을 task-github 게이트에 활용.
- **상위:** C(merge/done closeout 자동화)의 첫 조각. C2(`closeout.py` 스크립트)는 다음 사이클.

## 문제

task-github의 hard gate가 `wiki refresh --strict`(전체 체크) → hygiene 경고(orphan/stale/tags)에도 PR 생성·머지를 차단. 너무 무딤. 운용 오버헤드.

## 방향

hard gate를 **`refresh --level integrity --strict`**(구조적 깨짐만 차단)로 좁히고, hygiene는 **비차단 경고**로 가시화. drift 게이트(`changed-path-stale`)는 task-github의 의도적 hard 정책이라 유지(별도 명시 check, tier 무관).

- **integrity (차단):** schema, broken-rel, task-ref, duplicate-basename, supersede, active-ref-retired.
- **hygiene (경고):** stale, orphan, index, retired-in-index, tags, changed-path-stale, empty-lesson, decision/task-quality.
- **drift (차단, 불변):** `changed-path-stale` 명시 check — 코드↔문서 drift는 task-github가 PR/머지 차단 유지.

## 변경

1. **`rules/quality-gates.md` G1**(게이트 정본): hard gate를 `--level integrity --strict`로. tier 정책 명문화(integrity 차단 / hygiene 경고 / drift 차단 불변). `refresh --strict`는 integrity 이슈만 exit 6.
2. **`skills/verify/SKILL.md`**: G1 `refresh --strict` → `refresh --level integrity --strict`. `refresh --level hygiene --json` 비차단 경고 surface 추가(보고만, 판정에 영향 없음).
3. **`skills/merge/SKILL.md`**: G1 `refresh --strict` → `refresh --level integrity --strict`. drift 게이트 불변. hygiene 경고 surface.
4. **`skills/done/SKILL.md`**: 게이트는 drift-only라 불변. 일관성 위해 hygiene 경고 surface 추가.
5. 버전 0.4.0 → 0.5.0 (plugin.json ×2 + marketplace).

## 제약 / 불변

- 위키 없는 워크스페이스 graceful skip 유지.
- drift hard gate 유지(코드-문서 drift는 차단).
- 하위호환: integrity 이슈 0이면 종전 `--strict`와 동일하게 통과. hygiene-only 상황만 동작 변화(차단→경고).
- 밑단 tier 동작은 wiki-markdown B2에서 테스트 완료(`refresh --level`, exit code).

## 완료 기준

- 게이트 정본 + 3개 SKILL이 `--level integrity --strict` 사용, hygiene 경고 surface.
- `refresh --level integrity --strict`가 hygiene-only 볼트에서 exit 0 (B2 테스트로 검증됨).
- self-flow 리뷰 approved → PR → 머지.
- task-github는 유닛 테스트 부재 — 게이트 명령 유효성 + self-review로 검증.
