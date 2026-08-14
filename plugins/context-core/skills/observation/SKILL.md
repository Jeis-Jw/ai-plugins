---
name: observation
description: 작업 중 발견한 사실·근거·시행착오가 이후에도 재사용될 가치가 있지만 authoritative decision은 아닐 때 비권위 OBS로 preview, 조회, 교정, 재검증, 무효화, supersede 또는 폐기한다.
---

# Observation

OBS는 `authority: evidence`인 immutable semantic claim이다. DEC처럼 따를 결정으로 표현하지 않는다.

1. capture에는 substantive `관찰`과 최소 한 개의 substantive `근거`가 모두 있어야 한다.
2. `context_cli.py capabilities --json`의 observation descriptor만 사용해 bounded candidate와 `claim` attestation을 만든다.
3. title·summary·tags·search metadata 교정은 `annotate`; claim/evidence 의미 변경은 새 successor OBS를 만든 뒤 `supersede`한다.
4. supersede 전에 `lifecycle prepare`의 exact old/new input만 보고 `same_claim` attestation을 만든다. 두 primary claim을 evidence pointer로 각각 가리킨다.
5. supersede는 successor create와 predecessor History 이동을 한 owner result와 한 final bundle에 포함한다.
6. 반증은 free-text reason을 가진 `invalidate`, 실제 재확인은 evidence ref를 가진 `reverify`를 사용한다. 오래됨만으로 retire하지 않는다.
7. mutation은 complete bundle의 exact digest 승인 뒤 core `transaction apply`만 호출한다. exact ID/path와 backlink guard를 우회하지 않는다.

CLI는 `../context/scripts/context_cli.py observation ...`을 사용한다. preview/prepare/attestation 단계에서는 filesystem을 쓰지 않는다.
