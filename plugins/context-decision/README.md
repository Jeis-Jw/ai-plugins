# context-decision

`context-decision`은 “무엇을 결정했고, 왜 그 결정을 따르며, 어떤 대안을 반려했는가”를 다음 agent와 session에서 바로 복원하는 decision continuity plugin입니다. 현재 DEC는 authoritative하며 superseded history는 `do_not_follow`로 표시됩니다.

## Manual hard dependency

요구 좌표는 marketplace `jeis-ai-plugins`, plugin `context-core`, selector `context-core@jeis-ai-plugins`, source `Jeis-Jw/ai-plugins`, protocol `context-common/v2`입니다. 동명 plugin이나 다른 marketplace source는 대체하지 못합니다.

1. 사용자가 provider marketplace에서 exact core를 원하는 scope에 직접 설치·활성화합니다.
2. host를 reload하거나 새 session을 엽니다.
3. `$context-decision:init`을 한 번 호출합니다.
4. installed core public bootstrap이 필요한 core seed와 decision area를 적용하고, 현재 host의 `AGENTS.md` 또는 `CLAUDE.md`에 context 운영지침 managed block을 설치합니다. ready 재호출은 모두 noop입니다.

`context-decision`은 marketplace add, install, enable, update 또는 host configuration 변경을 자동 실행하지 않습니다. Manifest에도 dependency나 implicit/default install metadata가 없고 core 구현을 내장하지 않습니다. `schema`와 `capabilities`만 core 없이 확인할 수 있으며, 그 밖의 repository operation은 identity → source → enabled → protocol → read-only core doctor 순서의 preflight를 먼저 통과해야 합니다. `repository_state=absent`만 bootstrap-required로 분류하고, partial/invalid 진단은 전역 거부하지 않고 실제 decision target과 겹칠 때 해당 command가 중단합니다.

## Exact failure UX

- `core_missing`: source `Jeis-Jw/ai-plugins`의 `context-core@jeis-ai-plugins`를 사용자가 선택한 scope에 직접 설치하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_source_mismatch`: source `Jeis-Jw/ai-plugins`의 exact selector를 사용자가 선택한 scope에 직접 설치하고 다른 marketplace의 동명 plugin을 사용하지 않습니다. reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_disabled`: source `Jeis-Jw/ai-plugins`의 exact core를 사용자가 선택한 올바른 scope에서 직접 활성화하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_incompatible`: source `Jeis-Jw/ai-plugins`의 exact core를 사용자가 선택한 scope에서 `context-common/v2` 호환 버전으로 직접 업데이트하고 reload 또는 새 session 뒤 `context-decision:init`을 재시도합니다.
- `core_uninitialized`: plugin 설치 문제가 아닙니다. installed `context-core` public `bootstrap` surface가 같은 호출에서 core seed와 decision area를 순서대로 적용합니다. 별도 core init 호출은 필요하지 않습니다.
missing/source mismatch/disabled/incompatible 실패는 exact source와 manual action을 표시하며 repository와 host configuration bytes를 바꾸지 않습니다. Storage-level `context_root_missing`은 core read surface의 별도 오류이며 addon preflight에서는 installed core의 bootstrap-required `core_uninitialized`로 분류합니다. doctor의 partial/invalid `issues|warnings`는 성공 preflight의 diagnostics로 전달합니다.

Host는 `schema`/`capabilities`를 제외한 모든 CLI 호출에 `--host`, `--core-inventory @file`, `--core-doctor @file`을 전달합니다. Direct DEC는 `candidate prepare --candidate-id ... --commitment-evidence ...`로 exact candidate를 고정한 뒤 semantic owner가 판독하고, accepted choice만 `capture --candidate @file --attestation @file`로 draft합니다. fact/idea는 `capture --candidate @file --decline-reason ...`로 draft 없이 종료합니다.

## Product flow

context-core가 각 대화 delta를 같은 응답 pass에서 가볍게 audit하고, 선택의 형성·변경 신호가 있을 때만 context-decision을 부릅니다. 같은 scope·anchor와 `{id,sha256}`의 본문이 session context에 남아 있을 때만 재사용하며, 본문이 없거나 관련 anchor가 바뀌면 `check`가 metadata로 후보를 줄이고 Current DEC의 실제 `결정`, `취지`, `반려대안`을 제공합니다.

- `same`: 기존 결정을 재사용하고 중복 기록하지 않음
- `supporting`: 기존 결정을 유지하고 재사용 가치가 있는 새 근거만 OBS 후보로 제안
- `rationale_changed`: 결론 전에 취지 변화와 영향을 알리고 유지·변경 의도를 확인
- `conflict`: 양립하지 않는 내용을 결론 전에 알리고 유지·supersede 의도를 확인
- `new`: 조회된 범위 안에서 관련 기존 결정을 찾지 못함

이 비교는 실제 본문을 대상으로 하며 문자열 hash, ID나 metadata를 의미 동일성의 근거로 사용하지 않습니다. 충돌·취지 변경은 결론 전에 알리고, 그 외의 성숙한 결정은 원래 답 뒤 grouped proposal에 한 번 포함합니다. dismissed·deferred 후보는 새 evidence 전까지 반복하지 않으며 승인된 final bundle만 `context-core` coordinator가 적용합니다. 이후 brief는 세 핵심 section을 함께 복원하고, 새 결정이 같은 slot을 supersede하면 이전 DEC를 history로 이동해 더는 따르지 않도록 표시합니다.

`init`이 설치하는 managed policy가 증분 audit, 선택적 recall, 변화 알림과 grouped capture를 매 대화에서 유도합니다. 이는 agent의 같은 응답 pass에서 동작하는 운영지침이지 background daemon이나 per-turn hook은 아닙니다. 사용자 확인 없는 durable write는 계속 금지됩니다.

기존 `wiki/` 자동 migration은 제공하지 않습니다. PCMS는 조직 권한·승인 workflow·cross-project search·policy·audit·conflict queue의 control-plane 경계이며, 이 local plugin은 결정 기록과 recall 자체에 집중합니다.

0.2.0은 `claim_fingerprint`, `source_claim_fingerprint`와 batch-local `claim_key`를 제거한 breaking release입니다. `candidate_id`는 owner result 연결용 transport ID일 뿐 의미를 갖지 않습니다. 혼합 설치는 `context-common/v2` handshake에서 fail-closed합니다. 구형 artifact의 제거된 field는 읽을 수 있고 다음 승인 rewrite에서 lazy-clean합니다. 신규 candidate/draft에는 `schema_removed_field`로 계속 거부하며 fingerprint를 의미상 동일성 근거로 사용하지 않습니다.

0.2.1은 `context-common/v2` 호환 patch release입니다. core doctor의 `partial|invalid` 진단은 전역 preflight 실패가 아니라 warning으로 전달하고, 실제 decision target과 겹치는 blocking issue만 해당 operation을 중단합니다. init target 자체의 schema·owner·path가 안전하지 않을 때만 core bootstrap이 write 0으로 실패합니다.

0.3.0은 core audit가 선택 형성·변경 신호를 찾았을 때만 decision 비교를 수행합니다. `check`는 metadata로 후보를 먼저 좁히고 무관한 score-0 본문을 열지 않으며, 실제 관련 DEC 본문·scope·rationale 비교와 승인형 capture 경계는 그대로 유지합니다.
