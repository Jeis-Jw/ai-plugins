---
title: 위키 외부 도구 정책
created_at: 2026-05-29
summary: 외부 도구(Obsidian 등)와의 경계 정본: AI 검색 정본은 filesystem 단일(ripgrep+YAML), wikilink는 사람용 장식, .obsidian/ gitignore. plugin-definition 영역의 sub-ssot.
tags: [wiki, external-tools, ssot]
verified_at: 2026-05-29
---

## 현재 상태

### 원칙: "Obsidian-호환 뷰어 지원, Obsidian 런타임 의존 0"

- **AI 검색 정본 경로 = filesystem 단일** (ripgrep + YAML 파싱). 폴백/주경로 이원화 없음.
- **obsidian-cli / Dataview / Bases / 백링크 그래프는 AI 파이프라인에서 제외.** 사람용 편의일 뿐, 어떤 시스템 기능도 이를 요구하지 않음.

→ [[DEC-2026-05-29-105233-obsidian-zero-runtime-dependency]]

### 근거

- AI가 주 작성자 → obsidian-cli 메타데이터 캐시 **신선도 지연** 위험 (쓴 직후 조회 누락).
- CI·git hook·자율 에이전트·워크트리 같은 **헤드리스**에서 Obsidian 미동작.
- **양방향 관계(파생) + 관계정본 YAML + ISO 날짜** 가 obsidian-cli 강점(백링크·alias·타입 쿼리)을 데이터모델로 이미 대체.
- 1인 vault 수천 노트는 ripgrep 수십 ms — 사전 인덱스 불요.

### Wikilink 정책

- `[[basename]]` 문법은 **유지** — 파일이 `retired/`로 이동해도 안 깨지고(이동 내성) Obsidian 클릭 탐색 공짜.
- 단 **관계 정본은 아님** — 정본은 frontmatter YAML의 plain ID ([[wiki-data-model]] 참조).

### Repo 정책

- `.obsidian/`은 개인 설정 → **`.gitignore`**
- **Bases** (Obsidian 1.9+): 선택적 부가물, init 자동 설치 안 함

## 취지

이 정책이 추구하는 일급 원칙:

- [[INT-2026-05-29-104709-filesystem-primary-truth]] — 외부 도구가 정본이 되면 헤드리스에서 깨짐
- [[INT-2026-05-29-104712-parallel-safe-headless-operation]] — CI/워크트리에서 GUI 도구 미동작
- [[INT-2026-05-29-104710-ai-driven-documentation]] — AI 주작성자 가정과 캐시 신선도

## 구성요소

이 영역에 응집된 결정 anchor:

- [[DEC-2026-05-29-105233-obsidian-zero-runtime-dependency]] — Obsidian 런타임 의존 0

반려 대안: [[REJ-2026-05-29-105456-wikilink-as-relation-source]] (본문 wikilink를 관계 정본으로) / [[REJ-2026-05-29-105457-obsidian-cli-primary-search]] (obsidian-cli를 AI 검색 주경로로).

