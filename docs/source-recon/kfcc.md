# 소스 정찰: 새마을금고 (`kfcc_official`)

- 조사일: 2026-08-05
- 대상: 새마을금고 공식 「금고위치안내」 `https://www.kfcc.co.kr/map/main.do`
- 명세서 v3 §7.3 대응 문서
- 관련 문서: `docs/third-party/kfcc-reference.md` (참고 저장소 조사)

---

## 1. 도달성 판정 — 실행 위치가 결정적이다

`scripts/p0_kfcc_probe.py` 실행 결과, **같은 요청이 실행 위치에 따라 다른 결과**를 낸다.

| 실행 위치 | `robots.txt` | `map/main.do` | `map/list.do?r1=부산&r2=중구` | 판정 |
|---|---|---|---|---|
| 개발 컨테이너 (Claude Code 세션) | `400 Request Blocked` | `400 Request Blocked` | 미시도 (차단 즉시 중단) | **차단** |
| GitHub Actions 러너 (ubuntu-latest) | `200 OK` | `200 OK` | `200 OK` | **정상** |

프록시 상태(`__agentproxy/status`)는 `recentRelayFailures: []`로 정상이었고 GitHub·raw.githubusercontent 요청은
같은 경로로 성공했다. 따라서 차단 주체는 프록시가 아니라 새마을금고 측 접근제어로 판단된다.

### 결론

- `kfcc_official` 수집기는 **GitHub Actions 러너에서 실행**해야 한다.
- 개발 컨테이너에서는 공식 사이트 파싱을 실물로 검증할 수 없다.
  따라서 파서 개발은 **Actions에서 내려받은 원본 HTML fixture를 아티팩트로 가져와** 진행한다.
  (명세서 v3 §22 "실물 표본 없이 HTML 파서를 추정 구현하지 않는다" 준수)
- 차단 우회는 시도하지 않는다 (명세서 v3 §0.2, §16.1).

---

## 2. 요청 프로파일 (참고 저장소 기반, 실물 재검증 필요)

명세서 v3 §7.3.3이 제시한 경로. **아직 우리가 직접 응답 구조를 확인하지 않았다.**

```yaml
region_list:
  path: /map/list.do
  params: [r1, r2]          # r1=시도(예: 부산), r2=시군구(예: 중구)

rate_detail:
  path: /map/goods_19.do
  params: [OPEN_TRMID, gubuncode]

product_categories:
  demand_deposit: 12        # 요구불예탁금 — 실험 프로파일
  deferred_deposit: 13      # 거치식예탁금
  installment_savings: 14   # 적립식예탁금
```

`map/list.do?r1=부산&r2=중구`가 `200 OK`를 반환하는 것까지는 확인했으나,
**응답 본문 구조는 아직 파싱하지 않았다.** 다음 단계에서 원본 HTML을 아티팩트로 확보해 검증한다.

이 경로와 숫자는 공식 API 계약이 아니라 공개 웹페이지의 현재 구현 세부사항이다.
구조 지문이 바뀌면 `schema_changed`로 처리한다.

---

## 3. 기관 식별자

참고 저장소 실측 데이터에서 확인된 원천값 (`docs/third-party/kfcc-reference.md` §3.1):

```text
gmgoCd  공식 금고 코드   (예: "1203")
gmgoNm  금고명          (예: "대청")
divCd   본점·분점 구분   (예: "001")
divNm   본점·지점명      (예: "본점")
r1      시도            (예: "부산")
r2      시군구          (예: "중구")
```

- `institution` 키: `gmgoCd`
- `outlet` 키: `(gmgoCd, divCd)`
- 금리는 `gmgoCd`당 1회만 수집 — 부산 기준 점포 273개 대비 금고 137개이므로 요청이 절반으로 줄고 중복 행이 생기지 않는다.

---

## 4. 부산 수집 목표 모집단 (잠정)

참고 저장소 기준 **부산 137개 금고 / 273개 점포 / 16개 구·군**.
공식 직접수집으로 재확인하기 전까지 확정 모집단으로 쓰지 않는다
(명세서 v3 §13.4 "미확정이면 `모집단 확인 중`으로 표시").

구·군별 분포는 `docs/third-party/kfcc-reference.md` §3.1 표 참조.

---

## 5. 요청 제어 (명세서 v3 §7.3.8)

```yaml
concurrency: 2
request_interval_ms: 1000
request_jitter_ms: 300
connect_timeout_seconds: 10
read_timeout_seconds: 20
retry_count: 3
retry_backoff_seconds: [3, 10, 30]
max_consecutive_blocked: 3
circuit_breaker_minutes: 360
```

부산 137개 금고 × 상품군 2~3종 = 약 274~411회 요청.
1초 간격·동시성 2 기준 대략 3~4분 소요로 추정된다. (실측 아님)

---

## 6. 다음 단계

1. Actions에서 부산 1개 구(중구, 금고 6개)의 `map/list.do` 원본 HTML을 확보해 아티팩트로 저장
2. 목록 파싱으로 `gmgoCd`/`divCd` 추출 가능 여부 확인
3. 금고 1곳의 `rate_detail` 원본 HTML 확보
4. `.tblWrap`/`.tbl-tit`/`#divTmp1` 선택자 유효성과 `divTmp2` 등 추가 금리영역 존재 여부 확인
5. 확보한 HTML을 `tests/fixtures/kfcc/`에 golden fixture로 고정한 뒤 파서 구현 착수

---

## 7. 미해소 항목

1. `map/list.do` 응답 본문 구조 — 200 OK만 확인, 파싱 미검증
2. `map/goods_19.do`의 실제 파라미터 값 — `OPEN_TRMID`/`gubuncode`가 무엇을 받는지 미확인
3. 우대금리·우대조건 영역의 존재 여부와 위치
4. 이용약관·자동수집 정책 검토 — 운영 배포 전 필수 (명세서 v3 §15.3 `policy_status: review` 유지 중)
5. Actions 러너 IP가 지속적으로 허용될지 — 차단 시 회로차단기로 `blocked` 처리
