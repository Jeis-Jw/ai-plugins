---
title: session-review snapshot provider를 설정으로 선택하고 context-core를 연결한다
created_at: 2026-08-24
summary: 자동 발견 제거. .session-review.yml의 snapshot-provider(builtin|wiki-markdown|context-core)가 핸드셰이크 provider를 정하고, 못 찾으면 fallback 없이 오류. context-core adapter는 2단계 apply·1200자 cap·섹션 매핑을 facade 안에서 처리.
tags: [session-review, architecture, portability, context-core]
supersedes: [DEC-2026-06-19-144637-session-review-스냅샷-백엔드-하이브리드화]
relations:
  ssot: [session-review-plugin]
---

## 결정

session-review 0.7.0부터 snapshot 핸드셰이크 provider는 workspace의 `.session-review.yml`이 명시적으로 정한다 (`snapshot-provider: builtin|wiki-markdown|context-core`, 선택적 `snapshot-cli:`; env `SESSION_REVIEW_SNAPSHOT_PROVIDER`/`SESSION_REVIEW_SNAPSHOT_CLI`가 우선). 설정이 없으면 `builtin`(wiki snapshot과 동일 포맷·위치의 내장 writer). sibling `wiki_cli.py` 자동 발견과 `SESSION_REVIEW_WIKI_CLI`는 제거한다. 지정한 provider의 CLI는 sibling → 설치 cache(최신 버전) → PATH 순으로 찾되, 못 찾으면 silent fallback 없이 오류다. 자동 탐색은 provider를 *고르는* 데 쓰지 않는다.

context-core는 세 번째 provider다: `<worktree>/context/snapshot/<slug>.md`, 2단계 protocol(`snapshot save|update|discard` → bundle+digest → `transaction apply`)을 facade가 스스로 승인해 처리하고, status block은 `## 현재 맥락`에 둔다(wiki/builtin은 `## 현재 논의`). 스킬은 `git add wiki/snapshot` 대신 `snapshot-dir` 서브커맨드로 디렉터리를 얻는다.

## 취지

session-review 자체는 어떤 플러그인에도 의존하지 않는다. "snapshot을 핸드셰이크 매체로 쓰고 bespoke 포맷을 만들지 않는다"(DEC-2026-06-18)는 유지하되, *누구의* snapshot인지는 workspace 설정의 몫이다. 새 context-core 플러그인(별도 repo `context-plugins`)의 SNAP를 같은 리뷰 루프에 연결해야 했고, 암묵적 sibling 발견은 "옆에 깔려 있으면 동작이 바뀌는" 숨은 의존이라 명시 설정으로 바꿨다.

## 배경

2026-08-20 context-core/context-decision이 `context-manager/context-plugins`로 이관됐고, 사용자가 session-review의 wiki 의존을 확인하며 "설정파일로 외부 snapshot 플러그인을 정의, 자체 의존성 제거"를 요청했다(2026-08-23). context-core snapshot은 wiki와 모델이 다르다: `ctx_` UUID id, approval bundle → `transaction apply`, 섹션 `현재 맥락/열린 항목/다음 단계/정해진 것/참조/capture 후보`, `save`의 primary 1200자 cap, `--attestation` 필수. adapter는 seed 생성 후 `update --merge`(cap 없음)로 본문을 넣고, background는 `참조`에 합치며, list 섹션은 `- ` bullet화한다. `set-status`의 직접 body write는 context-core index가 frontmatter만 투영하므로 안전함을 실측(doctor/load/recall clean)과 테스트로 확인했다. 구현·검증: commit 0243cfd, 62 테스트(설치된 context-core 0.4.1 실제 round-trip 포함), 전체 633 green.

## 고려한 대안

- **하이브리드 자동 발견 유지 + context-core도 발견 대상에 추가**: 두 플러그인이 모두 깔린 workspace에서 어느 쪽이 이기는지 암묵 규칙이 생기고, 설치 여부로 동작이 바뀌는 숨은 의존이 남음 → 기각.
- **일반 command-template 설정(save/load/discard 셸 명령을 사용자가 정의)**: context-core의 attestation·2단계 apply·id 해석은 템플릿으로 표현 불가, 사용자가 wrapper 스크립트를 써야 함 → 과잉 일반화로 기각. provider별 adapter를 session-review 안에 두고 설정으로 고른다.
- **context-core 모듈 import로 Python API 직접 호출**: 내부 API 결합, CLI가 공개 표면 → 기각.
- **context-core 파일을 builtin처럼 직접 써서 포맷만 맞추기**: index가 안 갱신돼 recall 경고, coordinator 우회 → 기각. save/update/discard는 CLI 경유.
- **설정 없으면 오류**: 단독 설치 workspace 이식성(DEC-2026-06-19 취지) 손실 → builtin 기본 유지.

## 트레이드오프

얻음: 명시적·검사 가능한 provider 선택(doctor가 provider/source/cli/config 보고), 플러그인 무의존, context-core 연결, 설정 한 줄로 workspace별 전환. 잃음: session-review가 두 외부 CLI 표면(wiki_cli, context_cli)의 adapter를 보유 — 그쪽 CLI가 바뀌면 동기화 필요(특히 context-core의 1200자 cap·attestation 형식·section strip 비교). context-core 생성은 2 transaction(seed+merge). builtin writer의 wiki 포맷 중복은 그대로(DEC-2026-06-19 트레이드오프 승계).

## 재평가 조건

- context-core가 `snapshot save`의 primary cap을 없애거나 update에 cap을 넣을 때(seed+merge 우회 재검토).
- context-core index가 body 해시를 투영하기 시작할 때(`set-status` 직접 write를 `update --merge` 경유로 전환).
- 네 번째 provider 요구가 생겨 adapter가 3개를 넘을 때(provider contract 스크립트로 외부화 검토).
- studio cockpit 등 다른 플러그인이 session-review snapshot 위치를 직접 가정하지 않게 되면 `snapshot-dir` 외 추가 read 표면 불필요.
