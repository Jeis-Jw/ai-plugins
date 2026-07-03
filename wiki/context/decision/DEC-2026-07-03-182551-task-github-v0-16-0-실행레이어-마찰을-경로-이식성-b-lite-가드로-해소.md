---
title: task-github v0.16.0 — 실행레이어 마찰을 경로 이식성 + B-lite 가드로 해소
created_at: 2026-07-03
summary: copymachine Wave1 피드백 6건 반영. 실행 레이어 스케일 마찰을 경로 이식성·핸드오프·공유지식·closeout 가드로 메우고 경량 토폴로지 신모드는 반려.
tags: [task-github, portability, orchestrate, closeout, codex]
relations:
  intents: [INT-2026-05-29-104711-plugin-agent-neutrality, INT-2026-05-29-104712-parallel-safe-headless-operation]
  rejected_decisions: [REJ-2026-07-03-182352-solo-경량-브랜치-토폴로지-신모드]
---

## 결정

의사결정 레이어(challenge·의존성·DEC)는 유지하고 실행 레이어만 보강한다.

- **경로 이식성(C)**: 전 스킬·룰의 스크립트 경로를 `${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}` 앵커로 통일한다(Claude Code + Codex 공통). vendored `plugins/task-github/...`와 Claude 전용 `CLAUDE_SKILL_DIR`를 제거하고, 미해소 시 fail-loud STOP한다(조용한 스킵 금지). heredoc은 `python3 - "$ANCHOR" <<'PY'` argv[1]로 넘긴다. 규약은 `workflow.md §0`이 정본이고 `test_skill_path_portability.py`가 fenced-code에서 회귀를 막는다.
- **핸드오프 v2(D)**: orchestrate가 워커에 고정 env 블록(`TASK_GITHUB_ROOT`·`BASE_BRANCH`·`LEDGER`·`RUN_NOTES`, 전부 절대경로) + "재도출·재서술 금지, 플로우는 워커 스킬 소유" job-spec 원칙을 넘긴다.
- **공유지식 버스(A)**: `{container}-notes.md` run-notes(시드→run read→done append) + define 파일럿→팬아웃 규칙.
- **closeout 가드(B-lite)**: base-freshness `gh pr update-branch` 복구 · 컨테이너 머지업 전 pending-work 스캔(미커밋만) · wave freeze.
- **넛지(E/F)**: build≠동작 런타임 스모크 권고 · mechanism friction 보고.

main 9c60bda(v0.16.0), 158+2 tests green.

## 취지

실사용 1회전에서 의사결정 레이어는 토큰값을 했지만 실행 머시너리가 solo·소규모·원샷에 과했고, 그 머시너리가 실수(cache 경로 조용한 스킵, main 누락 니어미스, 형제 워커 재학습)를 만들었다. 스케일에 따라 실행 경로가 갈리되, 구조를 뒤엎지 않고 실체 결함만 메운다. [[INT-2026-05-29-104711-plugin-agent-neutrality]](설치 위치·하네스 비결합)과 [[INT-2026-05-29-104712-parallel-safe-headless-operation]](병렬 안전)에 직접 복무한다.

## 배경

task-github 0.15.3 **cache 설치**(레포 vendored 아님) 환경에서 copymachine solo·3리프·원샷 웨이브 실행 중 관측된 6개 마찰: (C) 스킬이 `plugins/task-github/...` 상대경로를 하드코딩해 cache에서 게이트/ledger가 조용히 스킵됨. (D) 오케스트레이터가 워커에 산문 핸드오프를 매번 재작성(토큰 배가·누락 위험). (A) 형제 워커가 같은 SDK API·env 버그를 각자 재도출. (B) 컨테이너 브랜치 발산으로 통합 PR이 in-flight 수정을 앞질러 머지→main 누락. (E) build-only verify가 런타임 크래시("빌드 성공, 화면 블랙") 놓침. (F) 워크플로 자체 회고 채널 부재. 기존 [[DEC-2026-07-02-224910]](ceremony=merge-edge-gear)·[[DEC-2026-07-02-212109]](all-PR·메인 워크트리 HEAD 불변)·[[DEC-2026-07-02-205231]](orchestrated expected-base 계약) 위에서 실행 레이어만 보강한다.

## 고려한 대안

- **B-full solo 경량 토폴로지 신모드** → 반려([[REJ-2026-07-03-182352-solo-경량-브랜치-토폴로지-신모드]]): 니어미스의 실체 원인은 브랜치 깊이가 아니라 동기화 가드 부재였고, 제안 구조는 이미 현 구조와 동형이며 승격 게이트·메인 HEAD 불변식을 무력화한다.
- **경로를 레포별 `.task-github.yml`에 두기** → 반려: 머신 종속 절대경로라 커밋 부적합.
- **pending-work 스캔에 unpushed(`@{u}`) 포함** → 반려: micro/normal 리프는 로컬 FF라 no-upstream이 정상이라 false-negative가 난다(adversarial 검증에서 blocker로 확정). 커밋된 미통합은 `child_merge_evidence`가 이미 게이트하므로 스캔은 **미커밋만** 본다.

## 트레이드오프

경로 앵커를 매 호출부에 인라인 반복하면 스니펫이 다소 길어진다 — 그러나 Bash 툴이 호출마다 새 셸이라 env가 블록 간 유지되지 않으므로 인라인 재해소가 견고하고, 조용한 스킵 제거가 길이보다 우선한다. B-lite는 토폴로지 근본 재설계가 아니라 실체 결함만 메우는 최소 개입이라, solo 과중 구조 자체는 남는다(재발 시 재론 여지로 의도적 보류).

## 재평가 조건

- cache/Codex에서 경로 회귀가 다시 나면 앵커 규약·portability test 재점검.
- B-lite 가드 적용 후에도 solo·소규모 웨이브에서 브랜치 발산/누락 니어미스가 재발하면 [[REJ-2026-07-03-182352-solo-경량-브랜치-토폴로지-신모드]]의 경량 토폴로지 스위치를 재론.
- run-notes가 형제 워커 재학습을 실제로 못 줄이면 define 파일럿→팬아웃을 프롬프트 권고에서 코드 강제로 승격 검토.
