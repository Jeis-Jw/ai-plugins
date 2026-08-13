---
name: snapshot
description: 명시적으로 요청된 unfinished session handoff를 여러 named SNAP 중 하나로 preview, 갱신, 조회 또는 폐기한다.
---

# Snapshot

SNAP은 `authority: staging`인 mutable resume context다. 결정·관찰의 권위 기록으로 취급하지 않는다.

1. 저장 요청에 unfinished context와 handoff 의도가 모두 있는지 확인한다.
2. `context_cli.py capabilities --json`의 snapshot descriptor만 사용해 bounded candidate와 `claim` attestation을 만든다.
3. `save`는 create-only이며 `현재 맥락`, `열린 항목`, `다음 단계`를 모두 채운다.
4. `update`는 기본 full replacement다. 일부만 바꿀 때만 `--merge`를 사용한다.
5. 모든 mutation은 반환된 complete bundle을 보여주고 exact `approval_digest` 승인 뒤 `transaction apply`로 적용한다.
6. `load`의 `freshness`는 warning label일 뿐 SNAP lifecycle을 바꾸지 않는다.
7. `discard`는 exact SNAP ID만 사용한다. SNAP에는 archive/history/retired 상태가 없다.

CLI는 `../context/scripts/context_cli.py snapshot ...`을 사용한다. `@file` body를 우선하고, 승인 뒤 candidate·timestamp·bundle을 다시 생성하지 않는다.
