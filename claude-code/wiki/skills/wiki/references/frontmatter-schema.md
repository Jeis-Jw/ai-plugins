# Frontmatter 스키마 (참조)

각 wiki 문서는 YAML frontmatter로 시작한다. 본 문서는 키별 의미·필수/선택·타입별 차이를 정리한다. 정본은 `wiki/ssot/plugin_definition_v1.md` §7.

## 공통 키 (모든 타입)

| 키 | 필수? | 타입 | 의미 |
|---|---|---|---|
| `title` | ✅ | 문자열 | 사람이 읽는 제목. 자유 변경 가능 (파일명과 무관). |
| `created_at` | ✅ | ISO 날짜 (YYYY-MM-DD) | 문서 생성일. capture 자동 기입. |
| `summary` | ✅ | 한 줄 문자열 | **인덱스가 여기서 파생**. 자족적이고 검색 키워드를 포함하는 한 줄. 제목 재탕 금지. |
| `tags` | ✅ | 인라인 리스트 | 통제 어휘(`wiki/ssot/tag-vocabulary.md`)에서. faceted 검색 근거. |
| `audience` | 선택 | 리스트 | `[human, agent]`(기본) 또는 `[agent]`/`[human]`. AI-native 시스템이라 구분. |
| `search_terms` | 선택 (recognized optional) | 인라인 리스트 | recall Stage 1 매칭 표면 (summary/tags 미매칭이어도 발견됨). capture/refresh 강제 안 함. |

## 타입별 한정 필드

| 필드 | 적용 타입 | 의미 |
|------|-----------|------|
| `verified_at` | **ssot/runbook 권장, trial_error/observation 선택, intent/decision/rejected_decision 없음** | 현재도 유효함을 마지막 확인한 날. record 중 intent/decision/rejected_decision의 유효성은 supersede로만 판정. capture에서 적용 외 타입에 지정하면 **exit 2**. |
| `affects_paths` | **ssot/runbook/trial_error/observation 선택** | 관련 코드 경로 (glob 허용: `src/auth/**`). `changed-path-stale` 검사 기반. capture에서 적용 외 타입에 지정하면 **exit 2**. |

## `relations` (중첩 블록, record만)

키 자체는 record 타입(intent/decision/rejected_decision/trial_error/observation)만 가질 수 있다. **living(ssot/runbook)은 `relations` 키 자체를 두지 않는다 (불변식)**.

| 타입 | 가능한 sub-key |
|---|---|
| `intent` | (없음 — 허브) |
| `decision` | `intents`, `rejected_decisions`, `ssot`, `tasks` |
| `rejected_decision` | `intents` |
| `trial_error` | `decisions`, `tasks` |
| **`observation`** | `ssot`, `runbook`, `decisions`, `tasks` |

각 sub-key의 값은 인라인 리스트. 위키 문서 참조는 **항상 전체 basename**. `tasks`만 외부 작업 ID(`owner/repo#N`).

```yaml
relations:
  intents: [INT-2026-04-17-143052-signup-speed]
  rejected_decisions: [REJ-2026-04-17-143055-email-auth]
  tasks: [owner/repo#18]
```

## 생명주기 키 (top-level, record만)

**중요: top-level — `relations` 안에 넣지 않는다.**

| 키 | 의미 | 자동 / 수동 |
|---|---|---|
| `supersedes` | 인라인 리스트 of basename | 이 record가 *대체한* 옛 record(들). capture --supersedes 또는 retire가 자동. |
| `superseded_by` | 단일 basename | 이 record를 *대체한* 새 record. retire가 자동. |
| `retired_at` | ISO 날짜 | 폐기일. retire가 자동. |
| `retired_type` | `deprecated` 또는 `superseded` (v1 2값) | 폐기 사유. retire가 자동. |

## 키 순서 규약 (capture 출력)

CLI는 다음 순서로 frontmatter를 직렬화한다(읽을 때 사람 친화):

1. `title`, `created_at`, `summary`, `tags`
2. `verified_at`, `audience` (있을 때)
3. `search_terms`, `affects_paths` (있을 때)
4. `supersedes` (capture --supersedes 시)
5. `relations` (있을 때 마지막)
6. retire 시 추가되는 `retired_at`, `retired_type`, `superseded_by`는 그 시점의 마지막에 append

사람이 손편집한 frontmatter도 read 시 받아들인다 (block-style 리스트, 코멘트 허용).

## 직렬화 규칙 (write)

- 스칼라: `key: value` (특별한 인용 없음)
- 리스트: 인라인 `key: [a, b, c]` (콤마+공백). 빈 리스트 → 키 자체 생략.
- `relations`: 비어있지 않은 sub-key만 emit. 모든 sub-key가 비면 `relations` 키 전체 생략.

