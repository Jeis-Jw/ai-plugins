---
name: verify
description: Issue 또는 task-worker DefinitionArtifact node의 완료 조건을 검증하고 구조화된 evidence를 기록한다. Issue 번호는 코멘트 경로, --artifact/--run-state는 local evidence facade다. "task-github:verify", "검증해줘", "완료 조건 확인해줘" 등의 요청에 실행하라.
---

# verify — 검증 리포트 생성

**검증 실행이 아니라 "구조화된 검증 결과 문서의 생성"이 본질.** plan이 계약서면 verify는 이행 증명서.

## 입력

```
$ARGUMENTS: {N} | --artifact {PATH} --run-state {RUN_JSON}
```

## 절차

### local DefinitionArtifact facade

`--artifact/--run-state`가 있으면 `recover.next_event == verify`를 확인하고 artifact node의 완료/검증 조건을 대조한다. 구조화한 결과를 run-state evidence로 기록하며 GitHub dependency 조회와 Issue comment는 하지 않는다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" recover \
  --artifact {PATH} --run-state {RUN_JSON}
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" local-event \
  --artifact {PATH} --run-state {RUN_JSON} --event verify --evidence '{검증 결과 JSON object}'
```

위키 integrity/drift와 Knowledge Capture Audit는 동일하게 적용하되 기록 대상은 위키와 run-state뿐이다. 아래 `{N}` 절차는 변경 없는 legacy/projected Issue 경로다.

### Step 1. plan의 검증 체크리스트 추출
- 세션 컨텍스트 우선, 끊겼으면 `gh issue view {N} --comments`
- "작업 계획" 코멘트의 **검증 체크리스트** 항목 추출 (즉석 기준 생성 금지)
- 체크리스트 없으면 plan 미수행 → `[중단]` 보고

### Step 2. 완료 조건 대조 (실질/형식 2분류)
- **충족**: 근거(파일 경로·커밋 해시·동작) 명시
- **실질(MUST) 미충족**: 보완 방법 파악 → `run` 복귀 → CHANGES_REQUESTED
- **형식(SHOULD) 미충족**: "제안"으로만, 판정 영향 없음

required check의 physical command는 task-github 내부에서 직접 허용 여부를 판단하지 않는다. `task_worker_bridge.py execution-claim`으로 command profile·impact rule·QA mode·duplicate/run-cap을 atomic claim하고, 실행 뒤 `execution-complete`/`execution-project`가 반환한 immutable receipt/evidence id+digest만 Issue comment와 orchestration ledger에 투영한다. `reuse-evidence`는 기존 ref를 사용하고, machine-readable STOP은 legacy 검증 경로로 fallback하지 않는다. merge로 새 integration head가 생긴 root gate는 leaf receipt가 있어도 `integration-full` purpose로 별도 수행한다.

> **빌드 통과 ≠ 동작.** build/lint/self-grep은 컴파일만 보증한다 — 런타임 크래시(예: SDK가 특정 env에서 throw)나 렌더 오류는 "빌드 성공, 화면 블랙"으로 구조적으로 빠져나간다. UI/앱형 유닛은 **런타임 증거**를 실질 조건으로 요구한다: 헤드리스 렌더 + 콘솔 에러 스캔, HTTP 200/응답 형태, 또는 최소 프리뷰 스모크. 이런 유닛은 `required_checks`(Execution Contract)에 런타임 스모크를 1개 포함해 verify 게이트가 build-only로 통과하지 않게 한다.

dependency 상태도 실질 조건으로 기록한다. 열린 `blocked_by`가 있으면 프로토콜 위반이므로 통과 판정을 내리지 않는다:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
API_VERSION="2026-03-10"
OPEN_BLOCKERS=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocked_by" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')
```
dependency API 조회가 실패하면 "확인 불가"로 기록하고 사령관 확인 없이는 `done`으로 넘기지 않는다.

### Step 3. (복잡 PR) pr-verifier 서브에이전트로 독립 검증

### Step 4. 지식 기록 검토 (위키 가용 시)
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
Issue 코멘트에서 태그 탐색 → 위키 타입으로 캡처 **제안 후 확인** (타입·관계는 [wiki-bridge.md](../../rules/wiki-bridge.md) §3). 아래 캡처(개념)는 관계 인자만 보여준다 — **실제 호출 시 `--title`/`--summary`/`--tags`를 반드시 채운다**(없으면 exit 2):

