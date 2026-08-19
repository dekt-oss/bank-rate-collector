# Vercel deployment / 금리 데이터 갱신 안정화

- 기준일: 2026-08-19
- 후속 대상: PR #151 post-merge review R1~R6
- 목적: Vercel Hobby deployment 한도는 보호하되 운영 화면의 request-time GitHub Raw 의존성을 제거한다.

## 1. 현재 문제와 결정 변경

PR #151은 두 문제를 동시에 풀었다.

1. feature/main Git push가 불필요한 Vercel deployment를 만드는 문제
2. 정기 금리수집의 `rate-data` 갱신도 Vercel deployment를 만드는 문제

재검토 결과 두 문제의 위험도가 같지 않다. 정상 수집은 평일 하루 수회 수준이고,
100 deployments/day 한도의 직접 위험은 개발 PR/feature commit에 대한 불필요한 Git
Integration 반응이 더 컸다. 반면 수집 deployment를 0회로 만들기 위해 도입한
GitHub Raw 프록시는 운영 요청마다 외부 upstream을 추가한다.

따라서 최종 결정은 다음과 같다.

- **유지:** feature/main 자동 Git deployment 차단
- **철회:** `/`, `/strategy.html`, `/data/*`, `/site-manifest.json`의 GitHub Raw live proxy
- **복귀:** `rate-data` commit만 Vercel이 정적 사이트를 production으로 배포

즉 quota 방어와 운영 서빙 안정성을 분리한다.

## 2. 최종 목표 구조

```text
feature / PR push
  -> Vercel deployment 0회

main merge
  -> 수집 workflow의 publish-only 경로
  -> rate-data commit
  -> Vercel production deployment 1회

정기 / 수동 금리수집
  -> canonical DB/R2 갱신
  -> rate-data commit
  -> Vercel production static deployment 1회
  -> Vercel CDN에서 HTML/JSON 제공
```

`rate-data`가 유일하게 Vercel Git deployment를 허용하는 branch다.

```json
{
  "git": {
    "deploymentEnabled": {
      "**": false,
      "rate-data": true
    }
  }
}
```

Vercel은 `deploymentEnabled` branch pattern에 minimatch를 사용하고, 일치하지 않는 branch는
기본적으로 deployment가 허용된다. 후속 구현 과정에서 `"*": false`를 사용했을 때 실제
`fix/vercel-static-serving-stabilization-...` branch commit에 Vercel deployment가 생성되어
`success`까지 진행되는 것을 관측했다. slash가 포함된 branch까지 포괄하도록 globstar
`"**": false`로 수정한 뒤 다음 동일 branch commit에서는 Vercel status가 생성되지 않았다.

따라서 `*`가 모든 실제 branch name을 막는다고 가정하지 않는다. `**` deny + `rate-data` allow를
계약 테스트로 고정한다. 기존 `ignoreCommand`의 `rate-data` check도 defense-in-depth로 유지한다.

## 3. Raw proxy를 최종안으로 채택하지 않는 이유

### 3.1 GitHub Raw proxy

장점:

- 수집마다 Vercel deployment를 만들지 않는다.
- 기존 `rate-data/site-public` artifact를 거의 그대로 재사용할 수 있다.

기각 이유:

- 운영 `/`와 `/strategy.html`이 request-time GitHub Raw 가용성에 의존한다.
- `/data/*`와 manifest도 외부 upstream 경로가 추가된다.
- upstream/CDN propagation에 따라 `rate-data` push 직후 즉시 일치가 보장되지 않는다.
- quota 문제의 주원인이 아닌 하루 수회의 정상 수집을 제거하려고 운영 SPOF와 진단 복잡도를
  추가하는 trade-off가 과하다.

PR #151의 첫 activation은 성공했지만, 성공했다는 사실과 장기 운영 구조가 최선이라는 판단은
구분한다.

## 4. 대안 비교

### 4.1 R2 public data origin + 정적 HTML release

장기적으로는 가장 명확한 data/control-plane 분리 후보다.

```text
UI release -> Vercel static HTML
collection -> R2 public JSON/data
browser -> R2 data fetch
```

이번 변경에서 보류하는 이유:

- 현재 HTML 안에는 `rate-monitor-data`를 포함한 generated payload가 들어간다.
- data-only origin으로 전환하려면 frontend bootstrap, CORS, version/freshness contract,
  cache policy를 함께 재설계해야 한다.
- deployment quota 안정화보다 task boundary가 훨씬 크다.

