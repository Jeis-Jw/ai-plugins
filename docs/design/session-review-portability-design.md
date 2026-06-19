# 설계 — session-review 이식성 보강 (Claude Code + Codex)

- **대상 플러그인:** `plugins/session-review/` (0.1.0 → 0.2.0)
- **근거:** self-flow 도그푸드(2026-06-19)에서 서브에이전트 리뷰어가 보고한 friction 6건.
- **불변(존중):** [[DEC-2026-06-18-224414-session-review를-wiki-기능-위-리뷰-루프로-설계]] — wiki snapshot = 핸드셰이크 매체, 별도 파일포맷·디렉터리 안 만듦.

## 문제

self 플로우 도그푸드에서 드러난 마찰:

1. status block을 손으로 Read+Edit 해야 함 — CLI에 변이 커맨드 없음(`replace_status()`는 존재하나 미노출).
2. `validate-turn`은 진입 상태만 검사, 작성한 verdict의 일관성은 미검증.
3. 스냅샷 연산이 wiki-markdown `wiki_cli.py`에 하드 의존 — session-review만 설치된 워크스페이스에선 동작 불가.
4. SKILL.md가 `plugins/session-review/...`, `plugins/wiki-markdown/...` 모노레포 상대경로 하드코딩 — 설치형 플러그인에서 깨짐. **Claude Code 전용 `${CLAUDE_PLUGIN_ROOT}`에만 의존하면 Codex에서 깨짐.**
5. `validate-turn`이 load JSON에서 추출한 fs 경로를 요구 — slug→path 수동 배선.
6. severity(blocking/non-blocking/nit)가 자유문장으로만 존재 — "blocking 0 ⇒ approved"가 기계 검증 불가.

## 아키텍처

**`session_review.py` = 완전한 facade + 자기위치 기반. 스킬은 오직 이것만 호출.** wiki_cli는 선택적 백엔드.

```
SKILL.md → session_review.py <cmd> --slug ...   (하니스가 알려준 base-dir서 경로 해석)
                 │
       snapshot backend (hybrid)
       ├─ wiki_cli 발견 → 위임 (DEC-2026-06-18 유지)
       └─ 없음 → 내장 writer (동일 frontmatter+섹션 포맷·동일 위치, bespoke 아님)
```

## 컴포넌트

### 1. 경로 해석 — 하니스 무관 (#4)
- **원칙:** `session_review.py`가 `Path(__file__)`로 자신·플러그인 루트·형제 플러그인·vault를 자력 해석. 하니스 env는 편의일 뿐, 의존 아님.
- **유일한 하니스 의존 = 스크립트 호출 경로 한 토큰.** 두 하니스 모두 스킬 로드 시 위치를 모델에 알림. SKILL.md 지시: "이 플러그인의 `scripts/session_review.py` 실행 — Claude Code면 `$CLAUDE_PLUGIN_ROOT/scripts/session_review.py`, 아니면 이 스킬 디렉터리 상위(플러그인 루트)에서 해석. 명시 override는 env `SESSION_REVIEW_CLI`."

### 2. 백엔드 해석기 — 하이브리드 (#3)
- `resolve_wiki_cli()`: env `SESSION_REVIEW_WIKI_CLI` → `__file__` 기준 형제 탐색(`../../wiki-markdown/skills/wiki/scripts/wiki_cli.py` 및 설치형 형제 플러그인 후보) → PATH → `None`. **CLAUDE_PLUGIN_ROOT 안 씀.**
- 백엔드 인터페이스: `snapshot_save/load/discard`.
  - wiki_cli 발견 → 위임(현 동작 보존, DEC 존중).
  - 없음 → 내장 최소 reader/writer가 `<vault>/snapshot/SNAP-<slug>.md`에 **동일 frontmatter+섹션** 기록. 별도 포맷 안 만듦 → DEC 합치.
- vault 위치: env `WIKI_VAULT` → cwd `./wiki` (wiki_cli 기본과 동일).

### 3. facade 서브커맨드 (#4·#5)
- `snapshot-save --slug --title --summary --tags [--discussion ... --merge ...]` → 백엔드 위임.
- `snapshot-load --slug [--json]` → 백엔드. path+text 반환.
- `snapshot-discard --slug`.
- 전부 `--slug`로 경로 내부 해석(#5 해결).

### 4. set-status (#1)
- `set-status --slug --status-json '{...}'` → 백엔드 load → `replace_status`(이미 존재) → 백엔드 save.
- 쓰기 시 일관성 검증(아래 #5 규칙) 위반이면 거부.

### 5. validate-status + severity ledger (#2·#6)
- status block에 선택 필드 `blocking_count: int` 추가.
- `validate-status --slug`: block 형식 + `PHASE_OWNER` 일관성(phase↔next_actor) + **`phase=approved ⇒ blocking_count==0`** 강제. approved 결정이 기계 검증됨.
- `set-status`도 동일 규칙으로 쓰기 거부.

### 6. SKILL.md ×4 재작성
- `plugins/...` 하드코딩 + wiki_cli 직접호출 제거.
- 새 facade 서브커맨드 + 하니스 무관 호출 규약으로 절차 기술.

### 7. 문서 + DEC
- README/plugin.json(×2): wiki-markdown = 권장 동반(스냅샷 백엔드), 내장 fallback 존재, `SESSION_REVIEW_WIKI_CLI`/`SESSION_REVIEW_CLI` override 명문화.
- DEC 갱신: 하이브리드 백엔드(DEC-2026-06-18 재평가조건 self-mode 항목 건드림) 기록. 사용자 확인됨.

## 테스트

- 백엔드 해석기: `SESSION_REVIEW_WIKI_CLI` override / 형제 탐색 / 미발견 fallback.
- 내장 snapshot: save→load→discard round-trip, `--merge` 부분 갱신, 동일 포맷.
- facade 패리티: wiki_cli 경로와 내장 경로가 동일 파일 산출.
- `set-status`: block 변이 정확, 불일치(approved+blocking_count>0) 거부.
- `validate-status`: 정상/불일치 케이스.
- 경로 스모크: cwd·하니스 무관하게 `session_review.py`가 self-locate.

## 시퀀싱 (단위 분해)

1. 백엔드 추상화 + 내장 snapshot (core).
2. facade 서브커맨드(snapshot-save/load/discard).
3. set-status + validate-status + blocking_count.
4. SKILL.md ×4 재작성 (하니스 무관 + facade).
5. README/plugin.json + DEC. 버전 0.1.0 → 0.2.0.

## 완료 기준

- 각 단위 구현 + 테스트 + 기존 session-review 테스트 통과.
- Claude Code·Codex 양쪽 경로 해석 동작(self-locate 스모크).
- wiki-markdown 유/무 양쪽에서 핸드셰이크 동작(하이브리드).
- 구현 후 session-review **self 플로우**로 리뷰 → approved → 완료.
