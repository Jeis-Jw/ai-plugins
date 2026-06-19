---
title: session-review(self): C2 closeout.py
created_at: 2026-06-19
summary: Self-flow review of task-github closeout automation.
tags: [session-review, review, dogfood]
type: snapshot
updated_at: 2026-06-19
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "diff"
target_ref: "task/c2-closeout-script"
base_ref: "454dc466500e3c2047e0870c89362508b5f082b8"
responding_to: "04034c0"
round: 2
flow_mode: "self"
review_strength: "hard"
blocking_count: 0
```

### 리뷰 피드백 (round 2) — verdict: approved (blocking 0)

Round-1 비차단 3건의 회귀 검토(hard). 승인된 코드는 재심하지 않고 델타(45c93fd)만 적대적으로 확인. 테스트 13/13 통과.

**#1 result-before-sync — 해결 확인.** run_closeout(closeout.py:159~182): `gh pr merge`(159) 직후, 어떤 로컬 sync보다 **앞서** `_detect_root_task`로 root/task를 산출하고 `result` dict(`task_to_complete` 포함, 166~170)를 완성한다. 그 다음에야 git checkout/pull/branch -d를 돌리는데, 이는 단일 루프에서 `subprocess.run`으로 직접 실행되어 returncode≠0이면 `sync_warnings`에 수집될 뿐 **절대 raise하지 않는다**(174~181). 따라서 머지 성공 후 dirty worktree·pull 충돌·브랜치 부재가 `task_to_complete`를 삼켜 task 노드를 active/에 방치하는 경로는 사라졌다 — 머지(역행불가)와 sync(역행가능)가 깔끔히 분리됨. 미사용 `git()` 헬퍼는 제거됨(`def git(` 0건, `git(` 호출부 0건 — dead code 없음). `subprocess` import 유지(21행).

**#2 extract_task_id stop-set — 해결 확인.** TASK_ID_RE가 `[^\s)\]]+` → `[^\s)\],.]+`로 후행 `,`/`.` 흡수를 차단(closeout.py:28). 신규 테스트 2건(test_stops_at_trailing_punctuation: 후행 `.`·`,`) 추가. 회귀 무: round-1 보존 케이스(대괄호/괄호 strip, 한글 슬러그 보존, absent→None) 전부 통과. **부수효과 무위험 확정**: wiki slug 계약(wiki_cli.py sanitize_slug:567~588)은 Unicode alnum+`-`만 허용하고 `.`을 명시적으로 금지하므로, 실재 TASK id에는 `.`/`,`가 들어올 수 없다 — stop-set 추가는 산문 후행 구두점만 떼어내며 정당한 슬러그를 절단할 길이 없다(`TASK-…-ab.c` 절단 케이스는 실 id에선 도달 불가).

**#3 done/wiki-bridge grep Unicode-safe — 해결 확인.** done/SKILL.md:131·wiki-bridge.md:122 둘 다 `[A-Za-z0-9-]+` → `[^[:space:]]+`로 교체. task-github 전역 sweep 결과 ASCII TASK grep 잔존 0건(`grep -rn A-Za-z0-9 | grep task` → 없음). merge 경로(스크립트 정규식)와 done/reconcile 경로(셸 grep)의 한글 슬러그 처리가 이제 일관됨.

**dry-run 무변경 재확인(restructure 후).** `if dry_run:`(141)이 모든 mutation(라벨제거 154~157 / merge 159 / sync 175~181)보다 앞에서 return(145~152). dry-run 분기는 읽기 전용 호출만 하고 별도 return dict를 가지므로, sync 루프 신설이 dry-run 경로에 닿지 않는다.

종합: 3건 모두 정확·완결, 회귀·부작용 없음. closeout은 이제 비가역 머지에 대해 견고하다(머지 성공 후 sync 실패가 결과/후속 task 전이를 절대 유실시키지 않음). blocking 0 → approved, next_actor=worker.

## 리뷰 요청 (round 1, flow_mode=self, hard)

C2: closeout.py — merge closeout 자동화(git/gh 전용). 대상 diff: git diff main..HEAD.
irreversible 머지 코드라 review-strength=hard. 순수 헬퍼 정확성, gh/git 시퀀스 로직, dry-run이 절대 머지 안 하는지, 에러 처리, merge SKILL 재작성 일관성 적대적 확인.

## 배경

target_mode=diff, base_ref=454dc466500e3c2047e0870c89362508b5f082b8, review_branch=task/c2-closeout-script-review, flow_mode=self

## 정해진 것

round1 비차단 3건 반영: #1 결과 dict를 sync 전 확정 + git sync best-effort(머지 후 실패가 task_to_complete 삼키지 않게), #2 extract_task_id 후행 구두점 stop-set+테스트, #3 done/SKILL·wiki-bridge grep Unicode-safe(한글 슬러그). 테스트 13.

## 아직 열린 질문



## 다음에 볼 것



## 관련 파일/문서



## 승격 후보
