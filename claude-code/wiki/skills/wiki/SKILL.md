---
name: wiki
description: AI-native wiki 관리 — 프로젝트의 취지·결정·반려 대안·시행착오·관찰(observation)·현재 상태(SSOT)·운영 절차(Runbook)를 결정 그래프로 축적·조회·점검한다. "wiki 초기화/기록/회수/점검", "이 결정 위키에 남겨줘", "왜 이렇게 결정했지?", "관련 결정/취지 찾아줘", "이거 발견했는데 분류는 나중에", "위키 무결성 확인", "이거 폐기해줘" 등 결정·취지·반려·시행착오·관찰·사실·운영 절차를 다루는 모든 요청에서 본 스킬을 호출하라. filesystem-primary이며 결정적(deterministic) CLI라 토큰을 거의 안 쓰고도 정합성을 유지한다.
---

# Wiki

이 스킬은 단일 Python CLI `wiki_cli.py`를 통해 vault를 관리한다. 모든 호출은 `python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" <subcommand> [args]` 형식. 종료 코드·출력 스키마가 결정적이라 에이전트가 결과를 안정적으로 해석할 수 있다.

## 언제 사용하나

다음 발화를 만나면 즉시 본 스킬을 호출하라:

- **취지/결정/반려/시행착오/관찰 기록**: "이 결정 정리해줘", "취지 적어둬", "왜 거부했는지 남겨줘", "이 함정 기록해줘", "이거 발견했는데 분류는 나중에 봐줘"
- **현재 상태/운영 절차**: "현재 인증 구조 정리", "배포 절차 문서화"
- **조회**: "관련 결정 찾아줘", "이 취지에 묶인 결정·반려 보여줘", "auth 관련 기록", "이거 누가 supersede 했나", "이 묶음 한꺼번에 읽어줘"
- **점검**: "위키 점검", "stale fact 찾아줘", "깨진 링크 확인", "인덱스 동기화", "이번 변경에 영향받는 문서 있나"
- **vault 초기화**: "wiki 세팅", "지식베이스 만들어줘"
- **폐기**: "이 결정 deprecated 처리", "X를 Y로 supersede"

설계 문서(`wiki/ssot/plugin_definition_v1.md`)의 §1 원칙대로, **결정 전에 recall로 기존 맥락을 먼저 조회**하고, 결정 후에는 **반드시 기록**한다.

## 빠른 시작

```bash
# 0. vault 초기화 (멱등). observation 폴더 포함.
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" init

# 1. 취지 기록 (record, 백링크 대상)
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture intent \
  --title "가입 전환 속도" \
  --summary "가입 퍼널의 마찰을 최소화해 전환율을 높인다." \
  --tags growth,conversion

# 2. 결정 기록 (이긴 취지 + 반려 대안 + 작업 ID 링크)
# --intents 값은 slug 단편(친숙 참조)도 가능 — capture가 basename으로 자동 해소
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture decision \
  --title "인증을 BFF 구조로 전환" \
  --summary "세션 토큰을 BFF에서 관리한다." \
  --tags auth,architecture \
  --intents 가입-전환-속도 \
  --tasks owner/repo#18

# 3. observation (분류 전 발견, 후속 TRI/DEC로 승격될 수 있음)
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture observation \
  --title "webhook 처리 타임아웃 리스크" \
  --summary "외부 webhook이 30초 이상 지연될 가능성 발견. 현재 차단되지 않음." \
  --tags webhook,reliability \
  --ssot webhook-architecture \
  --affects-paths "src/webhook/**" \
  --tasks owner/repo#42

# 4. 회수 (3-stage + batch read)
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall "auth" --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall "auth" --stage 2 --section 취지
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall --backlinks-of INT-2026-04-17-143052-가입-전환-속도 --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall --read DEC-2026-04-17-143052-인증을-bff-구조로-전환,INT-2026-04-17-143052-가입-전환-속도

# 5. 폐기/대체
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" retire DEC-... --type superseded --superseded-by DEC-new
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" retire DEC-... --type deprecated

# 6. 무결성 점검 (기본 리포트 only; --fix는 화이트리스트만)
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --strict --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --check changed-path-stale --changed-path "src/auth/x.ts,src/payment/y.ts"
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --fix index,retired-in-index
```

