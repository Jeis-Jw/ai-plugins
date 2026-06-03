# CLAUDE.md

이 워크스페이스의 Claude용 에이전트 진입점(agent-entry 표면). 작업환경 운영 정책은 아래 `agent-operating-policy` 관리 블록이 정본이다.

## 프로파일

```
프로파일: solo
```
1인 개발자 + AI 에이전트 환경. (`task-github` 플로우는 2단: micro→express / full→planned --full. 기어 **라벨**은 프로파일 무관하게 공통 `gear:micro|normal|major` — `gear:full`은 없다.)

## 메커니즘/근거 포인터

- **작업관리 ↔ 위키 결합 규약**: 아래 `agent-operating-policy` 관리 블록 및 Codex용 `AGENTS.md`
- **위키 메커니즘**: `plugins/wiki-markdown/` + `wiki/ssot/plugin-definition/`
- **작업 프로토콜 메커니즘**: `plugins/task-github/` (`rules/`·`DESIGN.md`)
- **정책 변경 근거**: 이 repo의 `wiki/context/decision/`에 dogfood 기록

## 4계층 분리

| 계층 | 위치 |
|------|------|
| mechanism | `plugins/wiki-markdown/`, `plugins/task-github/` |
| policy statement | 이 파일의 관리 블록, `AGENTS.md` |
| policy rationale | `wiki/context/decision/` |
| knowledge | `wiki/*` |

상세는 [[wiki-four-layer-separation]] 참조.

<!-- BEGIN agent-operating-policy (managed by wiki-markdown) -->
## Agent Operating Policy

- Profile: solo
- Scope: these auto-loaded entry files are the source for working-environment policy.
- Concurrency: Use git worktrees for concurrent tasks; do not let parallel agents edit the same working tree.
- Tracker: Use task-github for tracked work: root issues own the task, wiki task nodes bridge decisions to the issue when a wiki vault exists.
- Knowledge capture: use wiki-markdown for product, system, and design knowledge; do not store working-environment operating policy in a consumer project's wiki vault.
- Design altitude: brainstorming defines decomposition and thin unit boundaries; unit-internal schema/API/DDL/prompt contracts belong in the unit issue body or in DEC/OBS captured during that unit's run. Do not create wiki task nodes for leaf issues.
- Capture authority: observations may be recorded when low-risk; decisions, rejected alternatives, trial-error records, and promotions need explicit user confirmation.
<!-- END agent-operating-policy (managed by wiki-markdown) -->
