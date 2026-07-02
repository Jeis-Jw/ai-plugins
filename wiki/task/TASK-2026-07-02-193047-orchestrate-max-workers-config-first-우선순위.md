---
title: orchestrate max-workers config-first 우선순위
created_at: 2026-07-02
summary: orchestrate의 --max-workers를 review-mode와 동일하게 .task-github.yml orchestrate.max-workers 설정값을 먼저 읽게 하고, 없으면 시스템 기본값 3을 쓴다(현재는 CLI/기본값 1 고정)
tags: [task-github, orchestrate, config]
relations:
  decisions: [DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]
  tasks: [Jeis-Jw/ai-plugins#33]
---

## 개요

`orchestrate`는 `--review`(review-mode)를 판단할 때 commander 지시 > `.task-github.yml orchestrate.review-mode` > 시스템 기본값 순서를 이미 따른다. 그런데 `--max-workers`는 이 우선순위를 따르지 않고 CLI 인자가 없으면 곧바로 시스템 기본값(1)로 고정된다. 병렬도를 프로젝트별로 config에 고정해두고 싶은 사용자 요청 — review-mode와 같은 config-first 패턴으로 통일한다.

## 근거

- 사용자 요청(세션 내 직접 지시) — review-mode의 config 우선순위 패턴을 max-workers에도 적용해달라는 요청
- [[TASK-2026-07-02-190021-define-topology-제안-품질-개선]] 작업 중 orchestrate SKILL.md/task_config.py 구조를 살펴보다 발견된 비일관성

## 범위와 완료 기준

영향 경로: `plugins/task-github/scripts/task_config.py`, `plugins/task-github/skills/orchestrate/SKILL.md`, `plugins/task-github/tests/test_task_config.py`

완료 기준:
1. `task_config.py`: `ORCH_KEYS`에 `max-workers` 추가, 양의 정수(또는 빈 값)만 허용하는 validation 추가
2. `orchestrate/SKILL.md`: `--max-workers` 우선순위를 "commander 지시 > `.task-github.yml orchestrate.max-workers` > 시스템 기본값(3)"으로 문서화 (입력 섹션, 루프 순서, 불변식의 "v1 `--max-workers 1` 기본" 문구 갱신)
3. 시스템 기본값을 1 → 3으로 변경(문서·근거만 있는 값이라 코드 기본값 변경 지점 없으면 문서만)
4. `test_task_config.py`에 max-workers validation 테스트(유효/무효 케이스) 추가

검증: `python3 -m unittest discover -s plugins/task-github/tests -p "test_*.py"` green
