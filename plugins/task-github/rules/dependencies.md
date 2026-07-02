# GitHub Issue dependency 규약

> 이 룰은 sub-issue 간 실행 순서 제약을 GitHub **Issue dependencies**로 표현하고, 스킬이 그 제약을 읽어 작업 시작/종료를 막거나 안내하는 공통 절차다.

---

## 1. 의미

| 관계 | 의미 | 실행 해석 |
|------|------|----------|
| sub-issue parent/child | 업무 분해 구조 | 무엇으로 쪼갰는가 |
| `blocked_by` | 이 이슈가 선행 이슈 완료를 기다림 | 열린 blocker가 있으면 시작/종료 차단 |
| `blocking` | 이 이슈가 다른 이슈를 막고 있음 | 이슈 close 후 downstream 후보 안내 |
| dependency 없음 | 선행 제약 없음 | 형제 리프끼리 병렬 가능 |

`parallel`/`sequential` 라벨은 두지 않는다. 병렬/직렬은 이분법이 아니라 DAG이며, GitHub dependency가 정본이다.

---

## 2. 부모 연결 정본

서브이슈 부모 연결은 GraphQL `createIssue(parentIssueId)`를 정본으로 쓴다. REST `sub_issues` 경로와 섞지 않는다. `define`은 `skills/define/scripts/create_issue_tree.py`를 사용해 루트 생성, 부모 연결, dependency 생성을 한 경로로 처리한다.

---

## 3. 공통 변수

```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
API_VERSION="2026-03-10"
```

REST dependency API는 `issue_id`로 REST numeric id를 요구한다. 이슈 번호를 id로 변환할 때는 GraphQL node id가 아니라 REST issue id를 읽는다:

```bash
BLOCKER_ID=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{BLOCKER_NUMBER}" --jq '.id')
```

---

## 4. dependency 생성

`{ISSUE}`가 `{BLOCKER}` 완료 뒤에만 실행되어야 하면:

```bash
BLOCKER_ID=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{BLOCKER}" --jq '.id')

gh api -X POST -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{ISSUE}/dependencies/blocked_by" \
  -F issue_id="$BLOCKER_ID"
```

관계 방향은 항상 **대상 이슈가 blocked_by를 갖는다**로 쓴다. 예: `#13 blocked_by #12`는 "#13은 #12가 끝나야 시작 가능"이다.

`blocked_by`에는 **직접(direct) 의존만** 선언한다. 이슈는 자기가 직접 필요로 하는 이슈만 나열하며, 그 blocker의 조상까지 옮겨 적는 transitive 의존이나 "혹시 몰라" 넣는 방어적 blocker는 두지 않는다. 예: `#13 blocked_by #12`, `#12 blocked_by #11`이면 `#13`에 `#11`을 다시 걸지 않는다 — `#11`은 `#12`를 통해 이미 전이된다. 불필요한 blocker는 병렬 폭(parallel width)을 인위적 직렬 사슬로 무너뜨린다. 근거: [[DEC-2026-07-02-224910]].

---

## 5. 시작/종료 차단 체크

`start`, `run`, `done`, `merge`는 같은 체크를 쓴다:

```bash
OPEN_BLOCKERS=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocked_by" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')

if [ -n "$OPEN_BLOCKERS" ]; then
  echo "차단: 이 이슈는 아직 열린 blocker가 있습니다."
  printf '%s\n' "$OPEN_BLOCKERS"
  exit 1
fi
```

이 체크는 GitHub가 직접 강제하지 않는 운영 규칙을 task-github가 강제하는 지점이다. 사령관이 명시적으로 override하면 이슈 코멘트에 `[결정] dependency override`와 사유를 남긴 뒤 진행할 수 있다.

---

## 6. downstream 안내

이슈가 close되었거나 close될 예정이면, 이 이슈가 막고 있던 downstream을 안내한다:

```bash
BLOCKING=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocking" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')

[ -n "$BLOCKING" ] && printf '이 이슈 완료 후 재검토할 downstream:\n%s\n' "$BLOCKING"
```

downstream이 실제로 ready인지 확정하려면 각 downstream의 `blocked_by`를 다시 조회해 열린 blocker가 0개인지 확인한다.

---

## 7. 실패 처리

Issue dependency API는 권한/플랜/gh 버전에 따라 실패할 수 있다. 수동 `define`의 dependency 생성 실패는 sub-issue 생성을 되돌리지 않고 fallback 코멘트로 남길 수 있다. orchestrate 대상 tree는 `--strict-deps`로 생성해 실패 시 `dep_create_failed`로 중단한다. `start`/`run`/`done`/`merge`의 dependency 조회 실패는 자동 진행하지 않고 사령관에게 수동 확인을 요청한다.

`define` 중 dependency 생성이 실패하면 해당 하위 이슈에 fallback 코멘트를 남긴다:

```bash
gh issue comment {ISSUE} --body "[관찰] dependency API 실패: 이 이슈는 #{BLOCKER} 완료 뒤 진행되어야 한다. GitHub dependency가 기록되지 않았으므로 start 전 수동 확인 필요."
```
