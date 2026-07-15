---
name: init
description: Studio workspace와 .studio.yml을 한 번에 안전하게 초기화한다. 외부 worker/reviewer는 명시한 provider만 설정하며 미지정 시 native를 유지한다. "studio:init", "Studio 초기화", "스튜디오 기본 설정 만들어줘" 요청에 실행하라.
---

# init — Studio 작업장과 설정 초기화

Studio가 소유하는 로컬 작업장 `.studio/`와 agent/tool 정책 `.studio.yml`을 한 번에 만든다.
초기화는 외부 plugin을 탐색하거나 호출하지 않으며 GitHub·배포 서비스도 변경하지 않는다.

## 기본 실행

```bash
STUDIO="${STUDIO_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/studio.py}"
python3 "$STUDIO" init --json
```

미지정 worker/reviewer는 `native`다. 선택적 adapter를 설정할 때만 명시한다.

```bash
python3 "$STUDIO" init --worker task-worker --json
python3 "$STUDIO" init --worker task-github --reviewer session-review --json
```

`task-github`는 내부 task-worker adapter 책임을 포함하므로 worker를 둘 다 설정하지 않는다.
이 명령은 provider 설정만 기록하며 provider 자체를 초기화하지 않는다. 선택한 provider의
init은 해당 plugin 명령으로 별도 수행한다.

## 안전 계약

- 동일한 내용은 `skip`하고 성공한다.
- 기존 파일이 다르면 아무것도 쓰지 않고 `conflict`로 종료한다.
- `--force`에서만 Studio-owned scaffold 파일을 갱신한다. live board도 포함되므로 명시적
  재초기화가 아니면 사용하지 않는다.
- `--dry-run`은 실제 파일을 쓰지 않고 동일 plan과 config validation을 반환한다.
- `--workspace <path>`와 `--config <path>`로 기본 경로를 바꿀 수 있다.
- 결과 JSON 최소 필드는 `plugin`, `action`, `changed`, `paths`, `validation`, `dry_run`이다.

초기화 후 read-only 진단은 `studio:doctor`를 사용한다.
