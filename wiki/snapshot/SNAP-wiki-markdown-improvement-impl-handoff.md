---
title: wiki-markdown 개선 구현 핸드오프 — Unit A·B 머지, C/body-file/closeout 잔여
created_at: 2026-06-25
summary: wiki 0.12→0.14 운용효율 개선 구현 중간 인계. 다음 세션이 Unit C부터 이어받음.
tags: [wiki-markdown, improvement, handoff]
type: snapshot
search_terms: [wiki improvement unit C recall pack discard handoff]
---
## 현재 논의

wiki-markdown 0.12.0→0.14.0 운용효율 개선 구현 중. session-review 3라운드 수렴 방향을 Unit A/B/C+closeout으로 분해해 정식 PR 플로우(PR→adversarial 리뷰→머지→완료)로 진행.

완료:
- Unit A (표면 재설계: capture --json payload 확장, compact SKILL 236→~150, drift 수정 --level/--sec-*/--lite/--merge, negative trigger). PR #21, v0.13.0.
- Unit B-discard (canonical 노드 mistake-undo 삭제 + 가드). PR #22, v0.14.0. adversarial 리뷰가 supersede-edge dangling blocking 잡아 수정.

잔여:
- Unit B 나머지: --body-file/STDIN (capture+snapshot 함께, @file 또는 stdin 단일).
- Unit C: recall --pack(deterministic projection) · authority/stale additive label(relation-aware) · machine-discoverability(wiki schema/help --json, capture --dry-run --json).
- closeout(P2): complete/reopen payload 강화.

상태: main @ 3bdac48 (origin push됨). 테스트 149개 green: python3 plugins/wiki-markdown/tests/test_wiki_cli.py

## 배경

근거: DEC-2026-06-25-182926(방향 결정), 작업정의 TASK-2026-06-25-182926, GitHub 루트 이슈 Jeis-Jw/ai-plugins#20(A·B 체크 코멘트 완료). 상세 방향+구현노트는 docs/proposals/wiki-markdown-improvement-direction.md (특히 §4 우선순위, §8 구현단계 노트). gear:normal — 단 discard류 파괴적 작업은 adversarial review 필수.

## 정해진 것

다음 세션이 지켜야 할 규칙(session-review 수렴 결과):
- 플로우: unit별 feat/ 브랜치 → 구현+테스트 → PR(--base main, body에 DEC+#20 ref) → adversarial 리뷰(cavecrew-reviewer subagent 또는 cross-model) → blocking 수정 → squash merge(--delete-branch) → #20 코멘트. rationale는 main 직접, 코드는 PR.
- 설계 제약: (a) Unit A류=surface+additive only, behavior 불변. (b) payload 확장은 additive·이미 계산된 metadata만. (c) discard 가드 패턴=exact basename·backlinks ∪ supersede_refs 거부·--force·--dry-run preview(find_supersede_refs 참고). (d) recall --pack=deterministic 추출만(frontmatter/relations/fixed-section/task header), prose 추론 금지·추론분은 candidate_*/source_summaries. (e) authority=additive label(authority/freshness/use_as/warnings), 기본 recall 강제정렬 금지, 강 ranking은 --pack 내부만. (f) stale=relation-aware, anchor 없으면 authority_unknown(possibly_stale 금지). (g) closeout=새 명령 금지, complete/reopen payload 강화(moved_from/to·updated_indexes·suggested_git_paths), GitHub 감지는 task-github closeout.py 소관.
- 버전: 현재 0.14.0, unit마다 bump(.claude-plugin + .codex-plugin plugin.json 둘 다). negative trigger 이중배치(SKILL+agent-policy) 이미 반영됨.

## 아직 열린 질문

환경 이상(주의): 백그라운드 spawn_task 프로세스가 task/session-review-reviewer-posture 및 -review 브랜치를 생성하고 작업 중 체크아웃을 한 번 가로챘음. 다음 세션은 모든 git 작업 전에 git branch --show-current로 브랜치 확인할 것. task/session-review-reviewer-posture-review 브랜치는 그 백그라운드 task 소유로 보이니 건드리지 말 것.
미정: body-file(쉬움) 먼저냐 Unit C(가치 큼) 먼저냐 — 권장은 Unit C recall --pack부터.

## 다음에 볼 것

1) git pull 후 git branch --show-current로 main 확인. 2) feat/wiki-unit-c 브랜치 생성. 3) Unit C recall --pack(deterministic projection)부터 구현 → 테스트 → PR → adversarial 리뷰 → 머지 → #20. docs/proposals/wiki-markdown-improvement-direction.md §4(P1 Unit C)·§8 참조. 이어서 authority/stale label, discoverability, 그다음 body-file, 마지막 closeout.

## 관련 파일/문서

docs/proposals/wiki-markdown-improvement-direction.md, plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py, plugins/wiki-markdown/skills/wiki/SKILL.md, plugins/wiki-markdown/skills/wiki/references/wiki-protocol.md, plugins/wiki-markdown/tests/test_wiki_cli.py, Jeis-Jw/ai-plugins#20, DEC-2026-06-25-182926, TASK-2026-06-25-182926

## 승격 후보
