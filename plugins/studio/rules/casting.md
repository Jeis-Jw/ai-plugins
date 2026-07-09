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

## Tool policy

- 과거 결정/맥락 필요: `wiki-markdown recall`.
- 지속 작업/상태 추적 필요: `task-github`.
- 독립 검토/승인 필요: `session-review`.
- durable/parallel execution이 필요: 향후 execution workflow tool.
- crew 상호작용 자체가 품질을 만들 때: studio ritual run.

## Owner gates

Producer가 묻는 것은 줄인다. 다만 아래는 owner 전권이다.

- mission 계약 확정 또는 변경
- 신규 epic / 방향 전환
- 비가역 변경
- 외부 공개 또는 출시
- 예산 상향
- decision / rejected_decision wiki 승격
