"""권역·구·기간별 중앙값 집계 (조회 화면 R1 §3, 차트 2·3).

**최고값이 아니라 중앙값을 쓴다.** 최고값은 그 권역에 우대 조건이 붙은
상품이 단 한 건만 있어도 통째로 끌어올린다 — 발행 데이터에서 새마을금고
직장금고 하나 때문에 부산 강서구 `base_max`가 10.00%로 찍힌다. 그건 권역의
대표값이 아니라 «가장 튄 한 건»이다.

**구 단위 중앙값을 다시 중앙값 내면 권역 중앙값이 아니다.** 구마다 관측
수가 달라서 96건짜리 구와 1,284건짜리 구가 같은 무게로 들어간다. 그래서
`by_region`을 따로 발행한다.
"""

import logging

import pytest

from rate_monitor.services.dashboard_service import (
    REGION_GROUPS,
    REGION_OTHER,
    _by_region,
    _median_of,
)
from rate_monitor.services.site_service import INLINE_KEYS

# ── 중앙값 자체 ─────────────────────────────────────────────────────────


def test_the_median_reads_the_padded_strings_as_numbers() -> None:
    """저장 형식이 `003.4000` 꼴이라 사전순 == 수치순이다 (db/types.Rate)."""
    assert _median_of(["003.4000", "010.0000", "002.6000"]) == 3.4
    assert _median_of([None, "003.2000", None]) == 3.2
    assert _median_of([]) is None
    assert _median_of([None]) is None


def test_one_outlier_does_not_move_the_median() -> None:
    """이 집계가 최고값 대신 중앙값을 쓰는 이유를 그대로 못박는다."""
    normal = ["003.0000", "003.2000", "003.4000"]
    assert _median_of(normal) == 3.2
    # 직장금고 10%가 한 건 섞여도 대표값은 흔들리지 않는다.
    assert _median_of([*normal, "010.0000"]) == 3.4
    # 같은 입력에서 최고값은 통째로 뒤집힌다.
    assert max(float(v) for v in [*normal, "010.0000"]) == 10.0


# ── 권역 묶음 ───────────────────────────────────────────────────────────


def test_every_sido_the_data_actually_has_is_mapped() -> None:
    """`전남광주통합특별시`가 매핑에 없으면 그 행들이 조용히 «기타»로 샌다.

    발행 데이터에 실제로 들어 있는 값이다 (`by_district` 실측).
    """
    assert REGION_GROUPS["전남광주통합특별시"] == "전라"
    # 화면이 세는 권역은 아홉이다. 그보다 많으면 막대가 얇아 비교가 안 된다.
    assert len(set(REGION_GROUPS.values())) == 9
    assert REGION_OTHER not in REGION_GROUPS.values()


def test_busan_stands_alone() -> None:
    """이 제품의 중심이 부산이고, 드릴다운도 부산에서만 열린다."""
    assert REGION_GROUPS["부산"] == "부산"
    assert [k for k, v in REGION_GROUPS.items() if v == "부산"] == ["부산"]


# ── 모르는 시도 ─────────────────────────────────────────────────────────


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params):  # noqa: ARG002 — 질의는 여기서 안 돈다
        return iter(self._rows)


def test_an_unmapped_sido_is_kept_and_reported(caplog) -> None:
    """조용히 버리면 총합이 안 맞는데 아무도 모른다.

    «기타» 막대로 모으고 로그에 남긴다. 둘 다 해야 한다 — 모으기만 하면
    왜 «기타»가 생겼는지 알 수 없고, 로그만 남기면 행이 사라진다.
    """
    rows = [
        # (시도, 구·군, 업권, 기관, 기본금리)
        ("부산", "동구", "savings_bank", "i1", "003.0000"),
        ("달나라특별시", "고요의바다구", "savings_bank", "i2", "004.0000"),
    ]
    with caplog.at_level(logging.WARNING):
        out = _by_region(_FakeConn(rows), ["run-1"], " FROM x", "?")

    # 권역 전체 행만 본다. 구 단위 행은 드릴다운용으로 따로 나온다.
    by_region = {r["region"]: r for r in out
                 if r["district"] is None and r["sector"] == "savings_bank"}
    assert set(by_region) == {"부산", REGION_OTHER}
    assert by_region[REGION_OTHER]["observations"] == 1
    assert "달나라특별시" in caplog.text


