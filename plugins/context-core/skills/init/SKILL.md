---
name: init
description: 사용자가 현재 repository의 context-core 초기화나 bootstrap을 명시적으로 요청했을 때 canonical seed를 안전하고 멱등하게 적용한다. 일반 recall·capture 중에는 자동 실행하지 않는다.
---

# Init

`context_cli.py init --json`을 한 번 호출한다. repository가 absent이면 canonical root/SNAP/OBS seed를 context-core coordinator로 즉시 적용하고 `doctor.repository_state=ready`를 반환한다. 이미 ready이면 `phases[core_init].status=noop`이며 filesystem diff는 0이다. 직전 fixed init bundle의 write 순서와 bytes가 일치하는 exact canonical prefix만 남은 index write를 재개한다. 그 밖의 partial 또는 invalid 상태는 기존 bytes를 고치거나 덮어쓰지 않고 `partial_core_init`으로 중단한다.

이 명시적 init 호출은 fixed seed에만 적용 권한을 준다. 일반 SNAP·OBS·DEC/user-content mutation은 기존 complete bundle과 exact `approval_digest` 승인을 계속 요구하며, 물리 write는 context-core coordinator만 수행한다.

agent policy는 init에 포함하지 않는다. 사용자가 별도로 명시한 경우에만 repository root의 `AGENTS.md` 또는 `CLAUDE.md`를 `policy preview`하고 exact approval 뒤 `transaction apply`한다. 기존 파일의 managed marker 밖 byte는 그대로 보존하고, marker가 깨졌거나 중복됐거나 target이 symlink·nested path이면 중단한다.
