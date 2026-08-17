"""NH e-joy 우대금리 → internet max-rate variant 계약 테스트."""

import asyncio
import html as html_lib
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

from rate_monitor.collectors.nh_local import parser as nh
from rate_monitor.collectors.nh_local.adapter import LIST_SCREEN, NhLocalAdapter
from rate_monitor.domain.enums import JoinChannel, ProductType
from rate_monitor.domain.schemas import CollectionRequest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nh_local"
AS_OF = date(2026, 8, 17)
OUTLET = nh.NhOutlet("777001", "테스트농협", "부산광역시 테스트구 테스트로 1")


def _detail(rows: list[tuple[str, str, str, str, str]]) -> str:
    rendered = []
    for product, term, rate, note, interest in rows:
        rendered.append(
            "<tr>"
            f"<td>{html_lib.escape(product)}</td>"
            f"<td>{html_lib.escape(term)}</td>"
            f"<td><strong>{html_lib.escape(rate)}</strong></td>"
            f"<td>{html_lib.escape(note)}</td>"
            f"<td>{html_lib.escape(interest)}</td>"
            "</tr>"
        )
    return (
        "<table><caption>금리 상세정보</caption><tbody>"
        + "".join(rendered)
        + "</tbody></table>"
    )


def _ejoy_html(
    *, note: str = nh.EJOY_APPLICABILITY_NOTE, first_rate: str = "0.1%", duplicate: bool = False
) -> str:
    rows = [
        (nh.EJOY_PRODUCT_NAME, "1개월 이상~12개월 미만", first_rate, note, "고정금리"),
        (nh.EJOY_PRODUCT_NAME, "12개월 이상~24개월 미만", "0.2%", note, "고정금리"),
        (nh.EJOY_PRODUCT_NAME, "24개월 이상~36개월 미만", "0.3%", note, "고정금리"),
        (nh.EJOY_PRODUCT_NAME, "36개월 이상", "0.4%", note, "고정금리"),
    ]
    if duplicate:
        rows.append(rows[0])
    return _detail(rows)


def _base_html() -> str:
    return _detail(
        [
            ("정기예탁금", "3개월 이상~6개월 미만", "3%", "기본행", "고정금리"),
            ("정기예탁금", "12개월 이상~24개월 미만", "2.9%", "기본행", "고정금리"),
            ("정기예탁금", "48개월 이상~60개월 미만", "2.8%", "기본행", "고정금리"),
            ("다른예금", "12개월 이상~24개월 미만", "4%", "기본행", "고정금리"),
        ]
    )


def _options(**kwargs):
    return nh.extract_ejoy_options(_ejoy_html(**kwargs), brc=OUTLET.brc)


def test_ejoy_evidence_requires_exact_note_and_non_overlapping_intervals() -> None:
    options, warnings = _options()
    assert warnings == []
    assert [(o["lower_months"], o["upper_months"]) for o in options] == [
        (1, 12),
        (12, 24),
        (24, 36),
        (36, None),
    ]
    assert all(o["source_brc"] == OUTLET.brc for o in options)
    assert all(o["source_locator"].startswith(f"{OUTLET.brc}/SFDPW0163R/") for o in options)

    drifted, drift_warnings = _options(note=nh.EJOY_APPLICABILITY_NOTE + " 변경")
    assert drifted == []
    assert any("대상상품 문구 변경" in warning for warning in drift_warnings)

    duplicated, duplicate_warnings = _options(duplicate=True)
    assert duplicated == []
    assert any("기간 중복" in warning for warning in duplicate_warnings)


def test_internet_variant_preserves_base_and_uses_interval_containment() -> None:
    options, _ = _options()
    rows, warnings = nh.parse_detail(
        _base_html(),
        outlet=OUTLET,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=AS_OF,
        ejoy_options=options,
    )
    assert warnings == []

    base = [
        row
        for row in rows
        if row.product_name == "정기예탁금" and row.join_channel == JoinChannel.UNKNOWN
    ]
    internet = [
        row
        for row in rows
        if row.product_name == "정기예탁금" and row.join_channel == JoinChannel.INTERNET
    ]
    assert len(base) == len(internet) == 3
    assert all(row.max_rate is None for row in base)

    by_term = {row.term_months: row for row in internet}
    assert by_term[3].max_rate == Decimal("3.1")
    assert by_term[12].max_rate == Decimal("3.1")
    assert by_term[48].max_rate == Decimal("3.2")
    assert by_term[3].extra["ejoy_interval_lower_months"] == 1
    assert by_term[12].extra["ejoy_interval_lower_months"] == 12
    assert by_term[48].extra["ejoy_interval_lower_months"] == 36

    original = next(row for row in base if row.term_months == 3)
    derived = by_term[3]
    assert derived.source_product_key == original.source_product_key
    assert derived.base_source_locator == original.base_source_locator
    assert derived.option_source_locator == options[0]["source_locator"]
    assert derived.source_record_hash != original.source_record_hash
    assert derived.extra["base_source_record_hash"] == original.source_record_hash
    assert derived.extra["option_source_record_hash"] == options[0]["source_record_hash"]
    assert derived.extra["max_rate_method"] == "base_plus_source_declared_ejoy_add_rate"

    non_target = [row for row in rows if row.product_name == "다른예금"]
    assert len(non_target) == 1
    assert non_target[0].max_rate is None


