# UI / Strategy 화면 발행 계약

## 목적

Strategy 및 공개 UI 코드는 `main`에 존재하지만 실제 서비스는 `rate-data` 브랜치의
`site-public/` 산출물을 배포한다. 따라서 UI 코드 merge와 실제 화면 반영은 같은 사건이 아니다.

2026-09-18 확인 당시:

- `rate-data/site-public/site-manifest.json` 생성시각: **2026-09-18 03:52 KST**
- Strategy IA PR #336 merge: **2026-09-18 08:59 KST**

즉 실제 공개 화면은 merge 이전에 만들어진 정적 산출물이었고, 브라우저 캐시가 원인이 아니었다.

## 정상 발행 흐름

```text
main UI/presentation 변경
        ↓
Publish UI — main presentation changes
        ↓
collect.yml / 화면만 재발행
        ↓
authoritative DB restore
        ↓
snapshot / validate / build-site / P1-A / size / volume gates
        ↓
rate-data/site-public push
        ↓
rate-data branch 전용 Vercel deploy
```

## 자동 발행 대상

`.github/workflows/publish-ui.yml`은 `main`의 다음 변경을 감시한다.

- Strategy/site presentation Python
- Strategy service/read-model
- `web/templates/**`
- `web/public-structural-v2/**`
- `web/api/**`
- `web/runtime/**`
- `vercel.json`
- UI publish workflow / reusable collect workflow 자체

presentation 변경이 merge되면 다음 정기 수집을 기다리지 않고 `화면만 재발행` 경로를 호출한다.

## 안전 경계

UI-only publish는 원천 데이터를 다시 수집하지 않는다.

- source collect 단계: `PUBLISH_ONLY=true`로 차단
- P1-A 검증: `--no-collection` 계약으로 실행
- canonical DB: authoritative R2에서 restore만 수행
- authoritative R2 state upload: **수행하지 않음**
- `rate-data-writer` concurrency: 기존 reusable workflow 계약을 그대로 사용
- 공개 정적 산출물 `rate-data/site-public`만 새 코드로 다시 생성

따라서 UI 배포를 위해 데이터 수집 안정성이나 canonical DB를 변경하지 않는다.

## 수동 복구

자동 발행이 실패하거나 즉시 재발행이 필요하면 기존
`수집 — 일반·새마을금고` workflow의 `화면만 재발행` target을 사용할 수 있다.

수동 복구도 동일한 build/validation/publish 경로를 사용한다.

## 운영 확인

UI merge 후에는 최소 다음을 확인한다.

1. UI publish workflow 성공
2. `rate-data/site-public/site-manifest.json.generated_at`이 merge 이후 시각
3. `rate-data` branch에 새 site publish commit 존재
4. 실제 서비스 페이지에서 새 IA/메뉴가 표시
5. 데이터 행수 및 canonical R2 state가 UI-only publish 전후 동일

PR merge나 CI 성공만으로 실제 화면 반영 완료로 판정하지 않는다.
