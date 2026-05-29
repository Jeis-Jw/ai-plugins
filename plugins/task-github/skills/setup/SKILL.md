---
name: setup
description: 새 프로젝트 워크스페이스에 git을 초기화하고 GitHub 레포를 생성해 연결한다. "task-github:setup", "git 초기화해줘", "GitHub 레포 만들어줘", "새 프로젝트 시작하자" 등의 요청에 실행하라.
---

# setup — git/GitHub 초기화

새 워크스페이스를 git + GitHub로 부트스트랩한다.

## 입력

```
$ARGUMENTS: [owner]   # 선택. 생략 시 현재 로그인 사용자.
```

## 절차

### Step 0. 현재 상태 확인
```bash
git rev-parse --git-dir 2>/dev/null && echo "git 있음" || echo "git 없음"
git remote -v 2>/dev/null
```

### 분기
- git 없음 → Step 1부터
- git 있고 remote 없음 → Step 2부터
- 둘 다 있음 → 이미 구성됨, 중단

### Step 1. git 초기화 및 첫 커밋
```bash
git init
git add .
git commit -m "chore: 초기 환경 설정 — 자율 작업 프로토콜 및 슬래시 명령 구성"
```

### Step 2. GitHub 레포 생성 및 연결
```bash
# owner 지정 시
gh repo create {owner}/{레포명} --private --source=. --remote=origin --push

# owner 미지정 시 (현재 사용자)
OWNER=$(gh api user -q .login)
gh repo create ${OWNER}/{레포명} --private --source=. --remote=origin --push
```
레포명은 현재 디렉토리명(`basename $(pwd)`).

### Step 3. 라벨 부트스트랩 (없으면 생성)
```bash
gh label create "gear:micro"  --color "0E8A16" --description "자기 파일 내부만 영향" 2>/dev/null || true
gh label create "gear:normal" --color "FBCA04" --description "자기 서비스 내부 영향" 2>/dev/null || true
gh label create "gear:major"  --color "D93F0B" --description "외부 계약 변경" 2>/dev/null || true
gh label create "in-progress"       --color "1D76DB" --description "작업/재작업 중" 2>/dev/null || true
gh label create "in-review"         --color "5319E7" --description "리뷰 대기/검토 중" 2>/dev/null || true
gh label create "changes-requested" --color "E99695" --description "피드백 반영 필요" 2>/dev/null || true
```

### Step 4. (위키 연동) vault 제안
```bash
[ -d "./wiki" ] || echo "위키 vault 없음 — 결정 그래프 연동을 원하면 'wiki init' 제안"
```
- `./wiki/` 없고 `wiki-markdown` 플러그인이 있으면 `wiki init`을 **제안**(강제 아님). 자세한 연동은 [wiki-bridge.md](../../rules/wiki-bridge.md).

### Step 5. 안내
- 생성된 레포 URL 출력
- (프로파일 미설정 시) `CLAUDE.md`에 `프로파일: solo|team` 명시 권장
- 다음 단계 안내: `task-github:define` 또는 `task-github:start`

## 불변식
- 멱등에 가깝게: 이미 구성된 환경은 덮어쓰지 않고 중단.
- 레포는 기본 **private**.
- 위키 init은 제안만 — setup이 강제로 vault를 만들지 않는다.
