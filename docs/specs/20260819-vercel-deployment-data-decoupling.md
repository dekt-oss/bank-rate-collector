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

`rate-data` 한 브랜치가 계속 최신 public payload의 Source of Truth 역할을 맡되,
**payload 갱신**과 **Vercel release**를 서로 다른 계약으로 분리한다.

- 평소 `rate-data` commit: 최신 수집 결과와 생성된 `site-public`을 갱신한다.
  commit 안의 `vercel.json`은 `git.deploymentEnabled=false`이므로 Vercel deployment를
  만들지 않는다.
- release `rate-data` commit: `main` push로 실행되는 publish-only 경로 또는 명시적
  `화면만 재발행`에서만 staged `vercel.json`을 release 모드로 바꾼다. 이 commit만
  `rate-data=true` allow rule을 가져 Vercel production deployment를 한 번 만든다.

운영 Vercel deployment는 고정 라우터 역할을 한다.

- `/`, `/index.html`, `/strategy.html`: Vercel Function이 현재
  `rate-data/site-public`의 HTML을 읽어 `text/html`로 반환한다.
- `/data/*`: Vercel external rewrite가 현재 `rate-data/site-public/data/*`를 프록시한다.
- `/site-manifest.json`: 같은 방식으로 현재 live manifest를 프록시한다.
- `/api/collect`, `/api/health`: release에 포함된 기존 Vercel Functions를 그대로 사용한다.

따라서 수집 결과와 생성 HTML은 `rate-data`가 바뀌는 즉시 운영 URL이 새 payload를 읽으며,
수집 자체는 Vercel deployment를 필요로 하지 않는다. API/라우팅 인프라 변경은 release
commit이 필요하다.

## Git deployment gate

저장소의 기본 `vercel.json`은 다음 계약을 가진다.

```json
{
  "git": { "deploymentEnabled": false }
}
```

Vercel 공식 계약상 이는 모든 자동 Git deployment를 막는다. 따라서 feature/main branch
push도 deployment를 만들지 않는다.

`collect.yml`의 publish-only 경로만 `scripts/prepare_vercel_release.py`를 staged config에
실행해 아래처럼 바꾼다.

```json
{
  "git": {
    "deploymentEnabled": {
      "*": false,
      "rate-data": true
    }
  }
}
```

Vercel 문서 계약상 여러 패턴에 동시에 일치하면 하나라도 true이면 deployment가
허용되므로, 해당 staged commit에서는 `rate-data`만 release된다. 기존 `ignoreCommand`는
방어선으로 유지한다.

## Writer 계약

### 일반·새마을금고 (`collect.yml`)

- schedule / 실제 수집: 기본 config 그대로 `rate-data` publish → Vercel deployment 없음
- main push / `화면만 재발행`: staged config를 release 모드로 바꾼 뒤 `rate-data` publish
  → Vercel production deployment 1회

### 은행권 경량 (`collect-savings-fast.yml`)

- 기존대로 `rate-data` publish
- 저장소 기본 config가 deployment OFF이므로 Vercel deployment 없음

### 농·축협 (`nh-attempt.yml`)

- 기존대로 terminal payload를 `rate-data` publish
- 저장소 기본 config가 deployment OFF이므로 Vercel deployment 없음

모든 writer는 기존 `rate-data-writer` concurrency 직렬화를 유지한다. 수집 주기와 source
precedence, R2 authoritative state 계약은 바꾸지 않는다.

## Production smoke

expected manifest는 기존과 같이 `rate-data/site-public/site-manifest.json`을 사용한다.
첫 migration release가 성공한 뒤에는 수집 workflow 성공 후 Vercel 재배포를 기다리지 않고
현재 `rate-data` payload와 운영 URL의 일치를 검증할 수 있다.

## Rollout 조건

이 변경을 main에 merge하는 것만으로 첫 activation이 완결되는 것은 아니다. 현재 production
deployment에는 live proxy 라우팅이 없기 때문에 publish-only 경로가 만든 새 `rate-data`
release가 Vercel에 **한 번은 성공적으로 배포**되어야 한다. 그 한 번 이후부터 정기/수동
수집 갱신은 Vercel 재배포 없이 운영 URL에 반영된다.

현재 Vercel Hobby deployment quota가 잠겨 있다면 첫 activation은 quota가 다시 허용하는
시점까지 runtime 미검증 상태로 남는다. PR/CI 성공을 activation 성공으로 간주하지 않는다.

## 비목표

- R2 bucket을 public origin으로 전환하지 않는다.
- 수집 주기나 source precedence를 변경하지 않는다.
- DB schema, stable product identity, 금리 계산 계약을 변경하지 않는다.
- Strategy release gate 상태를 임의로 변경하지 않는다.
