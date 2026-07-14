# studio casting policy

Producer는 모든 crew를 부르지 않는다. mission을 분류하고, 가장 작은 조합을 소집한다.
`producer` 이름은 메인스레드 전용이다. crew role로 재사용하지 않는다.

## Crew catalog

| 영역 | crew | 책임 |
|---|---|---|
| 전략/기획 | `planner-a` | growth stance. 기회, 확장, 사용자 가치 |
| 전략/기획 | `planner-b` | risk stance. 실패 비용, 복잡도, 되돌림 가능성 |
| 전략/기획 | `strategist` | 제품 방향, 포지셔닝, 범위 선택 |
| 자료수집/분석 | `researcher` | 내부/외부 근거 수집과 해석 |
| 제품/설계 | `product-designer` | UX, 사용자 흐름, 정보구조 |
| 제품/설계 | `visual-designer` | 시각 품질, 레이아웃, 브랜드/톤 |
| 제품/설계 | `architect` | 기술 구조, 경계, API/CLI/schema 계약 |
| 제작/실행 | `dev` | 소프트웨어 구현 |
| 제작/실행 | `creator` | copy, visual, docs 등 artifact 제작 |
| 검수/검증 | `qa` | 재현 가능한 실패, 테스트, edge case |
| 검수/검증 | `reviewer` | 독립 승인/반려 판단 |
| 검수/검증 | `critic` | run의 delta/evidence/theatre 판정. rubric-backed system role |
| 기록/지식 | `curator` | wiki 기록 후보와 승격 gate 정리 |

## Default casts

`studio.py cast suggest <kind>`가 같은 기본값을 JSON으로 돌려준다.

| kind | 상황 | ritual | cast |
|---|---|---|---|
| `idea` | 아이디어 탐색 / 방향 모호 | `brainstorm` | `planner-a`, `planner-b`, `researcher`, `critic` |
| `product-direction` | 제품 방향 / 범위 결정 | `brainstorm` | `strategist`, `planner-a`, `planner-b`, `product-designer`, `critic` |
| `technical-design` | 기술 설계 필요 | `brainstorm` | `architect`, `dev`, `qa`, `critic` |
| `ui-build` | UI/UX 포함 제작 | `brainstorm` | `product-designer`, `visual-designer`, `dev`, `qa` |
| `content` | 콘텐츠/자료 제작 | `brainstorm` | `strategist`, `creator`, `visual-designer`, `reviewer` |
| `implementation` | 구현 | `pairing` | `dev`, `qa` |
| `launch` | 출시/완료 판단 | `brainstorm` | `qa`, `reviewer`, `curator` |

`critic`은 일반 persona가 아니라 ritual 검증 역할이다. `cast suggest`의 `participants`에는
broker에 넘길 persona만 들어가고, `critic: true`이면 critic rubric을 붙인다.
brainstorm persona의 설정 key는 `roleId || name`이다. `role`은 화면과 prompt에 쓰는 표시용
문구이므로 `설계`, `자료수집` 같은 현지화된 값으로 policy lookup을 하지 않는다.

## Tool policy

Studio native harness가 기본이며 위 crew catalog 전체를 외부 plugin 없이 사용할 수 있다. 외부 도구는 run parameter 또는 `.studio.yml`에 이름이 있을 때만 후보로 평가한다. 미설정 도구는 discovery/probe하지 않는다.

- worker 후보가 명시됨: `task-worker|task-github` 중 하나만 track lease. task-github 선택 시 task-worker 별도 lease 금지.
- reviewer 후보가 명시됨: risk/independence-required edge에서만 `session-review`를 고려하고 동일 episode를 재사용.
- wiki가 명시됨: 굳은 context/decision handoff에만 사용. runtime 상태를 복제하지 않음.
- 후보 없음: native cast와 critic/reviewer로 완주.

도구 선택 우선순위는 run parameter > `.studio.yml` > native다. explicit unavailable은 STOP, configured unavailable은 선언된 fallback을 따른다.

## Owner gates

Producer가 묻는 것은 줄인다. 다만 아래는 owner 전권이다.

- mission 계약 확정 또는 변경
- 신규 epic / 방향 전환
- 비가역 변경
- 외부 공개 또는 출시
- 예산 상향
- decision / rejected_decision wiki 승격
