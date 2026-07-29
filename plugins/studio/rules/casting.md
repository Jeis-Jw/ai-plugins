# Studio casting

Producer는 미션에 필요한 가장 작은 역할 조합을 선택한다. 이 표는 기본값이며 고정
topology가 아니다.

| kind | 기본 역할 |
|---|---|
| `idea` | `planner`, `researcher`, `reviewer` |
| `product-direction` | `strategist`, `planner`, `product-designer`, `reviewer` |
| `technical-design` | `architect`, `dev`, `qa`, `reviewer` |
| `ui-build` | `product-designer`, `visual-designer`, `dev`, `qa` |
| `content` | `strategist`, `creator`, `visual-designer`, `reviewer` |
| `implementation` | `dev`, `qa`, `reviewer` |
| `launch` | `qa`, `reviewer`, `curator` |

## 선택 규칙

- 독립적인 관점이나 작업이 있을 때만 역할을 추가한다.
- 한 agent가 자연스럽게 끝낼 수 있는 작업을 회의로 만들지 않는다.
- 구현자는 만들고, QA는 깨고, reviewer는 완료 여부를 독립적으로 판정한다.
- 같은 작업의 피드백과 재작업은 원래 agent handle로 돌려보낸다.
- 역할은 작업 단위 동안 유지하며, 작업이 끝나면 종료한다.
- Producer는 crew 역할이 아니며 산출물을 직접 만들지 않는다.

## 실행 경계

Studio는 역할과 작업만 정한다. agent 실행, 권한, sandbox, tool access, context window와
수명주기는 Codex 또는 Claude Code가 제공하는 native subagent 기능이 소유한다.