def test_explicit_zero_add_rate_is_traceable_not_a_base_fallback() -> None:
    options, _ = _options(first_rate="0%")
    rows, _ = nh.parse_detail(
        _base_html(),
        outlet=OUTLET,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=AS_OF,
        ejoy_options=options,
    )
    row = next(
        row
        for row in rows
        if row.product_name == "정기예탁금"
        and row.term_months == 3
        and row.join_channel == JoinChannel.INTERNET
    )
    assert row.base_rate == row.max_rate == Decimal("3")
    assert row.extra["ejoy_add_rate"] == "0"
    assert row.option_source_locator


def test_brc_mismatch_and_metadata_tampering_fail_closed() -> None:
    options, _ = _options()
    wrong_brc = deepcopy(options)
    for option in wrong_brc:
        option["source_brc"] = "OTHER"
    rows, warnings = nh.parse_detail(
        _base_html(),
        outlet=OUTLET,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=AS_OF,
        ejoy_options=wrong_brc,
    )
    assert not [
        row
        for row in rows
        if row.product_name == "정기예탁금" and row.join_channel == JoinChannel.INTERNET
    ]
    assert any("metadata invalid" in warning for warning in warnings)

    tampered = deepcopy(options)
    tampered[0]["note"] = "다른 조건"
    rows, warnings = nh.parse_detail(
        _base_html(),
        outlet=OUTLET,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=AS_OF,
        ejoy_options=tampered,
    )
    assert not [row for row in rows if row.source_row_ref.endswith("/internet")]
    assert any("metadata invalid" in warning for warning in warnings)


def test_without_ejoy_evidence_original_rows_remain_unchanged() -> None:
    rows, warnings = nh.parse_detail(
        _base_html(),
        outlet=OUTLET,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=AS_OF,
    )
    assert warnings == []
    assert len(rows) == 4
    assert all(row.max_rate is None for row in rows)
    assert all(not row.source_row_ref.endswith("/internet") for row in rows)


def test_real_fixture_generates_internet_variants_for_both_product_screens() -> None:
    fixture_outlet = nh.NhOutlet(
        "333072", "강릉농협 강동지점", "강원특별자치도 강릉시 강동면 와천로 463"
    )
    deposit_html = (FIXTURES / "deposit_detail_333072.html").read_text(encoding="utf-8")
    saving_html = (FIXTURES / "saving_detail_333072.html").read_text(encoding="utf-8")
    options, warnings = nh.extract_ejoy_options(deposit_html, brc=fixture_outlet.brc)
    assert warnings == [] and len(options) == 4

    deposit_rows, _ = nh.parse_detail(
        deposit_html,
        outlet=fixture_outlet,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=AS_OF,
        ejoy_options=options,
    )
    saving_rows, _ = nh.parse_detail(
        saving_html,
        outlet=fixture_outlet,
        product_type=ProductType.INSTALLMENT_SAVINGS,
        as_of=AS_OF,
        ejoy_options=options,
    )
    assert any(
        row.product_name == "정기예탁금"
        and row.join_channel == JoinChannel.INTERNET
        and row.max_rate is not None
        for row in deposit_rows
    )
    assert any(
        row.product_name == "정기적금"
        and row.join_channel == JoinChannel.INTERNET
        and row.max_rate is not None
        for row in saving_rows
    )
    assert not any(row.product_name == "자유로부금" for row in (*deposit_rows, *saving_rows))


class _FixtureFetchAdapter(NhLocalAdapter):
    def _load_prefixes(self, request: CollectionRequest) -> tuple[str, ...] | None:
        return ("부산광역시 강서구 가락대로 1459",)

    async def _get(self, client, screen, params, *, phase):
        del client, params, phase
        if screen == LIST_SCREEN:
            return (FIXTURES / "outlet_list_busan.html").read_bytes()
        if screen == nh.SCREEN_BY_PRODUCT[ProductType.TERM_DEPOSIT]:
            return (FIXTURES / "deposit_detail_333072.html").read_bytes()
        if screen == nh.SCREEN_BY_PRODUCT[ProductType.INSTALLMENT_SAVINGS]:
            return (FIXTURES / "saving_detail_333072.html").read_bytes()
        raise AssertionError(screen)


async def _no_sleep(_: float) -> None:
    return None


def test_adapter_carries_deposit_ejoy_evidence_to_same_brc_savings_artifact() -> None:
    adapter = _FixtureFetchAdapter(sleep=_no_sleep)
    artifacts = asyncio.run(
        adapter.fetch(
            CollectionRequest(
                source_id="nh_local",
                options={
                    "products": (
                        ProductType.INSTALLMENT_SAVINGS,
                        ProductType.TERM_DEPOSIT,
                    )
                },
            )
        )
    )
    rates = [artifact for artifact in artifacts if artifact.request_meta.get("kind") == "rate"]
    assert [artifact.request_meta["product_type"] for artifact in rates] == [
        ProductType.TERM_DEPOSIT.value,
        ProductType.INSTALLMENT_SAVINGS.value,
    ]
    assert len(rates[0].request_meta["ejoy_options"]) == 4
    assert rates[1].request_meta["ejoy_options"] == rates[0].request_meta["ejoy_options"]
    assert {option["source_brc"] for option in rates[1].request_meta["ejoy_options"]} == {
        "817020"
    }


def test_custom_savings_only_fetch_does_not_make_or_infer_ejoy_evidence() -> None:
    adapter = _FixtureFetchAdapter(sleep=_no_sleep)
    artifacts = asyncio.run(
        adapter.fetch(
            CollectionRequest(
                source_id="nh_local",
                options={"products": (ProductType.INSTALLMENT_SAVINGS,)},
            )
        )
    )
    rate = next(artifact for artifact in artifacts if artifact.request_meta.get("kind") == "rate")
    assert rate.request_meta["ejoy_options"] == []
    rows = adapter.parse(rate)
    assert all(row.max_rate is None for row in rows)
