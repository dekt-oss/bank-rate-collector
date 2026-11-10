#!/usr/bin/env bash
# 완료 확인: CI(.github/workflows/ci.yml)가 돌리는 검사 중 린트·테스트를 그대로 오프라인으로 돌린다.
cd "$(git rev-parse --show-toplevel)" || { echo "SMOKE FAIL 0/0 (git 저장소 밖)"; exit 1; }
source .claude/shared/smoke-run.sh

# 의존성은 잠금 파일(uv.lock) 그대로 맞춘다 — CI 의 "Sync dependencies" 단계와 같다.
step "의존성 동기화" uv sync --locked
# 웹 로그인 런타임 검사 — CI 의 "Check website authentication runtime" 단계와 같다(네트워크 없음).
step "웹 인증 문법" node --check web/runtime/auth-core.mjs
step "웹 미들웨어 문법" node --check web/runtime/middleware.js
step "웹 인증 테스트" node --test tests/web_auth.test.mjs
# 린트 — CI 의 "Lint" 단계와 같은 대상.
step "린트(ruff)" uv run ruff check src tests scripts
# 테스트 — CI 의 "Test" 단계. CI 는 외부 네트워크·시크릿 없이 돈다(ci.yml 머리말)라서 제외 표시를 따로 두지 않는다.
step "테스트(pytest)" uv run pytest -q

finish
