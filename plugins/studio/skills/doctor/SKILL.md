---
name: doctor
description: Studio workspace와 .studio.yml을 읽기 전용으로 진단하고 native-first 설정을 보고한다. 미설정 외부 plugin은 탐색하지 않는다. "studio:doctor", "Studio 설정 진단", "스튜디오 준비 상태 확인" 요청에 실행하라.
---

# doctor — Studio 로컬 상태 진단

```bash
STUDIO="${STUDIO_CLI:-$CLAUDE_PLUGIN_ROOT/scripts/studio.py}"
python3 "$STUDIO" doctor --json
```

다른 경로를 쓴다면 `--workspace <path>`와 `--config <path>`를 함께 넘긴다.

doctor는 다음만 확인한다.

- `.studio/` 핵심 작업장과 board schema
- `.studio.yml` parse/schema
- 설정에 명시된 worker/reviewer provider

doctor는 파일을 수정하지 않는다. `.studio.yml`이 없으면 native tool과 세션 model/effort
상속이 유효하므로 warning만 남긴다. 설정에 없는 provider는 discovery/probe하지 않으며,
설정된 외부 provider의 실제 capability probe도 producer의 mission-scoped preflight 책임이다.
