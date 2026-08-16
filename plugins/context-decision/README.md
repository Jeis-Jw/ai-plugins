# context-decision

`context-decision`은 “무엇을 결정했고, 왜 그 결정을 따르며, 어떤 대안을 반려했는가”를 다음 agent와 session에서 바로 복원하는 decision continuity plugin입니다. 현재 DEC는 authoritative하며 superseded history는 `do_not_follow`로 표시됩니다.

## Manual hard dependency

요구 좌표는 marketplace `jeis-ai-plugins`, plugin `context-core`, selector `context-core@jeis-ai-plugins`, source `Jeis-Jw/ai-plugins`, protocol `context-common/v1`입니다. 동명 plugin이나 다른 marketplace source는 대체하지 못합니다.

1. 사용자가 provider marketplace에서 exact core를 원하는 scope에 직접 설치·활성화합니다.
2. host를 reload하거나 새 session을 엽니다.
3. `$context-decision:init`을 한 번 호출합니다.
4. installed core public bootstrap이 필요한 core seed와 decision area를 적용하고, 현재 host의 `AGENTS.md` 또는 `CLAUDE.md`에 context 운영지침 managed block을 설치합니다. ready 재호출은 모두 noop입니다.

`context-decision`은 marketplace add, install, enable, update 또는 host configuration 변경을 자동 실행하지 않습니다. Manifest에도 dependency나 implicit/default install metadata가 없고 core 구현을 내장하지 않습니다. `schema`와 `capabilities`만 core 없이 확인할 수 있으며, 그 밖의 repository operation은 identity → source → enabled → protocol → read-only core doctor `repository_state` 순서의 preflight를 먼저 통과해야 합니다. Init만 `repository_state=absent`를 installed core public bootstrap으로 넘깁니다.

## Exact failure UX

- `core_missing`: source `Jeis-Jw/ai-plugins`의 `context-core@jeis-ai-plugins`를 사용자가 선택한 scope에 직접 설치하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_source_mismatch`: source `Jeis-Jw/ai-plugins`의 exact selector를 사용자가 선택한 scope에 직접 설치하고 다른 marketplace의 동명 plugin을 사용하지 않습니다. reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_disabled`: source `Jeis-Jw/ai-plugins`의 exact core를 사용자가 선택한 올바른 scope에서 직접 활성화하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_incompatible`: source `Jeis-Jw/ai-plugins`의 exact core를 사용자가 선택한 scope에서 `context-common/v1` 호환 버전으로 직접 업데이트하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_uninitialized`: plugin 설치 문제가 아닙니다. installed `context-core` public `bootstrap` surface가 같은 호출에서 core seed와 decision area를 순서대로 적용합니다. 별도 core init 호출은 필요하지 않습니다.
- `partial_core_init`: source `Jeis-Jw/ai-plugins`의 exact core와 사용자가 선택한 scope를 유지하고 core doctor의 issue/path를 확인합니다. 승인된 수동 repair로 `repository_state=ready`를 만든 뒤 reload 또는 새 session에서 `context-decision:init`을 재시도합니다.

missing/source mismatch/disabled/incompatible/partial 실패는 exact source와 manual action을 표시하며 repository와 host configuration bytes를 바꾸지 않습니다. Storage-level `context_root_missing`은 core read surface의 별도 오류이며 addon preflight에서는 installed core의 bootstrap-required `core_uninitialized`로 분류합니다.

Host는 `schema`/`capabilities`를 제외한 모든 CLI 호출에 `--host`, `--core-inventory @file`, `--core-doctor @file`을 전달합니다. Direct DEC는 `candidate prepare --candidate-id ... --commitment-evidence ...`로 exact candidate를 고정한 뒤 semantic owner가 판독하고, accepted choice만 `capture --candidate @file --attestation @file`로 draft합니다. fact/idea는 `capture --candidate @file --decline-reason ...`로 draft 없이 종료합니다.

## Product flow

대화가 선택으로 수렴하거나 기존 선택을 바꾸려 하면 `check`가 먼저 관련 Current DEC의 실제 `결정`, `취지`, `반려대안`을 bounded input으로 제공합니다. agent는 이를 새 후보와 비교해 다음 중 하나로 판정합니다.

- `same`: 기존 결정을 재사용하고 중복 기록하지 않음
- `supporting`: 기존 결정을 유지하고 재사용 가치가 있는 새 근거만 OBS 후보로 제안
- `rationale_changed`: 결론 전에 취지 변화와 영향을 알리고 유지·변경 의도를 확인
- `conflict`: 양립하지 않는 내용을 결론 전에 알리고 유지·supersede 의도를 확인
- `new`: 조회된 범위 안에서 관련 기존 결정을 찾지 못함

이 비교는 실제 본문을 대상으로 하며 문자열 hash나 지문을 의미 동일성의 근거로 사용하지 않습니다. 결정이 확정되면 원래 대화의 답을 먼저 마친 뒤 기록할지 한 번 묻고, 승인된 final bundle만 `context-core` coordinator가 적용합니다. 이후 brief는 세 핵심 section을 함께 복원하고, 새 결정이 같은 slot을 supersede하면 이전 DEC를 history로 이동해 더는 따르지 않도록 표시합니다.

`init`이 설치하는 managed policy가 scoped recall, 사전 비교, 변화 알림, semantic milestone의 grouped capture 제안을 매 대화에서 유도합니다. 이는 agent 운영지침이지 background daemon이나 runtime hook은 아닙니다. 사용자 확인 없는 durable write는 계속 금지됩니다.

기존 `wiki/` 자동 migration은 제공하지 않습니다. PCMS는 조직 권한·승인 workflow·cross-project search·policy·audit·conflict queue의 control-plane 경계이며, 이 local plugin은 결정 기록과 recall 자체에 집중합니다.

0.2.0은 `claim_fingerprint`와 `source_claim_fingerprint`를 제거한 breaking release입니다. 구형 artifact에 이 field가 남아 있으면 `schema_removed_field`로 중단하며 자동 삭제하거나 의미상 동일한 것으로 간주하지 않습니다. 기존 record는 별도의 검토·승인된 bounded migration 뒤 derived index를 rebuild해야 합니다.