수집 빈도가 향후 크게 증가하거나 정적 deployment가 다시 quota/latency 문제가 될 때 별도 ADR로
재검토한다.

### 4.2 Deploy Hook 배치

예: 수집은 계속 `rate-data`를 갱신하고 하루 N회만 Deploy Hook을 호출한다.

보류 이유:

- 의도적으로 화면 freshness를 늦춘다.
- hook secret, batching, missed-hook recovery라는 새로운 운영 state를 만든다.
- 현재 정상 수집 횟수에서는 필요성이 낮다.

### 4.3 선택안 — rate-data-only Git deployment

- feature/main push는 deployment 0회
- canonical `rate-data` publish만 deployment
- 기존 Vercel static/CDN 서빙과 smoke 의미를 유지
- 가장 작은 rollback surface

현재 수집 빈도에서는 이 구성이 단순성과 운영 안정성의 균형이 가장 좋다.

## 5. Vercel rewrite cache 검토 결과

리뷰 R3는 Vercel 공식 문서로 확인했다. external rewrite를 사용할 경우
`vercel.json`의 route `headers`에 `x-vercel-enable-rewrite-caching: 0`을 두는 방식이 공식적으로
지원된다. 따라서 PR #151의 설정 위치 자체는 오류가 아니었다.

이번 최종안은 external rewrite를 제거하므로 해당 header도 운영 config에서 제거한다.

## 6. Production smoke 계약

정적 배포 복귀 후 smoke는 다시 "Vercel production이 canonical rate-data보다 오래되지 않았는가"를
검증한다.

- expected manifest와 production manifest의 `generated_at`이 같으면 `rows`, `data_bytes`도
  exact-match한다.
- smoke가 시작된 뒤 다른 성공 writer가 배포되면 production이 expected보다 **더 최신**일 수 있다.
  이는 stale가 아니므로 PASS한다.
- production `generated_at`이 expected보다 과거면 FAIL한다.
- Production Strategy Release Gate가 ON인 현재 `strategy.html`은 expected/production manifest에
  **항상 존재해야 한다.** 없으면 FAIL한다.
- `/`, `/strategy.html`, `/api/health`의 실제 runtime marker/contract 검사는 계속 유지한다.

이 계약은 concurrent writer 때문에 발생한 false failure를 줄이면서 stale production은 계속 잡는다.

## 7. Strategy production-data E2E 계약

ECOS 공표시차나 연속월 부족은 코드 회귀가 아니다. E2E는 외부 feature의 **계약 오류**와
**정상적인 availability 상태**를 구분한다.

허용:

- bundle: `ready`, `partial`, `no_data`
- policy/bank rate: `ready`, `no_data`
- sector balance: `ready`, `no_data`, `insufficient_history`, `non_consecutive_months`

실패:

- `schema_unavailable`
- `source_contract_mismatch`
- `invalid_previous_balance`
- 정의되지 않은 status

`ready`일 때는 값과 DOM 표시의 일치를 계속 검증한다. availability가 낮으면 UI가 `—` 및 상태
라벨로 fail-closed하는지를 검증하고 전체 payload는 artifact로 보존한다.

## 8. 파일 위생

`collect.yml`, `collect-savings-fast.yml`, `nh-attempt.yml`, `production-smoke.yml`은 EOF newline을
항상 가져야 한다. 과거 "add trailing newlines" 성격의 변경에서 반대로 newline이 사라진 이력이
있으므로 `tests/test_workflow_file_hygiene.py`로 이 계약을 직접 고정한다.

## 9. 불변 조건

이번 안정화에서 변경하지 않는다.

- R2 authoritative DB와 storage contract
- 금리 수집 schedule
- source precedence
- stable product identity
- 금리 계산 / 전략 계산
- Production Strategy Release Gate ON 상태
- `rate-data-writer` concurrency 직렬화

## 10. Rollout / rollback

Rollout:

1. 후속 PR CI green
2. production-data Strategy E2E green
3. merge 승인 후 `main` publish-only run
4. `rate-data` Vercel static production deployment success 확인
5. `/`, `/strategy.html`, manifest, `/api/health` Production smoke 확인
6. 다음 실제 scheduled collection의 `rate-data` commit도 Vercel success인지 확인
7. feature/main slash branch commit에는 Vercel deployment가 생성되지 않는지 재확인

Rollback:

- 후속 PR revert 후 publish-only로 이전 production artifact 재배포
- DB/R2 데이터 상태에는 rollback write를 하지 않는다.

PR/CI 성공만으로 production 완료를 선언하지 않는다.
