---
title: define 배치 헬퍼와 wiki relate를 배포한다
created_at: 2026-06-03
summary: task-github define은 테스트된 issue-tree 헬퍼로 루트·서브이슈·dependency를 만들고, wiki-markdown은 기존 노드 관계 보강을 위해 relate와 견고한 ref/task-ref 정규화를 제공한다.
tags: [plugin, task-github, wiki, workflow]
relations:
  ssot: [wiki-data-model]
---

## 결정
`task-github:define`의 루트/서브이슈/dependency 생성은 `skills/define/scripts/create_issue_tree.py`를 정본 헬퍼로 사용한다. 부모 연결은 GraphQL `createIssue(parentIssueId)`로 통일하고, dependency는 REST Issue dependency API(`X-GitHub-Api-Version: 2026-03-10`)를 쓴다.

`wiki-markdown`에는 기존 문서 관계를 안전하게 보강하는 `wiki relate`를 추가한다. task 노드는 semantic relation과 외부 task ref를 추가할 수 있고, immutable record는 `relations.tasks`만 추가할 수 있다. 동시에 mixed CJK/Latin slug fragment 해석, 누락 ref 후보 표시, quoted task-ref 정규화를 배포한다.

운영정책에는 "brainstorm은 분해와 얇은 단위 경계까지만, 단위 내부 상세설계는 서브이슈 본문 또는 해당 단위 실행 중 DEC/OBS"라는 altitude 규칙을 `CLAUDE.md`/`AGENTS.md` 관리 블록에 둔다.

## 취지
반복 세션에서 에이전트가 sub-issue 생성을 셸 루프로 재구현하면 zsh 배열 인덱싱, GitHub API 방식 혼재, dependency 인자 실수 같은 깨지기 쉬운 지점이 매번 재발한다. 이 부분은 프로젝트별 판단이 아니라 플러그인 메커니즘이 제공해야 할 안정 경로다.

반대로 단위별 상세설계가 어디 사느냐는 작업환경 운영정책이다. 위키 leaf task 노드를 늘리는 대신 루트 task 노드 1:1 원칙을 지키고, 실행 단위의 세부 계약은 서브이슈 본문과 실행 중 캡처되는 지식으로 흘린다.

## 배경
토탈 리포트 헤어 총론 자동화 업무 정의 세션에서 서브이슈 6개를 손으로 만들다 첫 이슈 누락과 번호 시프트가 발생했다. 또 brainstorming 산출물을 리프 task 노드로 옮겨 wiki-bridge의 "업무 1개 = 루트 이슈 1 + task 노드 1" 불변식과 충돌했다.

같은 세션에서 `wiki capture task --decisions <slug fragment>`가 한글+라틴 혼합 slug 접두 fragment를 찾지 못했고, 수동 frontmatter 편집으로 추가한 `tasks: ["owner/repo#N"]`가 `task-ref` 검사에서 거부됐다.

## 고려한 대안
- `define` 스킬에 셸 스니펫만 더 자세히 둔다: 여전히 각 에이전트가 fragile한 배치 생성 단계를 재구현한다.
- REST `sub_issues` 경로와 GraphQL parent 경로를 모두 문서화한다: 선택지가 늘어 API ID 종류(DB id/node id) 혼동이 남는다.
- 기존 노드 관계 추가는 수동 편집으로 둔다: frontmatter quoting, 중복 추가, semantic relation 변경 범위를 매번 사람이 판단해야 한다.

## 트레이드오프
헬퍼 스크립트가 task-github에 작은 실행 코드 표면을 추가한다. 대신 dry-run JSON 테스트가 가능하고, 실제 GitHub 호출 방식이 한 곳으로 모인다.

`wiki relate`는 immutable record를 "편집"하는 새 경로지만, record semantic relation은 막고 외부 task ref 보강만 허용해 capture/supersede 원칙의 훼손을 제한한다. task 노드는 본래 living-like bridge 성격이므로 관계 보강을 허용한다.

## 재평가 조건
GitHub의 sub-issue parent 생성 API가 안정적으로 REST 단일 경로를 제공하고 GraphQL parent 연결보다 단순해지면 parent method를 재검토한다.

`wiki relate`가 semantic relation 변경 우회로로 남용되거나, immutable record의 의미 변경 요구가 반복되면 record 대상 relate 범위를 더 줄이고 successor capture만 허용하는 방향을 검토한다.
