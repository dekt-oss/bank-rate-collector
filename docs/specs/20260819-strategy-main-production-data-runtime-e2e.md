# Strategy merged-main production-data runtime E2E

## 목적

Strategy 기능의 마지막 검증을 `preview/strategy-dashboard` 브랜치나 Vercel 배포 성공 여부에 의존하지 않는다.

merged main 또는 이 workflow 자체를 개발하는 branch에서 다음 경로를 한 GitHub-hosted runner 안에서 끝낸다.

1. 현재 production canonical DB를 **runner-local copy**로 restore
2. local copy에만 migration 적용
3. `RATE_MONITOR_STRATEGY_DASHBOARD=1`을 **이 빌드에서만** 설정
4. 현재 source SHA의 코드로 Strategy 정적 사이트 build
5. payload의 `strategy.external_features`가 실제 production data로 `ready`인지 검사
6. localhost에서 Chrome desktop 1280 / mobile 390 smoke
7. screenshot + external feature payload를 artifact로 보존
8. exact SHA에 `strategy-main-runtime-e2e` commit status 기록

## 안전 경계

- Production Strategy Release Gate를 켜지 않는다.
- production DB/R2/rate-data에 write하지 않는다.
- runner-local DB copy만 migration/build에 사용한다.
- Strategy site를 Vercel이나 production branch에 publish하지 않는다.
- 수집을 재실행하지 않는다. 마지막 canonical snapshot을 읽기만 한다.

## External Market Context acceptance

실제 production data에 대해 다음이 모두 성립해야 한다.

- `external_features.status == ready`
- `policy_rate.status == ready` + value 존재
- `deposit_market.status == ready`
- 은행 순수저축성예금 신규취급 금리 ready
- 은행 1년 정기예금 신규취급 금리 ready
- 저축은행/신협/새마을금고/광의 상호금융 잔액 4종 모두 ready
- 4종 모두 MoM 존재
- DOM 금리 카드 3장 / 잔액 카드 4장
- DOM 값이 payload 값과 일치
- `농·축협과 1:1 동일하지 않음` 의미 경계 유지
- desktop/mobile 모두 horizontal overflow 및 runtime console error 없음

## 관측성

기존 connector는 push-triggered Actions run을 SHA로 열람하지 못하는 경우가 있다. 이 workflow는 GitHub commit status API에 직접:

- pending: `Strategy production-data runtime E2E running`
- success: `Strategy production-data runtime E2E passed`
- failure: `Strategy production-data runtime E2E failed`

를 기록한다. 따라서 run 목록 접근이 없어도 exact SHA의 결과를 확인할 수 있다.

## 비범위

- E1 내부실적 calibration
- inflow coefficient 변경
- E2 최적금리 solver
- source/collector 변경
- DB schema/migration 변경
- Production Strategy Release Gate ON
