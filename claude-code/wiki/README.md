# wiki — AI-native Wiki Plugin (Claude Code)

1인 개발자 + AI 에이전트가 프로젝트의 **취지·결정·반려 대안·시행착오·관찰(observation)·현재 상태(SSOT)·운영 절차(Runbook)**를 결정 그래프로 축적·조회·점검하는 Claude Code 플러그인.

설계 정본: `wiki/ssot/plugin_definition_v1.md` (별도 리포지토리/디렉토리).

> **플러그인 루트는 `claude-code/wiki/`** — 본 디렉토리에 `.claude-plugin/plugin.json`이 있다. `claude-code/`(한 단계 위)를 plugin path로 지정하면 manifest를 찾지 못해 로드되지 않는다.

## 무엇인가

- **filesystem-primary, headless**: vault는 평범한 markdown + YAML frontmatter. ripgrep으로 검색, 본 CLI로 무결성 보장. Obsidian 같은 외부 도구 의존 없음.
- **결정적(deterministic) CLI**: `init`/`capture`/`retire`/`recall`/`refresh`는 종료 코드·`--json` 출력이 모두 정해져 있어 에이전트가 안정적으로 호출/해석한다.
- **토큰 효율 우선**: recall은 Stage 1(frontmatter 요약, ≤2KB) → Stage 2(고정 섹션, ≤500B/섹션) → Stage 3(전문) 계층. 명시 묶음은 `recall --read a,b,c` 배치.
- **취지/결정/반려/시행착오/관찰 분리**: 한 정보 단위 = 한 파일. 취지가 한 번 정해지면 결정이 그것을 *이기거나*, 반려 대안이 그것을 *지면서* 섬긴다. 관찰은 분류 전 임시 record로 후속 record가 supersede하며 정리된다. 백링크가 트레이드오프 승/패 기록을 이룬다.
- **agent-neutral**: 플러그인은 mechanism 계층(§15 4계층)만 제공. agent별 운영 규약은 프로젝트 정본 `wiki/ssot/agent-operating-model.md`(policy)에 둔다.

## 디렉토리 구조

```
.claude-plugin/plugin.json        ← Claude Code 매니페스트
README.md                          ← 본 문서
rules/
  knowledge-protocol.md            ← 메커니즘 계층 (플러그인과 함께 이동)
templates/
  intent.md / decision.md / rejected_decision.md
  trial_error.md / observation.md / ssot.md / runbook.md  ← 타입별 본문 placeholder
skills/
  wiki/
    SKILL.md                       ← 에이전트가 읽는 스킬 계약
    scripts/wiki_cli.py            ← stdlib-only Python CLI (코어)
    references/
      frontmatter-schema.md
      section-schema.md
      claude-md-snippet.md
tests/
  test_wiki_cli.py                 ← 단위/수용 테스트 (`python3 -m unittest tests.test_wiki_cli`의 "Ran N tests" 참조)
```

## 설치

본 플러그인은 별도 marketplace.json을 두지 않는다. 두 가지 설치 경로:

### A. jeis-plugins 마켓플레이스에 등록 (권장)

해당 마켓플레이스 리포지토리에서:

```jsonc
// .claude-plugin/marketplace.json
{
  "plugins": [
    {
      "name": "wiki",
      "source": "<path-to>/wiki-plugin/claude-code/wiki",
      "version": "0.1.7",
      "description": "AI-native wiki ..."
    }
  ]
}
```

그리고 Claude Code에서 `/plugin marketplace add jeis-plugins` (또는 이미 추가됐다면 `/plugin` 메뉴에서 `wiki` 활성화).

### B. 로컬 심볼릭 링크

```bash
ln -s /Users/<you>/.../wiki-plugin/claude-code/wiki ~/.claude/plugins/local/wiki
# Claude Code의 /plugin 메뉴에서 'wiki' 활성화
```

설치 후 `${CLAUDE_PLUGIN_ROOT}`이 본 플러그인 루트(`claude-code/wiki/`)를 가리키고, SKILL.md 내부 스크립트는 공식 `${CLAUDE_SKILL_DIR}`(=`skills/wiki/`)을 사용해 `scripts/wiki_cli.py`를 호출한다.

## 빠른 시작

