# 자율 작업 프로토콜 (task-github)

> 이 룰은 `task-github` 플러그인의 **공통 규약**이다. 모든 스킬이 이 규약을 공유한다.
> 프로파일·기어·플로우·레이어·에러복구·완료조건·지식기록의 **단일 정의**다.
> 설계 배경·불변식 전체는 [DESIGN.md](../DESIGN.md) 참조.

---

## 0. 역할: Tech Lead

에이전트는 **Tech Lead**로서 사령관(사용자)의 의도를 받아:
1. 작업을 분석하고 적절한 기어/플로우를 판단한다
2. 직접 수행하거나 서브에이전트에 위임한다
3. 결과를 종합해 사령관에게 보고한다

---

## 1. 프로파일 (환경 분류)

`CLAUDE.md`에 `프로파일: solo` 또는 `프로파일: team`으로 명시한다. **미지정 시 `solo`**.

| 항목 | solo (기본) | team |
|------|------|------|
| 플로우 판단 단위 | 2단 (micro / full) | 3단 (micro / normal / major) |
| 기어 **라벨** | `gear:micro/normal/major` (공통) | `gear:micro/normal/major` (공통) |
| 지식 기록(위키) | 권장 | 권장 |
| 서브에이전트 | 선택 | 적극 고려 |
| `review` 머지 | 자동 허용 | `--auto-merge` 명시 시만 |

- **기어 라벨은 프로파일과 무관하게 항상 `gear:micro|normal|major`** — 라벨은 영구 히스토리라 환경에 의존하면 안 된다. **`gear:full` 같은 라벨은 존재하지 않는다.**
- solo의 `full`은 **플로우 판단 단위**일 뿐이다: "micro가 아니면 제대로 한다(planned --full)". 라벨을 붙일 땐 실제 파급력대로 `gear:normal`(서비스 내부) 또는 `gear:major`(외부 계약)를 고른다. 즉 solo는 normal/major를 **라벨로는 구분하되 플로우로는 통합**(둘 다 planned --full)한다.
- team과의 유일한 차이: team은 normal→`plan`, major→`plan --full`로 플로우를 나누지만, solo는 full(normal·major) 모두 `plan --full`로 통합한다.
- 프로파일은 **같은 스킬을 다르게 동작**시키는 게 아니라, 호출자(에이전트/사용자)의 **판단 강도**를 조절한다.

---

## 2. 기어 (작업의 파급력)

> **★ 가장 중요한 분류**: 기어는 **영향 반경(파급력)** 으로만 판단한다. 크기(파일 수·커밋 수)는 근거가 아니다.

| 기어 | 영향 반경 | 예시 | 플로우 |
|------|----------|------|--------|
| **micro** | 자기 파일 내부만 | 오타, 주석, 로컬 로직 | express |
| **normal** | 자기 서비스/모듈 내부 | 신규 기능, 일반 로직 | planned |
| **major** | 외부 계약 변경 | API/DB/CLI/파일포맷/공개 IF | planned --full |

판단 규칙:
- **애매하면 상위 기어.** 잘못 판단 시 승격(강등 금지).
- 여러 기어 섞이면 **가장 높은 기어**.
- **라벨은 항상 micro/normal/major.** solo는 *플로우*만 micro/full 2단으로 통합할 뿐, 라벨은 파급력대로 normal/major를 구분해 붙인다(`gear:full` 없음).

---

## 3. 플로우 (승인 관문)

기어에서 자동 결정된다:

| 플로우 | 트리거 (team) | 트리거 (solo) | 절차 |
|--------|--------|--------|------|
| **express** | micro | micro | `run` → (자동 검증) → 완료 |
| **planned** | normal | — | `plan` → 승인 → `run` → `verify` |
| **planned --full** | major | full (normal·major) | `plan --full` → 승인 → `run` → `verify` (롤백·영향 분석 포함) |

- **express**: plan 없이 즉시 실행. 단순 변경에만.
- **planned**: Plan Mode로 계획 → 사령관 승인 → 실행 → 검증. (team의 normal 전용)
- **planned --full**: 롤백 계획·영향 범위·ADR 초안 포함. team은 major 전용, **solo는 full(=micro 아닌 모든 것)** 에 적용.

오버라이드(매핑 이탈)는 **양방향 재확인**: 하향(major를 express로)은 검증 없이 외부 계약 변경하는 위험, 상향(micro를 planned로)은 과도한 오버헤드 — 둘 다 사령관 재확인.

---

## 4. 레이어 (작업 추상화 단계)

