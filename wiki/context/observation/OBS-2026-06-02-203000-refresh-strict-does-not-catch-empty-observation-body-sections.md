---
title: refresh strict does not catch empty observation body sections
created_at: 2026-06-02
summary: Review found observation records with all fixed body sections empty while wiki refresh --strict still returned no issues. This leaves Stage-2 recall with headers but no evidence.
tags: [wiki, observation, schema, quality]
verified_at: 2026-07-15
affects_paths: [plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py, plugins/wiki-markdown/tests/test_wiki_cli.py, wiki/context/observation/**]
relations:
  decisions: [DEC-2026-05-29-105322-observation-record-type]
---

## 관찰

`wiki refresh --strict`가 observation record의 고정 본문 섹션이 모두 비어 있는 상태를 issue로 보고하지 않았다. 실제로 `OBS-2026-06-02-200327-...`와 그 retired predecessor는 `## 관찰`, `## 근거`, `## 영향`, `## 현재 처리`, `## 후속 분류 조건`만 있고 내용이 없었지만 strict refresh는 `{"issues": []}`를 반환했다.

## 근거

리뷰 중 `nl -ba`로 해당 파일을 직접 확인했고, 이어 `python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py refresh --strict --vault wiki --json`을 실행했을 때 깨끗한 결과가 나왔다. 현재 refresh strict는 `empty-lesson` check로 `trial_error`의 빈 `## 교훈`은 강하게 검증하지만 observation의 본문 충실도는 잡지 않는다.

## 영향

Stage-2 recall은 고정 섹션 본문을 읽어 맥락을 복원하므로, 헤더만 있는 observation은 장기 기억으로서 가치가 낮다. strict refresh가 이를 놓치면 "검증 통과"처럼 보이지만 실제 기록 품질은 낮을 수 있다.

## 현재 처리

이번에 발견된 빈 observation 두 개는 수동으로 본문을 채웠다. 다만 CLI schema 규칙 자체는 아직 바꾸지 않았으므로, 같은 형태의 빈 observation이 다시 생길 가능성은 남아 있다.

## 재검증

2026-07-03 observation 재검증 메모를 추가하는 과정에서도 `refresh --strict`는 본문 충실도 자체를 hard gate로 보지 않는다. 이 record의 문제 제기는 여전히 유효하며, 이번 변경은 해당 한계를 해소하지 않는다.

2026-07-14 observation freshness 갱신 후에도 `refresh --strict`는 observation 고정 섹션의 본문 충실도를 검사하지 않았고, 빈 기록을 수동 보완한다는 현재 처리와 검증 한계는 그대로 유효함을 재확인했다.

## 후속 분류 조건

observation 본문 최소 충실도 검사를 CLI에 추가하기로 결정하면 이 record를 decision 또는 trial_error로 승격한다. 구현 후보는 `schema` check가 observation의 필수 섹션 중 전부 또는 핵심 섹션이 비어 있을 때 issue를 내도록 하는 것이다.
