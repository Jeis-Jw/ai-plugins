---
name: init
description: context-decision owner descriptor와 empty decision index seed를 context-core에 등록하도록 제안한다.
---

# Init

먼저 context-core 설치와 `context-common/v1` compatibility를 확인한다. host가 exact plugin inventory와 read-only doctor receipt를 준비한 뒤 `decision_cli.py init --host <codex|claude-code> --core-inventory @file --core-doctor @file --json`을 호출한다. six-state preflight가 `ready`일 때만 owner descriptor와 empty index seed를 반환하며 파일을 쓰지 않는다. host는 이를 context-core area-register preview에 전달하고 사용자가 exact digest를 승인한 뒤 core coordinator로만 적용한다.
