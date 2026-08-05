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

## 2. 요청 프로파일 — 실물 확인 완료 (2026-08-05)

부산 중구 목록 페이지 원본 HTML(28,855 bytes)을 확보해 검증했다.
fixture: `tests/fixtures/kfcc/list_busan_junggu.html`
(sha256 `070b689d253b27d6ed46c2bb1f24bd85c4e003ca3dcb2d89281fcad095f8bf44`)

### 2.1 목록 — 확인됨

```yaml
region_list:
  path: /map/list.do
  method: GET
  params: [r1, r2]          # r1=시도(부산), r2=시군구(중구)
```

`200 OK`, 목록이 **초기 HTML에 그대로 들어 있다.** AJAX 추가 요청이 필요 없다.

### 2.2 금리 페이지 — 명세서 v3 §7.3.3을 정정한다

명세서는 `/map/goods_19.do?OPEN_TRMID=&gubuncode=`를 가정했으나,
실제 페이지의 「금리」 버튼은 다른 경로를 호출한다.

```javascript
function view_rate(elm) { _view(elm, "sub_tab_rate"); }
function _view(elm, tabId) {
  var param = M4Dom.loadSpanSection(trElm);   // 행의 숨김 span 전부
  param.tab = tabId;
  M4Ajax.actionForm("view.do", param, { method: "get" });
}
```

```yaml
rate_detail:
  path: /map/view.do
  method: GET
  params: <목록 행의 숨김 span 값 전부> + tab=sub_tab_rate
```

즉 금리 조회는 별도 코드 체계가 아니라 **목록 행의 값을 그대로 되돌려 보내는 방식**이다.
`OPEN_TRMID`/`gubuncode`는 현재 페이지에 존재하지 않는다. 상품군 코드(12/13/14) 가정도
근거를 찾지 못했으므로, 상품군 구분은 `view.do` 응답 본문에서 확인해야 한다.

이 경로는 공식 API 계약이 아니라 공개 웹페이지의 현재 구현 세부사항이다.
구조 지문이 바뀌면 `schema_changed`로 처리한다.

---

## 3. 기관 식별자 — 실물 확인 완료

목록 페이지는 원천값을 **숨김 span**으로 노출한다.

```html
<span hidden="true" style="display: none;" title="gmgoCd">1203</span>
<span hidden="true" style="display: none;" title="gmgoNm">대청</span>
<span hidden="true" style="display: none;" title="divCd">001</span>
```

한 행이 제공하는 필드 전체 (실측):

| title | 예시 | 용도 |
|---|---|---|
| `gmgoCd` | `1203` | **institution 키** |
| `gmgoNm` | `대청` | 금고명 |
| `name` | `대청` | 표시명 (gmgoNm과 중복) |
| `divCd` | `001` | **outlet 키 구성요소** |
| `divNm` | `본점` | 점포명 |
| `gmgoType` | `지역` | **지역금고/직장금고 구분** |
| `telephone` | `051-463-2166` | 대표번호 |
| `fax` | `051-464-0881` | 팩스 |
| `addr` | `부산 중구 대청로 101-1` | **전체 주소** |
| `r1` / `r2` | `부산` / `중구` | 시도 / 시군구 |
| `code1` / `code2` | `1203` / `001` | gmgoCd/divCd 사본 |
| `sel`, `key`, `pageNo` | (빈값) / `1` | 화면 상태값 |

### 3.1 참고 저장소보다 우위인 지점

공식 목록은 참고 저장소 JSON에 **없는 3개 필드**를 제공한다.

- `gmgoType` — 명세서 v3 §7.3.4 item 7이 요구한 "직장금고 여부를 명칭으로 확정하지 말 것"을
  공식 값으로 해결한다. 부산 중구 표본은 전부 `지역`이었다.
- `addr` — 전체 주소. 행정구역 코드 매핑과 지역 검증에 쓸 수 있다.
- `telephone` / `fax` — 기관 마스터 보강.

### 3.2 교차 검증

부산 중구 목록 파싱 결과 **9행 / 고유 `gmgoCd` 6개**.
참고 저장소 집계(중구: 금고 6, 점포 9)와 **독립적으로 일치**한다.

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

1. ~~부산 중구 `map/list.do` 원본 HTML 확보~~ — **완료.** fixture 고정 완료
2. ~~목록 파싱으로 `gmgoCd`/`divCd` 추출 가능 여부 확인~~ — **완료.** 9행/6금고 추출, 참고 데이터와 일치
3. `view.do?tab=sub_tab_rate` 금리 페이지 원본 HTML 확보 — 진행 중
4. `.tblWrap`/`.tbl-tit`/`#divTmp1` 선택자 유효성과 `divTmp2` 등 추가 금리영역 존재 여부 확인
5. 금리표 파서 구현 + golden 기대값 고정

---

## 7. 미해소 항목

1. ~~`map/list.do` 응답 본문 구조~~ — **해소.** 숨김 span 구조 확인, 파서 검증 완료
2. ~~`map/goods_19.do`의 파라미터~~ — **해소(정정).** 해당 경로가 아니라 `view.do`가 실제 경로
3. 금리 페이지(`view.do`) 응답 본문 구조 — 표본 확보 진행 중
4. 상품군(거치식/적립식/요구불) 구분 방식 — 명세서의 12/13/14 코드 가정은 근거 미발견. 응답 본문에서 재확인 필요
5. 우대금리·우대조건 영역의 존재 여부와 위치
6. 이용약관·자동수집 정책 검토 — 운영 배포 전 필수 (명세서 v3 §15.3 `policy_status: review` 유지 중)
7. Actions 러너 IP가 지속적으로 허용될지 — 차단 시 회로차단기로 `blocked` 처리
