# CLAUDE.md 권장 스니펫

본 wiki 플러그인을 사용하는 프로젝트의 `CLAUDE.md`(또는 `AGENTS.md`)에 아래 섹션을 추가하면, 에이전트가 결정·취지·반려·시행착오·관찰을 만났을 때 vault를 우선 회수·기록하도록 정책이 잡힌다.

본 스니펫은 **agent entry 계층**(§15 4계층)이다 — 짧은 정책 포인터. 메커니즘(`rules/knowledge-protocol.md`)을 강제하지 않고, 운영 정책 정본은 별도 `wiki/ssot/agent-operating-model.md`(프로젝트가 작성)에 둔다. 정책은 프로젝트마다 다를 수 있으므로 필요에 맞게 편집해 사용한다.

---

## (붙여넣기 시작)

## 지식 관리: wiki 플러그인

이 프로젝트의 모든 지식(취지·결정·반려 대안·시행착오·관찰·현재 상태·운영 절차)은 `wiki/` vault에 축적·조회한다. `wiki` 플러그인이 정합성을 보장하며, AI 에이전트가 결정 직전·직후에 사용한다.

### 항상 지키는 원칙

1. **결정 전 회수**: 사용자의 결정 요청이 들어오면, 응답 *전에* `wiki:recall <주제>`로 기존 맥락(decisions/intents/rejected_decisions/trial_error/observations)을 먼저 조회한다. 과거 결정·취지를 모른 채 결론을 내지 않는다.
2. **결정 후 기록**: 사용자가 새 결정·취지·반려 대안·시행착오·관찰을 명시하면 *즉시* `wiki:capture <type>` 호출. 머릿속에만 두지 않는다.
3. **취지(intent)는 결정과 분리**: "왜 그렇게 하는가"의 원칙은 `intent`로, 그 원칙을 어떻게 다뤘는지는 `decision`(이김) / `rejected_decision`(짐)으로. 둘이 한 문서에 섞이면 트레이드오프 추적이 깨진다.
4. **분류가 아직 불명확한 발견은 observation으로**: 사용자/에이전트가 코드 작업 중 "이상한 점"·"잠재 리스크"·"나중에 더 봐야 할 패턴"을 발견했는데 즉시 결정·갱신할 수준은 아니면 `wiki:capture observation`. 후속 TRI/DEC로 승격(supersede)될 수 있다.
5. **Living vs Record 구분**: 현재 상태(ssot)·운영 절차(runbook)는 **제자리 갱신**, 결정·취지·반려·시행착오·관찰은 **불변 + supersede**. CLI가 이를 강제한다 — 적절한 타입만 고르면 됨.
6. **본문 전체를 기본으로 읽지 않기**: `wiki:recall`은 Stage 1(요약) → Stage 2(섹션) → Stage 3(전문) 계층. 토큰 효율이 설계의 우선순위다. 명시 묶음을 빠르게 읽으려면 `wiki:recall --read a,b,c`(순서 보존 batch).

### 자주 쓰는 패턴

```bash
# 새 결정을 다루기 전에
wiki:recall "<주제 키워드>" --json

# 결정 직후
wiki:capture decision --title "..." --summary "..." --tags ... --intents <취지-slug> [--rejected REJ-...] [--tasks owner/repo#N]

# 반려한 대안도 같이 (진 취지 보존)
wiki:capture rejected_decision --title "..." --summary "..." --tags ... --intents <진-취지-slug>

# 함정·시행착오 발견 시 (결정과 묶기)
wiki:capture trial_error --title "..." --summary "..." --tags ... --decisions <DEC-...>

# 분류 전 발견·관찰
wiki:capture observation --title "..." --summary "..." --tags ... --ssot <ssot-slug> --affects-paths "src/foo/**"

# 명시 묶음 batch read
wiki:recall --read DEC-...-a,INT-...-b,trial-c --json

# 큰 변경 후 또는 주기적으로
wiki:refresh --strict
# CI에서 코드 drift 감지
wiki:refresh --check changed-path-stale
# 인덱스 동기화는 안전한 자동수정
wiki:refresh --fix index
```

### 절대 하지 않는 것

- vault의 인덱스 파일(`<폴더명>.md`의 `## 노트` 섹션)을 손으로 편집하지 않는다. capture/init/refresh --fix가 자동 관리한다.
- ssot/runbook에 `relations` 키를 적지 않는다 (불변식).
- record를 직접 수정하지 않는다 — 변경이 필요하면 새 record로 supersede한다.
- 위키 문서 ID(파일 basename)를 변경하지 않는다. slug는 생성 시 정하고 영구.
- `--verified-at`를 intent/decision/rejected_decision에 주지 않는다 (CLI가 거부한다).

상세 메커니즘: `~/.claude/plugins/.../wiki/rules/knowledge-protocol.md`
운영 정책 정본: `wiki/ssot/agent-operating-model.md` (프로젝트별로 작성)

## (붙여넣기 끝)

---

## 프로젝트 튜닝 권장 항목

스니펫을 그대로 쓰지 말고 프로젝트 특성에 맞게 조정하라:

- **수집 트리거 강도**: 1인 사이드 프로젝트라면 "모든 결정"이 과할 수 있음 → 임계값 명시 ("의식적으로 결정한 것만").
- **observation 사용 기준**: 어떤 신호가 observation을 만드는지 (코드 리뷰 중·작업 마무리 직전·CI 실패 후 등) 정책 ssot로 명시.
- **태그 어휘 도입 시점**: 초기엔 어휘 없이(자유 태그) 가다가 노트가 30개 정도 모이면 `wiki/ssot/tag-vocabulary.md`를 만들어 어휘 통제 시작.
- **작업 시스템 연계**: 작업 시스템(예: GitHub Issue)을 쓰는 프로젝트는 capture 시 `--tasks owner/repo#N` 항상 첨부하도록 정책 추가.
- **refresh 주기**: CI에서 `wiki:refresh --strict` 게이트를 둘지, 사람이 가끔 수동으로 돌릴지. `--check changed-path-stale`는 PR diff와 같이 돌리면 강력.