| 태그 | 위키 타입 | 캡처(개념, 필수 인자 생략) |
|------|----------|-----------|
| `[결정]` | `decision` | `wiki capture decision … --intents {INT} --tasks owner/repo#{루트이슈}` |
| plan의 "고려한 대안" | `rejected_decision` | `wiki capture rejected_decision … --intents {동일 INT}` (※ rejected는 `--tasks` 금지) |
| `[시행착오]` | `trial_error` | `wiki capture trial_error … --decisions {DEC} --tasks owner/repo#{루트이슈}` |
| `[관찰]` (run이 미캡처분) | `observation` | `wiki capture observation … --tasks owner/repo#{루트이슈} --affects-paths "..."` |
| `[사실]`(현재상태) | `ssot` 갱신 | 기존 ssot 제자리 갱신(+`verified_at`) 또는 신규 |

> `…`는 `--title "..." --summary "..." --tags ...`(필수 3종)를 줄인 표기. **`--tasks`는 업무의 루트 이슈 번호.** 캡처 전 [wiki-bridge.md](../../rules/wiki-bridge.md) §4 공통 스니펫 (a)로 `$ROOT`를 확보한다:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-{N}}   # 이후 --tasks "$OWNER/$REPO#$ROOT"
```

추가:
- **`[관찰]` 처리 — 중복 방지**: run이 작업 중 이미 자동 캡처한 observation은 **다시 만들지 않는다.** 위 표의 `[관찰]` 행은 run이 놓쳐 코멘트 태그로만 남은 관찰을 verify가 보강 캡처할 때만 적용한다.
- **observation 승격 검토**: 기존 observation(run/verify가 만든 것) 중 분류가 확정된 것 → 후속 trial_error/decision 캡처(`--supersedes {OBS}`)로 승격 **제안**.
- **major면 ADR 초안 confirm** (done 후 `capture decision`으로 승격).
- **무결성 hard gate** ([quality-gates.md](../../rules/quality-gates.md) G1) — integrity 등급만 차단:
```bash
STRICT=$(wiki refresh --level integrity --strict --json) || {
  printf '%s\n' "$STRICT"
  exit 1
}
```
`refresh --level integrity --strict`가 비0 종료하거나 `issues`가 있으면 검증 판정은 `CHANGES_REQUESTED`다. 이 경우 `done`으로 넘기지 않고, 이슈 목록과 보완 방법을 검증 리포트에 기록한다.
- **hygiene 경고 surface**(비차단): `HYG=$(wiki refresh --level hygiene --json)` 의 `issues`(orphan/stale/tags 등)는 검증 리포트에 경고로만 적고 판정에는 영향 주지 않는다(사령관이 청소 시점 판단).
- **품질 flag** ([quality-gates.md](../../rules/quality-gates.md) G2/G3):
```bash
QUALITY=$(wiki refresh --check decision-quality,task-quality --json)
```
`decision-quality`/`task-quality`는 v0에서 block이 아니라 `FLAG-to-human`이다. flag가 있으면 Knowledge Capture Audit에 `proposed`로 남기고, confirm 전에 보완하거나 의도적 예외인지 사령관에게 묻는다.
- 미가용 → Issue 코멘트 기록만 유지.

이 단계는 [knowledge-capture.md](../../rules/knowledge-capture.md)의 Knowledge Capture Audit다. 후보가 없더라도 `none`과 이유를 검증 리포트에 기록한다. 후보가 있으면 `recorded` 또는 `proposed`로 남기며, 1급 노드는 사령관 확인 없이 캡처하지 않는다.

### Step 5. 검증 리포트 기록 (고정 형식)
```bash
gh issue comment {N} --body "## 검증 결과

### 완료 조건 (실질)
| # | 조건 | 판정 | 근거 |
|---|------|------|------|
| 1 | ... | ✅ 충족 | {커밋/파일} |
| D | 열린 dependency blocker 없음 | ... | {blocked_by 조회 결과} |

### 제안 (형식)
- {항목} — {개선안}

### 지식 기록 검토
| 후보 | 위키 타입 | 처리 | 근거 |
|------|----------|------|------|
| [결정] | decision | proposed 또는 실행 ID | 장기 운영 규칙 변경 |

### Knowledge Capture Audit
- recorded/proposed/none: {결과와 이유}

### 판정
- 실질 미충족: N건 → 통과/CHANGES_REQUESTED

### 다음 단계
- 통과 → task-github:done {N}
- 미통과 → task-github:run {N}"
```

## 불변식
- Issue mode 산출물은 코멘트 1개, record:none mode는 run-state evidence 1개·고정 형식.
- 항목 누락 시 verify 미완료.
- **Issue comment 또는 local evidence 기록이 본질이다.**
- 1급 노드(decision/rejected/trial_error) 캡처와 승격은 **제안 후 확인**.
- `refresh --level integrity --strict`는 hard gate다(integrity 등급만 차단). hygiene 등급(orphan/stale 등)과 `decision-quality`/`task-quality`는 경고/`FLAG-to-human`이며 block 아니다.
- Knowledge Capture Audit가 없으면 verify 미완료.
