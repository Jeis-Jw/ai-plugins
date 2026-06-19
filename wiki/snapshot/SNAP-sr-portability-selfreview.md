---
title: session-review(self): portability v0.2.0
created_at: 2026-06-19
summary: Self-flow review of session-review portability hardening.
tags: [session-review, review, dogfood]
type: snapshot
updated_at: 2026-06-19
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "diff"
target_ref: "task/session-review-portability"
base_ref: "33b5708130dc6782ce805d0a2a72e6d4e413cf7c"
responding_to: "c3c8537"
round: 3
flow_mode: "self"
review_strength: "normal"
blocking_count: 0
```

### 리뷰 피드백 (round 3)
판정: **approved** (round 3, blocking 0). round2 nit 3건 회귀 확인 — 모두 정확히 반영, 새 결함 없음. 20개 테스트 통과(round2 17 → +3). 수정 커밋 c3c8537은 정확히 3파일(session_review.py·review/SKILL.md·tests)만 건드려 나머지 SKILL 3종은 무영향.

### nit #1 회귀 OK — `snapshot-save --merge` 인자 백필
`cmd_snapshot_save`가 title/summary/tags 누락 시 `_split_frontmatter`+`_fm_scalar`로 기존 스냅샷에서 백필. 라이브 검증:
- merge로 셋 다 생략 + `--decided`만 → 원본 `Original Title`/`orig summary`/`[alpha, beta]` 보존, 기존 discussion 유지, 새 섹션 추가. (exit 0)
- 부분 override(`--tags`만 변경) → title/summary 유지, tags만 교체. `title or _fm_scalar`·`tags if tags is not None` 분기가 필드별 누락을 정확히 처리.
- 신규 스냅샷 + 필드 없음 + merge 아님 → `--title/--summary/--tags are required for a new snapshot` exit 2.
- merge + 없는 스냅샷 → `snapshot_load`가 `StatusError`(exit 2). 두 테스트(`test_merge_reuses_existing_frontmatter_when_omitted`, `test_merge_on_missing_snapshot_without_fields_errors`) 의도와 라이브 일치.

### nit #3(코드) 회귀 OK — `render --fenced`
`cmd_render`가 `--fenced` 시 `\`\`\`yaml\n<body>\n\`\`\``로 감싼다(`body.rstrip("\n")`로 펜스 직전 빈 줄 없음, 단일 trailing newline). 라이브: 첫 줄 `\`\`\`yaml`, 끝 줄 `\`\`\``, 내부는 표준 status block(스칼라 인용·round 정수·null lock). `--fenced` 없으면 기존 `end=""` 무변경. `test_render_fenced_wraps_in_yaml_fence` 라이브 일치.

### nit #2(문서) 회귀 OK — review/SKILL.md 하위헤딩 + 내부 정합
피드백을 `### 리뷰 피드백 (round N)` 하위 헤딩으로 옮겨 `## 현재 논의` 안에 머물게 한 것이 **기능적으로 정확**. 근거를 라이브로 입증: `_parse_snapshot_sections`가 `## ` 라인만 섹션 경계로 인식하므로 — 구방식(discussion 값에 sibling `## 리뷰 피드백`)은 다음 merge 라운드에서 그 헤딩 이후 본문이 미인식 섹션으로 **소실**(라이브 재현: feedback survived=False). 신방식(`###`)은 round-trip 생존 확인. 문서가 제시하는 명령(`render --fenced` → `snapshot-save --merge` 백필 → `validate-status`)을 현 facade에 대해 그대로 실행 → 전부 정상 동작(approved/0 통과, approved/blocking>0은 `phase 'approved' requires blocking_count == 0` exit 2로 거부). 문서-코드 정합 OK.

