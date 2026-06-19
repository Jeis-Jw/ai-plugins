# 설계 — task-github C2: closeout.py (git/gh-only)

- **대상:** `plugins/task-github/` (0.5.0 → 0.6.0)
- **상위:** C(closeout 자동화)의 둘째 조각. C1(tier 게이트)는 완료.
- **근거:** `merge` 스킬의 post-gate 시퀀스가 수동 다단계 연쇄 — 체감 오버헤드 핵심.

## 목적

`merge` 스킬의 **결정적 post-gate 시퀀스**를 단일 스크립트로(`create_issue_tree.py` 패턴). **wiki를 부르지 않음** — 게이트는 스크립트 전에 에이전트가, `wiki complete`는 스크립트가 방출한 TASK id로 에이전트가 후처리. wiki 경로 의존 0 = 이식성.

## CLI

`closeout.py --pr <N> [--dry-run] [--json]`

## 시퀀스 (live)

1. PR 해석: `gh pr view` → linked issue(`Closes #N` 파싱), headRef, state.
2. 의존성 재확인: `blocked_by` open 있으면 중단(exit nonzero, JSON error).
3. 라벨 정리: PR+issue에서 `in-review`/`in-progress`/`changes-requested` 제거.
4. 머지: `gh pr merge --merge --delete-branch`.
5. 동기화+정리: `git checkout main && git pull`; 로컬 headRef 브랜치 `-d`.
6. downstream 안내: `blocking` 목록 방출.
7. 루트 닫힘 감지: parent walk(graphql) → 루트 state CLOSED → root body서 `TASK-…` 추출 → 방출.
8. JSON 출력: `{ok, pr, issue, root, root_closed, task_to_complete|null, downstream:[], merged}`.

## dry-run

1·2·6·7(읽기 전용) 실행 + "할 일" 리포트(머지 명령, 제거할 라벨, 삭제할 브랜치, complete 대상). **머지·라벨·삭제 일절 안 함.** irreversible 안전장치.

## 순수 헬퍼 (유닛 테스트 대상)

- `parse_linked_issue(pr_body) -> int|None`: `(?i)(closes|fixes|resolves)\s+#(\d+)`.
- `extract_task_id(issue_body) -> str|None`: `TASK-\d{4}-\d{2}-\d{2}-\d{6}-[^\s)\]]+` — **Unicode 슬러그(한글) 보존**(기존 SKILL의 ASCII-only grep은 한글 슬러그를 잘랐음, 개선).
- `labels_to_remove(current) -> list`: `{in-review,in-progress,changes-requested}` 교집합.

## merge 스킬 흐름 (재작성)

게이트(integrity/drift) → `closeout.py --pr N --dry-run`(계획 확인) → `closeout.py --pr N`(실행) → 출력 `task_to_complete` 있으면 `wiki complete <task>` → `wiki refresh` + Knowledge Capture Audit.

## 테스트 / 검증

- task-github 첫 `tests/test_closeout.py` 신설 — 순수 헬퍼(파싱/라벨/Unicode TASK id).
- gh/git 오케스트레이션은 gh 없는 환경이라 유닛 불가 → `--dry-run`(읽기 전용) + self-flow 리뷰로 검증.

## 불변 / 제약

- wiki 경로 의존 0(이식성). `gh pr merge`는 live에서만, dry-run 절대 머지 안 함.
- 게이트는 스크립트 밖(머지 차단 결정 = 에이전트). 위키 없는 워크스페이스 graceful(스크립트는 wiki 무관하므로 영향 없음).
- 기존 merge SKILL의 task-done 전이/루트 감지 로직을 스크립트로 이관(중복 제거).
- `${CLAUDE_SKILL_DIR}/scripts/closeout.py`로 호출(create_issue_tree.py와 동일 패턴).

## 완료 기준

- `closeout.py` + `tests/test_closeout.py`(순수 헬퍼) 통과.
- `--dry-run --json`이 머지 없이 계획 방출.
- merge SKILL 재작성 + DESIGN/wiki-bridge 갱신, 버전 0.6.0.
- self-flow 리뷰 approved → PR → 머지.
