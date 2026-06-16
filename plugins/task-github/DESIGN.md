# task-github — 설계·이관 SSOT (v3)

> **이 문서의 위상**
> 이 문서는 `task-github` 플러그인의 **단일 진실 공급원(Single Source of Truth)** 이다.
> "왜 이렇게 설계했는가(취지)"와 "무엇을 깨면 안 되는가(불변식)"를 담으며, 이어서 개발·확장·이관할 때 가장 먼저 읽는다.
>
> - **이 문서**(`DESIGN.md`): 설계 의도 · 아키텍처 · 불변식 · 위키 통합 · 확장/이관 가이드
> - **`README.md`**: 사용자 관점 사용법 요약
> - **`skills/*/SKILL.md`, `rules/*.md`, `agents/*.md`**: 실제 실행 명세(런타임이 읽는 코드)
> - **`CLAUDE.md` / `AGENTS.md` operating policy block**: 위키↔task **결합 규약(policy)** — 이 플러그인 밖, 자동로드 agent-entry 표면에 산다([§2](#2-4계층에서-task-github의-위치) 4계층 분리)
>
> 충돌 시 신뢰 순서: **실행 명세(SKILL/rules/agents) > DESIGN > README**. 결합 규약(policy)은 mechanism(이 문서)과 **다른 계층**이므로 경쟁하지 않고 보완한다.

> **상태**: 이 문서가 기술하는 v3 설계는 **구현 완료**됐고, v3.1에서 policy 슬롯을 자동로드 agent-entry 표면으로 옮겼다(위키 CLI `task` 타입, task-github 스킬·룰·에이전트, `CLAUDE.md`/`AGENTS.md` operating policy). 구현 순서·현황은 [§19](#19-구현-순서-완료됨) 참조. 위키 task 설계는 vault에 dogfood로도 기록돼 있다([§6.1](#61-위키-task-노드--설계-확정)).

---

## 0. 30초 요약

`task-github`는 **GitHub Issue/PR/Label을 작업 추적의 기본 자료구조로 삼아**, AI 에이전트가 작업을 점유·계획·실행·검증·완료하는 구조화된 자율 작업 프로토콜이다. 그리고 같은 마켓플레이스의 **`wiki-markdown` 결정 그래프와 `task` 노드로 연결**되어, 작업 흐름이 곧 지식 그래프를 키우도록 한다.

- **무엇으로**: GitHub Issue(작업 단위·트리) + Label(상태·성격) + Assignee(점유) + PR(코드 변경) + Issue 코멘트(실행 기록)
- **어떻게 분류하나**: 작업을 **3개 축**으로 분류 — 프로파일(환경) · 기어(파급력) · 플로우(승인 관문)
- **위키와 어떻게 엮나**: **업무 하나 = 위키 `task` 노드 1개 + GitHub 루트 이슈 1개**(1:1 다리). task 노드는 "어떤 결정·취지로 이 업무가 생겼나"를 요약하고 루트 이슈를 가리킨다. 루트 이슈는 그 task 노드를 메인 컨텍스트로 참조하며 상세를 담는다. 작업 중 나온 결정·시행착오·관찰은 위키 record로 승격한다.
- **계층 위치**: 이 플러그인은 **agent-neutral 메커니즘**이다. "언제·누가·무엇을 캡처/연결하는가"의 운영 규약은 자동로드 **agent-entry policy 표면**(`CLAUDE.md` / `AGENTS.md`)에 둔다.

핵심 한 문장: **"휘발되는 작업 히스토리·결정 맥락을 GitHub 기본 도구 위 얇은 프로토콜로 고정하고, 위키 `task` 노드를 다리 삼아 '결정 → 업무 → 실행'을 하나의 그래프로 잇는다."**

---

## 1. 해결하려는 문제 (취지)

AI 에이전트는 강력하지만 구조 없이 쓰면 세 가지가 반복적으로 무너진다.

| 문제 | task-github의 해법 |
|------|-------------------|
| 작업 히스토리가 남지 않음 | 모든 작업을 Issue로 추적, 실행 활동을 Issue 코멘트에 태그로 기록 |
| 결정의 맥락이 휘발됨 | `[결정]/[시행착오]/[관찰]` 태그 → 위키 결정 그래프로 승격 |
| 결정과 실제 작업이 끊김 | 위키 `task` 노드가 "결정 → 업무 → 이슈"를 잇는 다리 |
| 반복 작업마다 같은 지침을 재설명 | 프로파일·기어·플로우로 동작을 규약화, 스킬로 절차를 고정 |

설계가 따른 메타 원칙:

1. **GitHub 네이티브 우선** — 별도 DB·상태 파일을 만들지 않는다. Issue/Label/Assignee/PR이 곧 상태 저장소. 어디서든 `gh`만 있으면 복원 가능.
2. **빌트인 최대 활용** — Plan Mode, 서브에이전트 타입 등 기본 기능을 쓴다. 플러그인은 "언제 무엇을 호출하는가"의 규약만 제공.
3. **얇은 프로토콜** — 코드가 아니라 마크다운 명세(스킬·룰)로 동작을 정의. 이식성·가독성.
4. **그레이스풀 디그레이데이션** — 의존(위키, worktree, sub-issue)이 없어도 핵심 흐름은 끊기지 않는다.
5. **계층 분리** — 안정 자산(작업 프로토콜)과 변동 자산(위키 결합 운영 규약)을 분리한다([§2](#2-4계층에서-task-github의-위치)).

### 1.1 위키가 비워둔 자리를 채운다

이 플러그인은 진공에서 설계되지 않았다. `wiki-markdown`의 4계층 분리는 **작업환경 policy와 wiki knowledge를 분리하는 자리**를 명시적으로 예약했다. v3 최초 설계는 그 자리를 `wiki/ssot/agent-operating-model.md`로 보았고, v3.1에서는 자동로드 실패 문제를 해결하기 위해 `CLAUDE.md`/`AGENTS.md` operating policy block으로 옮겼다:

> "작업관리·GitHub Issue/PR 운영 규약은 현재 의도적으로 보류 상태다… 본 문서는 그 메커니즘을 특정 작업관리 시스템에 묶지 않기 위한 정책 자리만 예약한다."

예약된 채울 항목: **leaf issue 규약(Issue↔record 연결) · PR 리뷰 흐름 · promotion 트리거 · 캡처 권한 · GitHub template.** task-github는 이 슬롯을 채우는 구현체다. 더해, 위키는 이 연계를 위해 **`task` 타입(제3 범주)을 신설**까지 했다([§6.1](#61-위키-task-노드--설계-확정)) — 두 플러그인이 한 그래프로 만나도록 설계 단계에서 맞춘 짝이다.

---

## 2. 4계층에서 task-github의 위치

`wiki-markdown`의 핵심 결정은 **4계층 분리**다(`DEC-…-four-layer-separation`). task-github는 이 분리를 그대로 존중한다.

| 계층 | 위치 | task-github가 담는 것 |
|------|------|----------------------|
| **mechanism** | `plugins/task-github/` (이 플러그인) | 작업 프로토콜: 3축·라벨·스킬 절차·라벨 전이·브랜치 규약. **agent-neutral**(특정 위키·도구 이름에 묶이지 않음) |
| **policy statement** | 루트 `CLAUDE.md` / `AGENTS.md` operating policy block | 위키↔task 결합 규약: 캡처 권한, task 노드↔이슈 연결 포맷, promotion 트리거, PR 리뷰 흐름 ([§13](#13-자동로드-policy-슬롯에-채울-내용)) |
| **policy rationale** | 프로젝트가 정한 운영 이력 위치. 이 플러그인 개발 repo는 `wiki/context/decision/`에 dogfood 기록 | 왜 이 정책을 택했는가. 소비 프로젝트 wiki에 자동 생성하지 않음 |
| **knowledge** | `wiki/*` | 작업이 낳은 실제 노드(`task` + decision/trial_error/observation 등) |

> **왜 결합 규약을 플러그인 mechanism에 하드코딩하지 않는가**: 위키는 이미 "plugin은 구조 검증만, 의미 판정은 policy"라 결정했고(`DEC-…-promotion-threshold-in-plugin-spec`), "plugin CLI/스키마에 특정 도구 이름 없음"을 불변식으로 박았다(`DEC-…-plugin-agent-neutral-cli-schema`). task-github의 결합 규약(예: "define이 루트 이슈를 만들 때 task 노드를 함께 만든다")은 **변동 자산**(운영하며 바뀜)이고 **위키 타입에 의존**한다. 이를 task-github의 rules에 하드코딩하면 안정 자산과 변동 자산이 한 곳에서 함께 흔들린다. 다만 policy statement는 매 세션 자동 적용되어야 하므로, 소비 프로젝트 wiki가 아니라 `CLAUDE.md`/`AGENTS.md`에 둔다.

**경계의 실제 의미**:
- task-github의 SKILL/rules는 "**위키가 있으면** task 노드를 만들어 이슈와 잇고, 관련 지식을 recall하고, 발견한 결정을 capture **하도록 위임**한다"까지만 쓴다 — *어떤 타입으로, 누가, 어떤 임계로* 연결·승격할지의 구체 규약은 자동로드 operating policy를 참조한다.
- 위키가 없는 환경으로 단독 이관해도 task-github는 mechanism만으로 완전 동작한다(policy 미적용 = 그레이스풀 스킵).

---

## 3. 디렉토리 구조와 구성요소 맵

```
plugins/task-github/
├── .claude-plugin/
│   └── plugin.json          # 매니페스트 (name: task-github)
├── .codex-plugin/
│   └── plugin.json          # Codex 매니페스트 (skills discovery + UI metadata)
├── README.md                # 사용자용 가이드
├── DESIGN.md                # ★ 이 문서 — 설계/이관 SSOT
├── rules/                   # 프로토콜 규약 (스킬이 공유하는 헌법)
│   ├── task-protocol.md     #   역할·프로파일·기어·플로우·태그·에러복구·완료조건
│   ├── workflow.md          #   GitHub/Git 워크플로우·라벨 체계·상태 전이·브랜치·커밋·PR
│   ├── dependencies.md      #   GitHub Issue dependencies 기반 선후관계·차단 규약
│   ├── knowledge-capture.md #   작업 종료 전 지식 기록 감사 규약
│   └── wiki-bridge.md       #   ★신규: 위키 감지·task 노드 연결·호출 규약(mechanism 측). 결합 정책은 자동로드 operating policy 참조
├── skills/                  # 호출 단위 동작 (10종)
│   ├── setup/SKILL.md       #   git+GitHub 초기화 (+위키 vault 부재 시 init 제안)
│   ├── open/SKILL.md        #   Issue 읽기 전용 로드 (+연결된 task 노드/결정 표시)
│   ├── define/SKILL.md      #   업무 정의: 루트 이슈(+트리) + ★task 노드 생성·연결
│   ├── start/SKILL.md       #   리프 Issue 점유 + 기어 판단 (+task 노드 맥락 주입)
│   ├── plan/SKILL.md        #   Plan Mode 계획 수립 (+recall 주입)
│   ├── run/SKILL.md         #   실행 (+observation 즉시 캡처)
│   ├── verify/SKILL.md      #   검증 리포트 (+태그→타입 캡처, refresh 게이트)
│   ├── done/SKILL.md        #   PR 생성/close (+drift 검사, ADR 승격)
│   ├── review/SKILL.md      #   PR 검증 (+PR↔decision cross-link)
│   └── merge/SKILL.md       #   PR 머지 (+task 노드 done 전이, 영향 record verified_at 안내)
└── agents/
    └── pr-verifier.md       # PR 검증 전용 서브에이전트
```

**3계층 구조**(rules=헌법 / skills=함수 / agents=외부감사)는 v2와 동일. 신규는 `rules/wiki-bridge.md` 하나 — 위키 **감지·task 노드 연결·호출의 메커니즘**만 담고, *결합 정책*은 자동로드 operating policy를 가리킨다.

### 매니페스트 & 마켓플레이스 등록

`plugin.json`:
```json
{
  "name": "task-github",
  "version": "0.3.1",
  "description": "GitHub 기반 자율 작업 프로토콜 — Issue 추적·Plan Mode·PR 검증을 wiki-markdown task 노드로 결정 그래프와 연계"
}
```

루트 `.claude-plugin/marketplace.json`의 `plugins` 배열에 추가:
```json
{ "name": "task-github", "source": "./plugins/task-github", "version": "0.3.1",
  "description": "GitHub 기반 자율 작업 프로토콜 — wiki-markdown task 노드 연계" }
```

Codex 배포는 `.codex-plugin/plugin.json`이 `skills: "./skills/"`를 노출한다. Claude/Codex 매니페스트와 marketplace의 version은 항상 동기화한다.

---

## 4. 핵심 개념 — 3개의 분류 축

작업은 서로 **직교하는 3개 축**으로 분류된다. 이 셋의 조합이 동작 전체를 결정한다.

```
프로파일(환경)  ×  기어(파급력)  →  플로우(승인 관문)  →  스킬 시퀀스  →  위키 연동 강도
   solo/team       micro/normal/major   express/planned                    (기어가 게이트)
```

### 4.1 프로파일 — 환경

`CLAUDE.md` 또는 `AGENTS.md` operating policy block에 `Profile: solo` 또는 `Profile: team`으로 명시한다. **미지정 시 `solo`.**

> **v2→v3 변경**: 기본값을 `team` → **`solo`** 로 바꾼다. 이 워크스페이스의 위키가 자신을 "1인 개발자 + AI 에이전트"로 규정하므로(`wiki/README.md`), 1인 흐름이 기본이 맞다. team은 협업 환경에서 명시 선택.

| 항목 | solo (기본) | team |
|------|------|------|
| 플로우 판단 단위 | 2단 (micro / **full**) | 3단 (micro / normal / major) |
| 기어 **라벨** | `gear:micro/normal/major` (공통) | `gear:micro/normal/major` (공통) |
| 지식 기록(위키) | 권장 | 권장 |
| 서브에이전트 | 선택 | 적극 고려 |
| `review` 머지 | 자동 허용 | `--auto-merge` 명시 시만 |

> `full`은 라벨/기어가 아니라 **solo 프로파일의 플로우 판단 단위**다(micro→express / full→planned --full). 기어 **라벨**은 프로파일과 무관하게 항상 `gear:micro|normal|major` — `gear:full`은 없다([rules/task-protocol.md](rules/task-protocol.md) §1·§2).

- solo의 `full`은 team의 normal+major를 통합한 **플로우 판단 단위**(기어 라벨이 아님). solo는 "가볍게(micro→express) / 제대로(full→planned --full)" 2단으로 플로우를 가른다. 라벨은 그래도 파급력대로 `gear:normal|major`.
- 프로파일은 **같은 스킬을 다르게 동작**시키는 게 아니라, 호출자의 **판단 강도**를 조절한다.

### 4.2 기어 — 파급력(영향 반경)

> **★ 가장 중요한 설계 결정**: 기어는 **영향 반경(파급력)** 으로만 판단한다. 크기(파일 수·커밋 수·코드 라인)는 **판단 근거가 아니다.**

| 기어 | 영향 반경 | 예 |
|------|----------|-----|
| **micro** | 자기 파일 내부만 영향 | 오타, 주석, 소규모 로직 수정 |
| **normal** | 자기 서비스 내부 영향 | 신규 로직, 일반 기능 개발 |
| **major** | 외부 계약(contract) 변경 | DB schema, API spec, 파일 포맷, CLI, public 인터페이스 |

판단 규칙(불변식): **애매하면 상위 기어**, 잘못 판단 시 승격(강등 금지), 여러 기어 섞이면 **최고 기어**. solo는 *플로우*만 micro/full로 통합하며, 기어 **라벨**은 프로파일과 무관하게 micro/normal/major를 쓴다(`gear:full` 없음).

> 왜 크기가 아니라 파급력인가: 문서 보완처럼 파일이 많아도 영향이 자기 안에 갇히면 micro. 한 줄짜리 API 시그니처 변경은 외부 계약을 바꾸므로 major. **"설계·규약·계약을 바꾸는가"가 위험의 본질**이며 크기는 위험과 비례하지 않는다.

### 4.3 플로우 — 승인 관문

플로우는 **승인 관문의 유무**로 나뉘며 기어와 **1:1 매핑**된다.

| 플로우 | 구성 | 적용 기어 | plan 산출물 |
|--------|------|---------|-----------|
| **express** | `run` | micro | (없음) |
| **planned** | `plan → 승인 → run → verify` | normal | 실행계획 + 검증계획 |
| **planned (`--full`)** | `plan → 승인 → run → verify` | major | 위 + 롤백계획 + 영향 범위 분석 + ADR 초안 |

- **승인 없는 plan은 없다.** plan을 수립하면 반드시 Plan Mode 승인 관문을 거친다.
- plan과 verify는 **검증 체크리스트**를 매개로 계약 관계다.

### 4.4 기어 ↔ 플로우 ↔ 위키 연동

```
micro   →  express           →  run {N}                위키: 스킵(자기완결)*
normal  →  planned           →  plan {N}               위키: task 노드 + recall + capture
major   →  planned --full    →  plan {N} --full        위키: task 노드 + recall + capture + intent연결 + rejected + drift + ADR
```
\* micro라도 `[관찰]/[시행착오]`를 발견하면 기록은 권장(저비용 capture). task 노드는 업무(루트 이슈) 단위라, 단발 micro 수정은 보통 만들지 않는다. [§6.6](#66-캡처--승격-정책).

**오버라이드(매핑 이탈)는 양방향 재확인**: 하향(major를 express로)은 외부 계약을 검증 없이 진행하는 위험, 상향(micro를 planned로)은 과도한 오버헤드 — 둘 다 사령관이 재확인.

---

## 5. 라벨 · Issue 트리 · dependency · 태그 어휘

### 5.1 라벨 체계 — 2계열

**① 상태 라벨 (3종, 교체/제거)** — close/merge 시 제거.

| 라벨 | Issue | PR |
|------|-------|-----|
| `in-progress` | 코딩 중 | 재작업 중 |
| `in-review` | PR 제출, 리뷰 대기 | 리뷰어 검토 중 |
| `changes-requested` | 피드백 반영 필요 | 작성자 조치 필요 |

**② 기어 라벨 (3종, 1개 필수, 영구 유지)** — close/merge 후에도 히스토리로 남는다.

| 라벨 | 의미 | 색상 |
|------|------|------|
| `gear:micro` | 자기 파일 내부 | `0E8A16` |
| `gear:normal` | 자기 서비스 내부 | `FBCA04` |
| `gear:major` | 외부 계약 변경 | `D93F0B` |

> **불변식**: 상태 라벨은 "교체만", 기어 라벨은 "한 번 붙이면 유지". 정리 로직(done/review/merge)은 **상태 라벨만 제거하고 `gear:*`는 절대 건드리지 않는다.**

### 5.2 업무 · Issue 트리 · task 노드

**업무(work)** = 하나의 의미 있는 작업 덩어리. 위키 `task` 노드 1개 + GitHub **루트 이슈** 1개가 1:1로 대응한다. 루트 이슈는 분해 여부에 따라 컨테이너이거나 단일 리프다.

```
        위키 task 노드 ◄──1:1 다리──► GitHub 루트 이슈
         (업무 요약·근거)              (업무 상세)
                                          │ (분해되면)
                                   ┌──────┼──────┐
                              리프 이슈  리프 이슈  리프 이슈
                              (실제 점유·작업 단위)
```

| 종류 | 정의 | 작업 가능? | task 노드 |
|------|------|----------|----------|
| **루트 이슈** | 업무의 최상위 이슈(컨테이너 또는 단일 리프) | 컨테이너면 ✗ / 단일이면 ✓ | **여기에 task 노드 1:1 연결** |
| **컨테이너 이슈** | 자식 있음 | ✗ `start` 차단 | (루트면 task 노드 보유) |
| **리프 이슈** | 자식 없음 | ✓ `start`로 점유 | 루트의 task 노드를 상속(자체 캡처 안 함) |

- 트리 생성/분해·task 노드 생성은 `define`, 점유·작업은 `start` 이하(역할 분리).
- **task 노드는 업무(루트) 단위**다 — 리프마다 만들지 않는다. 리프는 부모 루트의 task 노드를 통해 위키와 이어진다.

### 5.3 Issue dependency — 실행 선후관계

GitHub sub-issue는 **분해 구조**만 나타낸다. 하위 작업의 실행 순서와 병렬 가능 여부는 GitHub **Issue dependencies**가 정본이다([rules/dependencies.md](rules/dependencies.md)).

| 관계 | 의미 | task-github 동작 |
|------|------|------------------|
| dependency 없음 | 선행 제약 없음 | 병렬 가능으로 간주 |
| `#B blocked_by #A` | B는 A 완료 뒤 실행 | `start`/`run`/`done`/`merge`에서 열린 A가 있으면 차단 |
| `#A blocking #B` | A가 B의 진행을 막음 | A 완료 후 B가 ready인지 안내 |

`parallel`/`sequential` 라벨은 두지 않는다. A/B는 병렬, C는 A+B 뒤 같은 혼합 DAG를 정확히 표현하려면 dependency 관계가 필요하다.

### 5.4 Issue 코멘트 태그 어휘 (위키 7+1타입과 정렬)

실행 중 의미 있는 활동을 Issue 코멘트에 **태그**로 남긴다. 이것이 세션 간 맥락 복원과 위키 승격의 원천이다.

| 태그 | 의미 | 위키 타입 | 캡처 |
|------|------|----------|------|
| `[결정]` | 여러 선택지 중 하나 선택 | `decision` | 제안 후 확인 |
| `[시행착오]` | 실패·우회·안티패턴 | `trial_error` | 제안 후 확인 |
| `[관찰]` ← **신규** | 분류 전 발견(아직 어디 둘지 모름) | `observation` | **자동**(저위험) |
| `[사실]` | 재검증 가능한 현재 상태 사실 | `ssot` 갱신 / `observation` | 제안 후 확인 |
| `[질문]` | 사령관 확인 필요 | — | 캡처 안 함 |
| `[중단]` | 복구 불가 실패 기록 | — | 캡처 안 함 |

> **v2→v3 변경**: 옛 `[사실]→fact`의 `fact` 타입이 새 위키에 없다. "재검증 가능한 현재 상태"는 `ssot`의 본질과 겹치므로 ssot로, 아직 분류가 안 서면 `[관찰]→observation`으로 흘려보내고 나중에 승격. 옛 `pattern`은 ssot/decision으로 흡수. 신규 `[관찰]`은 위키의 핵심 기능(분류 전 발견)을 작업 흐름에 연결한다. 이 태그들은 **작업 중 부수적으로 나오는 지식**이고, 업무 자체의 다리는 `task` 노드가 담당한다(아래 §6).

---

## 6. 위키 통합 (핵심 장)

task-github ↔ wiki-markdown은 **비대칭·감지 기반 결합**이다. task-github가 wiki를 조건부 호출하고, wiki는 task-github를 전혀 모른다(역방향 의존 금지). 연결의 중심은 위키의 **`task` 노드**다.

```
   intent ◄── decision ◄── task 노드 ──relations.tasks──► GitHub 루트 이슈
  (취지)     (결정·근거)   (업무 요약)   ◄──"## Wiki Context"──  (업무 상세)
                              │                                    │
                              └─ 상태: 활성 / done (경로)            └─ 상태: open/labels/closed
                                 연결 시 GitHub이 정본, task-github가 done 투영·reconcile
```

### 6.1 위키 `task` 노드 — 설계 확정

위키에 **`task` 타입(record/living과 나란한 제3 범주)** 이 신설되었고, 이 설계는 이미 위키 vault에 dogfood로 기록되어 있다(`DEC-…-task-third-category`, `DEC-…-task-binary-state-github-sot` 등 6개 노드).

| 속성 | 값 |
|------|-----|
| 범주 | 제3 범주 — 제자리 갱신(living 성질) + 관계 보유(record 성질) |
| 그래프 위치 | **순수 잎** — outbound만, 아무도 task를 저장 edge로 가리키지 않음(역방향은 파생 백링크) |
| relations | `intents` / `decisions` / `ssot` / `tasks`(외부 작업 ref: Issue/PR 등) |
| ID | `TASK-YYYY-MM-DD-HHMMSS-<slug>` |
| 경로 | `wiki/task/` (완료 시 `wiki/task/done/`) |
| 상태 | **이진**: 활성 vs 완료(경로 이동) |
| CLI | `capture task` / `complete` / `reopen` (위키 CLI v0.3.0 이후 구현됨 — [§6.8](#68-위키-cli-task-지원-구현-완료)) |

### 6.2 업무 ↔ 이슈/PR 참조 다리 (핵심 자료구조)

task-github로 정의한 **한 업무 = task 노드 1개 + 루트 이슈 1개.** 둘이 서로를 가리켜 양방향 다리를 이룬다. 단, 위키 task 자체는 GitHub 없이도 생성·수행·완료 가능한 작업지시서형 handoff 노드다. task-github는 위키가 가용할 때 그 task를 source/context로 읽고 GitHub 실행 단위와 연결하는 optional adapter다.

- **task 노드 → 외부 작업 기록**: `relations.tasks: [owner/repo#N]` (루트 이슈 번호, 또는 `github:owner/repo#N`). GitHub은 이슈·PR이 번호공간을 공유하므로 PR도 동일한 `#N` 형식으로 가리킨다. task는 record 성질이라 외부 작업 ref를 **가질 수 있다** — 이것이 task 노드를 신설한 핵심 이유다(아래 박스).
- **task 노드 → 결정/취지**: `relations.decisions`, `relations.intents` (이 업무가 어떤 결정·취지에서 나왔나 = 보조 컨텍스트의 정본).
- **이슈/PR → task 노드**: 루트 이슈 본문 `## Wiki Context`에 task 노드 basename을 **메인**으로, 관련 결정을 **보조**로 기록한다. PR은 루트 이슈 링크 또는 동일 Wiki Context를 둔다.

> **왜 task 노드가 비대칭 문제를 푸는가**: `intent`/`ssot`는 hub(또는 living)라 `relations.tasks` 역링크를 못 가진다. 그래서 "에픽 ↔ intent"를 직접 이으려 하면 단방향이 된다. `task`는 record 성질이라 외부 작업 ref를 들 수 있어 **양방향 탐색 다리**가 된다. 역방향 조회("이 결정이 낳은 업무는?")는 task의 outbound 관계를 **파생 백링크**(`recall --backlinks-of DEC-x`)로 잡으므로, decision/intent 스키마는 손대지 않는다(순수 가산).

**요약 ↔ 상세 분리** (중복처럼 보이는 것의 해소):

| | 위키 `task` 노드 | GitHub 루트 이슈 |
|---|---|---|
| 입자도 | **요약** (업무 개요) | **상세** (범위·완료조건·체크박스·자식 이슈) |
| 본질 | **왜 이 업무가 생겼나** (결정·취지·제약 묶음 handoff) | **무엇을·어떻게** (실행) |
| 관점 | 위키 탐색자: "어떤 결정 → 어떤 업무" | 실행자: 구현 디테일 |
| 변경 빈도 | 거의 없음 | 지속(상태·코멘트·진행) |

→ 루트 이슈는 task 노드 + 결정 컨텍스트를 **재료로 상세하게** 구성한다.

**루트 이슈 `## Wiki Context` 포맷**(정확한 형식은 policy [§13.2]):
```markdown
## Wiki Context
**메인**: [[TASK-2026-…-payment-bff-migration]] — 이 업무의 정의(요약·근거)
**보조**:
- [[DEC-2026-…-move-auth-to-bff]] — 근거가 된 결정
- [[INT-2026-…-signup-speed]] — 상위 취지
```

### 6.3 감지 · 호출 메커니즘 (`rules/wiki-bridge.md`)

옛 `[ -d "plugins/wiki/obsidian" ]` 하드코딩 경로를 폐기하고:

| 단계 | 방식 |
|------|------|
| **감지** | 프로젝트 로컬 `./wiki/` vault 디렉토리 존재 확인 (마켓플레이스 설치 경로와 무관, 신뢰 가능) |
| **호출** | `wiki` 스킬에 위임(자기 `${CLAUDE_SKILL_DIR}` 해석) 또는 `python3 <wiki-cli> … --json` 직접 실행 |
| **반응** | JSON `{ok, data}` + exit code로 분기. 파싱 불필요(결정적 출력) |
| **미감지** | 모든 위키 호출 **스킵(오류 아님)**. 지식은 Issue 코멘트 태그로만 — 나중에 위키 구축 시 수동 이관 가능 |

> **불변식**: 위키 미감지는 정상 경로다. 어떤 스킬도 위키 부재로 **중단되지 않는다**. (그레이스풀 디그레이데이션)

### 6.4 통합 터치포인트 맵 (어느 스킬에서 무엇을)

| 스킬 | 위키 연동 | 동작 | 기어 게이트 |
|------|----------|------|-----------|
| `setup` | init 제안 | `./wiki/` 없고 위키 플러그인 있으면 `wiki init` 제안 | — |
| `open` | recall(읽기) | 루트 이슈의 `## Wiki Context` → task 노드 + 결정 표시. 리프면 부모 루트의 task로 거슬러 표시 | 전기어 |
| `define` | **★task 노드 생성** | 루트 이슈 생성 시 ①관련 결정 recall ②`capture task --decisions … --intents … --tasks owner/repo#N` ③루트 이슈 본문 `## Wiki Context`에 task 노드 링크 | 전기어 |
| `start` | recall(맥락 주입) | 리프 점유 시 부모 루트의 task 노드 + 연결 결정을 세션 컨텍스트로 주입 | normal/major |
| `plan` | recall(적극) | task 노드의 `decisions`/`intents` 따라 읽기 + 키워드 recall로 trial_error/observation 주입; "고려한 대안"=rejected 후보; ADR초안=decision 후보 | normal/major |
| `run` | capture observation | `[관찰]` 발견 즉시 `capture observation`(자동, `--tasks` 역링크) | normal/major |
| `verify` | **capture(핵심)** | 태그→타입 캡처 제안, observation 승격 검토, `refresh --strict` 무결성 게이트 | normal/major |
| `done` | **drift + ADR** | PR diff→`refresh --check changed-path-stale`; major면 ADR→`capture decision`(`--tasks`로 task와도 연결) | normal/major |
| `review` | cross-link | pr-verifier가 PR↔task 노드의 연결 decision 교차 확인 | — |
| `merge` | **task done 전이** | 루트 이슈가 close되면(마지막 PR 머지) 연결 task 노드를 `complete`로 `done/` 전이 + 영향 record `verified_at` 안내 | — |

### 6.5 task 노드 상태 동기화 (정본은 하나)

위키 task 노드 상태(활성/done)와 GitHub 이슈 상태가 같은 사실을 이중으로 들면 드리프트한다. 그래서 **정본을 하나로** 둔다:

| 모드 | phase 정본 | task-github의 동기화 |
|------|-----------|---------------------|
| **독립** (위키만, 작업 플러그인 없음) | 위키 | 세션에서 작업 후 `complete`/`reopen` |
| **연결** (task-github 사용) | **GitHub 루트 이슈/PR 흐름** | 루트 이슈 close 시 task 노드 `complete`(→`done/`). 밖에서 닫힌 경우 reconcile |

- 위키가 추적하는 건 **이진(활성/done)** 뿐이라, 동기화할 전이는 **"루트 이슈 close → task complete" 하나(단조)**. 상세 phase(in-progress/in-review/changes-requested)는 위키가 **안 들고** 이슈에 위임 → 복제 안 하니 드리프트가 없다.
- **reconcile**: 밖에서 이슈가 닫힌 out-of-band 변경은 task-github가 `gh`로 이슈 상태를 읽어 위키를 정렬한다(위키의 `refresh` 드리프트 idiom과 동형: 감지→정렬). **위키 CLI는 `gh`를 모른다** — reconcile 주체는 task-github.
- 머지 없이 닫힌 이슈(won't-fix/중복)도 `done/`로 보낸다(터미널). "이 업무 자체가 잘못 정의됐다"는 위키 `retire`로 별도 처리(완료 ≠ 폐기).

### 6.6 캡처 / 승격 정책 (위키 기존 결정과 정합)

위키는 **자동 승격을 이미 반려**했다(`REJ-…-promotion-auto-judgment`; `DEC-…-promotion-threshold-in-plugin-spec`: "plugin은 구조 검증만, 판정은 policy"). task-github는 이를 존중한다.

| 대상 | 방식 | 근거 |
|------|------|------|
| `task` 노드 생성(`define`) | **제안 후 확인** | 업무 정의 = 1급 노드 |
| `observation` 캡처 | **자동** | 저위험·분류 전, AI 주도 문서화 취지 |
| `decision`/`intent`/`rejected`/`trial_error` 캡처 | **제안 후 확인** | 그래프 1급 노드, 되돌리기 비용 |
| 승격(observation→TRI/DEC + retire) | **항상 제안** | 위키가 자동 판정을 반려함 |

> 구체적 임계·권한(누가 어떤 타입을 언제)은 mechanism이 아니라 **policy**의 몫이다([§13](#13-자동로드-policy-슬롯에-채울-내용)). 이 표는 mechanism이 보장하는 **기본 강도**만 규정한다.

### 6.7 드리프트 탐지 (신규 능력)

위키의 `affects_paths` + `refresh --check changed-path-stale`는 **코드 변경이 어떤 위키 문서를 낡게 만들었는지** 자동 포착한다. v2 설계엔 없던 기능.

```bash
# done/merge 시 PR이 건드린 파일 목록을 위키에 던진다
gh pr diff {PR} --name-only > /tmp/changed
python3 <wiki-cli> refresh --check changed-path-stale --changed-path "$(paste -sd, /tmp/changed)" --json
# → affects_paths 글롭에 걸리는데 verified_at이 갱신 안 된 ssot/runbook/trial_error/observation 리포트
```
→ 리포트된 문서는 `verified_at` 갱신(여전히 유효) 또는 supersede(낡음) 대상. 판정은 사령관/policy.

### 6.8 위키 CLI task 지원 (구현 완료)

위키 CLI(`wiki_cli.py`)는 v0.3.0 이후 `task` 타입과 `complete`/`reopen`을 **구현 완료**했다:
- `capture task` (타입 등록 + `relations`: intents/decisions/ssot/tasks 허용, 경로 `wiki/task/`)
- `complete <basename>` / `reopen <basename>` (활성 ↔ `done/` 경로 이동)
- `refresh` 스키마에 task 타입 반영, `templates/task.md`, 테스트(WikiCliTaskTests)

→ task-github의 위키 연동은 이 기능 위에서 동작한다. 위키 타입·관계의 정본은 `wiki-markdown`의 `wiki-data-model`이다.

---

## 7. 스킬 카탈로그 (10종)

각 스킬은 **순수함수에 가깝게** 설계된다: 인자가 없으면 기본 동작, **인자가 동작을 결정**. 호출자의 상태(기어·플로우)는 호출자가 인자로 번역해 전달.

```
[초기화]  setup
[조회]    open
[구조화]  define   ← 여기서 업무 정의 = 루트 이슈 + task 노드
[점유]    start
[실행]    plan → run → verify        (express는 run만)
[종료]    done
[리뷰]    review → merge             ← merge에서 task 노드 done 전이
```

아래는 v2 대비 **위키 터치포인트**를 굵게 표기. (위키 무관 핵심 동작은 v2와 동일하므로 요약.)

### 7.1 `setup` — git/GitHub 초기화
- **입력**: `[owner]`. **동작**: `git init`→첫 커밋→`gh repo create … --private --source=. --push`. 멱등(이미 구성 시 중단).
- **위키**: `./wiki/` 없고 위키 플러그인 감지되면 `wiki init` 제안(강제 아님).

### 7.2 `open` — Issue 읽기 전용 로드
- **입력**: `{N}`(필수). **동작**: `gh issue view`+GraphQL(부모/자식/진행률)+REST dependency(`blocked_by`/`blocking`)+연결 PR. 상태/기어 라벨 분리 표시. **부작용 0.**
- **위키**: 루트 이슈면 본문 `## Wiki Context`의 task 노드+결정을 `recall --read`로 브리핑. 리프면 부모 루트의 task 노드로 거슬러 표시. 읽기만.

### 7.3 `define` — 업무 정의 (루트 이슈 + task 노드)
- **입력 3모드**: (없음) 대화→업무 / `{N}` 분해 기준 요청 / `{N} {기준}` 분해.
- **동작**: `skills/define/scripts/create_issue_tree.py`가 루트=`gh issue create`, 서브=GraphQL `createIssue(parentIssueId)`, 필요 시 REST Issue dependency 생성을 한 spec에서 처리한다. **등록 전 사령관 확인. 자동 분해 금지. 기어 라벨 안 붙임**(start의 책임).
- **위키(핵심)**: 업무의 루트 이슈를 만들 때 task 노드를 함께 만들어 잇는다 —
  1. 관련 결정/취지 `recall` (이 업무가 어떤 결정에서 나오는지)
  2. 루트 이슈 생성 → 이슈 번호 확보
  3. `capture task --title … --summary <업무 요약> --decisions <관련 DEC> --intents <상위 INT> --tasks owner/repo#<루트이슈>` (제안 후 확인)
  4. 루트 이슈 본문 `## Wiki Context`에 task 노드(메인)+결정(보조) 링크
  5. (이슈 상세는 task 노드 요약 + 결정 컨텍스트를 재료로 풍부하게)
- **불변식**: task 노드는 **업무(루트) 단위 1:1**. 리프마다 만들지 않는다. brainstorm으로 나온 단위 상세설계는 서브이슈 본문 또는 해당 단위 실행 중 캡처되는 DEC/OBS에 둔다. dependency는 GitHub Issue dependencies가 정본이고, 없으면 병렬 가능으로 본다.

### 7.4 `start` — 리프 점유 + 기어 판단
- **입력 2모드**: `"제목" [설명]`(생성+점유, **micro 단발 전용** — normal/major 업무는 define 경유) / `{N}`(기존 점유).
- **동작**: ①기어 판단(파급력) ②컨테이너 차단/이슈 생성 ③dependency 차단 체크(`blocked_by` 중 open 있으면 차단) ④점유 가능 판단(`in-progress`/`in-review`면 차단) ⑤`gh issue edit --add-assignee @me --add-label in-progress --add-label gear:{micro|normal|major}` ⑥(코드 변경 시) 워크트리 ⑦다음 단계 권장. (라벨은 항상 micro/normal/major — `gear:full` 없음; solo의 `full`은 플로우 단위일 뿐.)
- **위키**: 모드 B에서 점유한 리프의 부모 루트에 연결된 task 노드 + 그 결정/취지를 세션 컨텍스트로 주입(재조회 최소화). 모드 A(micro 단발)는 주입 생략.
- **불변식**: 기어 판단·라벨 부여의 **단일 책임 지점**. 컨테이너 차단. 열린 blocker가 있는 이슈 점유 금지. 점유 중복 방지.

### 7.5 `plan` — Plan Mode 계획 수립
- **입력**: `{N} [--full]`.
- **동작**: ①`EnterPlanMode` ②세션 컨텍스트 우선 ③**`recall` 주입** ④계획 제시(Context/태스크/변경대상/서브에이전트/리스크/관련지식/커밋구조/검증체크리스트; `--full`이면 +롤백/영향분석/ADR초안) ⑤승인→`ExitPlanMode` ⑥**계획 전문**을 Issue 코멘트로 기록.
- **위키**: task 노드의 `decisions`/`intents`를 따라 읽어 기존 방향을 확인하고, 키워드 `recall`로 trial_error/observation 주입(재결정·재시행착오 방지). plan의 "고려한 대안"은 verify에서 rejected_decision 후보.
- **불변식**: 계획 전문 기록(축약 금지). 검증 체크리스트 = plan↔verify 계약. 승인 없는 plan 없음.

### 7.6 `run` — 실행
- **입력**: `{N}`. **동작**: dependency 차단 재확인 후 계획 있으면 태스크 목록, 없으면 완료 조건 기준. 재작업 감지(`changes-requested`→`in-progress`). 워크트리·`.worktreeinclude`. **원자적 커밋**.
- **위키**: 작업 중 `[관찰]` 발견 시 `capture observation`(자동, `--tasks` 역링크 + `--affects-paths`). `[결정]/[시행착오]`는 코멘트 태그로 남기고 verify에서 승격.
- **불변식**: 원자적 커밋(1커밋=1논리변경, WIP 금지). 워크트리 미커밋 변경 보존.

### 7.7 `verify` — 검증 리포트 생성
- **입력**: `{N}`. **본질**: "구조화된 검증 결과 문서의 생성".
- **동작**: ①plan의 **검증 체크리스트** 추출(없으면 `[중단]`) ②완료 조건 실질(MUST)/형식(SHOULD) 대조 ③(복잡 PR) pr-verifier ④**지식 기록 검토**(태그→타입 캡처 제안) ⑤고정 형식 리포트를 Issue 코멘트로.
- **위키**: (a) Issue 코멘트의 `[결정]/[시행착오]/[관찰]/[사실]` 태그를 [§5.4](#54-issue-코멘트-태그-어휘-위키-71타입과-정렬) 매핑대로 캡처. 캡처하는 decision/trial_error/observation은 `--tasks`로 루트 이슈에도 연결(같은 업무로 묶임) (b) `[관찰]` observation 중 분류 확정분 **승격 제안**(+retire) (c) `refresh --strict`로 무결성 게이트(이슈 있으면 리포트). major면 plan의 ADR 초안 confirm.
- **판정**: 실질 미충족 0 → 통과(done). ≥1 → CHANGES_REQUESTED(run 복귀).
- **불변식**: 산출물은 코멘트 1개·고정 형식. **기록이 본질.**

### 7.8 `done` — PR 생성 또는 close
- **입력**: `{N}`. **2경로**: dependency 차단 재확인 후 (A) 변경 있음 → 커밋→`in-progress→in-review`(gear 유지)→`git push`+`gh pr create`(본문 `Closes #N`)→downstream 안내→로컬 정리. (B) 변경 없음 → 결과 코멘트→상태 라벨 제거→`gh issue close`→downstream 안내.
- **위키**: (a) **drift 검사** — PR diff 파일을 `refresh --check changed-path-stale`에 던져 낡은 위키 문서 리포트 (b) major면 ADR 초안 → `capture decision`(`--intents` + `--tasks` + `--rejected`). (task 노드 done 전이는 merge에서 — 리프 done이 곧 업무 완료는 아니므로.)
- **불변식**: PR은 코드 변경 시만. 상태 라벨만 정리, `gear:*` 유지.

### 7.9 `review` — PR 검증
- **입력**: `[PR] [--auto-merge]`. **동작**: 대상 PR `in-review` 부착→**verify 결과 로드**(있으면 pr-verifier spot-check, 없으면 전수)→판정별 행동(APPROVED+`--auto-merge`→merge / APPROVED→안내 / CHANGES_REQUESTED→`changes-requested` / NEEDS_REVIEW→사령관).
- **위키**: pr-verifier에 연결 task 노드의 `decisions`를 전달해 PR이 그 결정(또는 이미 반려된 대안)과 모순되지 않는지 cross-check.
- **불변식**: review는 판정·라벨까지, 머지는 merge가. team은 `--auto-merge` 명시 필요(solo 자동 허용).

### 7.10 `merge` — PR 머지
- **입력**: `{PR}`. **동작**: 연결 Issue 추출→dependency 차단 재확인→PR+Issue **상태 라벨만 제거**(gear 유지)→`gh pr merge --merge --delete-branch`→downstream 안내→로컬 정리+`git checkout main`+`git pull`.
- **위키(핵심)**: 이 머지로 **루트 이슈가 close되면**(업무 완료) 연결 task 노드를 `complete`로 `done/` 전이([§6.5]). 단일 리프 업무면 그 이슈 close가 곧 업무 완료. 컨테이너 업무면 마지막 자식 close 시점. + drift 리포트에 걸린 문서 `verified_at` 갱신/ supersede 안내(자동 변경 안 함).
- **불변식**: `--merge` 방식. 상태 라벨 제거하되 `gear:*` 유지. Issue는 `Closes #N`으로 자동 close.

---

## 8. 에이전트 — `PR Verifier`

`agents/pr-verifier.md`. `review`(및 복잡 PR의 `verify`)가 호출하는 **독립 검증 서브에이전트**.

- **2모드**: spot-check(verify 결과 입력 시, 의심 2~3건 재검증) / 전수(verify 결과 없을 때 완료 조건 전체).
- **절차**: `gh pr view --json`→연결 Issue(`Closes #N`)→`gh pr diff`→완료 조건 1:1 대조→**PR 코멘트 게시 후** 메인에 동일 결과 반환.
- **위키**: 연결 task 노드의 `decisions`를 받으면, PR 변경이 그 결정과 **모순**되는지 추가 점검(예: 이미 반려된 대안으로 회귀했는지).
- **판정**: `APPROVED` / `CHANGES_REQUESTED` / `NEEDS_REVIEW`.
- **불변식**: 후속 조치(머지)는 **메인 에이전트의 몫**. pr-verifier는 판정만(관심사 분리).

---

## 9. 전체 생애주기 & 워크플로우

```
   (새 워크스페이스)  setup → git init + gh repo create  (+ wiki init 제안)
                                    │
        ┌───────────────────────────┼───────────────────────────┐
   open {N}                    define [기준]                  start "제목"
   (읽기+task 노드)      (★루트 이슈 + task 노드 1:1 생성)   (리프 생성+점유)
        └──────────────┬───────────┘                              │
                       ▼                                          ▼
                  start {N} ◀──────────────────────────────  기어 판단 + task 맥락 주입
                  (리프 점유 + 기어 라벨)
                       │
        ┌──────────────┼──────────────────────────────┐
   micro│express                          normal/major │planned
        ▼                                               ▼
      run {N}                                  plan {N} [--full]  ← task의 결정 따라 recall
        │                                               │ (Plan Mode 승인)
        │                                               ▼
        │                                          run {N}  ← [관찰] observation 자동 캡처
        │                                               │
        │                                          verify {N} ──┐ 실질 미충족
        │                                     (태그→capture,    └─► run {N} (보완, ≤3회)
        │                                      refresh 게이트)
        └──────────────┬───────────────────────────────┘ 통과
                       ▼
                   done {N}   ← drift 검사 + (major) ADR→decision
              ┌────────┴────────┐
        변경 있음             변경 없음
        PR 생성               Issue close
              │
        review {PR} ──┬─ APPROVED ──► merge {PR}  ← 루트 close 시 task 노드 complete(done/)
                      ├─ CHANGES_REQUESTED ──► run {N} (재작업) ──► review (반복)
                      └─ NEEDS_REVIEW ──► 사령관 판단
```

**세션 컨텍스트 우선 원칙**(전 스킬 공통): 같은 세션에서 이미 아는 정보(기어·플로우·계획·커밋·recall 결과)는 재조회하지 않는다. `gh issue view`·`recall`은 **세션이 끊겼을 때의 폴백**.

---

## 10. 상태 머신 — Issue / PR 라벨 전이 + task 노드

### Issue
```
(없음) ─start─► in-progress+assignee ─done(PR)─► in-review
   in-review ─review APPROVED─► merge ─► 라벨 제거 + close
   in-review ─review CHANGES_REQUESTED─► changes-requested ─run─► in-progress ─push─► in-review (반복)
```
### PR
```
(없음) ─review 픽업─► in-review ─APPROVED─► merge ─► 라벨 제거
   in-review ─CHANGES_REQUESTED─► changes-requested ─run─► in-progress ─push─► (리뷰어 픽업 대기)
```
### task 노드 (위키, 이진)
```
capture(define) ─► 활성(wiki/task/) ─ 루트 이슈 close(merge) ─► 완료(wiki/task/done/)
   완료 ─ reopen(이슈 재오픈) ─► 활성
   * 연결 시 GitHub 이슈가 정본; task-github가 전이를 투영, out-of-band는 reconcile
```

### 중복 방지 쿼리 (team 협업 시)
```bash
is:open is:issue label:in-progress,in-review                  # 점유됨(건드리지 않음)
is:open is:issue label:changes-requested                      # 재작업 대기(원작업자 우선)
is:open is:issue -label:in-progress -label:in-review -label:changes-requested no:assignee  # 가용
is:open is:pr -label:in-review -label:in-progress             # 리뷰 가능 PR
```

---

## 11. 브랜치 · 커밋 · 워크트리 규약

| 항목 | 규칙 |
|------|------|
| 메인 브랜치 | `main` |
| 작업 브랜치 | `task/issue-{N}` |
| 워크트리 경로 | `.worktrees/issue-{N}` |
| 커밋 형식 | `{type}: {요약} (#{N}) — {Why}` (`feat/fix/docs/refactor/test/chore`) |
| 커밋 원칙 | 원자적(1커밋=1논리변경), WIP 금지, `#N`으로 Issue 연결 |

워크트리 사용 조건: 병렬 작업 / main 오염 방지 / 다중 브랜치 전환. 생성 전 대상 프로젝트 `.gitignore`에 `.worktrees/`가 없으면 추가한다. `.worktreeinclude`로 gitignore 파일 복사. 진입 후 잔재는 `git clean` **제안만**(자동 실행 금지).

---

## 12. 외부 의존성

| 의존 | 용도 | 없을 때 |
|------|------|--------|
| `gh` CLI | Issue/PR/Label/Assignee/repo, GraphQL | **필수** |
| `git` | 브랜치·커밋·워크트리·push | **필수** |
| `python3` | wiki CLI 실행 | 위키 연동에만 필요(보통 존재) |
| GitHub sub-issue(GraphQL) | 트리 구조 | 트리만 제약, 단일 이슈 정상 |
| GitHub Issue dependencies(REST) | 하위 작업 선후관계와 blocked 상태 | 생성 실패는 fallback 코멘트, 조회 실패는 수동 확인 |
| Plan Mode | `plan` 읽기 전용 분석 | planned 플로우 핵심 |
| 서브에이전트 타입 | 위임 | 직접 수행으로 대체 |
| **`wiki-markdown` 플러그인** | 결정 그래프 연계(task 노드/recall/capture/refresh) | **선택** — `./wiki/` 미감지 시 그레이스풀 스킵([§6.3](#63-감지--호출-메커니즘-ruleswiki-bridgemd)) |

> **GitHub API 주의**: sub-issue GraphQL과 Issue dependency REST API는 권한·플랜·`gh` 버전에 따라 동작하지 않을 수 있다. sub-issue 실패 시 단일 이슈 흐름으로, dependency 생성 실패 시 fallback 코멘트로 폴백한다. dependency 조회 실패는 자동 작업/종료를 멈추고 수동 확인을 요구한다.
> **위키 CLI task 지원**: 위키 CLI가 task 타입·`complete`·`reopen`을 구현했다([§6.8]).

---

## 13. 자동로드 policy 슬롯에 채울 내용

> **이 절은 mechanism이 아니라 policy다.** 합의되면 이 내용을 `CLAUDE.md` / `AGENTS.md` operating policy block에 반영한다. `wiki-markdown`의 `agent-policy` 스킬이 두 entry 파일을 멱등 스캐폴드한다. 소비 프로젝트 wiki vault에는 운영정책을 자동 생성하지 않는다.

### 13.1 캡처 권한 (어느 스킬이 어떤 타입을)

| 스킬 | 캡처/전이 가능 | 방식 |
|------|--------------|------|
| `define` | `task` 생성, `intent` | 제안 후 확인 |
| `run` | `observation` | 자동 |
| `verify` | `decision`, `rejected_decision`, `trial_error`, `observation` 승격 | 제안 후 확인 |
| `done`(major) | `decision`(ADR) | 제안 후 확인 |
| `merge` | `task` → `complete`(done/), `ssot` 갱신 안내 | 자동 전이 / 갱신은 제안 |

### 13.1.1 Knowledge Capture Audit

모든 비 trivial 작업은 종료 전 Knowledge Capture Audit를 수행하고 결과를 `recorded`/`proposed`/`none` 중 하나로 보고한다. 절차·타입 판정·출력 어휘 정본은 [rules/knowledge-capture.md](rules/knowledge-capture.md)에 두고, 정책 의무는 자동로드 operating policy에 둔다.

### 13.2 업무↔이슈 연결 규약

- **업무 1개 = task 노드 1개 + 루트 이슈 1개(1:1).** task 노드는 업무 단위, 리프마다 만들지 않음.
- **task 노드**: `relations.tasks: [owner/repo#<루트이슈>]` (PR은 동일 `#` 번호공간, 필요 시 `github:owner/repo#<PR>`) + `relations.decisions/intents`(근거). 본문은 업무 **handoff/context 요약**.
- **루트 이슈/PR** 본문 `## Wiki Context`: task 노드를 **메인**, 결정/취지를 **보조**로 (포맷 [§6.2]). PR은 루트 이슈 링크 또는 동일 Wiki Context를 둔다.
- 항목은 위키 노드 **basename**. wikilink 문법은 Obsidian 탐색용 장식, 정본 연결은 위키 노드의 `relations`.

### 13.3 promotion 트리거

- `observation` → `trial_error`/`decision` 승격은 **verify에서 분류가 확정될 때 제안**. 자동 판정 금지(`REJ-…-promotion-auto-judgment`).
- 승격 시: 후속 노드 `capture`(`--supersedes <OBS>` 또는 사후 `retire --type superseded --superseded-by`) → `refresh --check supersede`로 양방향 확인.
- 승격 가치 기준(위키 추상 기준 재사용): 장기 재사용성 · 구조적 영향 · 반복 가능성 · 되돌리기 비용 · 후속 작업자 필요성 중 ≥1.

### 13.4 PR 리뷰 흐름 ↔ 위키

- `review`/`pr-verifier`는 연결 task 노드의 `decisions`를 받아 **PR이 반려된 대안(rejected_decision)으로 회귀하지 않는지** 점검.
- 머지 후 drift 리포트(`changed-path-stale`)에 걸린 ssot/runbook은 `verified_at` 갱신 또는 supersede.

### 13.5 task 노드 상태 동기화 정책

- 연결 시 **GitHub 루트 이슈/PR 흐름이 정본**, 위키 task 상태는 투영([§6.5]).
- 전이 시점: 루트 이슈 close(머지/직접) → `complete`. 이슈 reopen → `reopen`.
- out-of-band(밖에서 닫힘) reconcile 주기·방식(예: `open`/`merge` 시 점검).

### 13.6 기어별 연동 강도 그라디언트

| 기어 | task 노드 | recall | capture | drift |
|------|:---:|:---:|:---:|:---:|
| micro | 보통 생략(단발) | — | 발견 시 observation/trial_error | — |
| normal | ✅ 업무면 생성 | ✅ | decision/trial_error/observation | ✅(done) |
| major | ✅ + intent/rejected 연결 | ✅ | + ADR decision | ✅(done) |

### 13.7 GitHub template (선택)

`.github/ISSUE_TEMPLATE/`의 루트 이슈 템플릿에 `## Wiki Context` 빈 섹션을 포함해 본 규약과 동기. (운영 시점 도입.)

---

## 14. 완료 조건 평가 · 자동 반복 한계 · 에러 복구

**완료 조건 2수준**(verify 적용): **실질(MUST)**(기능·데이터·독립성·프로토콜 위배 → 미충족 시 CHANGES_REQUESTED) / **형식(SHOULD)**(빈 디렉토리·네이밍 → 제안만). 구분 모호하면 **실질로 분류**(안전 우선).

**자동 반복 한계**: verify/run 루프가 **3회** 초과 시 자동 중단 → `[중단]` 태그 → 사령관 브리핑.

**에러 복구**: ①Issue에 `[중단]` 코멘트(지점·원인·상태) ②복구 가능→재시도 ③불가→사령관 보고, 다음 세션 `[중단]`으로 맥락 복원 ④워크트리 미커밋 변경 **보존**.

**위키 호출 실패 처리**: wiki CLI가 비0 종료(exit 4 ref 오류 등)면 **작업을 막지 않는다** — 해당 캡처/전이만 스킵하고 `[관찰]` 코멘트로 사유 기록, 사령관에 알림. (위키는 보조이지 작업의 게이트가 아님. `verify`의 `refresh --strict` 게이트도 "리포트 후 진행"이지 "차단"이 아니다.)

---

## 15. 역할 모델 — Tech Lead & 위임

실행 주체는 **Tech Lead**. 사령관(사용자)의 의도를 파악하고, 직접 수행하거나 서브에이전트에 위임해 종합. 위임은 독립 전문성이 필요할 때만.

| 작업 속성 | 빌트인 타입 |
|---------|---------|
| 구조 설계·트레이드오프 | Architect |
| 요구사항 정제·스펙 | Product Analyst |
| API·DB·서버 로직 | Backend Engineer |
| UI·클라이언트 | Frontend Engineer |
| 배포·인프라·CI/CD | DevOps Engineer |
| 코드 품질 검토 | Code Reviewer |
| 테스트 전략·코드 | QA Engineer |
| 보안 취약점 | Security Auditor |

---

## 16. 설계 불변식 (이어 개발 시 보존해야 할 계약)

깨면 플러그인의 정체성이 바뀌는 핵심 계약. 바꾸려면 의식적 결정(ADR)으로 남긴다.

**작업 프로토콜(mechanism) 불변식**
1. 기어는 **파급력으로만** 판단 — 크기는 근거 아님.
2. 강등 금지, 애매하면 상위 기어, 섞이면 최고 기어.
3. 기어 ↔ 플로우 1:1, 이탈 시 양방향 재확인.
4. 승인 없는 plan은 없다(Plan Mode 관문).
5. 상태 라벨은 교체/제거, 기어 라벨은 영구 — 정리 로직은 `gear:*` 불건드림.
6. 세션 컨텍스트 우선 — 아는 정보 재조회 금지, 조회는 폴백.
7. 스킬은 순수함수 — 인자가 동작 결정.
8. plan ↔ verify 계약 — plan이 검증 체크리스트 산출, verify가 그것으로만 대조.
9. 계획은 전문 기록(축약 금지).
10. verify의 본질은 기록(구조화 리포트 생성).
11. 기어 판단·라벨 부여의 단일 책임 = `start`.
12. 컨테이너 이슈 직접 작업 금지 — 리프만 점유.
13. Issue dependency는 GitHub REST 관계가 정본 — dependency 없음은 병렬 가능.
14. 열린 `blocked_by`가 있는 이슈는 `start`/`run`/`done`/`merge`에서 차단.
15. 점유 중복 방지 — 타인 점유 Issue는 사령관 확인.
16. 워크트리 미커밋 변경 보존 — `git clean`은 컨펌 후.
17. 자동 반복 ≤ 3회.
18. review와 merge 분리 / pr-verifier는 판정만(관심사 분리).

**위키 통합 불변식**
19. **비대칭 결합** — wiki-markdown으로의 역방향 의존을 만들지 않는다(wiki는 task를 모름).
20. **그레이스풀** — `./wiki/` 미감지 시 모든 위키 호출 스킵, 핵심 흐름 유지. 위키는 작업의 게이트가 아니다.
21. **결합 규약은 policy에** — "누가·언제·어떤 타입을" 같은 운영 규약은 task-github의 rules가 아니라 자동로드 operating policy(`CLAUDE.md` / `AGENTS.md`)에 둔다(agent-neutrality 보존).
22. **자동 승격 금지** — observation 자동 캡처는 허용하되, 1급 노드(task/decision/intent/trial_error) 캡처와 모든 승격은 **제안 후 확인**.
23. **지식 기록 감사 의무** — 비 trivial 작업은 종료 전 `recorded`/`proposed`/`none` 중 하나로 Knowledge Capture Audit 결과를 남긴다.
24. **업무 단위 = task 노드 1:1** — task 노드는 업무(루트 이슈) 하나에 하나. 리프마다 만들지 않는다.
25. **task 노드 상태 정본은 하나** — 연결 시 GitHub 이슈가 정본, 위키는 투영. 상세 phase는 위키가 복제하지 않는다(이진만).
26. **타입별 관계 제약 준수** — task의 `relations.tasks`는 외부 작업 ref(Issue/PR 등)만. task는 순수 잎(아무도 task를 저장 edge로 가리키지 않음). 위키 hub(intent/ssot/runbook)에 `--tasks` 시도 금지(exit 2).
27. **위키 정본 존중** — task-github는 위키 인덱스·retired/done 디렉토리를 **직접 쓰지 않는다**. 오직 wiki CLI(`capture/retire/recall/refresh/relate/complete/reopen`)를 통해서만 vault를 변경.

---

## 17. 확장 가이드

**새 스킬 추가**: `skills/{이름}/SKILL.md`(frontmatter `name`/`description`+트리거). 입력은 `$ARGUMENTS` 순수함수. 생애주기(§9) 위치·라벨 전이·위키 터치포인트 명시. 세션 컨텍스트 우선. README·§7 갱신.

**새 기어/플로우**: 불변식 1~3 직접 변경 → ADR 필수. 기어 라벨 추가 시 `start`(부여)와 정리 로직(done/review/merge) 동기.

**새 위키 연동**: mechanism(이 플러그인)에는 **감지·호출 방법**만, **정책**(언제·어떤 타입)은 자동로드 operating policy에. 위키 타입/CLI가 바뀌면 [§6](#6-위키-통합-핵심-장)·[§13](#13-자동로드-policy-슬롯에-채울-내용)·`rules/wiki-bridge.md` 동기. 타입별 관계 제약(불변식 23)은 위키 `wiki-data-model`을 정본으로 재확인.

**다른 플러그인과 연동**: task-github가 상대를 **조건부 호출**하는 단방향으로. 상대는 task-github를 몰라야 한다. 가용성 판정 → 미가용 시 스킵.

---

## 18. 다른 프로젝트로 이관

### 18.1 단독 이식
```bash
# task-github만
claude --plugin-dir /path/to/ai-plugins/plugins/task-github
# 위키 연계까지
claude --plugin-dir /path/to/ai-plugins/plugins/task-github \
       --plugin-dir /path/to/ai-plugins/plugins/wiki-markdown
```

### 18.2 대상 프로젝트 1회 설정
```bash
python3 <wiki-markdown>/skills/agent-policy/scripts/scaffold_agent_policy.py \
  --target all --profile solo --tracker task-github --concurrency worktree
# 기어 라벨(필수)
gh label create "gear:micro"  --color "0E8A16" --description "자기 파일 내부만 영향"
gh label create "gear:normal" --color "FBCA04" --description "자기 서비스 내부 영향"
gh label create "gear:major"  --color "D93F0B" --description "외부 계약 변경"
# 상태 라벨(권장)
gh label create "in-progress"       --color "1D76DB" --description "작업/재작업 중"
gh label create "in-review"         --color "5319E7" --description "리뷰 대기/검토 중"
gh label create "changes-requested" --color "E99695" --description "피드백 반영 필요"
# 위키 연계 시
python3 <wiki-cli> init    # ./wiki/ vault 생성 (task 타입 지원 버전 필요)
# CLAUDE.md/AGENTS.md에 operating policy block 반영
```

### 18.3 이관 체크리스트
- [ ] `gh` 인증(`gh auth status`) + 대상 레포 권한
- [ ] git remote(없으면 `setup`)
- [ ] 기어 라벨 3종 / 상태 라벨 3종
- [ ] `CLAUDE.md` / `AGENTS.md` operating policy block 명시(기본 solo)
- [ ] sub-issue(GraphQL) 동작 확인 — 안 되면 단일 이슈 폴백
- [ ] Issue dependency(REST) 동작 확인 — 안 되면 fallback 코멘트로 수동 확인
- [ ] (위키 연계) `./wiki/` 존재 또는 `wiki init` / 위키 CLI가 **task 타입 지원** / 자동로드 operating policy block 반영
- [ ] 메인 브랜치가 `main`이 아니면 `rules/workflow.md` 조정
- [ ] `.worktrees/`가 `.gitignore`에 포함

> **v2→v3 이관 차이**: 위키 가용성 판정이 옛 하드코딩 경로(`plugins/wiki/obsidian`)에서 **프로젝트 로컬 `./wiki/` 감지**로 바뀌어, 단독 이관 환경에서도 위키만 있으면 자동 연동된다.

---

## 19. 구현 순서 (완료됨)

이 설계는 **위키 CLI 선행 → task-github** 순서로 구현됐다(task-github 스킬이 위키 task 명령을 호출하므로). 아래는 그 순서이며 모두 완료된 상태다:

1. ✅ **위키 CLI `task` 타입** ([§6.8]) — `capture task` / `complete` / `reopen` + refresh 스키마 + `templates/task.md` + 테스트. (위키 측 설계는 vault에 dogfood됨.)
2. ✅ **task-github mechanism** — `plugin.json` + `rules/`(task-protocol/workflow/wiki-bridge) + `skills/`×10 + `agents/pr-verifier.md`.
3. ✅ **policy 반영** — [§13]을 `CLAUDE.md`/`AGENTS.md` operating policy block에 반영.
4. ✅ **마켓플레이스 등록** — `.claude-plugin/marketplace.json`에 task-github 추가.

---

## 20. 변경 이력 (v2 → v3)

v3는 연계 대상을 `wiki-obsidian` → `wiki-markdown`(결정 그래프)으로 전환하며 통합을 재설계했다.

1. **계층 분리 도입**: 위키↔task 결합 규약을 플러그인 mechanism이 아니라 자동로드 **policy statement**(`CLAUDE.md` / `AGENTS.md`)에 둔다(위키 4계층 분리 존중, 불변식 19).
2. **`task` 노드 다리 모델**: 옛 "리프마다 `## Wiki Context`" → **업무 1개 = task 노드 1개 + 루트 이슈 1개(1:1)**. task 노드가 결정/취지를 안고 이슈를 가리켜, 위키 hub의 `--tasks` 불가 문제를 해소(불변식 21~23). 위키에 `task` 제3 범주를 신설(dogfood 완료).
3. **타입 모델 교체**: decision/fact/lesson/pattern → 위키 7타입 + task. `[사실]`→ssot/observation, 신규 `[관찰]`→observation.
4. **요약↔상세 분리**: task 노드=업무 요약(왜), 루트 이슈=상세(무엇·어떻게). 중복이 아니라 입자도 분리.
5. **이진 상태 + 정본 위임**: task 노드는 활성/done 이진만, 연결 시 GitHub이 정본, task-github가 투영·reconcile(불변식 22) — 동기화 면적 최소화.
6. **브릿지 강화**: "순수 선택" → **"감지 후 적극 활용"**. 감지 경로를 하드코딩에서 `./wiki/`로(불변식 18).
7. **CLI 기반 호출**: 스킬 호출 → 결정적 CLI(JSON+exit code) 파싱.
8. **드리프트 탐지(신규)**: done/merge에서 `changed-path-stale`로 코드 변경이 낡게 만든 위키 문서 자동 포착([§6.7]).
9. **승격 정책 정합**: 위키의 자동 승격 반려 결정 존중 — observation 자동, 1급 노드·승격은 제안(불변식 20).
10. **프로파일 기본값**: team → **solo**(이 워크스페이스가 1인+AI).

> 이전 v2 플러그인(`for-claude-code/plugins/task/github`)의 Issue는 `start {N}` 재실행으로 새 기준 재평가.

---

## 21. 용어집

| 용어 | 정의 |
|------|------|
| 사령관 | 사용자. 의사결정 주체. |
| Tech Lead | 실행 주체(에이전트)의 역할. |
| 프로파일 | 환경 분류(solo/team). `CLAUDE.md` / `AGENTS.md` operating policy block에 명시(기본 solo). |
| 기어 | 작업의 파급력(micro/normal/major). 라벨로 영구 기록. |
| 플로우 | 승인 관문(express/planned). 기어와 1:1. |
| 업무(work) | 하나의 작업 덩어리. 위키 task 노드 1개 + GitHub 루트 이슈 1개(1:1). |
| 루트 이슈 | 업무의 최상위 이슈(컨테이너 또는 단일 리프). task 노드가 여기 1:1 연결. |
| 컨테이너/리프 이슈 | 자식 있음(직접 작업 불가) / 없음(점유·작업 단위). |
| `task` 노드 | 위키 제3 범주. 업무 요약·근거·제약을 담는 작업지시서형 handoff 노드. GitHub와 연계하면 루트 이슈/PR을 외부 ref로 가리킨다. 이진 상태(활성/done). |
| 실질/형식 | 완료 조건 2수준. 실질만 판정에 영향. |
| `## Wiki Context` | 루트 이슈→위키 링크 섹션(task 노드=메인, 결정=보조). |
| drift(changed-path-stale) | 코드 변경이 `affects_paths` 글롭에 걸리는데 `verified_at` 미갱신인 위키 문서. |
| 승격(promotion) | observation → trial_error/decision + retire. 항상 제안(자동 금지). |
| reconcile | out-of-band로 닫힌 이슈를 task-github가 `gh`로 읽어 위키 task 상태를 정렬. |
| mechanism/policy | 안정 자산(이 플러그인) / 변동 자산(자동로드 operating policy의 결합 규약). |

---

*이 문서는 `wiki-markdown` 플러그인 명세(`wiki/ssot/plugin-definition/`, `skills/wiki/`, `wiki_cli.py`)와 vault에 dogfood된 task 설계(`DEC-…-task-third-category` 등), v2 `task-github` 실행 명세를 분석해 작성되었다. 위키 타입/CLI가 바뀌면 [§6](#6-위키-통합-핵심-장)·[§13](#13-자동로드-policy-슬롯에-채울-내용)을 갱신하라 — 위키 `wiki-data-model`이 타입·관계의 정본이다.*
