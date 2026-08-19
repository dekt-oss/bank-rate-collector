# Vercel deployment / live data 분리

- 기준일: 2026-08-19
- 목적: Vercel Hobby의 deployment 생성 한도를 금리 수집 빈도와 분리한다.

## 문제

기존 구조에서는 모든 canonical site writer가 `rate-data` 브랜치를 교체했다.
Vercel Production Branch도 `rate-data`이므로 코드/화면 release와 정기·수동 금리 수집
결과 갱신이 같은 Vercel deployment 한도를 사용했다.

또한 Vercel Git Integration은 feature/main 브랜치 push에도 반응한 뒤
`ignoreCommand`에서 build를 건너뛰었다. 실제 build가 없어도 불필요한 Git deployment
시도가 생길 수 있었다.

## 목표 상태

브랜치 역할을 둘로 고정한다.

- `rate-live`: 최신 수집 결과와 생성된 `site-public`을 보관하는 live payload branch.
  정기/수동 수집은 이 브랜치만 갱신한다. Vercel Git deployment 대상이 아니다.
- `rate-data`: Vercel Production Branch인 release branch. `main` push로 실행되는
  publish-only 경로와 명시적 `화면만 재발행`에서만 갱신한다.

Vercel 운영 URL은 release에 포함된 라우팅 설정으로 다음을 제공한다.

- `/`, `/index.html`, `/strategy.html`: Vercel Function이 `rate-live/site-public`의
  최신 HTML을 읽어 `text/html`로 반환한다.
- `/data/*`: Vercel external rewrite가 `rate-live/site-public/data/*`를 프록시한다.
- `/site-manifest.json`: 같은 방식으로 live manifest를 프록시한다.
- `/api/collect`, `/api/health`: 기존 release에 포함된 Vercel Functions를 그대로 사용한다.

따라서 수집 결과와 생성 HTML 갱신은 `rate-live` push만으로 운영 URL에서 읽히고,
Vercel deployment를 만들 필요가 없다. API/라우팅 인프라 변경은 `rate-data` release가
필요하다.

## Git deployment gate

`vercel.json`의 `git.deploymentEnabled` 계약:

- `rate-data`: true
- `*`: false

Vercel 문서 계약상 여러 패턴에 동시에 일치하면 하나라도 true이면 deployment가
허용된다. 따라서 `rate-data`만 허용되고 feature/main/rate-live는 자동 Git deployment를
만들지 않는다. 기존 `ignoreCommand`는 defense-in-depth로 유지한다.

## Writer 계약

### 일반·새마을금고 (`collect.yml`)

- schedule / 실제 수집: `rate-live`만 publish
- main push / `화면만 재발행`: `rate-live` publish 후 `rate-data` release

### 은행권 경량 (`collect-savings-fast.yml`)

- 항상 `rate-live`만 publish

### 농·축협 (`nh-attempt.yml`)

- terminal publish가 필요한 attempt만 `rate-live` publish

모든 writer는 기존 `rate-data-writer` concurrency 직렬화를 유지한다. 이름은 과거 이름을
유지하지만 보호 대상은 canonical R2 state + public live/release branch 전체다.

## 복원 계약

R2가 authoritative인 현재 운영 경로는 기존과 동일하게 R2에서 DB를 복원한다.
GitHub legacy fallback이 필요한 경우에는 `rate-live`를 우선하고, 아직 branch가 없는
초기 전환 시 `rate-data`를 fallback으로 사용한다.

## Production smoke

Production smoke의 expected manifest는 `rate-live`가 존재하면 이를 사용하고,
초기 rollout 전에는 `rate-data`로 fallback한다. 첫 migration release가 성공한 뒤에는
수집 workflow 성공 후 Vercel 재배포를 기다리지 않고 live payload와 운영 URL의 일치를
검증한다.

## Rollout 조건

이 변경을 main에 merge하는 것만으로 첫 activation이 완결되는 것은 아니다.
현재 production deployment에는 live proxy 라우팅이 없기 때문에 `rate-data`의 새 release가
Vercel에 **한 번은 성공적으로 배포**되어야 한다. 그 한 번 이후부터 수집 갱신은 Vercel
재배포 없이 반영된다.

## 비목표

- R2 bucket을 public origin으로 전환하지 않는다.
- 수집 주기나 source precedence를 변경하지 않는다.
- DB schema, stable product identity, 금리 계산 계약을 변경하지 않는다.
- Strategy release gate 상태를 임의로 변경하지 않는다.
