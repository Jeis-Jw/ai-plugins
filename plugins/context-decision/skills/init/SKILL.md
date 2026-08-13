---
name: init
description: context-decision owner descriptor와 empty decision index seed를 context-core에 등록하도록 제안한다.
---

# Init

먼저 context-core 설치와 `context-common/v1` compatibility를 확인한다. `decision_cli.py init --json`은 owner descriptor와 empty index seed만 반환하며 파일을 쓰지 않는다. host는 이를 context-core area-register preview에 전달하고 사용자가 exact digest를 승인한 뒤 core coordinator로만 적용한다.
