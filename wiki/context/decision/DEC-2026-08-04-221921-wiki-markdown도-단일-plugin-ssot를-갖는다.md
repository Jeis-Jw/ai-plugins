---
title: wiki-markdown도 단일 plugin SSOT를 갖는다
created_at: 2026-08-04
summary: wiki-markdown이 studio/task-github/task-worker/session-review와 같은 단일 진입점 SSOT(wiki-markdown-plugin.md)를 갖는다. 이 문서가 버전·진화·소유범위·구성의 정본이고 plugin-definition 6종 sub-ssot는 세부 계약 정본으로 유지된다.
tags: [wiki, plugin-definition, ssot, structure]
relations:
  intents: [INT-2026-05-29-104710-ai-driven-documentation]
---

## 결정

wiki-markdown 플러그인도 studio/task-github/task-worker/session-review와 동일하게 단일 진입점 SSOT(`wiki/ssot/wiki-markdown-plugin.md`)를 갖는다. 이 문서가 버전·진화 요약·소유 범위·구성의 정본이고, `plugin-definition/` 6개 sub-ssot(wiki-data-model/wiki-lifecycle/wiki-retrieval/wiki-external-tools-policy/wiki-four-layer-separation/plugin-definition)는 그 아래 세부 계약 정본으로 계속 남는다. `plugin-definition.md`는 새 문서를 가리키기만 하고 버전 숫자를 중복 서술하지 않는다.

## 취지

[[INT-2026-05-29-104710-ai-driven-documentation]] — AI가 주 작성자인 문서는 '지금 몇 버전, 최근에 뭐가 바뀌었나'를 답할 단일 진입점이 있어야 캐시 신선도·drift를 스스로 유지할 수 있다. 다른 4개 plugin SSOT가 이미 이 패턴을 증명했다.

## 배경

이번 정렬 세션에서 이 비대칭이 실제로 만든 사각 2건을 확인했다 — plugin-definition.md의 marketplace 버전 문자열이 0.8.1로 13-minor(0.8.1→0.21.0) 방치됐고, 0.21.0 릴리스(f41a6d6, proactive recall 계약)가 어떤 wiki record에도 기록되지 않았다. 단일 버전 진입점이 없어 '이 플러그인 지금 몇 버전, 뭐가 최근에 바뀌었나'를 답할 단일 장소가 없었다. 반면 studio/task-github/task-worker/session-review는 각자 단일 SSOT가 있어 이번 세션에서 버전 drift를 빠르게 찾고 고칠 수 있었다. 부수 발견: `plugin-definition` SSOT는 자기 basename이 소속 폴더의 인덱스 파일명 규약(`<폴더명>.md`)과 겹쳐 `find_doc_anywhere`가 이를 파생 인덱스로 취급해 제외한다 — 그 결과 이 문서는 현재 `--ssot`/`--decisions` 등 정식 relation target으로 지정할 수 없다(본 DEC도 이 때문에 `ssot: [plugin-definition]`을 relate하지 못했다).

## 고려한 대안

(a) affects_paths+changed-path-stale 감지만으로 유지 — 기각: 이 감지는 verified_at이 이미 있는 문서의 '코드가 바뀌었는데 재검증 안 됨'만 사후적으로 잡을 뿐 '버전이 몇인지 답하는 단일 진입점 부재' 자체는 풀지 못한다(실제로 plugin-definition.md의 stale 버전 문자열은 이 세션 전 affects_paths가 비어 있어 이 검사로 못 잡았고, 채워진 지금도 '재검증 필요'만 알릴 뿐 정답은 안 알려준다). (c) plugin-definition 6종을 단일 문서로 통합 — 기각: 6종은 각자 응집된 세부 계약을 담고 있어 병합하면 문서가 비대해지고 '폴더 인덱스가 overview 역할'이라는 기존 설계(DEC-2026-05-29-105319/105321)와 충돌한다.

## 트레이드오프

얻음: 5개 플러그인이 동일한 단일 SSOT 진입점 패턴을 가져 일관된 조회 경험, 버전 drift를 잡기 쉬움. 잃음: plugin-definition.md와 새 문서가 겹치는 정보(버전, 구성)를 일부 중복 소유할 위험 — 새 문서는 버전/현황, plugin-definition.md는 sub-ssot 라우팅으로 역할을 분리해 완화. 위험: 두 문서가 각자 버전 문자열을 서술하면 비대칭 drift가 재발할 수 있음.

## 재평가 조건

새 SSOT와 plugin-definition.md/sub-ssot 6종 사이에 버전·현황 서술이 다시 어긋나는 사례가 발견되면(refresh나 다음 정렬 세션에서) 한쪽만 정본으로 남기는 재설계를 검토한다.
