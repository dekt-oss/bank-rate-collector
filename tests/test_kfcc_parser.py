"""새마을금고 파서 검증 — 실물 fixture로 계약을 못박는다.

fixture는 2026-08-05에 공식 페이지에서 받은 것이다. 네트워크를 호출하지 않는다.

    tests/fixtures/kfcc/list_busan_junggu.html   목록 (부산 중구)
    tests/fixtures/kfcc/rate_1203_13.html        거치식예탁금 (대청)
    tests/fixtures/kfcc/rate_1203_14.html        적립식예탁금 (대청)
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.kfcc import parser
from rate_monitor.domain.enums import (
    AvailabilityScope,
    JoinChannel,
    ProductType,
    RateScope,
    Sector,
    ValidationStatus,
)

FIXTURES = Path(__file__).parent / "fixtures" / "kfcc"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def list_html() -> str:
    return _read("list_busan_junggu.html")


@pytest.fixture(scope="module")
def outlet(list_html: str) -> dict:
    return next(r for r in parser.parse_list(list_html) if r["gmgoCd"] == "1203")


@pytest.fixture(scope="module")
def deposit_html() -> str:
    return _read("rate_1203_13.html")


@pytest.fixture(scope="module")
def savings_html() -> str:
    return _read("rate_1203_14.html")


# ── fixture 자체 모양 ───────────────────────────────────────────────────
# fixture가 조용히 바뀌면 아래 기대값이 먼저 시끄럽게 실패해야 한다.


def test_list_fixture_shape(list_html: str) -> None:
    rows = parser.parse_list(list_html)
    assert len(rows) == 9
    assert len({r["gmgoCd"] for r in rows}) == 6


def test_rate_fixture_shape(deposit_html: str, savings_html: str) -> None:
    deposit = parser.summarize(deposit_html)
    assert deposit["base_rate_tables"] == 4
    assert deposit["products"] == [
        "Block예금",
        "MG더뱅킹정기예금",
        "꿈드림회전정기예탁금",
        "정기예탁금",
    ]
    assert deposit["basis_date"] == date(2026, 8, 5)

    savings = parser.summarize(savings_html)
    assert savings["base_rate_tables"] == 9
    assert savings["basis_date"] == date(2026, 8, 5)


# ── 목록 ────────────────────────────────────────────────────────────────


def test_list_row_carries_official_identifiers(outlet: dict) -> None:
    assert outlet["gmgoCd"] == "1203"
    assert outlet["divCd"] == "001"
    assert outlet["gmgoNm"] == "대청"
    assert outlet["divNm"] == "본점"
    # gmgoType은 직장금고 여부를 명칭 추측이 아니라 공식 값으로 준다 (v3 §7.3.4-7).
    assert outlet["gmgoType"] == "지역"
    assert outlet["addr"] == "부산 중구 대청로 101-1"


def test_every_list_row_address_matches_the_requested_district(list_html: str) -> None:
    """화면 파라미터(r2)만 믿지 않고 주소로 되짚는다."""
    for row in parser.parse_list(list_html):
        assert f" {row['r2']} " in f" {row['addr']} "


# ── 표 선별 — 가장 위험한 지점 ─────────────────────────────────────────


def test_only_base_rate_tables_are_collected(deposit_html: str) -> None:
    """중도해지이율·만기후이율 표를 기본금리로 저장하면 안 된다.

    세 표가 모두 같은 상품명(.tbl-tit)을 달고 나오므로 순서로 고르면
    0.1% 수준의 중도해지이율이 정상 금리로 들어간다.
    """
    summary = parser.summarize(deposit_html)
    # 상품 4개 × 표 3종 = 12개 영역이지만 기본이율은 4개뿐이다.
    assert summary["sections"] == 4
    assert summary["base_rate_tables"] == 4


def test_early_termination_headers_are_rejected() -> None:
    assert parser._is_base_rate_table(["상품명", "계약기간", "기본이율"]) is True
    assert parser._is_base_rate_table(["예치기간", "중도해지이율", "최저이율"]) is False
    assert parser._is_base_rate_table(["경과기간", "만기후이율"]) is False


def test_rate_columns_are_found_by_header_not_position() -> None:
    assert parser._rate_columns(["상품명", "계약기간", "기본이율"]) == [(2, "")]
    assert parser._rate_columns(
        ["상품명", "계약기간", "월지급식 기본이율", "만기지급식 기본이율"]
    ) == [(2, "월지급식"), (3, "만기지급식")]


# ── 금리 행 ─────────────────────────────────────────────────────────────


def test_deposit_rows(deposit_html: str, outlet: dict) -> None:
    rows, warnings = parser.parse_rates(
        deposit_html, gubuncode="13", outlet=outlet, join_channel=JoinChannel.BRANCH
    )
    assert warnings == []
    assert len(rows) == 49

    first = rows[0]
    assert first.sector == Sector.KFCC
    assert first.source_institution_key == "1203"
    assert first.institution_name == "대청"
    assert first.product_type == ProductType.TERM_DEPOSIT
    assert first.product_name == "정기예탁금"
    assert first.term_months == 1
    assert first.rate_scope == RateScope.INSTITUTION
    assert first.availability_scope == AvailabilityScope.LOCAL_MEMBERS
    assert first.address == "부산 중구 대청로 101-1"
    assert first.sigungu == "중구"


def test_two_rate_columns_expand_into_two_variants(
    deposit_html: str, outlet: dict
) -> None:
    """월지급식·만기지급식은 서로 다른 비교 단위다."""
    rows, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=outlet)
    same_term = [
        r for r in rows if r.product_name == "정기예탁금" and r.term_months == 3
    ]
    assert {r.payment_method for r in same_term} == {"월지급식", "만기지급식"}
    assert all(r.base_rate == Decimal("1.8") for r in same_term)


def test_savings_rows(savings_html: str, outlet: dict) -> None:
    rows, warnings = parser.parse_rates(savings_html, gubuncode="14", outlet=outlet)
    assert warnings == []
    assert len(rows) == 29
    assert all(r.product_type == ProductType.INSTALLMENT_SAVINGS for r in rows)

    regular = [r for r in rows if r.product_name == "정기적금"]
    assert [(r.term_months, r.base_rate) for r in regular][:3] == [
        (12, Decimal("3.5")),
        (24, Decimal("3.4")),
        (36, Decimal("3.2")),
    ]


def test_rowspan_does_not_shift_the_columns(deposit_html: str, outlet: dict) -> None:
    """상품명 셀에 rowspan이 걸려 둘째 행부터 칸이 하나 적다.

    열 인덱스를 고정했다면 계약기간을 상품명으로 읽어 term_months가 전부
    None이 됐을 것이다.
    """
    rows, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=outlet)
    terms = [r.term_months for r in rows if r.product_name == "정기예탁금"]
    assert None not in terms
    # 첫 표는 1·3·6·12·16·24·36개월대를 담는다. 둘 이상 확인되면 정렬이 맞다.
    assert len(set(terms)) >= 5


# ── 규칙 ────────────────────────────────────────────────────────────────


def test_max_rate_is_never_filled_from_base_rate(
    deposit_html: str, savings_html: str, outlet: dict
) -> None:
    """공식 화면에 우대금리 열이 없다. 참고 저장소가 틀린 지점이다."""
    for html, group in ((deposit_html, "13"), (savings_html, "14")):
        rows, _ = parser.parse_rates(html, gubuncode=group, outlet=outlet)
        assert rows
        assert all(r.max_rate is None for r in rows)


def test_effective_date_comes_from_the_page(deposit_html: str, outlet: dict) -> None:
    """조회기준일이 있으므로 지어내지 않는다 (v3.1 §7.3)."""
    rows, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=outlet)
    assert all(r.source_effective_at == date(2026, 8, 5) for r in rows)


def test_locator_points_at_the_source_cell(deposit_html: str, outlet: dict) -> None:
    rows, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=outlet)
    for row in rows:
        assert row.base_source_locator.startswith("table[")
        assert "/tr[" in row.base_source_locator
        assert row.source_record_hash.startswith("sha256:")


def test_parsing_is_deterministic(deposit_html: str, outlet: dict) -> None:
    first, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=outlet)
    second, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=outlet)
    assert first == second


def test_workplace_scope_uses_the_official_type(deposit_html: str, outlet: dict) -> None:
    workplace = {**outlet, "gmgoType": "직장"}
    rows, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=workplace)
    assert all(r.availability_scope == AvailabilityScope.WORKPLACE_MEMBERS for r in rows)


# ── 계약기간 파싱 ───────────────────────────────────────────────────────


def test_term_parsing_handles_the_narrative_form() -> None:
    assert parser.parse_term("1개월 이상") == (1, None, None)
    assert parser.parse_term("36개월 이상") == (36, None, None)
    assert parser.parse_term("3년") == (36, None, None)
    assert parser.parse_term("30일") == (None, 30, None)


def test_unreadable_term_becomes_error_not_a_silent_null(outlet: dict) -> None:
    """참고 저장소는 이 형태를 duration: null로 조용히 흘렸다."""
    months, days, message = parser.parse_term("별도 문의")
    assert months is None
    assert days is None
    assert message is not None

    html = """
    <div id="divTmp1" name="divTmp1">
      <div class="tbl-tit">시험상품</div>
      <table><thead><tr><th>상품명</th><th>계약기간</th><th>기본이율</th></tr></thead>
      <tbody><tr><td rowspan="1">시험상품</td><td>별도 문의</td><td>연1.0%</td></tr>
      </tbody></table>
    </div>
    """
    rows, _ = parser.parse_rates(html, gubuncode="13", outlet=outlet)
    assert len(rows) == 1
    assert rows[0].term_months is None
    assert rows[0].validation_status == ValidationStatus.ERROR
    assert "계약기간" in (rows[0].validation_message or "")


# ── 스키마 변경 등급 ────────────────────────────────────────────────────


def test_missing_product_title_is_breaking(outlet: dict) -> None:
    with pytest.raises(SchemaChangedError, match="tbl-tit"):
        parser.parse_rates("<html><body>없음</body></html>", gubuncode="13", outlet=outlet)


# ── 취급 상품 없음은 오류가 아니다 ──────────────────────────────────────
#
# 새마을금고는 금고마다 취급 품목이 다르다. 거치식만 하고 적립식은 안 하는
# 곳이 실제로 있다. 예전에는 이걸 구조 변경으로 보고 실행 전체를 partial로
# 떨어뜨렸다 — 2026-08-06 전국 수집에서 9장이 그랬고, 실물을 받아 보니
# 아홉 장 다 그냥 취급 상품이 없는 것이었다.

# 실물 표본 두 종. 2026-08-06에 건너뛴 9장을 실제로 받아 본 결과다.
#
#   rate_0225_13_no_products — 정상 페이지에 상품만 없다 (10,559 바이트).
#       조회기준일도 제목도 그대로 있고 .tbl-tit만 없다. 0225·2415·3568,
#       그리고 서울대학교병원금고(0128)의 적립식 화면이 이 모양이었다.
#   rate_1965_13_no_data — 사이트가 대놓고 없다고 답한다 (375 바이트).
#       본문이 통째로 alert("조회할 자료가 없습니다 ...") 하나다.
@pytest.mark.parametrize(
    "name", ["rate_0225_13_no_products.html", "rate_1965_13_no_data.html"]
)
def test_no_products_is_not_a_schema_change(name: str, outlet: dict) -> None:
    rows, warnings = parser.parse_rates(_read(name), gubuncode="13", outlet=outlet)
    assert rows == [], name
    assert warnings == [], name


def test_the_two_empty_shapes_really_are_different(outlet: dict) -> None:
    """표본 두 종이 실제로 서로 다른 모양인지. 같으면 검사가 하나만 도는 셈이다."""
    normal = _read("rate_0225_13_no_products.html")
    alert = _read("rate_1965_13_no_data.html")
    assert "조회기준일" in normal and "조회기준일" not in alert
    assert "조회할 자료가 없습니다" in alert and "조회할 자료가 없습니다" not in normal
    assert len(alert) < 1000 < len(normal)


def test_an_unknown_page_is_still_breaking(outlet: dict) -> None:
    """기준일도 없고 없다는 안내도 없으면 우리가 아는 화면이 아니다.

    여기까지 느슨하게 풀면 진짜 구조 변경이 조용히 0행으로 지나간다.
    """
    assert not parser.has_no_products("<html><body>전혀 다른 화면</body></html>")
    with pytest.raises(SchemaChangedError):
        parser.parse_rates(
            "<html><body>전혀 다른 화면</body></html>", gubuncode="13", outlet=outlet
        )


def test_a_page_with_products_is_never_treated_as_empty() -> None:
    """상품이 있는 화면을 빈 화면으로 오해하면 데이터가 통째로 사라진다."""
    assert not parser.has_no_products(_read("rate_1203_13.html"))
    assert not parser.has_no_products(_read("rate_1203_14.html"))


def test_only_early_termination_tables_is_breaking(outlet: dict) -> None:
    """기본이율 표가 사라지면 중도해지이율로 대체하지 않고 실패한다."""
    html = """
    <div id="divTmp1" name="divTmp1">
      <div class="tbl-tit">시험상품</div>
      <table><thead><tr><th>예치기간</th><th>중도해지이율</th><th>최저이율</th></tr></thead>
      <tbody><tr><td>3개월</td><td>연0.1%</td><td>연0.1%</td></tr></tbody></table>
    </div>
    """
    with pytest.raises(SchemaChangedError, match="기본이율"):
        parser.parse_rates(html, gubuncode="13", outlet=outlet)


def test_missing_container_falls_back_with_a_warning(outlet: dict) -> None:
    """divTmp가 없어도 .tbl-tit 기준으로 동작한다. 요구불 화면이 그렇다."""
    html = """
    <div class="tbl-tit">시험상품</div>
    <table><thead><tr><th>상품명</th><th>계약기간</th><th>기본이율</th></tr></thead>
    <tbody><tr><td rowspan="1">시험상품</td><td>12개월</td><td>연2.0%</td></tr>
    </tbody></table>
    """
    rows, warnings = parser.parse_rates(html, gubuncode="13", outlet=outlet)
    assert len(rows) == 1
    assert rows[0].base_rate == Decimal("2.0")
    assert any("divTmp" in w for w in warnings)


def test_fingerprint_is_stable_and_reacts_to_structure(
    deposit_html: str, savings_html: str
) -> None:
    assert parser.schema_fingerprint(deposit_html) == parser.schema_fingerprint(
        deposit_html
    )
    assert parser.schema_fingerprint(deposit_html) != parser.schema_fingerprint(
        savings_html
    )


# ── 지역 판정 ───────────────────────────────────────────────────────────


def test_region_comes_from_the_address_not_the_site_parameter(
    deposit_html: str, outlet: dict
) -> None:
    """r1/r2를 시도·시군구로 쓰면 기관이 엉뚱한 지역에 붙는다.

    2026-08-05 실측: `r1=광주`로 조회하면 전남 주소 124건이 함께 온다.
    r1은 사이트의 지역 구분값이지 행정구역이 아니다. 부산만 볼 때는 우연히
    일치했지만 전국으로 넓히면 곧바로 틀린다.
    """
    misleading = dict(outlet)
    misleading["r1"] = "광주"
    misleading["r2"] = "광주전체"
    misleading["addr"] = "전남 나주시 그린로 20"

    rows, _ = parser.parse_rates(deposit_html, gubuncode="13", outlet=misleading)
    assert rows, "행이 있어야 검사가 성립한다"
    assert {r.sido for r in rows} == {"전남"}
    assert {r.sigungu for r in rows} == {"나주시"}