## 타입 결정 가이드

| 사용자 발화 패턴 | 타입 | 이유 |
|---|---|---|
| "상황이 바뀌어도 유지돼야 하는 원칙" | `intent` | 그래프의 뿌리. 결정·반려가 이 취지를 가리킨다. |
| "이렇게 결정함 / 골랐음 / 채택함" | `decision` | 이긴 취지·트레이드오프·재평가 조건 보유 |
| "이 대안은 안 됨 / 거부함" | `rejected_decision` | 진 취지 보유 — 나중에 재고할 수 있게 |
| "이 함정 / 안티패턴 / 다음엔 피하자 / 교훈" | `trial_error` | 교훈·피해야 할 것 (교훈이 명확해야 함) |
| "발견했는데 분류·결정·갱신 어디로 갈지 아직 모름" | `observation` | 분류 전 임시 record. 후속 TRI/DEC/SSOT 갱신으로 승격(supersede)되며 정리 |
| "현재 어떻게 구성/동작하나" | `ssot` | living, 제자리 갱신 |
| "이건 어떻게 운영/배포하나" | `runbook` | living, 절차 |

**Living vs Record 구분**: ssot/runbook은 **주제 단위로 제자리 갱신**되는 living. 한 번 생성된 후에는 새로 만들지 않고 기존 문서를 수정한다 — 두 번째 capture는 exit 5(conflict)로 거부된다. context/* (intent/decision/rejected_decision/trial_error/observation)는 **불변 + supersede** 모델 — 변경하지 않고 새 record로 대체한다.

**observation vs trial_error**: trial_error는 *교훈이 명확*한 함정이고, observation은 *아직 교훈·결정으로 분류하기 이른* 발견이다. 분류가 정해지면 observation을 retire하면서 새 TRI/DEC를 successor로 둔다.

## 워크플로 (결정·취지·관찰을 만났을 때)

1. **recall로 맥락 조회** — "이 주제 관련 기존 결정·취지·반려·시행착오·관찰이 있나?" 무조건 먼저 본다.
   ```bash
   recall "<주제>" --json     # Stage 1: frontmatter 요약(+search_terms)만, ~2KB 가드
   ```
2. **capture로 스켈레톤 생성** — 적절한 타입 선택 후 `--title --summary --tags` 필수, 관계는 §11.3에 맞게.
3. **에이전트가 §8 고정 섹션 본문을 채움** — 사용자가 말한 내용을 본문에 풀어 쓴다. **섹션 헤더를 추가/삭제/이름 변경하지 않는다 (recall Stage 2가 이 고정성에 의존)**.
4. **필요시 supersede 처리** — 기존 record를 대체하면 `--supersedes <old>` 또는 별도 `retire ... --type superseded --superseded-by ...`. successor는 active context/* record여야 한다.
5. **주기적 refresh** — 큰 변경 후, 또는 점검 요청 시 무결성 리포트. CI에서는 `--check changed-path-stale`를 git diff와 같이.

## CLI 계약 (요약)

| sub | 필수 인자 | 주요 옵션 | 종료 코드 |
|---|---|---|---|
| `init` | — | `--dry-run` | 0 ok, 1 FS 오류 |
| `capture` | `<type>` `--title` `--summary` `--tags` | `--slug` `--intents` `--ssot` `--runbook` `--rejected` `--decisions` `--tasks` `--supersedes` `--verified-at` `--audience` `--affects-paths` `--search-terms` `--dry-run` | 0 ok / 2 인자·허브에 관계·living 슈퍼세이드·verified_at/affects_paths 적용 외 타입·observation에 intent 관계·successor가 record 아님 / 3 vault 없음 / 4 참조 모호·부재·task 형식 / 5 living 충돌(전역) |
| `retire` | `<basename>` `--type deprecated\|superseded` | `--superseded-by <ref>` (superseded 필수, **active context/\* record여야 함**), `--dry-run` | 0 ok / 2 인자·successor가 record 아님 / 3 / 4 |
| `recall` | (없음, 또는 `<query>`) | `--type` `--tag` (반복) `--section` `--stage` `--limit` `--backlinks-of` `--read <a,b,c>` `--include-retired` | 0 항상 (0건도 성공), 4 --read 대상 부재 |
| `refresh` | — | `--check <name,..>` (13종 + all) `--days N` `--path <sub>` `--changed-path <p,..>` `--fix index,retired-in-index` `--strict` | 0 / 2 (--check unknown·--fix 화이트리스트 위반·bare --fix) / 6 (strict + 이슈≥1) |

공통: `--vault <path>` (기본 `./wiki`), `--json` (기계용 출력). JSON 성공: `{"ok": true, ...}`. 실패: `{"ok": false, "error_code": "...", "message": "..."}`. `refresh`는 항상 `{"issues": [...]}` (strict-fail 시도). `--fix` 사용 시 `{"issues": [...], "fixed": [...]}`.

### 친숙 참조 해소 (§11.1)

`capture`의 관계 인자에는 (a) 전체 basename (`DEC-2026-04-17-143052-switch-to-bff`) 또는 (b) slug 단편 (`switch-to-bff`)을 줄 수 있다. CLI가 자동으로 정규 basename으로 해소해 저장한다. 모호하면 exit 4. **저장은 항상 전체 basename**.

`--tasks`는 외부 작업 시스템 참조라 형식만 검사한다(`owner/repo#N`). 위키 파일 존재 검사 안 함.

### refresh 검사 13종 (§13.5)

| 검사 | 대상 | 의미 |
|------|------|------|
| `stale` | living + verified_at 있는 trial_error | verified_at > N일 (기본 90). observation·intent·decision·rejected 미적용 |
| `supersede` | 전체 | supersede 쌍 양방향 일관성 |
| `broken-rel` | 전체 (tasks 제외) | relations 값이 실 위키 파일 |
| `task-ref` | tasks | `owner/repo#N` 형식 |
| `orphan` | active record | 어디서도 안 가리켜짐 |
| `index` | 인덱스 파일 | 파생 결과와 차집합 |
| `retired-in-index` | 인덱스 파일 | retired/ 문서가 인덱스에 잔존 |
| `active-ref-retired` | active 문서 | retired/ 가리키는 냄새 |
| `tags` | 어휘 보유 시 | 어휘 밖 태그 (`ssot/tag-vocabulary.md` 없으면 skip) |
| `changed-path-stale` | living + trial_error + observation | `affects_paths` glob이 `--changed-path` 또는 git diff에 매칭이고 `verified_at` 미갱신 |
| `duplicate-basename` | vault 전역 .md | basename 전역 유일성 |
| `empty-lesson` | trial_error | `## 교훈` 비었거나 placeholder |
| `schema` | 전체 | 필수 필드(title/created_at/summary/tags) 누락, frontmatter 자체 누락, placeholder 값(`<...>`), 잘못된 날짜(`created_at`/`verified_at`/`retired_at`은 실제 ISO 날짜), 금지 필드(id/status/classified_as), living에 relations, lifecycle을 relations 안에 둠, 타입별 허용 외 relation sub-key, 관계 대상 타입 불일치(broken-rel은 인덱스 파일 가리킴도 자동 감지), verified_at/affects_paths 적용 외 타입 |

알 수 없는 check 이름 또는 빈 `--check ""`는 **exit 2**로 거부된다(CI에서 오타 즉시 감지).

### slug 입력 팁

- 자동: `--title`에서 NFC 정규화 후 kebab-case로 파생.
- 직접 입력: `--slug` 값은 `slugify(s) == s` 검증을 통과해야 함 (Unicode alnum + `-`만, leading/trailing/연속 `-` 금지, `.` 금지).
- leading hyphen이 들어가는 slug는 argparse가 옵션처럼 해석할 수 있으므로 **`--slug=<value>` 형태 권장** (`--slug=-leading` 같은 케이스는 어차피 sanitize에서 거부됨).
- 한국어/CJK는 NFC로 자동 정규화되어 macOS NFD vs 다른 OS NFC 차이로 인한 resolver 깨짐을 방지한다.

### refresh --fix 화이트리스트 (§13.5)

- 허용: `--fix index`, `--fix retired-in-index`, 콤마 조합. **bare `--fix` → exit 2**.
- 그 외 인자(예: `--fix broken-rel`, `--fix stale`) → **exit 2** (의미 판단이 필요한 수정은 사람·에이전트가 capture·Edit으로 명시 처리).
- 실행 시 stdout/JSON에 `fixed` 배열로 변경 내역 보고 (silent 변경 금지).

## 권장 패턴

- **결정 직후 trial_error**: 결정을 내린 시점에 발견한 함정·우회는 즉시 `capture trial_error --decisions <DEC-...>`로 같이 남겨라.
- **분류 전 발견은 observation으로**: 결정으로 만들 정도는 아니나 추적해야 하는 발견은 `capture observation --ssot <ssot> --affects-paths "src/<area>/**"`. 분류가 정해지면 후속 TRI/DEC를 capture하면서 OBS를 `--superseded-by`로 retire.
- **취지의 승/패 추적**: 한 intent에 `recall --backlinks-of <INT-...>`을 걸면 decisions(이긴 자리) + rejected_decisions(진 자리)가 함께 나온다.
- **supersede 직후 refresh**: 양방향 일관성 점검을 위해 한 번 돌려보면 안전하다.
- **태그 어휘 관리**: `wiki/ssot/tag-vocabulary.md`에 `## 어휘` 섹션으로 허용 태그를 나열하면, refresh의 `tags` 검사가 자동으로 어휘 밖 태그를 플래그한다. 어휘 파일이 없으면 검사 스킵.
- **재검증 (verified_at)**: ssot/runbook은 `--verified-at YYYY-MM-DD`로 마지막 확인 일자를 남겨라. `refresh --check stale --days 90`이 90일 이상 미검증 항목을 리포트.
- **코드 변경에 따른 문서 drift 감지**: ssot/runbook/trial_error/observation에 `--affects-paths "src/<area>/**"`를 박아두고, PR diff 또는 `git diff --name-only HEAD` 결과를 `refresh --check changed-path-stale --changed-path <list>`로 흘려보내면, 코드 변경 영향 문서가 자동으로 플래그된다.
- **배치 read**: 묶음으로 읽어야 할 record가 명확하면 `recall --read a,b,c`로 순서 보존 batch (개별 호출보다 압축적).

## 4계층 분리 (§15)

본 플러그인은 **mechanism** 계층이다 — agent-neutral. agent별 운영 규약(언제 누가 무엇을 capture할지, GitHub Issue 흐름 등)은 프로젝트 정본 `wiki/ssot/agent-operating-model.md`(policy)에 둔다. 짧은 정책 포인터는 프로젝트 루트 `CLAUDE.md`/`AGENTS.md`(agent entry)에. 실제 축적 내용은 `wiki/`(knowledge).

## 참조

- `references/frontmatter-schema.md` — 타입별 필수/선택 frontmatter 키
- `references/section-schema.md` — 타입별 §8 고정 섹션의 작성 의도
- `references/claude-md-snippet.md` — 프로젝트 CLAUDE.md에 붙일 권장 스니펫
- `../../rules/knowledge-protocol.md` — 메커니즘 계층 (플러그인과 함께 이동)
- `../../templates/` — 타입별 본문 placeholder (인간 참조용)

## 출력 해석 팁

- `--json` 출력은 `json.loads`로 안전하게 파싱 가능. 다른 스킬·체인이 결과를 소비할 때 권장.
- 사람용 출력은 한국어 텍스트(기본). 사용자에게 보여줄 때 유용.
- `recall --json`의 Stage 1 결과가 `truncated: true`면 hint 메시지를 그대로 사용자에 전달하고 `--type/--tag`로 좁히도록 안내하라.
- `refresh`의 issue 배열은 각 항목이 `{check, path, field?, target?, message}`. `check` 코드별로 그룹화해 사용자에 보고하라.
- `recall --read a,b,c` JSON 응답의 `results`는 입력 순서를 보존한다.
