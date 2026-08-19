# Strategy Brand Visual System v3 — 2026-08-19

## 목적

Strategy dashboard를 일반 금리조회 dashboard와 같은 브랜드 계열로 정렬하면서도,
장시간 사용하는 금융 실무 분석화면답게 더 절제되고 전문적인 시각 위계를 만든다.

이 문서는 presentation contract만 정의한다. 계산식, 수집 데이터, 모델, DB/schema,
release gate는 변경하지 않는다.

## 기준 palette

일반 dashboard `web/templates/site.html`의 기존 palette를 Source of Truth로 재사용한다.

| 역할 | 값 | Strategy 사용 |
|---|---:|---|
| canvas | `#F7F4F8` | 전체 배경 |
| surface | `#FFFFFF` | 주요 카드 |
| text | `#251D27` | 본문/숫자 |
| plum | `#4D2D58` | 구조색, topbar |
| plum ink | `#5B2F64` | active text |
| violet | `#734A7E` | 분석 보조색 |
| rose | `#B34A77` | 브랜드 보조색 |
| pink | `#D33A7C` | interaction/selected |
| pink soft | `#F8EAF1` | selected background |
| positive | `#2E7D5B` | 상승/양수 의미 |
| warning | `#A9741A` | 주의/비용 의미 |
| negative | `#AC4238` | 하락/음수 의미 |

핑크를 넓은 면적으로 사용하지 않는다. `plum = structure`, `pink = interaction`,
`violet = analysis`, `green/amber/red = semantic` 역할을 고정한다.

## Typography

외부 font/CDN과 font binary를 추가하지 않는다.

우선순위:

`Pretendard Variable → Pretendard → SUIT Variable → SUIT → Wanted Sans Variable → Wanted Sans → Noto Sans KR → Apple SD Gothic Neo → Segoe UI → Arial`

- body: desktop 14px / mobile 13.5px 이상
- hero: `clamp(28px, 2.45vw, 36px)`
- analytical microcopy: 10.5px 미만 금지
- 숫자: sans-serif + `tabular-nums` / `lining-nums`
- optical sizing 사용 가능 font에서 활성화
- KPI 핵심 숫자: `clamp(30px, 2.6vw, 39px)`
- heading은 size보다 weight/spacing 차이로 위계 형성

## Shape / ratio

기존 v2의 다소 둥근 SaaS-card 인상을 줄인다.

- primary card radius: 14px
- KPI radius: 12px
- controls: 8px
- analytical inner surface: 10px
- workspace section spacing: 24px / label-bottom 10px
- shadow는 plum-tinted 저채도 그림자만 사용

## Topbar

일반 dashboard header의 브랜드 계열을 Strategy topbar에 재사용한다.

`#4D2D58 → #784060 → #B34A77`

나머지 dashboard는 light surface를 유지해 dark-dashboard 회귀를 만들지 않는다.

## Map

라이트 화면에서 기존 dark land fill이 과도하게 무거웠으므로 전국 지도 실루엣을
`#EFE7F0`으로 밝힌다.

- normal node: violet
- top node: brand pink
- Busan emphasis: rose
- 지역/금리 label은 deep plum 계열

## Runtime gate

production-data Chrome smoke에서 다음을 직접 검사한다.

- `data-strategy-palette="main-brand-v2"`
- `data-strategy-typography="variable-ui-v2"`
- `--accent == #D33A7C`
- `--accent-ink == #5B2F64`
- topbar gradient 존재
- Korea land fill `rgb(239, 231, 240)`
- dense analytical microcopy >= 10.5px
- E0/C2/D2 parent white surface 유지
- desktop/mobile horizontal overflow 없음

## 비범위

- 데이터/산식 변경
- inflow calibration
- D2 정보량 축약
- 메인 dashboard 재디자인
- Production Strategy Release Gate ON
