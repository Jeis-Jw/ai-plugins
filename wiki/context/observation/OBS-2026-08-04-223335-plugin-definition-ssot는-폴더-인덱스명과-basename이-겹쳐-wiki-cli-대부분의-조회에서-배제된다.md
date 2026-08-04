---
title: plugin-definition SSOT는 폴더 인덱스명과 basename이 겹쳐 wiki_cli 대부분의 조회에서 배제된다
created_at: 2026-08-04
summary: wiki/ssot/plugin-definition/plugin-definition.md는 basename이 소속 폴더명과 같아 _is_index_file(순수 이름 비교)이 파생 인덱스로 오분류한다. find_doc_anywhere·iter_active_docs가 배제해 relate 대상 지정뿐 아니라 refresh 무결성/hygiene 검사와 recall 검색에서도 통째로 빠진다.
tags: [wiki-markdown, mechanism-defect, index, relation]
affects_paths: [plugins/wiki-markdown/**]
relations:
  decisions: [DEC-2026-08-04-221921-wiki-markdown도-단일-plugin-ssot를-갖는다]
---

## 관찰

`wiki/ssot/plugin-definition/plugin-definition.md`는 자기 basename('plugin-definition')이 소속 폴더명('plugin-definition/')과 정확히 일치해, `wiki_cli.py`의 `_is_index_file(parts, path)`(== `_nfc(path.stem) == _nfc(parts[-1])`, 순수 파일명 비교) 판정에서 '파생 인덱스'로 분류된다. 그 결과 `find_doc_anywhere(..., include_indexes=False)`(기본값)와 `iter_active_docs`가 이 파일을 완전히 건너뛴다 — 실제로는 7개 일급 원칙, sub-ssot 라우팅 표, 진화 이력 등 상당한 수기 본문을 담고 있는데도 코드는 파일명 패턴만으로 이를 파생물로 오분류한다.

## 근거

`wiki_cli.py:815` `if _nfc(parts[-1]) == basename and not include_indexes: continue`(find_doc_anywhere fast-path 폴더 skip), `:824` 동일 목적 defense-in-depth 재확인, `:738` `iter_active_docs`의 `not _is_index_file(parts, c)` 필터, `:301-309` `_is_index_file` 정의. 직접 재현: `recall --read plugin-definition` → `{"ok": false, "error_code": "read_missing"}`. `capture decision --ssot plugin-definition` → `ref_missing`(DEC-2026-08-04-221921 capture 중 실제로 겪음).

## 영향

relation target 지정 불가(`--ssot`/`--decisions`/`--runbook` 등 모든 relate류)뿐 아니라, `iter_active_docs`가 refresh의 검사(stale/orphan/tags/schema/changed-path-stale 등) 전부와 `recall` Stage 1 매칭의 기반이므로 이 문서는 refresh 무결성·hygiene 검사와 recall 검색 대상에서도 통째로 빠진다 — verified_at이 stale해지거나 스키마를 위반해도 refresh가 못 잡고, `recall "plugin-definition"`으로 검색해도 안 걸릴 수 있다(단 `iter_every_md`를 쓰는 `duplicate-basename` 검사와 `capture`의 living-slug 충돌 검사(`include_indexes=True`)는 예외적으로 이 파일을 본다). 현재 이 충돌은 `plugin-definition/` 1개 폴더에만 해당하지만, basename == 소속 폴더명인 다른 nested ssot/runbook을 새로 만들면 동일하게 재현되는 구조적 결함이다.

## 현재 처리

수정하지 않고 관찰만 기록한다(owner 지시). plugin-definition.md의 버전 서술 등 이번 alignment는 별도로 완료했다(DEC-2026-08-04-221921). 이 관찰은 그 DEC 배경 절의 한 문장을 근거와 함께 독립 record로 승격한 것이다.

## 후속 분류 조건

`find_doc_anywhere`/`iter_active_docs`가 '폴더명과 파일명이 같다'는 이름 규칙 대신 '이 파일이 실제로 폴더의 대표 index 서술을 담당하는가'를 판별하는 별도 신호로 바뀌거나, owner가 수정 여부(예: nested ssot 루트 슬러그를 폴더명과 다르게 강제)를 판단하면 이 관찰을 DEC/TRI로 승격하거나 폐기한다.