### 잔여(비차단, 회귀 아님)
- `request-review/SKILL.md:72`는 여전히 수동 `printf '\`\`\`yaml...'`로 status를 펜스 — review는 `--fenced`로 통일됨. 둘 다 유효한 펜스 블록을 산출해 `validate-status` 통과하므로 무해. 추후 `--fenced`로 일원화 가능(이번 3건 범위 밖, 사전존재 nit). (nit)
- round1 nit 2건(built-in snapshot 인덱스 미갱신·merge NFC 생략) 유지 — 워크스페이스당 백엔드 고정이라 실害 낮음. (nit)

코어·이식성·하위호환은 round2에서 이미 승인됨. round3 3건 모두 정확·회귀 0 → approve. 다음: worker가 완료 절차 진행.

## 리뷰 피드백
판정: **approved** (round 2, blocking 0). round1 blocking 2건 모두 실효 해소 확인. 새 회귀 없음. 17개 테스트 통과(round1 16 -> +1).

### blocking #1 해소 — `snapshot-load --json` 수용
라이브 검증: `python3 "$SR" snapshot-load --slug X --json` -> exit 0, `--json` 없이도 exit 0(하위호환 유지). 파서에 `--json`이 `action="store_true"`(help: "accepted for parity; output is always JSON")로 등록 — 출력은 본래부터 JSON이라 무동작 no-op이 맞다. 신규 회귀테스트 `test_snapshot_load_accepts_json_flag`가 SKILL/wiki_cli 머슬메모리(`--json`)를 가드. SKILL x3(review:26, address-feedback:23, complete:23)의 1단계 명령이 이제 정상 실행된다.

### blocking #2 해소 — `SESSION_REVIEW_CLI` 와이어링
SKILL x4(review:17, request-review:16, address-feedback:14, complete:14) 전부 프리앰블이 `SR="${SESSION_REVIEW_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/session_review.py}"`로 통일 — 셸 레이어에서 env를 실제 소비한다. SR은 "스크립트를 어디서 부를지"를 정하는 로케이터 knob이므로 셸 프리앰블이 정확한 소비 지점이다(스크립트 내부가 아님). 비-Claude escape hatch가 이제 실동작.

### 회귀 재확인(모두 통과)
- 하니스 무관 resolver: session_review.py에 `CLAUDE_PLUGIN_ROOT` 부재 유지. 스크립트가 읽는 env는 `SESSION_REVIEW_WIKI_CLI`(wiki_cli 위치 knob)뿐 — 의도대로.
- 포맷 동치(DEC-2026-06-18): `test_builtin_file_is_readable_by_wiki_cli` 존속·통과. built-in writer 산출물을 실제 wiki_cli가 로드 가능.
- cwd 무관: `test_self_locates_regardless_of_cwd` 존속·통과.
- 핸드오프 facade(snapshot-load/save/render/validate-status/validate-turn) 라이브 정상.

### 잔여(round1 nit 유지, 비차단)
- built-in `snapshot_save/discard`가 `wiki/snapshot/snapshot.md` 인덱스를 미갱신(백엔드 혼용 시 이론적 어긋남). 워크스페이스당 백엔드 고정이라 실해 낮음. (nit)
- built-in merge가 NFC 정규화(`_nfc`) 생략(동일 세션 백엔드 고정이라 비실질적). (nit)

코어·이식성·하위호환·DEC 합치 모두 견고. round1 차단 2건 실효 해소, 회귀 0. -> approve. 다음: worker가 완료 절차 진행.

## 리뷰 피드백
판정: **changes-requested** (blocking 2). 코어(facade·하이브리드 백엔드·하니스 무관 resolver·DEC-2026-06-18 동일 포맷)는 견고. 16개 테스트 통과, `test_builtin_file_is_readable_by_wiki_cli`가 포맷 동치를, `test_self_locates_regardless_of_cwd`가 cwd 무관 resolver를, 코드에 `CLAUDE_PLUGIN_ROOT` 부재가 이식성을 입증. built-in writer의 frontmatter 필드/순서·body 7섹션 렌더·경로(`vault/snapshot/SNAP-<slug>.md`)가 wiki_cli와 정확히 일치 → DEC 합치 OK.

