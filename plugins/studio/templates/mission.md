# mission — <제목>

> Producer와 crew가 공유하는 미션 계약이다. 목표나 완료 조건 변경은 owner gate다.

```json
{
  "mission_id": "mission-example",
  "objective": "무엇을 왜 달성하는지 한 문단으로 쓴다.",
  "done_when": "완료로 판정할 수 있는 관찰 가능한 조건을 쓴다.",
  "constraints": [
    "변경하면 안 되는 범위",
    "반드시 지켜야 하는 제품·운영 조건"
  ],
  "owner_gates": [
    "제품 방향 변경",
    "비가역 변경",
    "외부 공개"
  ],
  "autonomy": "역할 선택, 작업 배정, 검증 가능한 재작업은 Producer가 묻지 않고 진행한다."
}
```

## 배경

crew가 작업에 필요한 배경, 관련 파일과 기존 결정을 짧게 적는다. 실행 transcript나
호스트 내부 상태를 복제하지 않는다.
