---
title: snapshot은 상태 폴더 없는 휘발 staging
created_at: 2026-06-18
summary: snapshot은 상태 폴더 없이 wiki/snapshot/ 루트의 SNAP-<slug>.md 파일로 관리한다. 토론당 현재 상태 하나만, 이력은 git과 record가 보유한다.
tags: [wiki, snapshot, lifecycle]
supersedes: [DEC-2026-06-17-002727-snapshot은-active-전용-휘발-staging]
relations:
  intents: [INT-2026-05-29-104713-single-canonical-current-state]
  rejected_decisions: [REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]
  ssot: [wiki-data-model, wiki-lifecycle, wiki-retrieval]
---

## 결정

snapshot staging layer는 **상태 폴더를 갖지 않는다**.

- `wiki/snapshot/snapshot.md`는 index다.
- 실제 snapshot 파일은 `wiki/snapshot/SNAP-<slug>.md`로 index 옆에 직접 둔다.
- `snapshot save`는 slug 기준 제자리 갱신이다. 같은 slug면 같은 파일을 덮어쓰고 `created_at`은 보존하며 `updated_at`을 기록한다.
- `snapshot discard <ref>`는 해당 `SNAP-<slug>.md` 파일을 삭제한다. 별도 `active/`, `archived/`, `promoted/` 폴더를 두지 않는다.
- 0.8.0의 `wiki/snapshot/active/*.md`는 CLI가 발견하면 `wiki/snapshot/*.md`로 자동 migration한다.
- 정식 지식화는 기존대로 별도 `capture`/Edit으로 수행한다. staging 자체는 이력·상태 추적 책임을 갖지 않는다.

## 취지

snapshot의 본질은 세션 컨텍스트 메모장이다. 메모장에는 "현재 이어서 말하기 위한 압축 맥락"만 있으면 충분하다. 상태가 하나뿐인 모델에서 `active/` 폴더는 의미 정보를 추가하지 않고, 오히려 3상태 모델의 흔적을 남겨 구현과 문서가 다시 `archived/promoted` 쪽으로 미끄러질 여지를 만든다.

따라서 존재 자체가 현재 staging 상태이고, 종료는 삭제다. 이력은 git과 정식 wiki record가 보유한다는 원칙을 유지한다.

## 배경

2026-06-17의 [[DEC-2026-06-17-002727-snapshot은-active-전용-휘발-staging]]은 0.7.0의 `active/archived/promoted` 3상태 누적 모델을 반려하고 active 단일 폴더 휘발 모델을 채택했다. 이후 2026-06-18 논의에서 "active-only면 active 폴더도 필요 없다"는 점을 확인했다.

상태 폴더가 하나뿐이면 `snapshot/active`는 경로 기반 상태 표현이 아니라 불필요한 중간 디렉터리다. wiki의 다른 폴더 index 패턴처럼 `snapshot/snapshot.md` index 옆에 실제 note를 두는 편이 단순하고 일관적이다.

## 고려한 대안

- **active 단일 폴더 유지(반려, superseded)**: [[DEC-2026-06-17-002727-snapshot은-active-전용-휘발-staging]]. 3상태 모델보다 낫지만, 상태가 하나뿐인 상황에서 `active/`가 남아 불필요한 개념을 유지한다.
- **3상태 누적 보존(반려)**: [[REJ-2026-06-17-002650-snapshot-3상태-누적-보존-모델]]. append-only/archived/promoted는 세션 메모장 목적과 맞지 않는다.
- **단일 `snapshot.md`만 사용(미채택)**: repo당 메모장 하나로 더 단순하지만, 서로 다른 토론을 병렬로 잠시 들고 있어야 하는 경우 slug 분리가 필요하다.

## 트레이드오프

- 얻음: 경로 모델이 더 단순해진다. `active/`라는 죽은 상태 표현이 사라지고, `snapshot/` index + note 구조가 다른 wiki 폴더와 맞아진다.
- 얻음: 기존 `snapshot/active/*.md`는 자동 migration하므로 0.8.0 사용자 데이터는 보존된다.
- 잃음: 제거된 CLI 표면(`--continues`/`--update`/`--include-*` 플래그, `archive` 명령)이나 `snapshot/active/...` 경로를 직접 참조하던 호출은 깨질 수 있다. 다만 vault 데이터는 자동 migration되고 pre-1.0 단계라 patch로 `0.8.1`을 올린다.
- 유지: CLI 명령 surface(`save/list/search/load/discard`)와 slug 제자리 갱신 시맨틱은 유지한다.

## 재평가 조건

- snapshot에 상태 전이가 실제로 필요해지는 경우.
- git 없는 vault에서 discard 이력이 손실되어 soft-delete가 필요해지는 경우.
- snapshot 파일 수가 많아져 root index 옆 배치가 탐색성 문제를 만들고, 폴더 분리가 다시 필요해지는 경우.
