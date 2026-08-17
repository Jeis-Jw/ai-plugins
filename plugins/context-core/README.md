# context-core

`context-core`는 다음 agent나 session이 작업을 이어갈 수 있도록 승인된 handoff와 재사용 가능한 근거를 Markdown으로 보존하는 가벼운 runtime입니다. SNAP은 재개용 staging, OBS는 비권위 evidence이며, `context.index.md`와 area index로 필요한 문서만 읽습니다.

## 시작하기

1. provider marketplace `jeis-ai-plugins`(source `Jeis-Jw/ai-plugins`)에서 `context-core@jeis-ai-plugins`를 원하는 scope에 직접 설치·활성화합니다.
2. host를 reload하거나 새 session을 엽니다.
3. `$context-core:init`을 한 번 호출하면 canonical storage seed와 활성 host의 관리형 운영지침을 core coordinator가 적용합니다.
4. 반환된 `doctor.repository_state: ready`, `policy.target`과 phase result를 확인합니다. ready 재호출은 noop입니다.

`schema`와 `capabilities`는 repository root 없이 확인할 수 있습니다. `doctor`는 read-only이며 `context-common/v2`와 `repository_state`를 보고합니다. 저장소가 아직 초기화되지 않은 read operation은 dependency 오류가 아닌 `context_root_missing`으로 실패합니다. `init`은 absent에서 fixed root/SNAP/OBS seed와 `codex → AGENTS.md`, `claude-code → CLAUDE.md` 관리형 block만 직접 적용합니다. marker 밖 bytes와 기존 파일 mode를 보존하고 직전 fixed bundle이 남긴 exact canonical write prefix만 재개하며, 그 밖의 partial/invalid는 자동 repair하지 않습니다.

## 제품 흐름

- Standalone: 명시적 handoff는 SNAP, 재사용 가능한 발견·근거는 OBS로 제안합니다.
- Integrated: semantic owner가 complete draft와 plan을 만들고, `context-core`가 grouped preview를 봉인한 뒤 유일한 physical coordinator로 적용합니다.
- Audit, route, claim, draft, preview와 denied apply는 repository와 host configuration을 변경하지 않습니다.
- 명시적 `init`과 addon init용 `bootstrap`만 fixed `core_init|area_register|policy_install`을 coordinator 검증으로 직접 적용합니다. 일반 artifact/index mutation의 exact digest approval은 유지됩니다.
- 관리형 운영지침은 substantive 판단 전에 scoped Current recall과 실제 본문·rationale 비교를 요구하고, conflict·취지 변경을 먼저 알린 뒤 milestone에서만 capture를 제안합니다. 의미 판정에 claim fingerprint를 사용하지 않습니다.

기존 `wiki/`를 자동 migration하지 않습니다. Obsidian은 repository root를 vault로 열 때의 선택적 view일 뿐 runtime dependency가 아닙니다. PCMS는 조직 권한·승인 queue·cross-project search·정책·감사 같은 control-plane 범위를 담당하며, 이 local plugin은 그 기능을 제한해 판매하는 제품이 아닙니다.

0.2.0은 의미 판정에 쓰던 `claim_fingerprint`, `source_claim_fingerprint`와 batch-local `claim_key`를 제거한 breaking release입니다. `candidate_id`는 owner result 연결용 transport ID일 뿐 의미를 갖지 않습니다. 혼합 설치를 호환으로 오판하지 않도록 wire/storage handshake를 `context-common/v2`로 올렸습니다. 제거된 field가 남은 0.1.x artifact/candidate는 조용히 무시하지 않고 `schema_removed_field`로 중단합니다. 기존 record는 별도의 검토·승인된 bounded migration에서 field를 제거한 뒤 derived index를 rebuild해야 합니다.
