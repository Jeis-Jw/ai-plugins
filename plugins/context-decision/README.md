# context-decision

`context-decision`은 “무엇을 결정했고, 왜 그 결정을 따르며, 어떤 대안을 반려했는가”를 다음 agent와 session에서 바로 복원하는 decision continuity plugin입니다. 현재 DEC는 authoritative하며 superseded history는 `do_not_follow`로 표시됩니다.

## Manual hard dependency

요구 좌표는 marketplace `jeis-ai-plugins`, plugin `context-core`, selector `context-core@jeis-ai-plugins`, source `Jeis-Jw/ai-plugins`, protocol `context-common/v1`입니다. 동명 plugin이나 다른 marketplace source는 대체하지 못합니다.

1. 사용자가 provider marketplace에서 exact core를 원하는 scope에 직접 설치·활성화합니다.
2. host를 reload하거나 새 session을 엽니다.
3. 사용자가 `$context-core:init`을 실행하고 repository state가 `ready`인지 확인합니다.
4. `$context-decision:init`을 다시 실행합니다.

`context-decision`은 marketplace add, install, enable, update, core init 또는 host configuration 변경을 자동 실행하지 않습니다. Manifest에도 dependency나 implicit/default install metadata가 없고 core 구현을 내장하지 않습니다. `schema`와 `capabilities`만 core 없이 확인할 수 있으며, 그 밖의 repository operation은 identity → source → enabled → protocol → read-only core doctor `repository_state` 순서의 preflight를 먼저 통과해야 합니다.

## Exact failure UX

- `core_missing`: source `Jeis-Jw/ai-plugins`의 `context-core@jeis-ai-plugins`를 사용자가 선택한 scope에 직접 설치하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_source_mismatch`: source `Jeis-Jw/ai-plugins`의 exact selector를 사용자가 선택한 scope에 직접 설치하고 다른 marketplace의 동명 plugin을 사용하지 않습니다. reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_disabled`: source `Jeis-Jw/ai-plugins`의 exact core를 사용자가 선택한 올바른 scope에서 직접 활성화하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_incompatible`: source `Jeis-Jw/ai-plugins`의 exact core를 사용자가 선택한 scope에서 `context-common/v1` 호환 버전으로 직접 업데이트하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_uninitialized`: plugin 설치 문제가 아닙니다. source `Jeis-Jw/ai-plugins`의 exact core와 사용자가 선택한 scope를 유지하고 `$context-core:init`을 직접 실행한 뒤 reload 또는 새 session에서 `context-decision:init`을 재시도합니다.
- `partial_core_init`: source `Jeis-Jw/ai-plugins`의 exact core와 사용자가 선택한 scope를 유지하고 core doctor의 issue/path를 확인합니다. 승인된 수동 repair로 `repository_state=ready`를 만든 뒤 reload 또는 새 session에서 `context-decision:init`을 재시도합니다.

모든 실패는 exact source와 manual action을 표시하며 repository와 host configuration bytes를 바꾸지 않습니다. Storage-level `context_root_missing`은 core read surface의 별도 오류이며 addon UX에서는 ready core의 `core_uninitialized`로 분류합니다.

## Product flow

결정이 확정되면 한 번의 grouped proposal에서 `결정`, `취지`, `반려대안`, lifecycle과 digest를 확인합니다. 승인된 final bundle은 `context-core` coordinator만 적용합니다. 이후 brief는 세 핵심 section을 함께 복원하고, 새 결정이 같은 slot을 supersede하면 이전 DEC를 history로 이동해 더는 따르지 않도록 표시합니다.

기존 `wiki/` 자동 migration은 제공하지 않습니다. PCMS는 조직 권한·승인 workflow·cross-project search·policy·audit·conflict queue의 control-plane 경계이며, 이 local plugin은 결정 기록과 recall 자체에 집중합니다.
