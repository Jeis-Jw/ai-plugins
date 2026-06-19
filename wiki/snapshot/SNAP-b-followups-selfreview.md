---
title: session-review(self): B followups
created_at: 2026-06-19
summary: Self-flow review of B follow-ups (wiki+session-review).
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
target_ref: "task/b-followups"
base_ref: "46ac0cb74fa41747ac8833c04f5376771d8fa88a"
responding_to: "46ac0cb74fa41747ac8833c04f5376771d8fa88a"
round: 1
flow_mode: "self"
review_strength: "normal"
blocking_count: 0
```

### 리뷰 피드백 (round 1)
판정: approved (blocking 0). B 후속 4건 정확성·하위호환 모두 확인. 테스트 wiki 152 / session-review 22 전부 통과(기대치 일치), 버전 범프 정확(wiki 0.11.0, session-review 0.2.1 — plugin.json ×2 each + marketplace).

**B1 (apply_section_updates 공유 헬퍼)** — snapshot --merge 출력은 main과 바이트 동일(일반 merge + 빈 값 섹션 클리어 edge 모두). capture도 대부분 동일하나 **EOF 공백 1줄 드리프트** 발견(non-blocking): `spec.sections`의 **마지막 섹션에 본문이 채워질 때만** main은 `...본문\n\n`(EOF 빈 줄), HEAD는 `...본문\n`로 끝난다. `--lite` 캡처는 항상(마지막 비-core 섹션이 placeholder로 채워짐), 마지막 섹션을 인라인(--sec-*)으로 채울 때도 발생. 마지막 섹션이 비면 동일. 구조/파싱/round-trip/refresh 영향 없는 순수 EOF 외형 차이이고 어떤 테스트도 옛 `\n\n`를 보증하지 않아(152 통과) 코스메틱. 단 헬퍼 docstring·과제가 "포맷 불변"을 표방하므로 후속에서 `_replace_section` 마지막-섹션 분기의 trailing-blank 처리를 맞추거나 의도된 정규화로 명시 권장. 순서 드리프트 없음(스캐폴드가 순서 고정).

**B2 (refresh check 등급)** — 분류 완전·배타 검증 완료: KNOWN_REFRESH_CHECKS 15개 = integrity 6 + hygiene 9, 교집합 0, 미분류 0, 오타 0. CHECK_TIER가 정확히 known 집합을 덮어 `.get(c,"hygiene")` 폴백은 실제로 발화하지 않는 안전망(타당). 런타임 방출 check 코드 집합도 이 15개와 일치(decision/task-quality는 _append_quality_issue 경유, 둘 다 hygiene). integrity 분류(schema/broken-rel/task-ref/duplicate-basename/supersede/active-ref-retired)는 모두 구조/그래프 무결성으로 타당. 하위호환: 기본 --level all 이슈 집합이 main과 동일(경로 정규화 후), 추가된 것은 가산적 `tier` 키뿐. strict 의미 보존: bare --strict=rc6, --level all --strict=rc6(동일), --level integrity --strict(hygiene만 존재)=rc0 → integrity에만 하드페일. --level은 이슈 수집 전에 checks를 필터하므로 strict 평가 시점에 해당 tier 이슈만 남음(정확).

**B3a (내장 인덱스 유지)** — _replace_h2_section 4속성 모두 정확: 헤더 매칭·교체, 형제 보존(앞/뒤), create-if-missing(패딩 정상), 빈 본문 클리어, 마지막-섹션 케이스. wiki_cli의 _replace_section과 의미 동등. _rewrite_builtin_snapshot_index는 snapshot.md가 있을 때만 갱신, 없으면 무크래시 no-op(신규 테스트 2건이 존재/부재 양쪽 커버, 통과). 이 repo는 wiki 백엔드라 빌트인 경로는 휴면이나 직접 호출 테스트로 검증됨.

**B3b (request-review --fenced)** — render --fenced 존재·동작 정확(```yaml 펜스째). SKILL.md가 bare render+수동 printf 펜스 → render --fenced 직접 사용 + printf에서 수동 펜스 제거로 일관(이중/누락 펜스 없음). 옛 printf-래핑 출력과 --fenced 출력 바이트 동일 확인.

다음: worker. blocking 없음 — 머지 진행 가능. B1 EOF 드리프트는 선택적 후속(코스메틱).

## 리뷰 요청 (round 1, flow_mode=self)

B 후속 4건. 대상 diff: git diff main..HEAD.
- wiki B1: apply_section_updates 공유 헬퍼(capture·snapshot 재사용, 포맷 불변)
- wiki B2: refresh check 2등급 + --level + tier 태그(기본 all 하위호환)
- session-review B3a: 내장 인덱스 유지(존재 시), B3b: request-review --fenced
정확성·하위호환·tier 분류 타당성 관점.

## 배경

target_mode=diff, base_ref=46ac0cb74fa41747ac8833c04f5376771d8fa88a, review_branch=task/b-followups-review, flow_mode=self

## 정해진 것



## 아직 열린 질문



## 다음에 볼 것



## 관련 파일/문서



## 승격 후보