## 금지

- `id` 필드 — basename이 정본
- `status` 필드 — 경로(`retired/`)가 정본
- living에 `relations` 키
- record의 lifecycle 키를 `relations` 안에 넣는 것
- **`classified_as` 필드** — v1은 OBS lifecycle을 `deprecated`/`superseded` 2값으로 단순화 (§17 반려). 어디에 두어도 위반.

## `refresh --check schema`가 자동 점검하는 항목

스키마 무결성은 `refresh`의 `schema` 검사가 사후 일괄 확인한다(`all`에 포함). 검사 항목:

| 검사 | 위반 신호 |
|------|-----------|
| 필수 공통 필드 | `title` / `summary` non-empty scalar, `tags` non-empty list 누락 |
| **날짜 유효성** | `created_at` 필수 + 유효 ISO 날짜, `verified_at`/`retired_at` 존재 시 유효 ISO 날짜 (`2026-99-99` 같은 가짜 날짜 거부) |
| **placeholder 검사** | `title`/`summary`가 `<...>` 형태(템플릿 placeholder)이거나 `tags`에 placeholder 항목 |
| frontmatter 자체 누락 | 문서가 `---`로 시작 안 함 → `frontmatter` 필드로 1건 보고 |
| 금지 필드 | `id` / `status` / `classified_as` 존재 |
| living relations | `ssot`/`runbook`에 `relations` 키 존재 |
| lifecycle 위치 오류 | `supersedes`/`superseded_by`/`retired_at`/`retired_type`이 `relations` 안 |
| 허용 외 relation sub-key | 타입별 `allowed_relations` 외 키 |
| 관계 대상 타입 불일치 | `relations.intents`가 intent 타입을 가리키지 않음 등 |
| 타입별 필드 scope | `verified_at` / `affects_paths`가 적용 외 타입에 존재 |
| **인덱스를 relation target으로 지목** | `relations.ssot: [ssot]`처럼 폴더 자체의 인덱스 파일(`<폴더명>.md`)을 가리킴 → `find_doc_anywhere`가 인덱스를 스킵하므로 `broken-rel`로 보고됨 |

**capture 시점에도 같은 규칙이 강제된다** — 동일한 module-level helper(`_is_valid_iso_date` / `_is_placeholder_value`)를 capture / schema / stale / changed-path-stale이 모두 사용. 손편집/외부 도구 변경은 schema check가 사후에 잡는다.

구체적으로 capture는 다음을 즉시 거부(exit 2):
- `--verified-at`이 strict YYYY-MM-DD 형식이 아님 (`2026-1-1`도 거부)
- `--title` 또는 `--summary`가 `<...>` 형태 placeholder
- `--tags`의 항목 중 하나라도 `<...>` placeholder

stale / changed-path-stale은 invalid `verified_at`을 silent skip하고, schema가 단독으로 보고한다 — 한 문서가 같은 invalid 값으로 중복 보고되지 않게 함.

## Unicode 정규화 (NFC)

- 모든 입력 경로(slugify의 title, `--slug`, relation refs)와 read 시점의 file basename은 **NFC**로 정규화된다.
- 이유: macOS APFS 등이 NFD(`가` → `ㄱ+ㅏ` 분해)로 파일명을 반환할 수 있어, NFC 입력 ref와 NFD 파일 basename이 byte-level에서 달라 resolver가 깨질 수 있음.
- vault에 새로 만드는 모든 파일 basename은 NFC. 외부 도구가 NFD로 파일을 만든 vault를 인계받는 경우, NFC ref로도 resolve되어야 함 (`read_doc`이 NFC normalize).

## YAML 파서 한계 (스코프 명시)

본 CLI는 frontmatter용 **제한된 YAML subset**만 지원한다. 다른 YAML 도구와 다르게 처리되는 점:

- **quoted string 미지원**: `summary: "값에 # 있음"`은 단순 scalar로 처리되며 `"` 자체를 값에 포함.
- **inline `#` comment 자동 제거**: 값 뒤에 ` #`(공백+해시)가 있으면 그 앞까지만 값으로 사용. 따라서 `summary: issue #42`처럼 *공백 뒤 해시가 의미 있는 값*은 잘릴 수 있음. 의도된 `#`이 필요하면 ` `(공백) 없이 붙이거나 (`owner/repo#42`처럼) 단어 일부로 사용하라. 인라인 리스트 안의 `#`은 `]` 이전이면 보존된다.
- 위 두 한계 때문에 정말 다양한 YAML 입력이 필요한 vault에서는 `schema` check + 직접 검증을 같이 돌릴 것을 권장.
