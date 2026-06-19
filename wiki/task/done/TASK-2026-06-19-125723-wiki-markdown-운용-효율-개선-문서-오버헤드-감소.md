---
title: wiki-markdown 운용 효율 개선 (문서 오버헤드 감소)
created_at: 2026-06-19
summary: 플러그인 취지(결정 그래프·핸드오프·최소 토큰·무결성·4계층) 보존하며 capture 3스텝·snapshot 전량 재공급·orphan 후속작업 등 운용 오버헤드를 줄인다. 5개 개선안 기획·구현.
tags: [wiki-markdown, efficiency, ergonomics]
relations:
  ssot: [wiki-lifecycle, wiki-data-model]
---

## 개요

wiki-markdown 운용 시 doc 작업 오버헤드를 줄인다. 플러그인 취지(AI-native 결정 그래프 / 결정성 CLI / 최소 토큰 / 핸드오프·무결성 / 4계층)는 **보존**한다. 영향 ssot: [[wiki-lifecycle]], [[wiki-data-model]]. 근거 분석은 doc-first 조율 dogfood 세션(2026-06-19) 회고에서 나왔다.

## 근거

실제 운용(session-review 도그푸드 + 조율 작업)에서 누적 오버헤드를 코드로 확인:
- `capture`(`wiki_cli.py:2784-2806`): 섹션 콘텐츠 플래그 없음 → 골격 → read → 채우기 **3스텝/노드**.
- `snapshot save`(`wiki_cli.py:1752`): 빠진 섹션을 `""`로 덮어씀 → 매 라운드 **전 섹션 재공급** 강제.
- `orphan`(`wiki_cli.py:2305`) vs `find_backlinks`(`wiki_cli.py:967`): orphan의 `incoming`은 active만 스캔, backlinks는 done 포함 → done task가 백링크해도 그 DEC가 orphan으로 뜨는 **자기 불일치**.

보통(코드가 산출물) 작업에선 작은 task당 4~6 위키 작업 × 캡처 사이클 → 빠른 수정엔 코드보다 문서가 더 커질 수 있다. solo·소규모일수록 비율 악화.

## 범위와 완료 기준

**범위 — 5개 개선안 (효과순)**
1. **orphan 체크가 done-task 백링크 포함** (data-model). orphan `incoming`이 done docs도 스캔(또는 `find_backlinks` 재사용). 최소 변경·즉효 버그픽스.
2. **snapshot save 부분 업데이트** (lifecycle). 전달 섹션만 갱신·나머지 보존(`--merge` 기본, `--replace` 전체교체). 라운드 비용 최대 절감.
3. **capture 1콜화** (lifecycle). 섹션 콘텐츠 인라인 입력(섹션 플래그 / `--sections-json` / stdin) → 골격→read→채우기 3스텝 제거. `_replace_section`(`wiki_cli.py:902`) 재사용.
4. **경량 capture** (data-model). `--lite` = 핵심 섹션만 본문, 나머지 헤더 유지·"해당 없음" 허용. quality FLAG는 풀 기대치(opt-in).
5. **(정책, 코드 아님) 캡처 임계 명문화**. 작은/일회성=observation·커밋 메시지, DEC=재방문/되돌리기 비용 있는 것만. refresh는 묶음 끝 1회. "리프 task 금지" 강화 → agent-policy 스캐폴드 + CLAUDE/AGENTS.

**제약 (취지 보존 — 깨면 안 됨)**
- 고정 섹션 헤더·스키마 유지(Stage-2 recall 전제). 헤더 삭제 금지, 본문 옵션화만.
- 결정성(같은 입력→같은 출력) + JSON/exit code 계약 유지.
- 4계층 분리 + 비대칭(wiki는 task-github를 모름) 유지.
- 하위호환: 부분 업데이트·인라인·lite는 opt-in 또는 하위호환 기본값.

**완료 기준**
- 1~4 각각: `wiki_cli.py` 구현 + 신규 동작 테스트 + 기존 테스트(현재 133) 통과 + `refresh --strict` 영향 확인. wiki-markdown 버전 범프.
- 5: scaffold 정책 텍스트 갱신 + CLAUDE.md/AGENTS.md 재렌더.
- 각 항목은 doc-first `define`으로 단위 분해(필요 시 GitHub 이슈 트리) 후 진행.
- 회귀 0: 기존 capture/snapshot/refresh 사용처 호환.
