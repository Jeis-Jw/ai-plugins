---
name: init
description: 외부 GitHub mutation 없이 task-github provider config와 local projection state를 초기화한다. "task-github:init", "task-github 설정 만들어줘" 요청에 실행하라.
---

# init — provider config 초기화

현재 workspace에 task-github가 소유하는 local 설정만 준비한다. Git/GitHub repository와 label을 만드는 `setup`과 분리된 명령이다.

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/init_workspace.py" --json
```

선택 인자:

```text
--base-branch {BRANCH}
--force
--dry-run
--json
```

생성·보완 대상:

- `.task-github.yml`: GitHub projection/closeout provider 정책
- `.task-github/local/projections/`: 재개 가능한 local projection checkpoint 경로
- `.gitignore`의 `.task-github/local/` 항목

결과 JSON의 최소 필드는 `plugin`, `action`, `changed`, `paths`, `validation`, `dry_run`이다.

## 불변식

- GitHub API, `gh`, Git remote, label, Issue, PR을 호출하거나 변경하지 않는다.
- 동일 내용이면 `skip`과 exit 0을 반환한다.
- 다른 기존 config는 `--force` 없이는 변경하지 않고 nonzero로 종료한다.
- `--dry-run`은 파일과 디렉터리를 변경하지 않는다.
- provider config 자체만 검증한다. `.task-worker.yml` 존재 여부나 execution policy는 init 성공 조건이 아니다.
