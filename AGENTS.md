# bank-rate-collector agent instructions

<!-- harness:begin — claude-config 에서 자동 배달. 이 블록과 .claude/shared/ 는 손으로 고치지 말 것 -->
## 공통 하네스 (Codex 도 따른다)
- 작업 전에 읽는다: 이 저장소의 `CLAUDE.md`(프로젝트 규칙), `.claude/shared/HARNESS.md`(공통 규칙), `.claude/shared/SKILL-MAP.md`(스킬 지도·알림·승인 규칙).
  프로젝트 규칙이 공통 규칙과 다르면 프로젝트 쪽이 이긴다.
- 스킬은 `.claude/skills/<이름>/SKILL.md` 를 직접 읽어 따른다. 유료 실행은 그 항목을 지목한 명시적 승인 없이 시작하지 않는다(SKILL-MAP 2절).
- 리뷰·검사: 어느 검사 AI 절차를 쓰는지와, **리뷰를 맡았을 때**(판정만)와 **직접 코드를 바꾼 뒤 커밋·PR 직전**(자체 점검 ≠ 독립 검사 → 독립 검사 대기)의
  구분은 SKILL-MAP 5절과 HARNESS §3 을 따른다.
- 완료 증거는 `bash scripts/smoke.sh` 의 마지막 줄(`SMOKE OK n/n`)이다.
<!-- harness:end -->

## Strategy production release policy

- Strategy dashboard is an established production surface. Canonical site-writer workflows keep `RATE_MONITOR_STRATEGY_DASHBOARD: "1"` and production tests enforce that contract.
- Do not describe Strategy production release as OFF based on historical handoff text or old conversation state. Repository workflow/test state is the source of truth.
- When the user explicitly authorizes a normal Strategy change to be merged, no second, separate "Release Gate ON" approval is required for the existing production writer to publish that merged Strategy code.
- Turning Strategy production publication OFF, removing `strategy.html`, or removing the Strategy navigation entry is a separate behavior change and requires explicit user approval.
- PR creation or merge is not runtime verification. For Strategy UI changes, use the existing production-data/preview browser E2E where applicable and report anything not verified.

## Financial/data safety

- Do not change prediction coefficients, source precedence, stable product identity, ranking populations, dedupe/identity rules, or persistent data contracts as a presentation cleanup unless the task explicitly requires it and the relevant evidence gate has been applied.
