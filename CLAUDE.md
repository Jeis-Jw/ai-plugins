# CLAUDE.md

이 워크스페이스의 에이전트 진입점(agent-entry 계층). 운영 정책 정본은 위키에 있다.

## 프로파일

```
프로파일: solo
```
1인 개발자 + AI 에이전트 환경. (`task-github` 플로우는 2단: micro→express / full→planned --full. 기어 **라벨**은 프로파일 무관하게 공통 `gear:micro|normal|major` — `gear:full`은 없다.)

## 운영 정책 포인터

- **작업관리 ↔ 위키 결합 규약**: `wiki/ssot/agent-operating-model.md` (policy 정본 — 캡처 권한·task 노드 연결·promotion·PR 흐름)
- **위키 메커니즘**: `plugins/wiki-markdown/` + `wiki/ssot/plugin-definition/`
- **작업 프로토콜 메커니즘**: `plugins/task-github/` (`rules/`·`DESIGN.md`)

## 4계층 분리

| 계층 | 위치 |
|------|------|
| mechanism | `plugins/wiki-markdown/`, `plugins/task-github/` |
| policy | `wiki/ssot/agent-operating-model.md` |
| agent entry | 이 파일 |
| knowledge | `wiki/*` |

상세는 [[wiki-four-layer-separation]] 참조.
