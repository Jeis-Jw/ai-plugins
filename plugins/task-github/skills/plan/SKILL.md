---
name: plan
description: Plan Mode로 작업 계획을 수립하고, 사령관 승인 후 Issue 코멘트에 기록한다. planned 플로우(normal/major 기어)의 첫 단계. 위키가 있으면 관련 결정·취지·시행착오를 주입한다. "task-github:plan", "계획 세워줘", "어떻게 구현할지 보여줘" 등의 요청에 실행하라.
---

# plan — Plan Mode 계획 수립

빌트인 **Plan Mode**(읽기 전용)로 코드베이스를 분석하고 실행 계획을 수립, 승인 후 Issue 코멘트에 기록한다.

## 입력

```
$ARGUMENTS: {N} [--full]   # 기본=normal용, --full=major용(+롤백·영향분석·ADR)
```

## 절차

### Step 1. Plan Mode 진입
`EnterPlanMode` (읽기 전용)

### Step 2. Issue 파악 (세션 컨텍스트 우선)
- 방금 `start`했으면 컨텍스트 재사용 (Issue·task 노드 재조회 금지)
- 끊겼으면: `gh issue view {N} --comments`

### Step 3. 관련 지식 주입 (위키 가용 시)
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
가용 시:
1. **연결 task 노드의 근거 따라 읽기** — 부모 루트 `## Wiki Context`의 task 노드가 가리키는 결정/취지:
```bash
wiki recall --read {TASK-...} --json     # task의 relations.decisions / intents 확보
wiki recall --read {DEC-...},{INT-...} --json
```
2. **키워드 recall** — 피해야 할 시행착오·미분류 관찰:
```bash
wiki recall "{Issue 키워드}" --stage 1 --limit 10 --json
```
- 기존 `decision` → 이미 결정된 방향 확인(재결정 금지)
- 기존 `trial_error` → 피해야 할 시행착오 반영
- 기존 `observation` → 분류 전 관찰 반영
- 미가용 → 스킵(오류 아님). Issue 본문만으로 계획.

### Step 4. 계획 수립 및 제시
기본 템플릿:
- Context (배경·목적)
- 태스크 목록 (순서)
- 변경 대상 (파일/모듈)
- 서브에이전트 위임 여부
- 리스크 / 결정 필요 지점
- 관련 지식 참조 (Step 3 결과)
- 예상 커밋 구조
- **검증 체크리스트** (plan↔verify 계약)

`--full` 추가:
- 롤백 계획
- 영향 범위 분석
- ADR 초안 (done 후 `capture decision`으로 승격 검토)
- "고려한 대안" — verify에서 `capture rejected_decision` 후보

### Step 5. 승인 → ExitPlanMode

### Step 6. Issue에 계획 기록
```bash
gh issue comment {N} --body "## 작업 계획

{계획 전문}"
```
**축약 없이 전문 기록.**

## 불변식
- **계획은 전문 기록** — run이 이 코멘트를 기준으로 작업한다.
- **검증 체크리스트 = plan↔verify 계약.** 반드시 산출.
- 승인 없는 plan은 없다.
- plan은 위키를 **읽기만**(recall). 캡처는 verify/done에서.