작업은 3개 레이어로 나뉜다. **인접 레이어만 호출**할 수 있다(건너뛰기 금지).

| 레이어 | 스킬 | 역할 |
|--------|------|------|
| L1 전략 | `define` | 작업을 Issue 트리 + dependency + 위키 task 노드로 구조화 |
| L2 전술 | `start`, `plan`, `verify` | 작업 점유·계획·검증 |
| L3 실행 | `run`, `done` | 코드 변경·완료 |

---

## 5. 에러 복구

작업 중 복구 불가 상황 발생 시:
1. Issue에 `[중단]` 코멘트로 실패 지점·원인·현재 상태 기록
2. 사령관에게 보고
3. 다음 세션에서 `[중단]` 코멘트로 맥락 복원

워크트리 미커밋 변경은 **보존**(함부로 삭제 금지).

**위키 호출 실패**: 캡처/전이 같은 보조 wiki CLI 호출이 비0 종료하면 해당 동작만 스킵하고 `[관찰]` 코멘트로 사유 기록 후 사령관에 알림. 단, `refresh --level integrity --strict`와 `changed-path-stale`는 [quality-gates.md](quality-gates.md) G1 hard gate라서 실패 시 `verify`/`done`/`merge`를 진행하지 않는다(hygiene 등급은 경고만). 위키가 없는 워크스페이스는 위키 단계를 skip한다.

**Issue dependency API 실패**: GitHub dependency를 생성/조회하지 못하면 그 dependency의 자동 강제는 적용되지 않는다. `define`은 fallback 코멘트를 남기고, `start`/`run`/`done`/`merge`는 사령관에게 수동 확인 필요성을 보고한다. 정상 조회 시 열린 `blocked_by`는 작업 차단 조건이다.

**지식 기록 감사**: 비 trivial 작업은 종료 전 [knowledge-capture.md](knowledge-capture.md)의 Knowledge Capture Audit를 수행한다. 결과는 `recorded`/`proposed`/`none` 중 하나로 최종 보고나 Issue 코멘트에 남긴다.

---

## 6. 완료 조건

작업 완료는 **2수준**으로 평가:
- **실질(MUST)**: 기능·데이터 보존·플러그인 독립성·프로토콜 규약. 미충족 시 작업 미완료.
- **형식(SHOULD)**: 빈 디렉토리·정적 메타·네이밍. 미충족은 "제안"으로만.

모호하면 **실질로 분류**(안전 우선).

**자동 반복 한계**: verify/run 루프가 **3회** 초과 시 자동 중단 → `[중단]` 태그 → 사령관 브리핑.

---

## 7. 지식 기록 (위키 연동)

작업 중 발생한 지식은 Issue 코멘트에 **태그**로 기록한다. 이것이 세션 간 맥락 복원과 위키 승격의 원천이다.

| 태그 | 의미 | 위키 타입 | 캡처 |
|------|------|----------|------|
| `[결정]` | 여러 선택지 중 하나 선택 | `decision` | 제안 후 확인 |
| `[시행착오]` | 실패·우회·안티패턴 | `trial_error` | 제안 후 확인 |
| `[관찰]` | 분류 전 발견(아직 어디 둘지 모름) | `observation` | 자동(저위험) |
| `[사실]` | 재검증 가능한 현재 상태 사실 | `ssot` 갱신 / `observation` | 제안 후 확인 |
| `[질문]` | 사령관 확인 필요 | — | 캡처 안 함 |
| `[중단]` | 복구 불가 실패 | — | 캡처 안 함 |

- 위키↔task 연동의 **방법(감지·호출)**은 [wiki-bridge.md](wiki-bridge.md)에, **정책(누가·언제·어떤 타입을)**은 자동로드 agent-entry 파일(`CLAUDE.md` / `AGENTS.md`)의 operating policy 블록에 둔다.
- 위키 미가용(`./wiki/` 없음) 시 모든 승격을 **스킵하고 Issue 코멘트 태그로만** 남긴다(정상 동작).

---

## 8. 빌트인 활용

- **Plan Mode**: `plan` 스킬에서 읽기 전용 분석에 사용.
- **서브에이전트**: 독립적 전문성이 필요할 때 위임 (Architect/Backend/Frontend/DevOps/Code Reviewer/QA/Security 등).
- **슬래시 명령**: 각 스킬은 `task-github:{name}`으로 호출된다.

---

*이 룰이 바뀌면 모든 스킬의 동작이 바뀐다. 신중히 수정하라.*
