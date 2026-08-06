# 금리수집기 저장소·이력 보관 구조 선행 수정안 v1
## GitHub 대용량 파일 제거 / SQLite 상태 저장 분리 / 1년 이력 및 장기백업

```yaml
document_type: prerequisite_implementation_spec
status: partially_implemented
date: 2026-08-06
target_repository: dekt-oss/bank-rate-collector
target_agent: Claude Code
execution_order:
  - this_spec
  - 금리수집기_우선기능재정비_작업명세서_v4
```

> **저장소 반영 메모** (2026-08-06)
>
> | §9 | 상태 |
> |---|---|
> | PR 1 긴급 Publish 안정화 | **완료** (#23). rate-data 177.67 → 74.41 MiB, orphan 발행, size gate |
> | PR 2 R2 상태 저장 | **완료** (#24). 3단계 전환 구조. 현재 `github_legacy` |
> | PR 3 변경이력 저장 | 미착수 |
> | PR 4 1년 이력 파티션 | 미착수 |
> | PR 5 1년 초과 archive | 미착수 |
>
> **명세서와 다르게 한 것 둘.**
>
> §9의 PR 1은 `rate-data` DB 제거를 포함하지만 그대로 하면 다음 수집이
> 깨진다 — `Restore previous database`가 그 파일에서 복원한다. §6.4가
> 금지한 "빈 DB로 시작"이 되므로 PR 2로 옮겼고, 실제 제거는 사용자가
> `backend: r2`로 전환할 때 일어난다.
>
> §2.3의 zstd 대신 gzip을 썼다. 파이썬 3.12 표준 라이브러리에 zstd가 없어
> 의존성이 늘고, 하루 한 번 오가는 파일이라 압축률 차이가 비용에 거의
> 영향을 주지 않는다. 표준 도구로 아무 데서나 풀 수 있는 쪽이 낫다.
>
> §4의 웹 JSON 분할은 아직 안 했다. 현재 `table.json`이 5.36 MiB로
> §10의 경고선(10 MiB) 아래다. 원천이 늘어 넘어설 때 한다.

---

# 0. 결론

현재 구조는 운영 DB 전체를 압축해 Git 브랜치에 매 실행마다 커밋한다.

```text
Actions 임시 작업 DB
→ 전체 이력 포함 SQLite 스냅샷
→ gzip
→ rate-data/latest/rate_monitor.sqlite3.gz
→ 다음 실행에서 다시 복원
```

이 구조는 다음 이유로 중단해야 한다.

1. GitHub 100MB 제한은 **저장소 전체가 아니라 개별 Git 파일/blob 기준**이다.
2. 현재 압축 DB와 전체 JSON이 이미 50MB 권고선을 넘었다.
3. DB가 매 실행마다 관측 이력을 누적하므로 개별 파일이 결국 100MB를 넘는다.
4. `rate-data` 브랜치의 과거 커밋에도 매번 새로운 압축 DB blob이 남아 저장소가 계속 커진다.
5. 시중은행·농축협을 추가하면 증가 속도가 빨라진다.

권장 구조:

```text
GitHub
├─ main                 코드·명세·테스트
└─ rate-data            최신 정적 사이트와 작은 분할 JSON만
                         DB와 전체 JSON은 저장하지 않음

Cloudflare R2
├─ state/               다음 실행 복원용 최신 compact SQLite
├─ history/             최근 1년 금리 변경이력
├─ raw/                 최근 90일 원본
└─ archive/             1년 초과 연도별 장기백업

GitHub Releases
└─ annual-backup-*      연 1회 장기백업의 보조 사본
```

관리형 PostgreSQL 서버는 도입하지 않는다. 현재 앱은 정적 사이트와 배치수집 구조이므로 SQLite + 오브젝트 스토리지가 가장 단순하고 비용이 낮다.

---

# 1. 현재 저장위치 정리

## 1.1 Actions 실행 중

```text
work/rate_monitor.sqlite3
```

GitHub Actions runner의 임시 디스크다. 실행이 끝나면 사라진다.

## 1.2 현재 영구 DB

```text
rate-data 브랜치
latest/rate_monitor.sqlite3.gz
```

다음 수집 실행이 이 파일을 GitHub에서 내려받아 복원한다. 즉 현재 운영 DB는 실질적으로 GitHub Git 브랜치에 저장되어 있다.

## 1.3 현재 원본과 보고서

```text
GitHub Actions Artifact
retention-days: 90
```

다음이 포함된다.

```text
data/raw/
publish/manifest.json
publish/summary.json
publish/export/
```

## 1.4 현재 웹 산출물

```text
rate-data/site/
rate-data/site-public/
```

Vercel은 `site-public/`을 정적 배포한다. Vercel은 운영 SQLite의 원본 저장소로 사용하지 않는다.

---

# 2. 목표 저장계층

## 2.1 GitHub 코드 저장소

저장:

```text
소스코드
테스트 fixture
작은 정찰 표본
명세
워크플로
마이그레이션
```

저장 금지:

```text
운영 SQLite
50MB 전체 JSON
일별 원본 HTML/JSON
월별 이력 데이터
```

## 2.2 rate-data 브랜치

목적:

```text
Vercel 정적 배포
최신 화면 데이터 전달
```

저장:

```text
site-public/index.html
site-public/data/index.json
site-public/data/{sector}/{region}-{part}.json.gz
site-public/data/benchmarks.json
site-public/site-manifest.json
latest/summary.json
latest/manifest-public.json
```

저장 금지:

```text
rate_monitor.sqlite3
rate_monitor.sqlite3.gz
rates_YYYYMMDD.json
대형 전체 CSV
원본 수집파일
과거 이력
```

브랜치 이력은 매번 최신 한 커밋으로 재작성한다.

## 2.3 R2 상태 저장소

목적:

```text
다음 Actions 실행이 이어받는 운영 상태
```

경로:

```text
state/current.json
state/snapshots/{timestamp}-{sha}.sqlite3.zst
```

`current.json` 예시:

```json
{
  "schema_version": 1,
  "object_key": "state/snapshots/20260806T021500Z-abcd.sqlite3.zst",
  "sha256": "...",
  "compressed_bytes": 12345678,
  "sqlite_bytes": 45678901,
  "generated_at": "2026-08-06T02:15:00Z",
  "integrity_check": "ok",
  "foreign_key_check_violations": 0
}
```

업로드 순서:

```text
새 snapshot 업로드
→ 다시 내려받아 hash 검증
→ SQLite integrity 검증
→ current.json 교체
```

검증 전에는 기존 `current.json`을 변경하지 않는다. 최근 snapshot 7개를 보존하고 그보다 오래된 것은 자동 삭제한다.

## 2.4 최근 1년 이력

경로:

```text
history/YYYY/MM/rate_changes.parquet.zst
history/YYYY/MM/collection_runs.parquet.zst
history/YYYY/MM/review_items.parquet.zst
history/YYYY/MM/manifest.json
```

최근 12개월은 월별 파티션으로 유지한다.

핵심 원칙:

```text
매일 전체 DB 복사 금지
변경된 금리·신규상품·종료상품만 기록
```

## 2.5 원본

최근 90일:

```text
raw/YYYY/MM/DD/{source_id}/{run_id}/...
```

90일 초과:

```text
archive/raw/YYYY/MM/raw-YYYY-MM.tar.zst
```

원본 장기보관이 불필요하다고 확정하기 전까지 월별 묶음으로 보존한다.

## 2.6 1년 초과 백업

매월 첫 실행에서 12개월을 초과한 월별 파티션을 연도별 아카이브로 합친다.

```text
archive/YYYY/rate-history-YYYY.tar.zst
archive/YYYY/raw-YYYY-part001.tar.zst
archive/YYYY/manifest.json
archive/YYYY/SHA256SUMS
```

연도가 종료되면 동일 파일을 GitHub Release에도 보조 사본으로 업로드한다.

```text
Release tag:
data-backup-YYYY
```

개별 파일이 커지면 1GB 이하 파트로 분할한다. R2가 1차 장기보관소이고 GitHub Release는 보조 사본이다.

---

# 3. 운영 DB를 compact 상태 DB로 변경

## 3.1 현재 문제

현재 `rate_observations`는 같은 금리라도 수집할 때마다 새 행이 생긴다.

```text
8월 6일 3.10
8월 7일 3.10
8월 8일 3.10
```

변화가 없어도 DB가 증가한다.

## 3.2 변경이력 모델

`rate_observations`를 변경 이벤트 중심으로 바꾼다.

추가 컬럼:

```text
first_seen_at
last_seen_at
seen_count
valid_from
valid_to
```

처리:

```text
이전 최신 content_hash == 새 content_hash
→ 새 observation 생성하지 않음
→ last_seen_at 갱신
→ seen_count + 1

content_hash 변경
→ 기존 최신행 valid_to 설정
→ 새 observation 생성
```

수집 실행별 품질·건수는 별도 통계로 보존한다.

신규 테이블:

```sql
CREATE TABLE collection_run_stats (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES collection_runs(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    fetched_count INTEGER NOT NULL,
    parsed_count INTEGER NOT NULL,
    unchanged_count INTEGER NOT NULL,
    changed_count INTEGER NOT NULL,
    new_variant_count INTEGER NOT NULL,
    missing_variant_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    created_at DATETIME NOT NULL
);
```

## 3.3 compact 상태 DB 보존범위

`state/current.sqlite3`에는 다음을 둔다.

```text
모든 활성 기관
모든 활성 점포
모든 활성 상품
모든 활성 variant
variant별 최신 정상 observation
variant별 직전 정상 observation 1건
최근 30일 collection_runs
최근 30일 collection_run_stats
현재 미해결 review_items
참조되는 raw_artifacts 메타데이터
sources
source_entity_links
entity_aliases
manual_overrides
```

제외:

```text
1년 전체 관측이력
완료된 오래된 review_items
90일 초과 raw artifact 메타데이터
오래된 실패 실행
```

## 3.4 전체 이력과 상태 DB 분리

```text
state/current.sqlite3
= 다음 수집과 현재 화면 생성에 필요한 상태

history/YYYY/MM/*
= 과거 변경 이력

archive/YYYY/*
= 1년 초과 백업
```

화면의 최근 1년 추이 기능이 필요할 경우 R2의 월별 이력 파일을 별도 빌드 단계에서 읽어 정적 차트 JSON을 생성한다.

---

# 4. 전체 JSON 제거와 웹 데이터 분할

## 4.1 제거

```text
latest/export/rates_YYYYMMDD.json
site-public/data/rates.json
```

## 4.2 대체

다운로드:

```text
downloads/rates-current.csv.zst
downloads/rates-current.ndjson.zst
```

웹 조회:

```text
site-public/data/index.json
site-public/data/savings_bank/all-001.json.gz
site-public/data/kfcc/busan-001.json.gz
site-public/data/cu/busan-001.json.gz
site-public/data/nh_local/busan-001.json.gz
site-public/data/bank/reference-001.json.gz
```

파일 분할 기준:

```text
압축 전 8MB 또는 20,000행 중 먼저 도달
압축 후 목표 5MB 이하
절대 내부 경고 20MB
```

`index.json`에 파일 목록과 행 수를 기록한다.

---

# 5. rate-data 브랜치 이력 제거

## 5.1 새 Publish 방식

기존 브랜치를 기반으로 커밋을 누적하지 않는다.

```text
정적 산출물 생성
→ orphan commit
→ force-with-lease
→ rate-data를 최신 1커밋으로 교체
```

업로드 전 현재 `rate-data` SHA를 읽고 `--force-with-lease`를 사용한다.

## 5.2 기존 대형 이력 정리

현재 브랜치에 이미 들어간 대형 blob은 파일을 삭제하는 새 커밋만으로 사라지지 않는다.

선행 작업에서:

```text
필요 산출물 R2 업로드 확인
rate-data orphan 재생성
원격 branch 강제교체
```

main 브랜치 이력은 건드리지 않는다.

## 5.3 보호장치

```text
main 브랜치 force push 금지
rate-data만 자동 재작성 허용
rate-data 단일 writer concurrency 유지
```

---

# 6. R2 연동

## 6.1 GitHub Secrets

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
R2_ENDPOINT
```

공개 사이트에서 R2 인증정보를 사용하지 않는다.

## 6.2 클라이언트

권장:

```text
AWS CLI S3 호환 명령
또는 boto3
```

새 의존성은 최소화한다. 이미 Python 실행환경이 있으므로 `boto3`를 명시 의존성으로 추가하는 방식을 권장한다.

## 6.3 원자적 상태 갱신

```text
1. 새 compact DB 생성
2. integrity_check
3. foreign_key_check
4. zstd 압축
5. versioned key에 업로드
6. HEAD/다운로드 검증
7. current.json.new 업로드
8. current.json 교체
9. 이전 snapshot 정리
```

R2의 같은 객체를 직접 덮어쓰는 것보다 버전 키 + 포인터 방식을 사용한다.

## 6.4 R2 장애 시

수집 시작 시 current DB 다운로드 실패:

```text
새 빈 DB로 시작 금지
Publish 중단
기존 사이트 유지
알림
```

수집 완료 후 R2 업로드 실패:

```text
rate-data Publish 금지
기존 current.json 유지
기존 사이트 유지
```

---

# 7. 1년 보관 및 초과 백업 정책

## 7.1 최근 1년

온라인 이력:

```text
정규화된 금리 변경이력 12개월
수집실행 통계 12개월
review_items 12개월
원본 파일 90일
원본 해시·메타데이터 12개월
```

## 7.2 1년 초과

```text
월별 이력 파티션을 연도별 아카이브로 합침
월별 원본 bundle을 연도별 archive로 합침
SHA256SUMS 생성
R2 archive/YYYY에 보존
GitHub Release에 연간 보조백업
```

## 7.3 삭제 조건

다음 조건을 모두 만족해야 월별 원본을 삭제할 수 있다.

```text
연간 archive 생성 성공
SHA256 검증 성공
R2 존재 확인
GitHub Release 보조 사본 존재 확인
manifest 행 수 대조
복원 테스트 성공
```

## 7.4 복원 테스트

분기 1회:

```text
임의 월 1개 선택
→ archive 다운로드
→ 압축 해제
→ manifest 검증
→ Parquet 읽기
→ 행 수·해시 확인
```

연 1회:

```text
연간 archive 전체 복원 dry-run
```

---

# 8. 비용 최소화 원칙

1. 별도 24시간 DB 서버를 운영하지 않는다.
2. Actions 실행시간 외 컴퓨팅 비용이 없다.
3. 정적 사이트는 기존 Vercel 구조를 유지한다.
4. 대용량 파일은 Git이 아니라 오브젝트 스토리지에 둔다.
5. 동일 금리 반복행을 저장하지 않고 변경이력만 저장한다.
6. 원본은 매일 개별 파일로 장기보존하지 않고 월별 zstd bundle로 합친다.
7. 최근 1년 데이터와 1년 초과 archive를 분리한다.
8. R2 사용량이 무료구간을 초과하기 전 월별 저장량을 산출해 경고한다.

월별 저장량 보고:

```text
state bytes
history bytes
raw bytes
archive bytes
estimated 12-month bytes
```

설정:

```yaml
storage_budget:
  warning_gb: 7
  hard_stop_gb: 9
```

실제 무료구간·가격은 R2 계정 생성 시점의 공식 요금표로 확정한다.

---

# 9. 작업 순서

## PR 1 — 긴급 Publish 안정화

- 전체 JSON 제거
- CSV/NDJSON zstd 전환
- 웹 JSON 분할
- 개별 파일 크기 게이트
- `rate-data` DB 제거
- `rate-data` 최신 1커밋 재작성
- 기존 rate-data 대형 이력 정리

완료 전에는 v4 기능 개발을 시작하지 않는다.

## PR 2 — R2 상태 저장

- R2 secrets 계약
- `storage_service.py`
- versioned snapshot 업로드
- current pointer
- 다운로드·해시·integrity 검증
- Actions restore/publish 변경
- 실패 안전성 테스트

## PR 3 — 변경이력 저장

- observation 변경감지
- `last_seen_at`, `seen_count`, `valid_from`, `valid_to`
- `collection_run_stats`
- 동일값 신규행 방지
- migration
- 기존 데이터 backfill

## PR 4 — 1년 이력 파티션

- 월별 Parquet/Zstd
- 12개월 보존
- 90일 raw 정책
- 월말 compaction
- manifest/checksum

## PR 5 — 1년 초과 archive

- 연간 archive 생성
- GitHub Release 보조백업
- 삭제 게이트
- 복원 테스트
- 저장량 보고

그 후:

```text
금리수집기 우선기능 재정비 및 확장 작업 명세서 v4
```

를 시행한다.

---

# 10. 파일 크기 게이트

Publish 전 검사:

```text
Git 저장 개별 파일:
warning 20 MiB
failure 40 MiB

R2 current snapshot:
warning 200 MiB
failure 500 MiB

웹 shard:
warning 10 MiB
failure 20 MiB

rate-data 전체:
warning 100 MiB
failure 200 MiB
```

GitHub의 100MB 한도 직전까지 사용하지 않는다.

---

# 11. 검증 체크리스트

## GitHub

```text
rate-data에 sqlite 파일 없음
rate-data에 전체 rates JSON 없음
rate-data 개별파일 20MB 이하
rate-data 커밋 수 1
main 이력 변경 없음
```

## R2

```text
current.json 존재
current snapshot 존재
SHA256 일치
integrity_check=ok
foreign_key_check=0
최근 snapshot 최소 2개
```

## 데이터

```text
최신 화면 행 수와 current DB 일치
동일 금리 재수집 시 observation 증가 0
금리 변경 시 observation 증가 1
last_seen_at 갱신
1년 이력 partition 생성
```

## 장애

```text
R2 다운로드 실패 시 빈 DB 시작 안 함
R2 업로드 실패 시 rate-data 미발행
snapshot 검증 실패 시 current pointer 미교체
웹 빌드 실패 시 기존 사이트 유지
```

## 백업

```text
월별 manifest 존재
연간 archive 생성
GitHub Release 보조 사본
임의 월 복원 성공
```

---

# 12. Claude Code 전달문

```text
현재 rate-data의 대용량 DB와 전체 JSON이 GitHub 파일 제한에 접근했습니다.
금리수집기 v4 기능 개발보다 이 선행 수정안을 먼저 시행해주세요.

main 브랜치의 실제 구현과 collect.yml을 먼저 확인하고 PR 1부터 순서대로
진행하십시오. 운영 SQLite와 전체 JSON을 Git에서 제거하고, R2에 versioned
compact SQLite를 저장하며, rate-data는 최신 정적 사이트만 단일 커밋으로
유지해야 합니다.

금리 이력은 동일값 반복행이 아니라 변경이력으로 1년간 월별 Parquet/Zstd로
저장하고, 1년 초과 데이터는 연도별 archive와 GitHub Release 보조 사본으로
백업하십시오.

각 PR 종료 시 실제 파일크기, 행 수, 압축률, R2 업로드·복원 결과,
Actions 결과, 남은 위험을 보고하십시오.
```
