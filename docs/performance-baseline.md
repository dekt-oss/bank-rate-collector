# Production browser performance baseline

기준일: 2026-08-11

Optimization v1 #74의 O2 판단 근거를 기록한다. 원칙은 **파일이 커 보인다는 이유만으로 sharding/lazy loading을 도입하지 않고 실제 production 병목을 먼저 측정한다**는 것이다.

## 측정 대상

- production: `https://bank-rate-collector.vercel.app`
- 공개 표: **326,793행**
- compact `table.json`: **21,251,456 bytes (20.27 MiB decoded)**
- 실제 Chromium 전송량: **1,650,693 bytes (1.57 MiB)**
- 측정 run: GitHub Actions `Performance baseline` run `31446157154`
- Chromium: Playwright headless Chromium 139
- cache disabled

## 결과

| 시나리오 | 첫 렌더 | table 응답 | 전송 | JSON parse | 검색 필터 | peak JS heap |
|---|---:|---:|---:|---:|---:|---:|
| desktop-fast · 1440×900 · 100 Mbps / 5 ms | 2,539 ms | 804.5 ms | 1.57 MiB | 119.1 ms | 498 ms | 237.25 MiB |
| mobile-LTE · 390×844 · 10 Mbps / 40 ms | 2,954 ms | 1,372.0 ms | 1.57 MiB | 131.7 ms | 497 ms | 230.79 MiB |
| mobile-slow-3G · 390×844 · 1.6 Mbps / 300 ms | 10,770 ms | 8,558.7 ms | 1.57 MiB | 143.2 ms | 482 ms | 173.72 MiB |

검색 필터 수치는 검색창 입력부터 결과 건수가 바뀐 뒤 두 번의 animation frame까지 잰 end-to-end 값이다. 현재 UI에는 `TYPING_PAUSE_MS = 200` debounce가 있으므로 약 0.5초 중 0.2초는 의도적인 타이핑 대기다.

## 판정

### 현재는 sharding/lazy loading을 도입하지 않는다

근거:

1. raw compact JSON은 20.27 MiB지만 CDN에서 실제 전송되는 양은 1.57 MiB다.
2. desktop/LTE 첫 렌더는 약 2.5~3.0초이고 JSON parse 자체는 약 0.12~0.13초다. 현재 병목은 JSON.parse 한 지점으로 수렴하지 않는다.
3. slow-3G 10.8초 중 table 응답이 8.6초라 회선 전송이 지배적이다. sharding은 이 조건에서 효과가 있을 수 있지만 현재 주요 사용 조건 전체에 복잡도를 추가할 만큼의 근거는 부족하다.
4. 검색 필터는 약 0.5초이나 200ms debounce를 포함한다. 현재 32만 행에서 즉시 구조 변경을 요구하는 수준으로 판정하지 않는다.
5. sharding을 도입하면 URL/filter/download/chart의 모집단 계약, source freshness와 publish gate, 정적 파일 생성 경로를 함께 복잡하게 만든다. 현재 측정 이득이 그 비용을 정당화하지 않는다.

### 감시할 수치

현재 구조를 유지하되 아래 변화가 있으면 다시 측정한다.

- 공개 행 수가 의미 있게 증가했을 때
- gzip 전송량이 현재 1.57 MiB에서 크게 증가했을 때
- desktop/LTE 첫 렌더가 반복 측정에서 악화될 때
- 필터 응답이 체감상 더 느려지거나 모바일 메모리 문제가 재현될 때

`Performance baseline` workflow와 `scripts/browser_perf.mjs`가 같은 방식으로 다시 측정할 수 있는 재현 경로다.

## 결론

**Optimization v1 O2에서 제품 코드의 구조 변경은 하지 않는다.** 측정 가능한 회귀 감시 경로를 추가하는 것이 현재 최소 범위의 최적화다. Static sharding은 후속 수치가 이를 요구할 때 별도 작업으로 연다.
