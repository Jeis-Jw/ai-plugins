---
name: cockpit
description: 세션 호핑 후 "내가 어디까지 했지"를 1커맨드로 답한다. task-worker/session-review/task-github/studio의 공개 read-only 표면만 집계해 각 소스의 present/absent/error 상태와 다음 실행 가능 action을 보여주며 아무것도 쓰지 않는다. "cockpit", "어디까지 했지", "작업 상태 집계", "studio status" 요청에 사용한다.
---

# Cockpit

워크스페이스의 작업 상태를 읽기 전용으로 집계한다. cockpit은 게이트가 아니다 —
소스가 비었거나 깨져도 항상 exit 0이며(usage 오류 2만 예외), 어떤 상태도 변경하지 않는다.

```bash
python3 "${STUDIO_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/cockpit.py" status [--config .studio.yml] [--json]
```

`--config`는 워크스페이스 앵커다: 모든 소스를 그 파일의 디렉터리 기준으로 읽는다
(파일 내용으로 어댑터를 바꾸지 않는다 — 소스 4개는 고정).

## 소스 (고정 3+1)

| source | 읽는 표면 | authority |
|--------|-----------|-----------|
| task-worker | `.task-worker/local/bindings/*.json` → binding마다 `definition_artifact.py resume` | live |
| session-review | `session_review.py snapshot-dir`(provider가 `.session-review.yml`로 결정)로 찾은 snapshot마다 `status`; status block 없는 snapshot은 건너뜀 | live |
| task-github | `.task-github/orchestrate/*.json` 직접 읽기 (network·`gh` 호출 없음) | local-projection |
| studio | `mission_receipt.py show` (RECEIPT 유닛 산출물) | live |

형제 플러그인 스크립트는 `TASK_WORKER_ROOT`/`SESSION_REVIEW_ROOT` env로 주입하고,
없으면 studio 옆의 `../task-worker`/`../session-review`를 쓴다.

## 상태 계약 (`studio.cockpit/v1`)

- `state:absent` — 스크립트 미해결 또는 로컬 상태 미존재. 정상이며 `summary:null`.
- `state:present` — `summary`에 소스별 요약, 실행 가능하면 `next[{source, action, ref}]` 제시.
- `state:error` — 어댑터 non-zero/비JSON. `reason`은 고정 코드
  (`exit_nonzero`|`invalid_json`|`read_failed`|`timeout`|`adapter_failed`)만 담고
  stderr 산문은 파싱도 저장도 하지 않는다.

`task-github`의 `authority:"local-projection"`은 GitHub 실상이 아니라 마지막
orchestrate 스냅샷 기준이라는 표시다. 실상 확인이 필요하면 `next`의
`task-github:orchestrate`를 실행한다.
