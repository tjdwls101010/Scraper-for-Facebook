# Implementation kickoff prompt (paste into a fresh session)

Copy everything in the box below into a new Claude Code session opened in this repo.

---

```
scraper-for-facebook 저장소의 v0.3.0 "active-mode" 확장을 구현해줘. 이건 구현 세션이야
(계획은 지난 세션에 끝났고, 계획과 구현을 분리하기 위한 것).

먼저 계획 두 문서를 정독해 (docs/active-mode-expansion-plan 브랜치에 있음):
- docs/plans/2026-07-20-active-mode-expansion-plan.md   ← 로드맵 (이게 메인)
- docs/plans/2026-07-20-recon-findings.md               ← 실증 데이터 (doc_id·변수·커서·PoC)

배경 한 줄 요약: 현재 v0.2.0은 브라우저 스크롤로 한 프로필만 긁는 passive 스크래퍼다.
목표는 페이스북 백엔드 GraphQL을 "순수 HTTP"로 읽는 active 모드(브라우저는 로그인+토큰
추출에만) + 기존 passive를 폴백으로, 파서는 둘이 공유. 그리고 feed / comments / search /
group / post 프리미티브를 추가한다. 다중 홉 탐색은 CLI가 아니라 나중에 만들 스킬이 명령을
연쇄해서 한다. active 모드는 지난 세션에 end-to-end로 실증됨(브라우저에서 fb_dtsg/쿠키
추출 → scrapling FetcherSession POST → 기존 parse.py/model.py가 그대로 파싱).

진행 방식:
1) 계획의 Phase 0(라이브 재검증)부터 시작해. doc_id는 회전하니, scratch/ 의 리콘 스크립트
   (recon_capture_v2.py / recon_comments.py / poc_replay.py)로 신선한 doc_id를 다시 캡쳐하고,
   지난번에 못 잡은 "댓글 페이지네이션" 쿼리도 캡쳐해. 리콘·브라우저는 Chrome 확장이 아니라
   패키지 자체 scrapling 브라우저를 써. default 프로필 세션이 만료됐으면 먼저 로그인이 필요해
   (버려도 되는 부계정 사용).
2) 그다음 Phase 1(active transport core: tokens.py / queries.py / graphql.py / transport.py)로,
   기존 `fetch`를 active-우선 + passive 폴백으로 바꾸고 active-vs-passive 파리티 테스트로 검증.
3) 이후 Phase 2~6을 순서대로. 각 Phase에 적힌 verify 게이트를 통과할 때까지 반복(loop).
   Phase 7(.claude/skills/facebook)은 PyPI 배포 후 별도 세션.

반드시 지킬 제약:
- CLAUDE.md 준수: 최소 코드, 수술적 변경, 투기적 추상화·미요청 기능 금지.
- 새 active-요청 rate 하한(non-bypassable)을 둬서 대량 스크래퍼가 되지 않게 (계획 §6).
- PII: 캡쳐 산출물·픽스처에 제3자 PII 커밋 금지 (scratch/, *.ndjson, *.json 은 gitignore됨).
  새 유닛 픽스처는 반드시 스켈레톤화·스크럽.
- 로그인: 격리 프로필이 기본. `input()` 로그인 UX는 브라우저-상태 폴링으로 고칠 것.
  `--from-chrome`는 옵트인이고, 방식 (a) 복호화+주입(pycookiecheat식)으로 구현 (계획 §3a).
- status/detect_wall의 로그인폼 오탐(계획 recon §5.1)도 고칠 것.

시작하기 전에: 계획 두 문서를 읽고 → 현재 코드 상태(유닛 테스트 그린 여부: `PYTHONPATH=src
.venv/bin/python -m pytest -q tests --ignore=tests/live -p no:cacheprovider`, 그리고 로그인
상태)를 확인한 뒤 → Phase 0 실행 계획을 짧게 제시하고 진행해. 계획을 벗어나는 스코프 변경이
필요하면 먼저 물어봐.
```

---

**Notes for you (not part of the paste):**
- The plan docs live on branch `docs/active-mode-expansion-plan`. If you want them on `main`
  for the implementation session, `git checkout main && git merge --ff-only
  docs/active-mode-expansion-plan` (docs-only, clean fast-forward), then branch for implementation.
- The `default` login profile was freshly logged in during the planning session (throwaway
  account), so it may still be valid — but sessions expire; re-login if `status` (once fixed) says so.
- Recon scripts are preserved under `scratch/` (gitignored). The venv's console scripts have a
  stale shebang (repo was moved) — run Python as `PYTHONPATH=src .venv/bin/python -m ...` and
  commit docs/tests with `--no-verify` if the pre-commit hook can't launch.
