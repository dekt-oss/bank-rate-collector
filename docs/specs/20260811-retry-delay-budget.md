# NH/KFCC Retry Delay Budget — 2026-08-11

## Decision

NH와 KFCC의 기존 `MAX_TOTAL_RETRIES=50`은 유지하되, 실제 retry sleep에 쓰는
누적 추가 대기를 source run당 **600초(10분)** 로 별도 제한한다.

## Evidence

2026-08-11 리뷰에서 이전 scheduled run의 queue delay와 runtime을 현재 00:17/04:17
스케줄에 대입했을 때 07:30 normal 목표의 관측 최소 여유는 약 10분이었다. 기존
50회 횟수 예산만으로는 KFCC retry backoff가 약 25분까지 늘 수 있다.

600초는 08:00 hard deadline을 보장한다는 뜻이 아니다. GitHub queue와 원천 응답시간은
통제할 수 없다. 이 상한은 **collector가 스스로 추가하는 retry sleep**이 관측된 normal
margin보다 커지는 것을 막는다. per-request connect/read timeout은 기존 값을 유지한다.

## Preserved contracts

- GET only
- 기존 retryable transport exception과 500/502/503/504만 재시도
- 400/403/429/block marker는 즉시 중단, 우회 없음
- 정상 1초 pacing 유지
- retry count 50 상한 유지
- NH/KFCC retry 구현 공통화는 이번 PR 범위 밖

## Failure taxonomy

누적 다음 sleep이 600초를 넘기면 `RETRY_DELAY_BUDGET_EXHAUSTED`로 종료한다.
해당 sleep은 실행하지 않으며 retry count도 증가시키지 않는다.
