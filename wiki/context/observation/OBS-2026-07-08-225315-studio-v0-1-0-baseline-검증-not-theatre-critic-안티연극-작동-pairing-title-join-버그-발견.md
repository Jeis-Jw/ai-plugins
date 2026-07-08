---
title: studio v0.1.0 baseline 검증 — not theatre, critic 안티연극 작동, pairing title-join 버그 발견
created_at: 2026-07-08
summary: notes-cli 미션으로 솔로 1 vs 팀 2run(brainstorm+pairing) 실행. theatre=false(팀 valid delta 45), critic이 pairing 모순 증거를 alive=false로 Kill. pairing 브로커 defended↔open title-string 조인 버그 발견(brainstorm index-join과 동종).
tags: [studio, multi-agent, baseline, dogfood]
---

## 관찰

studio v0.1.0 첫 실동작(baseline 프로토콜). 미션 notes-cli(마크다운 TODO/태그 추출 CLI). 결과:

1. not theatre (핵심 판정): 팀이 솔로가 안 만든 실질 delta 대량 생산. brainstorm valid delta 22(3라운드) — planner-a가 --done 플래그 자진 철회, planner-b가 unclosed-fence 침묵대응 자진 철회 등 실제 상호 양보·규칙 진화(첫문자숫자배제→전부숫자배제). pairing valid delta 23 — qa가 재현커맨드 딸린 실패 8건 발굴(list-marker 미추출·json 스키마 붕괴·splitlines 라인번호·FIFO hang·BOM 등), 다수가 AC 위반. 솔로는 유니코드태그·점디렉토리·단일파일인자·unclosed-fence 경고를 미지원/한계로 남겼는데 팀 AC는 커버.

2. critic 안티연극 작동: pairing critic이 alive=false로 Kill. 이유 정확 — 'defended 11/open 9인데 6건이 양쪽 동시 존재 → repro↔defense 쌍 미성립'. 칭찬 수렴 거부, 모순 증거 필터. rubric의 '애매하면 기각' 기본값이 실전 작동.

3. 발견한 studio 툴 버그(pairing.workflow.js): defended↔open 조인을 exact title string으로. qa 실패 title과 dev의 defended.failure_title을 두 에이전트가 다르게 표기 → 매칭 실패 → 방어해도 open에서 안 지워짐 → defended·open 동시 증가 모순. brainstorm critic index-join과 동일 계열(문자열/위치 조인 취약). 수정: qa 실패에 id 부여→dev가 defended id 에코→id 조인(brainstorm 수정과 동형).

4. 부수: 브로커 args 문자열화 방어(JSON.parse) 반영. Fable 쿼터 중단 run을 Opus resumeFromRunId로 완주(round1 캐시 재생) — 캐시 resume 실전 검증. 비용 150k/600k.

## 근거

brainstorm run wf_f0459fe6(alive=true,22 delta), pairing run wf_53a8ae20(alive=false,23 delta,3라운드). 솔로 baseline 서브에이전트(12 test green). evidence CLI: total_valid_deltas=45, theatre=false. board spent 150287. 산출 .worktrees/track-notes-cli/notes-cli/.

## 영향

컨셉 검증 성공 — studio는 연극이 아니라 실제 delta 생산. 단 pairing 브로커 조인 버그로 pairing verdict가 신뢰 불가(수정 전까지 pairing alive 판정 유보). brainstorm은 신뢰 가능.

## 현재 처리

pairing title-join 버그는 별도 태스크로 추적(id-join 수정). 이 관찰은 아직 DEC 승격 안 함 — 수정+재검증 후 owner 확인 시 승격.

## 후속 분류 조건

pairing 수정 후 재run에서 alive 판정이 안정적으로 나오면, baseline 성공을 DEC로 승격(studio 컨셉 검증 완료).