def test_no_runs_means_no_rows_not_an_empty_looking_zero() -> None:
    """수집 이력이 없으면 빈 목록이다. 0%짜리 막대를 만들지 않는다."""
    assert _by_region(_FakeConn([]), [], " FROM x", "?") == []


def test_the_sample_size_travels_with_the_median() -> None:
    """제주 96건과 서울 1,284건의 중앙값을 같은 신뢰도로 읽으면 안 된다.

    화면이 막대마다 «N개사 · N건»을 적으려면 집계가 둘 다 내야 한다.
    """
    rows = [
        ("서울", "강남구", "savings_bank", "a", "003.0000"),
        ("서울", "강남구", "savings_bank", "a", "003.4000"),  # 같은 기관의 다른 상품
        ("서울", "강남구", "savings_bank", "b", "003.8000"),
    ]
    out = _by_region(_FakeConn(rows), ["run-1"], " FROM x", "?")
    (region,) = [r for r in out
                 if r["district"] is None and r["sector"] == "savings_bank"]
    assert region["observations"] == 3
    assert region["institutions"] == 2, "기관은 중복을 빼고 센다"
    assert region["base_p50"] == 3.4


# ── 발행까지 실려 나가는가 ──────────────────────────────────────────────


def test_the_region_aggregate_reaches_the_published_page() -> None:
    """공개 화면은 요약을 통째로 싣지 않는다. `INLINE_KEYS`에 적힌 것만 간다.

    실제로 이 줄이 없어서 권역 차트가 막대 0개로 나갔다 (2026-08-07).
    코드에도 데이터에도 값이 있는데 화면에서만 비는 종류라, 소스만 보면
    멀쩡해 보인다.
    """
    assert "by_region" in INLINE_KEYS
    # 드릴다운은 구 단위를 본다. 둘 다 있어야 차트가 완성된다.
    assert "by_district" in INLINE_KEYS
    assert "by_term" in INLINE_KEYS


@pytest.mark.parametrize("region", ["서울", "인천·경기", "부산", "제주"])
def test_region_names_are_the_ones_the_screen_draws(region: str) -> None:
    assert region in set(REGION_GROUPS.values())


# ── 2금융권 합산 ────────────────────────────────────────────────────────


def test_the_second_tier_row_is_computed_from_observations_not_from_medians() -> None:
    """업권별 중앙값 넷을 다시 평균 내면 표본 크기가 무시된다.

    저축은행 6,666건과 제주 농·축협 322건이 같은 무게로 들어간다. 그래서
    원래 관측에서 한 번에 낸다.
    """
    from rate_monitor.services.dashboard_service import SECOND_TIER_SECTOR

    rows = [
        ("부산", "동구", "savings_bank", "a", "004.0000"),
        ("부산", "동구", "kfcc", "b", "002.0000"),
        ("부산", "동구", "kfcc", "c", "002.0000"),
        ("부산", "동구", "kfcc", "d", "002.0000"),
    ]
    out = _by_region(_FakeConn(rows), ["run-1"], " FROM x", "?")
    (combined,) = [r for r in out
                   if r["sector"] == SECOND_TIER_SECTOR and r["district"] is None]
    # 관측 넷의 중앙값은 2.0이다. 업권별 중앙값(4.0, 2.0)의 평균 3.0이 아니다.
    assert combined["base_p50"] == 2.0
    assert combined["observations"] == 4
    assert combined["institutions"] == 4


