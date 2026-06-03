# task-github

GitHub 기반 자율 작업 프로토콜. AI 에이전트가 작업을 점유·계획·실행·검증·완료하는 구조를 GitHub Issue/PR/Label 위에 얇게 올리고, 같은 마켓플레이스의 **`wiki-markdown` 결정 그래프와 `task` 노드로 연계**한다.

## 빠른 시작

```bash
# 1. 환경 초기화 (git + GitHub repo + 라벨)
task-github:setup

# 2. 업무 정의 (루트 이슈 + 위키 task 노드 1:1)
task-github:define

# 3. 작업 시작 (리프 점유 + 기어 판단)
task-github:start {N}

# 4. (normal/major) 계획 → 승인
task-github:plan {N}

# 5. 실행
task-github:run {N}

# 6. 검증 (지식 승격 제안)
task-github:verify {N}

# 7. 완료 (PR 생성 + 드리프트 점검)
task-github:done {N}

# 8. 리뷰 → 머지 (task 노드 done 전이)
task-github:review {PR} --auto-merge
```

## 3축 분류

- **프로파일**(환경): `solo`(기본) / `team` — `CLAUDE.md`에 명시
- **기어**(파급력): `micro` / `normal` / `major` — 영향 반경으로만 판단
- **플로우**(승인 관문): `express`(micro) / `planned`(normal/major)

## 위키 연계

`./wiki/` vault가 있으면 자동 연동(없으면 그레이스풀 스킵):
- **업무 1개 = 루트 이슈 1개 + 위키 `task` 노드 1개** (1:1 다리)
- 작업 중 `[결정]/[시행착오]/[관찰]`을 위키 결정 그래프로 승격
- `recall --backlinks-of {DEC}`로 "이 결정이 낳은 작업" 추적
- PR이 낡게 만든 위키 문서 자동 탐지(`changed-path-stale`)

연동 메커니즘은 [rules/wiki-bridge.md](rules/wiki-bridge.md), 운영 정책은 자동로드 agent-entry 파일(`CLAUDE.md` / `AGENTS.md`)에 있다. `wiki-markdown`의 `agent-policy` 스킬로 두 파일의 관리 블록을 스캐폴드할 수 있다.

## Issue dependency

하위 작업의 병렬/직렬 실행 가능성은 GitHub **Issue dependencies**가 정본이다.
- sub-issue는 업무 분해 구조만 표현한다.
- `define`은 `skills/define/scripts/create_issue_tree.py`로 루트/서브이슈/dependency를 한 spec에서 생성한다.
- `blocked_by`가 없으면 병렬 가능으로 간주한다.
- 열린 `blocked_by`가 있으면 `start`/`run`/`done`/`merge`가 차단한다.
- 이슈 완료 후에는 `blocking` downstream을 안내한다.

세부 규약은 [rules/dependencies.md](rules/dependencies.md)에 있다.

## Knowledge Capture Audit

비 trivial 작업은 끝내기 전에 위키 기록 후보를 감사한다.
- `observation`은 분류 전·저위험이면 자동 캡처한다.
- `decision`/`rejected_decision`/`trial_error`와 `ssot`/`runbook` 갱신은 제안 후 확인한다.
- 후보가 없으면 `none`과 이유를 최종 보고나 Issue 코멘트에 남긴다.

세부 규약은 [rules/knowledge-capture.md](rules/knowledge-capture.md)에 있다.

## 구성

| 구성요소 | 역할 |
|---------|------|
| `rules/task-protocol.md` | 프로파일·기어·플로우·태그·완료조건 (헌법) |
| `rules/workflow.md` | 라벨·상태전이·브랜치·커밋·PR |
| `rules/dependencies.md` | GitHub Issue dependencies 기반 선후관계·차단 |
| `rules/knowledge-capture.md` | 작업 종료 전 지식 기록 감사 |
| `rules/wiki-bridge.md` | 위키 감지·호출·task 노드 연동 (mechanism) |
| `skills/*` (10종) | setup·open·define·start·plan·run·verify·done·review·merge |
| `agents/pr-verifier.md` | PR 독립 검증 서브에이전트 |

자세한 설계·불변식·이관 가이드는 [DESIGN.md](DESIGN.md) 참조.