그러나 v0.2.0 스코프에 포함된 SKILL.md ×4 재작성에 **문서-코드 불일치 2건**이 있어, 스킬을 곧이곧대로 따르는 에이전트(Claude Code·Codex 양쪽)가 1단계에서 실패한다.

### blocking #1 — `snapshot-load --json`는 존재하지 않는 플래그
review/SKILL.md:26, address-feedback/SKILL.md:22, complete/SKILL.md:22 (request-review 제외 3종) 모두 첫 명령으로
`python3 "$SR" snapshot-load --slug <snapshot> --json` 을 제시한다. 그러나 facade의 `snapshot-load`는 `--json`을
받지 않고 exit 2(`unrecognized arguments: --json`)로 죽는다. 게다가 `snapshot-load`는 이미 기본으로 JSON을 출력하므로
플래그 자체가 불필요. → 3개 파일에서 `--json` 제거.

### blocking #2 — `SESSION_REVIEW_CLI` override는 코드에 없는 env
4개 SKILL.md(review:19, request-review:18, address-feedback:16, complete:16) 모두 "비 Claude 하니스에서
`SESSION_REVIEW_CLI`로 SR 위치를 지정 가능"이라 안내하지만, session_review.py에는 이 변수를 읽는 코드가 전혀 없다
(`grep` 결과 스크립트 0건). 스크립트가 보는 env는 `SESSION_REVIEW_WIKI_CLI`(이건 SR이 아니라 wiki_cli 위치 knob)뿐.
이 변경의 헤드라인이 "Codex 이식성"인데, 정작 비-Claude escape hatch가 문서상 존재하나 무동작 → 사용자가 의존하면 조용히 무시됨.
→ resolver에 `SESSION_REVIEW_CLI` 지원을 추가하거나(스킬은 절대경로 fallback이 있으니 선택), 4개 SKILL.md에서 해당 문구 제거.

### non-blocking / nit
- built-in `snapshot_save/discard`는 wiki_cli가 유지하는 `wiki/snapshot/snapshot.md` 인덱스를 갱신하지 않는다.
  built-in 단독 워크스페이스에선 인덱스를 읽는 주체가 없어 무해하나, 백엔드 혼용(wiki로 저장→built-in으로 discard) 시
  인덱스가 어긋난다. 워크스페이스당 백엔드는 안정적이라 실害 낮음. (nit)
- built-in merge는 wiki_cli의 NFC 정규화(`_nfc`)를 생략. 한글 round-trip에서 NFC/NFD 차이가 이론상 가능하나
  동일 세션 내 백엔드 고정이라 비실질적. (nit)

핸드오프 facade(snapshot-load/save/render/validate-status/set-status) 자체는 정상 동작 확인. 위 2건만 고치면 approve 가능.

## 리뷰 요청 (round 1, flow_mode=self)

session-review v0.2.0 이식성 보강. 대상 diff: `git diff main..HEAD` (이 task 브랜치).
새 facade(snapshot-save/load/discard, set-status, validate-status)·하이브리드 백엔드·하니스 무관 경로.

리뷰어는 정확성·하위호환·이식성(Claude+Codex)·DEC-2026-06-18 합치 관점으로 본다.

## 배경

target_mode=diff, base_ref=33b5708130dc6782ce805d0a2a72e6d4e413cf7c, review_branch=task/session-review-portability-review, flow_mode=self

## 정해진 것

round2 nit 3건 반영(코드 #1 merge 인자 옵션화·#3 render --fenced + 테스트, 문서 #2 피드백 ### 하위헤딩). round3는 이 3건 회귀 확인용.

## 아직 열린 질문



## 다음에 볼 것

fresh subagent reviewer가 snapshot-load 후 review skill 실행.

## 관련 파일/문서



## 승격 후보