```bash
# 0. vault 초기화 (현재 디렉토리 하위에 wiki/ 생성, observation 폴더 포함, 멱등)
python3 /path/to/skills/wiki/scripts/wiki_cli.py init

# 1. 취지 + 결정 + 반려 대안 흐름
python3 ... capture intent     --title "가입 전환 속도" --summary "..." --tags growth,conversion
python3 ... capture decision   --title "BFF 구조" --summary "..." --tags auth --intents 가입-전환-속도 --tasks owner/repo#18
python3 ... capture rejected_decision --title "이메일 인증" --summary "..." --tags auth --intents data-sovereignty

# 2. 분류 전 발견은 observation
python3 ... capture observation --title "webhook 타임아웃 리스크" --summary "..." --tags webhook \
    --ssot webhook-architecture --affects-paths "src/webhook/**"

# 3. 회수 (3-stage + batch read)
python3 ... recall "auth" --json
python3 ... recall --backlinks-of INT-2026-04-17-143052-가입-전환-속도 --json
python3 ... recall --read DEC-...,INT-...,OBS-...

# 4. 폐기 (대체) — successor는 active context/* record여야 함
python3 ... retire DEC-... --type superseded --superseded-by DEC-new
python3 ... retire OBS-... --type superseded --superseded-by TRI-new  # OBS 승격

# 5. 무결성 점검 (13종 검사 — schema 포함, 안전한 자동수정은 --fix index,retired-in-index)
python3 ... refresh --strict --json
python3 ... refresh --check changed-path-stale --changed-path "src/auth/x.ts"
```

(Claude Code 내부에서는 SKILL.md가 공식 `${CLAUDE_SKILL_DIR}` 변수로 스크립트 경로를 잡는다 — SKILL.md 참조.)

## 설계 철학 (요약)

1. **취지는 상수, 결정은 상황 함수** — 취지를 결정과 분리된 일급 시민으로.
2. **정보의 원자성** — 한 정보 = 한 파일. 다른 정보를 오염 안 시킴.
3. **계층적 조회로 토큰 효율** — 인덱스(요약) → 헤더(frontmatter) → 본문 순.
4. **primary = AI + filesystem + git** — 도구가 아니라 파일시스템이 정본.
5. **AI-Driven Documentation** — 사람은 결론·방향을, 에이전트는 생성·이동·인덱스·관계·검증.
6. **plugin은 agent-neutral** — agent별 규약은 policy 계층(`wiki/ssot/agent-operating-model.md`)으로 격리.
7. **ADR-compatible, not ADR-limited** — decision/rejected_decision은 ADR과 대응하되 intent/trial_error/observation까지 운영 기억으로 확장.

상세는 `wiki/ssot/plugin_definition_v1.md`.

## 4계층 분리 (§15)

| 계층 | 위치 | 담는 것 |
|------|------|---------|
| **mechanism** | 본 플러그인 (`plugin_definition_v1.md` + `rules/knowledge-protocol.md`) | 타입집합·ID포맷·스키마·관계·조회·생명주기 |
| **policy** | `wiki/ssot/agent-operating-model.md` (프로젝트별 정본) | agent 역할·이벤트 흐름·promotion triggers·capture 권한 |
| **agent entry** | 프로젝트 루트 `CLAUDE.md` / `AGENTS.md` | 정책 ssot 포인터 + 프로젝트 튜닝 |
| **knowledge** | `wiki/*` | 실제 축적 내용 |

플러그인은 CLAUDE.md를 소유하지 않는다 — 권장 스니펫은 `skills/wiki/references/claude-md-snippet.md`.

## 권장 CLAUDE.md 스니펫

`skills/wiki/references/claude-md-snippet.md`에 프로젝트 CLAUDE.md(또는 AGENTS.md)에 붙일 권장 정책 스니펫이 있다. 프로젝트 특성에 맞게 편집해 사용.

## 테스트 실행

```bash
cd <플러그인 루트>
python3 -m unittest tests.test_wiki_cli
```

stdlib-only, 외부 의존 없음. 현재 테스트 개수는 `python3 -m unittest tests.test_wiki_cli` 출력의 "Ran N tests" 참조.

## 호환성

- **Python**: 3.7+ (insertion-ordered dict 가정). 3.11에서 검증.
- **OS**: macOS / Linux. Windows는 path separator 외엔 동일 (직접 검증 안 함).
- **외부 의존**: 없음 (PyYAML 등 불요). `refresh --check changed-path-stale` 자동 모드는 `git`이 PATH에 있어야 함 (없거나 non-repo면 자동 모드 skip; `--changed-path`로 명시 입력은 항상 가능).

## 관련

- `~/.claude/plugins/cache/jeis-plugins/wiki-obsidian/` — 본 플러그인이 패턴을 *계승*한 Obsidian 의존 선행작 (이제는 분리됨).
- `codex/wiki/` (같은 리포지토리의 형제) — Codex 타겟용. 동일 설계, 동일 `wiki_cli.py` 코어 공유 가능.

## 라이선스 / 작성

작성자: Local developer (1인 풀스택 개발자 + AI agent). 설계 정본의 §1 원칙에 따라.
