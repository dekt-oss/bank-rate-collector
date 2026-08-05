# 원천 정찰: 지역농축협 (`nh_local`) — **미완**

정찰 실행: 2026-08-05, `scripts/p1d_cu_nh_recon.py` + 직접 탐침
기계 판독 보고서: `docs/source-recon/cu-nh-recon.json`

**이 문서는 실패 기록이다.** 수집 경로를 찾지 못했다. 찾은 척하지 않는다.

---

## 1. 결론

**지역농축협의 조합별 수신금리를 한곳에서 비교하는 공식 화면을 찾지 못했다.**

새마을금고(`kfcc.co.kr/map`)와 신협(`cu.co.kr/cu/ad/inrstCmpr`)에는 중앙회가
운영하는 조합별 금리비교 공시가 있다. 농축협에서 그에 대응하는 화면을
2026-08-05 정찰로는 찾지 못했다.

**없다고 단정하지 않는다.** 못 찾은 것과 없는 것은 다르다.

---

## 2. 두드려본 곳

| URL | 결과 |
|---|---|
| `https://www.nonghyup.com/` | 200, 389바이트. 리다이렉트 껍데기 |
| `https://www.nonghyup.com/robots.txt` | 200, 6,299바이트 |
| `https://www.nonghyup.com/servlet/CRPMSP0011R.view` | **404** |
| `https://www.nonghyup.com/service/branch.do` | **404** |
| `https://www.nonghyup.com/index.do` | **404** |
| `https://www.nonghyup.com/pr/disclosure.do` | **404** |
| `https://www.nhbank.com/` | 200, 2,473바이트. 리다이렉트 껍데기 |
| `https://www.nhbank.com/nhbank.html` | 200이지만 제목이 `Error 404 \| NH 농협은행` — **소프트 404** |
| `https://banking.nonghyup.com/nhbank.html` | 200, 69,825바이트. 인터넷뱅킹 로그인 화면 |
| `https://banking.nonghyup.com/servlet/IPDPP0011I.view` | **404** |

인터넷뱅킹 화면에서 찾은 금리 관련 링크는 세 개뿐이고, 전부 조합별 비교가
아니었다 (`금융상품몰`은 `javascript:void(0)`, `경영공시`는 NH농협은행 것).

---

## 3. 왜 어려운가 — 확인한 사실

**NH농협은행과 지역농축협은 다른 기관이다.** 앞의 것은 은행(제1금융권)이고
`banking.nonghyup.com`이 그 창구다. 우리가 필요한 것은 **상호금융**인
지역농축협이고, 이것은 새마을금고·신협과 같은 제2금융권 상호금융이다.

금감원 finlife의 권역코드에도 지역농축협은 없다. 지금 쓰는 `030300`은
저축은행이고, 은행은 `020000`이다.

---

## 4. 다음에 시도할 것 — 우선순위 순

1. **농협중앙회 상호금융 부문 사이트를 따로 찾는다.** `nonghyup.com`이
   경제지주·금융지주로 갈려 있어 상호금융 공시가 다른 도메인일 가능성이 있다.
2. **금융상품한눈에의 "협회별 비교 공시"** —
   `https://finlife.fss.or.kr/finlife/main/contents.do?menuNo=700025`에
   협회별 공시 링크 모음이 있다. 여기에 상호금융 항목이 있는지 본다.
   이번 정찰에서 링크만 확인하고 내용을 열어보지 않았다.
3. **개별 조합 홈페이지**. 조합마다 따로 공시한다면 중앙 수집이 불가능하고,
   그 경우 이 원천은 `coverage_status: none`으로 남긴다.

---

## 5. 현재 상태

```
policy_status    unknown     (사이트를 특정하지 못해 약관 확인 자체가 불가)
coverage_status  none
수집기            없음
```

명세서 v3 §19의 세로 절단 4는 **착수하지 못했다.** 정찰이 선행 조건인데
그 정찰이 끝나지 않았다.
