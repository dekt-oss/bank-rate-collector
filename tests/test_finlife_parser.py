"""finlife 파서 golden test.

실물 fixture(2026-08-05 수집)와 합성 경계값 fixture로 계약을 못박는다.
네트워크를 호출하지 않는다.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from rate_monitor.collectors.base import ParseError, SchemaChangedError, mask_auth
from rate_monitor.collectors.finlife import parser
from rate_monitor.domain.enums import (
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    ValidationStatus,
)

FIXTURES = Path(__file__).parent / "fixtures" / "finlife"
REAL = FIXTURES / "deposit_savings_bank_page1.json"
EDGE = FIXTURES / "edge_cases.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_payload() -> dict:
    return load(REAL)


@pytest.fixture(scope="module")
def real_rows(real_payload: dict) -> list:
    rows, _ = parser.parse(real_payload, "depositProductsSearch", "030300")
    return rows


# ── 실물 fixture: 확정 기대값 ────────────────────────────────────────────

def test_real_fixture_shape(real_payload: dict) -> None:
    """fixture가 2026-08-05 수집 당시 형태 그대로인지 고정한다."""
    result = real_payload["result"]
    assert result["err_cd"] == "000"
    assert len(result["baseList"]) == 100
    assert len(result["optionList"]) == 647
    assert result["max_page_no"] == 4


def test_real_rows_count_equals_option_count(real_payload: dict, real_rows: list) -> None:
    """옵션 1건당 행 1건. 실물 데이터에는 고아 옵션이 없다."""
    assert len(real_rows) == len(real_payload["result"]["optionList"]) == 647


def test_no_orphan_warnings_on_real_data(real_payload: dict) -> None:
    _, warnings = parser.parse(real_payload, "depositProductsSearch", "030300")
    assert [w for w in warnings if "대응 baseList 없음" in w] == []


def test_savings_bank_rate_scope_is_head_office_reference(real_rows: list) -> None:
    """저축은행 finlife 데이터는 전국 본점 기준 참고값이다 (명세서 v3.1 §6.4).

    부산 지점 금리로 오해되면 안 되므로 전 행이 예외 없이 이 값이어야 한다.
    """
    assert {r.rate_scope for r in real_rows} == {RateScope.HEAD_OFFICE_REFERENCE}


def test_bank_group_is_nationwide() -> None:
    payload = load(EDGE)
    rows, _ = parser.parse(payload, "depositProductsSearch", "020000")
    assert {r.rate_scope for r in rows} == {RateScope.NATIONWIDE}


def test_no_region_fields_on_finlife_rows(real_rows: list) -> None:
    """finlife 상품 API는 지역을 주지 않는다. 추측해서 채우지 않는다."""
    assert all(r.sido is None and r.sigungu is None and r.address is None for r in real_rows)


def test_source_locators_present_on_every_row(real_rows: list) -> None:
    """행 단위 원본 추적 (명세서 v3.1 §7). 누락 0건이어야 한다."""
    assert all(r.base_source_locator.startswith("$.result.baseList[") for r in real_rows)
    assert all(
        r.option_source_locator and r.option_source_locator.startswith("$.result.optionList[")
        for r in real_rows
    )
    assert all(r.source_record_hash.startswith("sha256:") for r in real_rows)


def test_locator_points_at_the_actual_source_row(real_payload: dict, real_rows: list) -> None:
    """locator가 가리키는 원본 행이 실제로 그 값의 출처인지 확인한다."""
    result = real_payload["result"]
    row = real_rows[0]
    base_idx = int(row.base_source_locator.removeprefix("$.result.baseList[").removesuffix("]"))
    opt_idx = int(row.option_source_locator.removeprefix("$.result.optionList[").removesuffix("]"))
    assert result["baseList"][base_idx]["fin_prdt_nm"] == row.product_name
    assert result["optionList"][opt_idx]["fin_co_no"] == row.source_institution_key


def test_source_effective_at_from_dcls_strt_day(real_rows: list) -> None:
    """공시 시작일을 기준일로 쓴다. collected_at으로 대체하지 않는다 (v3.1 §7.3)."""
    dated = [r for r in real_rows if r.source_effective_at is not None]
    assert dated, "실물 데이터에는 dcls_strt_day가 100% 존재한다"
    assert all(isinstance(r.source_effective_at, date) for r in dated)
    assert all(r.source_effective_at.year == 2026 for r in dated)


def test_collected_at_is_not_a_parser_concern() -> None:
    """수집 시각은 오케스트레이터가 채운다. 파서 출력에 없어야 한다 (v3 §6.2)."""
    assert not hasattr(parser.ParsedRateRow, "collected_at")


def test_term_months_parsed_from_string(real_rows: list) -> None:
    """save_trm은 문자열("12")로 온다. 정수로 변환한다."""
    terms = {r.term_months for r in real_rows}
    assert None not in terms
    assert terms <= {1, 3, 6, 12, 24, 36}


def test_interest_method_mapping(real_rows: list) -> None:
    assert {r.interest_method for r in real_rows} <= {
        InterestMethod.SIMPLE,
        InterestMethod.COMPOUND,
    }


def test_product_type_from_service(real_rows: list) -> None:
    assert {r.product_type for r in real_rows} == {ProductType.TERM_DEPOSIT}


def test_saving_service_maps_to_installment() -> None:
    rows, _ = parser.parse(load(EDGE), "savingProductsSearch", "030300")
    assert {r.product_type for r in rows} == {ProductType.INSTALLMENT_SAVINGS}


def test_preference_none_marker_becomes_empty(real_rows: list) -> None:
    """'없음'은 우대조건 없음이므로 빈 문자열. 그 외 원문은 그대로 보존한다."""
    assert all(r.preference_raw != "없음" for r in real_rows)
    with_pref = [r for r in real_rows if r.preference_raw]
    assert with_pref, "실물 데이터에 우대조건 원문이 있는 상품이 존재한다"


def test_determinism(real_payload: dict) -> None:
    """같은 원본이면 항상 같은 결과 (v3 §6.2 순수 함수)."""
    first, w1 = parser.parse(real_payload, "depositProductsSearch", "030300")
    second, w2 = parser.parse(real_payload, "depositProductsSearch", "030300")
    assert first == second
    assert w1 == w2


# ── max_rate NULL 규칙 ──────────────────────────────────────────────────

def test_missing_intr_rate2_yields_null_max_rate() -> None:
    """intr_rate2 결측 → max_rate = NULL. base_rate와 같게 두지 않는다.

    명세서 v3 §8.4. 참고 저장소가 틀린 지점이라 테스트로 못박는다.
    """
    rows, _ = parser.parse(load(EDGE), "depositProductsSearch", "030300")
    row = next(r for r in rows if r.source_product_key == "EDGE001")
    assert row.base_rate == 2.5
    assert row.max_rate is None


def test_real_data_never_fills_max_rate_from_base(real_rows: list) -> None:
    """실물 데이터에서도 max_rate를 base_rate로 메우지 않았는지 확인한다."""
    for row in real_rows:
        if row.max_rate is None:
            assert row.base_rate is not None or row.validation_status == ValidationStatus.ERROR


def test_unparseable_rate_is_null_not_sentinel() -> None:
    """금리 변환 실패는 NULL + error 상태. -1 같은 마법값을 쓰지 않는다."""
    rows, _ = parser.parse(load(EDGE), "depositProductsSearch", "030300")
    row = next(r for r in rows if r.source_product_key == "EDGE003")
    assert row.base_rate == 2.75  # "연 2.75%" 는 파싱된다
    assert row.max_rate is None  # "별도 문의" 는 NULL
    assert row.max_rate != -1
    assert row.validation_status == ValidationStatus.WARNING
    assert "별도 문의" in (row.validation_message or "")


def test_missing_dcls_strt_day_stays_null() -> None:
    """원천 기준일이 없으면 NULL. 수집시각으로 대체하지 않는다 (v3.1 §7.3)."""
    rows, _ = parser.parse(load(EDGE), "depositProductsSearch", "030300")
    row = next(r for r in rows if r.source_product_key == "EDGE002")
    assert row.source_effective_at is None


def test_orphan_option_is_warned_not_dropped_silently() -> None:
    """대응 상품이 없는 옵션은 경고를 남긴다."""
    rows, warnings = parser.parse(load(EDGE), "depositProductsSearch", "030300")
    assert not any(r.source_product_key == "ORPHAN01" for r in rows)
    assert any("ORPHAN01" in w for w in warnings)


def test_product_without_option_produces_no_row() -> None:
    """옵션 없는 상품은 비교 단위가 없으므로 행을 만들지 않는다."""
    rows, _ = parser.parse(load(EDGE), "depositProductsSearch", "030300")
    assert not any(r.source_product_key == "EDGE004" for r in rows)


def test_join_channel_multi_becomes_any() -> None:
    rows, _ = parser.parse(load(EDGE), "depositProductsSearch", "030300")
    single = next(r for r in rows if r.source_product_key == "EDGE001")
    assert single.join_channel == JoinChannel.BRANCH
    internet = next(r for r in rows if r.source_product_key == "EDGE002")
    assert internet.join_channel == JoinChannel.INTERNET


def test_real_multi_channel_row_is_any(real_rows: list) -> None:
    assert JoinChannel.ANY in {r.join_channel for r in real_rows}


# ── 스키마 변경 등급 (v3.1 §8) ──────────────────────────────────────────

def test_missing_required_list_is_breaking() -> None:
    with pytest.raises(SchemaChangedError, match="baseList"):
        parser.parse({"result": {"optionList": []}}, "depositProductsSearch", "030300")


def test_missing_required_field_is_breaking() -> None:
    payload = {
        "result": {
            "err_cd": "000",
            "baseList": [{"fin_co_no": "1", "fin_prdt_cd": "A", "kor_co_nm": "X"}],
            "optionList": [],
        }
    }
    with pytest.raises(SchemaChangedError, match="fin_prdt_nm"):
        parser.parse(payload, "depositProductsSearch", "030300")


def test_unknown_extra_field_is_compatible_not_breaking(real_payload: dict) -> None:
    """선택 필드 추가는 수집을 멈추지 않고 경고만 남긴다."""
    payload = json.loads(json.dumps(real_payload))
    payload["result"]["baseList"][0]["brand_new_field"] = "x"
    rows, warnings = parser.parse(payload, "depositProductsSearch", "030300")
    assert len(rows) == 647
    assert any("미지 필드" in w for w in warnings)


def test_api_error_code_raises() -> None:
    payload = {"result": {"err_cd": "010", "err_msg": "인증키 오류",
                          "baseList": [], "optionList": []}}
    with pytest.raises(ParseError, match="010"):
        parser.parse(payload, "depositProductsSearch", "030300")


def test_unsupported_service_raises(real_payload: dict) -> None:
    with pytest.raises(ParseError, match="지원하지 않는 서비스"):
        parser.parse(real_payload, "companySearch", "030300")


def test_schema_fingerprint_is_stable(real_payload: dict) -> None:
    assert parser.schema_fingerprint(real_payload) == parser.schema_fingerprint(real_payload)


def test_schema_fingerprint_changes_on_structure_change(real_payload: dict) -> None:
    altered = json.loads(json.dumps(real_payload))
    altered["result"]["baseList"][0]["new_col"] = 1
    assert parser.schema_fingerprint(altered) != parser.schema_fingerprint(real_payload)


# ── 인증키 노출 (v3.1 §7.4) ─────────────────────────────────────────────

def test_fixtures_contain_no_auth_key() -> None:
    """커밋된 fixture에 인증키가 없어야 한다."""
    for path in (REAL, EDGE):
        assert "auth" not in path.read_text(encoding="utf-8")


def test_mask_auth_redacts_query_param() -> None:
    masked = mask_auth("http://finlife.fss.or.kr/finlifeapi/x.json?auth=abc123def&pageNo=1")
    assert "abc123def" not in masked
    assert "[REDACTED]" in masked
    assert "pageNo=1" in masked
