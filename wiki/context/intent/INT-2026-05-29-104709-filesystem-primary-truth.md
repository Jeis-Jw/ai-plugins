---
title: 파일시스템 정본
created_at: 2026-05-29
summary: 정본 데이터 모델은 파일시스템(YAML + ripgrep)에 둔다. Obsidian 같은 외부 도구가 정본이 되면 헤드리스·자동화·이식에서 깨진다.
tags: [wiki, architecture, principle]
---

## 취지

정본 데이터 모델은 **파일시스템 + YAML + git**에 둔다. Obsidian, Notion, Confluence 같은 외부 도구가 정본이 되면, 그 도구가 동작하지 않는 환경(CI, 헤드리스 에이전트, 워크트리)에서 시스템이 깨진다.

외부 도구는 *뷰어*일 수는 있지만 *정본*일 수는 없다.

## 배경

- AI가 주 작성자이므로 obsidian-cli의 metadata cache 신선도 지연 위험(쓴 직후 조회 누락).
- CI·git hook·자율 에이전트·워크트리 같은 헤드리스 환경에서 GUI 도구 미동작.
- 외부 도구 정본은 도구 교체·중단 시 전면 마이그레이션 비용.
- 1인 vault 규모(수천 노트)에서 ripgrep + YAML 파싱은 수십 ms — 사전 인덱스 불요.

따라서 wikilink 문법은 *유지*(이동 내성 + Obsidian 클릭 탐색 공짜)하지만, **정본은 항상 frontmatter YAML의 plain ID**다.

