# mission — <제목>

> 이 파일은 팀 자율성의 **정본**이다. 팀(producer 포함) 누구도 이 계약 밖의
> 자율을 행사하지 못한다. 계약 변경은 owner 게이트다.
> 아래 ```json 블록이 머신 상태 — `studio.py mission validate <이 파일>`로 검증한다.

```json
{
  "mission": "한 문단으로: 무엇을 왜 이룬다.",
  "kpi": [
    { "id": "k1", "goal": "측정 가능한 목표 1" },
    { "id": "k2", "goal": "측정 가능한 목표 2" }
  ],
  "done_when": "완료로 간주하는 조건 (owner 시연 승인 등).",
  "budget": { "total_tokens": 200000, "per_run_default": 40000 },
  "gates": ["mission-contract", "new-epic", "irreversible", "decision-promotion", "external-publish", "budget-raise"],
  "autonomy": "팀이 묻지 않고 해도 되는 것의 서술 — 초안·리서치·구현+검증·백로그 제안·역할 노트·run 예산 배분(한도 내)."
}
```

## 배경 (사람용 서술 — 파서는 무시)

미션의 맥락, 제약, 참고 링크 등을 자유롭게 적는다. 머신 상태는 위 json 블록만이다.