def test_the_drilldown_gets_district_rows_for_the_same_sector() -> None:
    """부산 드릴다운은 같은 «2금융권» 잣대로 구·군을 봐야 한다.

    권역은 2금융권인데 구는 저축은행만이면 두 화면이 다른 것을 센다.
    """
    from rate_monitor.services.dashboard_service import SECOND_TIER_SECTOR

    rows = [
        ("부산", "동구", "savings_bank", "a", "003.0000"),
        ("부산", "해운대구", "kfcc", "b", "002.0000"),
    ]
    out = _by_region(_FakeConn(rows), ["run-1"], " FROM x", "?")
    districts = {r["district"] for r in out
                 if r["sector"] == SECOND_TIER_SECTOR and r["district"]}
    assert districts == {"동구", "해운대구"}


def test_a_row_without_a_district_still_counts_in_its_region() -> None:
    """구·군을 못 읽은 행도 권역 합계에는 들어가야 한다. 총합이 맞아야 한다."""
    from rate_monitor.services.dashboard_service import SECOND_TIER_SECTOR

    rows = [
        ("부산", None, "savings_bank", "a", "003.0000"),
        ("부산", "동구", "savings_bank", "b", "003.0000"),
    ]
    out = _by_region(_FakeConn(rows), ["run-1"], " FROM x", "?")
    (combined,) = [r for r in out
                   if r["sector"] == SECOND_TIER_SECTOR and r["district"] is None]
    assert combined["observations"] == 2


# ── 12개월 정기예금으로 못박기 ──────────────────────────────────────────


def test_the_region_median_counts_only_twelve_month_deposits() -> None:
    """참고카드와 같은 기준이어야 한다.

    기간·유형을 안 가리면 정기예금 1개월 1.00%와 12개월 3.40%가 한 중앙값에
    섞인다. 실제로 그래서 권역이 2.4~2.5%로 나왔고, 같은 화면의 참고카드
    3.40%와 1%p 가까이 벌어졌다.

    질의가 조건을 거는지를 본다 — `_by_region`이 SQL로 거르므로 가짜 행으로는
    확인할 수 없다.
    """
    import inspect

    from rate_monitor.services import dashboard_service as ds

    src = inspect.getsource(ds._by_region)
    assert "v.term_months = ?" in src
    assert "p.product_type = ?" in src
    # 참고카드와 **같은 상수**를 쓴다. 두 곳에 따로 적으면 한쪽만 바뀐다.
    assert "BENCHMARK_TERM_MONTHS" in src
    assert "BENCHMARK_PRODUCT_TYPE" in src
    assert ds.BENCHMARK_TERM_MONTHS == 12
    assert ds.BENCHMARK_PRODUCT_TYPE == "term_deposit"


def test_the_shared_where_clause_is_not_narrowed_for_everyone() -> None:
    """`district_sql`은 `by_district`도 쓴다.

    거기에 12개월 조건을 붙이면 구·군 수(화면의 «구·군 327»)가 통째로 줄어든다.
    조건은 `_by_region`의 질의에만 붙어야 한다.
    """
    import inspect

    from rate_monitor.services import dashboard_service as ds

    body = inspect.getsource(ds.build_summary)
    head, _, _ = body.partition("by_region = _by_region")
    district_sql = head[head.index("district_sql = ("):head.index("district_expr =")]
    assert "term_months" not in district_sql
    assert "product_type" not in district_sql


def test_the_district_rows_no_longer_carry_a_dead_median() -> None:
    """드릴다운이 `by_region`의 구 단위 행을 보게 되면서 아무도 안 읽는다.

    화면은 `by_district`의 길이만 쓴다. 두 곳에 있는 중앙값은 언젠가 어긋난다.
    """
    import inspect
    from pathlib import Path

    from rate_monitor.services import dashboard_service as ds

    body = inspect.getsource(ds.build_summary)
    assert "_fill_medians(\n            by_district," not in body

    screen = (Path(__file__).resolve().parents[1]
              / "web" / "templates" / "site.html").read_text(encoding="utf-8")
    assert "by_district" in screen, "구·군 수는 여전히 화면이 쓴다"
    # 다만 중앙값으로는 안 읽는다.
    assert "by_district || []).filter" not in screen
