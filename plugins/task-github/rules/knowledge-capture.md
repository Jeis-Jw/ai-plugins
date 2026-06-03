# 지식 기록 감사 규약

> 이 룰은 작업 중 나온 결정·취지·반려·시행착오·관찰을 위키에 남길지 판단하는 공통 절차다. 위키가 없어도 감사 자체는 수행하고, 결과는 최종 보고나 Issue 코멘트에 남긴다.
>
> **정본 경계**: `recorded`/`proposed`/`none` 어휘와 타입 판정의 정본은 이 룰(메커니즘)이다 — 위키 없이도 산출하므로. "모든 비 trivial 작업은 감사한다"는 의무 정본은 자동로드 operating policy(`CLAUDE.md` / `AGENTS.md`). DESIGN §13.1.1은 이 둘을 가리키는 포인터다.

---

## 1. 감사 시점

다음 중 하나라도 해당하면 작업 종료 전 **Knowledge Capture Audit**를 수행한다.

- `DESIGN.md`, `rules/`, `skills/`, `wiki/ssot/`, `wiki/runbook/`처럼 운영 규약이나 정책을 바꿨다.
- 대화 중 "우리는 이렇게 하자" 수준의 결정이 있었다.
- 대안을 비교하고 하나를 반려했다.
- 실수·누락·회귀·우회가 있었고 다음 작업자가 같은 함정을 피해야 한다.
- 현재 상태나 절차가 바뀌어 SSOT/runbook 갱신 여지가 있다.

감사 결과는 반드시 셋 중 하나로 끝난다.

| 결과 | 의미 |
|------|------|
| `recorded` | 규약상 자동 캡처 가능한 observation을 실제 기록했다. |
| `proposed` | 1급 기록 또는 living 문서 갱신 후보를 사령관에게 제안했다. |
| `none` | 기록할 장기 지식이 없다고 판단했고 이유를 남겼다. |

---

## 2. 타입 판정

| 신호 | 타입 | 처리 |
|------|------|------|
| 아직 분류 전인 발견, 작업 중 드러난 사실, 낮은 위험의 메모 | `observation` | 자동 캡처 가능 |
| 채택한 원칙·정책·설계 선택 | `decision` | 제안 후 확인 |
| 명시적으로 반려한 대안 | `rejected_decision` | 제안 후 확인 |
| 실수·누락·우회와 재발 방지 교훈 | `trial_error` | 제안 후 확인 |
| 현재 구조·상태의 정본 | `ssot` | 제자리 갱신 제안 |
| 반복 절차·운영 방법 | `runbook` | 제자리 갱신 제안 |

1급 노드(`task`/`decision`/`intent`/`rejected_decision`/`trial_error`) 캡처와 observation 승격은 제안 후 확인한다. 이 경계는 자동 캡처 편의보다 우선한다.

---

## 3. 실행 절차

1. **recall 먼저**: 기록 후보 주제로 기존 결정/관찰/시행착오/SSOT를 조회한다.
   ```bash
   wiki recall "{topic}" --stage 1 --limit 10 --json
   ```
2. **자동 가능한 observation 캡처**: 분류 전 발견이고 저위험이면 즉시 캡처한다.
   ```bash
   wiki capture observation \
     --title "{관찰명}" --summary "{무엇을 발견}" --tags {태그들} \
     --affects-paths "{관련 경로}"
   ```
   연결된 GitHub 업무 루트가 있으면 `--tasks owner/repo#ROOT`를 추가한다. 이슈가 없는 작업이면 `--tasks`를 생략한다.
3. **1급 기록 후보 제안**: decision/rejected/trial_error/ssot/runbook은 제목·요약·태그·관계·제안 사유를 적어 사령관 확인을 받는다.
4. **최종 보고에 감사 결과 포함**: `recorded`/`proposed`/`none` 중 하나와 근거를 남긴다.

---

## 4. Issue 코멘트/최종 보고 형식

```markdown
### Knowledge Capture Audit
| 후보 | 타입 | 처리 | 근거 |
|------|------|------|------|
| ... | observation | recorded: [[OBS-...]] | 분류 전 발견, 저위험 |
| ... | decision | proposed | 장기 운영 규칙 변경 |
```

기록할 것이 없으면:

```markdown
### Knowledge Capture Audit
- none: 단순 실행/검증만 있었고 장기 재사용 가능한 결정·관찰·교훈이 없음.
```
