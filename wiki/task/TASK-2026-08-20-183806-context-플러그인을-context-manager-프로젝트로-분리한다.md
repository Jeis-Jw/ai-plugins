---
title: context 플러그인을 context-manager 프로젝트로 분리한다
created_at: 2026-08-20
summary: context-core와 context-decision을 독립 공개 예정 context-plugins 저장소로 이전하고 context-manager 상위 프로젝트를 context 기반으로 초기화한다.
tags: [context-core, context-decision, repository-split, migration, context-manager]
---

## 개요

ai-plugins가 함께 소유하던 context-core와 context-decision을 personal/context-manager/context-plugins 독립 저장소로 분리한다. context-manager는 향후 context-plugins와 PCMS 같은 여러 구성요소를 묶는 상위 coordination 프로젝트다.

## 근거

사용자가 플러그인 두 개를 별도 공개 저장소로 운영하고 향후 semantic owner 플러그인과 PCMS 계열 솔루션을 context-manager 구성요소로 확장하겠다고 명시했다. 새 workspace는 wiki-markdown 대신 context-core/context-decision을 durable context layer로 사용한다.

## 범위와 완료 기준

완료 기준: (1) context-manager 상위 Git 프로젝트와 독립 context-plugins Git 저장소를 생성한다. (2) context-plugins가 두 플러그인의 source, host manifest/catalog, 공용 fixture/test, 공개용 README와 license 상태를 자급한다. (3) 새 canonical repository/marketplace 좌표로 계약과 테스트를 정렬한다. (4) context-manager와 context-plugins에 wiki 없이 context-common/v2 root와 decision area 및 Codex managed policy를 멱등 초기화한다. (5) 새 저장소 검증 후 ai-plugins의 기존 source/catalog/test 소유권을 정리하되 push나 외부 공개는 하지 않는다. (6) 양쪽 Git 상태와 복구 가능한 commit 근거를 남긴다.

## 실행 결과

- 상위 repository: `/Users/jinwuklee/SRCs/personal/context-manager@3639737`
- plugin repository: `/Users/jinwuklee/SRCs/personal/context-manager/context-plugins@69c0544790e4ba873efa18f63f4f2f285af0ea59`
- source provenance: `ai-plugins@eea43c9386735aa6141203a8a8912b0256746a64`
- 새 distribution: marketplace `context-plugins`, source `Jeis-Jw/context-plugins`, plugin version `0.4.0`
- 검증: 새 repository root에서 `152 passed, 98 subtests passed`, compileall·JSON validation·독립 review 통과
- 보류 경계: remote 생성·push·marketplace publication·live install은 미수행이며 공개 license는 아직 선택하지 않았다.
