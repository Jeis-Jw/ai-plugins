---
name: execute
description: Studio Producer가 미션을 수행할 때 host가 제공한 skill catalog의 공개 설명과 optional `.studio.yml` 정책으로 work, review, delivery skill을 선택하고, 선택한 SKILL.md를 따라 native crew와 함께 실행한다. "Studio로 실행", "Studio로 구현", "크루로 끝까지 진행", "execute" 요청에 사용한다.
---

# Execute

현재 대화의 root Producer 세션에서만 실행한다. leaf crew로 호출되면 작업을 재분해하거나
subagent를 만들지 말고 원래 Producer에게 반환한다.

Studio는 다른 플러그인의 이름, 적합성 규칙, CLI 순서, 상태 schema를 내장하지 않는다.
현재 host가 이미 제공한 skill catalog의 `name + description`이 유일한 discovery surface다.

## 1. 사용자 실행 정책 해석

consumer workspace 루트에서 필요한 route만 해석한다.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/studio_config.py" route \
  --path .studio.yml --kind <work|review|delivery>
```

`.studio.yml`의 `command`는 shell 명령이 아니라 사용자가 지정한 exact skill identifier다.
Studio가 알고 있는 도구 목록이나 dependency 선언이 아니다.

- `decision:producer-decision`: host catalog의 공개 설명으로 적합성을 판단한다.
- `decision:invoke-command`: 사용자가 exact skill을 선택했다. catalog에서 같은 identifier를
  확인하고 사용한다.
- `decision:native|skip`: 이 route에서는 외부 skill을 선택하지 않는다.
- `activation:auto`: configured command는 선호 후보다. description이 현재 미션과 맞을 때만
  선택하고, 맞지 않거나 catalog에 없으면 설정된 fallback을 적용한다.
- `activation:always`: 사용자의 exact 선택이다. 다른 skill로 바꾸지 않는다.
- `activation:never`: 해당 route의 skill 선택을 비활성화한다.
- 미설정 work/review route는 일반 host catalog selection을 사용한다.
- delivery는 외부 변경을 만들 수 있으므로 `enabled:true` 또는 현재 실행의 명시적 override가
  있을 때만 사용한다.

미설정·비활성 route를 위해 filesystem을 훑거나 plugin directory, executable, environment를
probe하지 않는다. host catalog에 없는 skill은 unavailable이다.

## 2. Description 기반 선택

route마다 다음 순서로 선택한다.

1. 현재 미션에서 필요한 능력과 관찰 가능한 완료 조건을 한 문장으로 고정한다.
2. host가 제공한 skill의 `name + description`만 비교한다. plugin 이름만 보고 용도를 추측하지
   않는다.
3. description이 무엇을 하는지와 언제 쓰는지를 현재 필요에 명시적으로 대응할 때만 후보로
   삼는다. 여러 후보가 맞으면 미션을 충족하는 최소 집합을 고른다.
4. 선택한 skill의 `SKILL.md`를 끝까지 로드한다. body의 precondition, negative trigger,
   authority, verification, closeout 계약을 그대로 따른다.
5. description과 body가 현재 미션에 맞지 않으면 선택을 취소하고 route fallback을 적용한다.

Studio는 선택한 skill의 실행법을 다시 설명하거나 부분 복제하지 않는다. Producer는 objective,
scope, 완료 조건, owner gate만 전달하고, artifact·state·receipt·evidence는 그 skill이 소유한
정본 참조만 보존한다.

## 3. Work

현재 작업에 맞는 work skill이 description으로 선택되면 root Producer가 그 skill을 직접
적용한다. 별도 orchestration crew에게 skill 선택을 위임하지 않는다.

선택된 work skill이 작업 분해, dependency, 격리, 검증 또는 통합을 소유한다면 그
`SKILL.md`의 lifecycle을 따른다. Studio는 자체 topology 기준이나 축약 lifecycle을 덧붙이지
않는다.

맞는 work skill이 없거나 route가 native면 Producer가 필요한 최소 crew를 직접 소집한다.
각 leaf는 배정된 산출물만 만들며 `execute`, 전체 재분해, sibling 작업 점유, nested subagent
생성을 하지 않는다.

## 4. Review

미션 완료 조건, 사용자 정책 또는 선택된 work skill이 별도 review를 요구할 때 host catalog에서
그 목적에 맞는 review skill을 같은 방식으로 선택한다. 단순 자기 점검과 독립 reviewer가 필요한
검토를 description보다 앞서 임의로 동일시하지 않는다.

- 선택한 review skill의 reviewer 분리, 재검토, approval, 기록 방식을 그대로 따른다.
- review handoff는 승인 완료가 아니다.
- blocking finding은 원래 작업을 수행한 addressable agent에게 돌려보낸다.
- 선택한 review skill이 완료를 판정하기 전에는 그 판정을 Studio가 합성하지 않는다.

적합한 review skill이 없고 review가 필요하면 native reviewer를 소집한다. review가 필요하지
않으면 route 자체를 사용하지 않는다.

## 5. Delivery

delivery는 명시적으로 활성화된 경우에만 configured exact skill을 사용한다. 선택된 skill의
description과 full instructions가 현재 대상과 요청된 외부 변경을 지원하는지 확인한 뒤 그
skill이 소유한 publish, merge, deploy, closeout 계약을 따른다.

Studio는 work 결과를 임의의 provider schema로 변환하거나 delivery 상태를 복제하지 않는다.
delivery가 꺼져 있으면 외부 skill을 조회하지 않고 local 결과로 끝낸다.

## 6. 완료 보고

- 선택한 work/review/delivery skill과 description이 미션에 맞았던 근거
- 적용된 사용자 config 또는 실행 override
- 역할별 agent handle과 적용된 model/effort
- 선택한 skill이 반환한 canonical result/ref와 미충족 gate
- 남은 owner gate와 위험

미측정 telemetry는 `null`로 두고 추정값을 실행 사실처럼 만들지 않는다.
