# studio — 살아있는 에이전트 팀

owner가 큰 미션을 주면, **producer**(메인스레드)가 **crew**(페르소나)를 백그라운드
**ritual run**으로 소집하고, 독립 **critic**이 delta 증거로 "비싼 연극"을 걸러낸다.
순차 파이프라인이 아니라 여러 track이 동시에 도는 포트폴리오 운영이다.

> 세계관: **owner가 studio에 mission을 주면, producer가 crew를 convene하고,
> critic이 연극을 걸러낸다.**

## 왜

`task-github orchestrate`는 *일이 정의된 후*의 실행 루프다. studio는 *일의 정의부터
시연까지*를 팀 안으로 들인다. 핵심은 에이전트 간 상호작용(기획끼리 브레인스토밍,
dev↔qa 공방)이 **실제 품질을 만드는가**이며, 그 판정을 critic + delta 증거로
객관화한다. 살아있음은 목적이 아니라 품질 수단이다.

## 구성

| 요소 | 위치 | 역할 |
|---|---|---|
| producer 스킬 | `skills/producer/` | 메인스레드 규약: 소집·중계·게이트, 직접 제작·판단 대리 금지 |
| studio CLI | `scripts/studio.py` | 결정적 상태: init·mission validate·backlog KPI 강제·run record(예산 원장)·evidence 집계·config(agent 정책) |
| agent 정책 | `.studio.yml` (repo 루트, `config scaffold`로 생성) | crew 서브에이전트의 model/effort 층별 설정 |
| 브로커 | `broker/brainstorm.workflow.js`, `broker/pairing.workflow.js` | ritual 실행체(Workflow) — transcript 릴레이, 순수 오케스트레이션(fs 없음) |
| crew | `crew/*.md` | 페르소나 데이터(name·role·prior·requested_tools·activation) — init이 `studio/crew/`로 복사 |
| critic rubric | `critic/rubric.md` | 검증 전용 계약 + anchor 규칙 |
| mission 템플릿 | `templates/mission.md` | 미션 계약(KPI·예산·게이트·완료기준) |

## 개념 (계약 층 — 은유 금지)

- **run I/O 계약**: `{ritual, participants, synthesis, minority, delta_log[{round, changed_what, anchor, evidence, rejected_alternative}], verdict{alive,reason}, proposals, cost, aborted}`
- **anchor**: delta가 실제로 닿는 대상 — `artifact | acceptance-criteria | risk | rejected-alternative | repro-test`. anchor 없는 delta는 delta가 아니다.
- **dry**: 유효 delta 없는 라운드. dry 2회 = 폐회.
- **theatre**: 팀 run인데 valid delta 0 → 연극 판정.

## agent model/effort 정책 (`.studio.yml`)

crew 서브에이전트가 어떤 모델·에포트로 돌지는 `.task-github.yml`과 같은 결의 repo
루트 설정파일 `.studio.yml`로 정한다. 4층 해석 (most→least specific):

```
run override(overrides) > rituals.<ritual>.<step> > roles.<role> > defaults > omit(세션 상속)
```

blank/null은 다음 층으로 넘어가고, 아무 층도 안 정하면 producer 세션 모델·에포트를
그대로 상속한다(하드코딩보다 안전한 기본값). producer가 `studio.py config get --json`으로
읽어 broker args의 `agentPolicy`로 주입하고, 브로커가 각 `agent()` 호출에 적용한다.
예: critic=high(연극 판정 날카롭게), summarizer=low(중립 압축은 싸게), diverge=low.

```bash
python3 plugins/studio/scripts/studio.py config scaffold   # .studio.yml 생성
python3 plugins/studio/scripts/studio.py config validate    # effort/model 값 검증
```

## 흐름

1. owner 미션 → producer가 `studio/missions/<slug>.md` 계약화 → **owner 게이트**.
2. 백로그 분해(KPI 링크 강제, `studio.py backlog check`).
3. producer가 페르소나·안건·rubric을 `args`로 실어 브로커 Workflow를 **백그라운드**
   소집. 회의형(brainstorm)은 무제한 병렬, 작업형(pairing)은 producer가 준비한
   track 워크트리에서 격리 실행.
4. 완료 회수 → `studio.py run record`(minutes + 예산 원장) → owner에 합성본+delta 보고.
5. 검증(baseline): 같은 소형 미션을 솔로 vs 팀으로 돌려 `studio.py evidence`로
   추가 delta를 센다. theatre면 리추얼 재설계.

## 게이트 (owner 전권)

미션 계약 확정·변경 / 신규 에픽·방향 전환 / 머지 등 비가역 / 결정·기각 wiki 승격 /
외부 공개(발행·배포·계정) / 예산 상향.

## 상태

v0.1.0 — MVP. 설계 정본은 이 repo 위키(INT/DEC studio) + `drafts/agent-team-concept.md`.
검증 테스트: `python3 plugins/studio/tests/test_studio.py`.

후순위(정의만, MVP 비활성): 리서치·디자인·마케팅 역할(`activation: gated`), 동적
채용(casting), standup/retro/demo 리추얼, task-github 작업형 백엔드 위임.
