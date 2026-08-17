"""NH e-joy derived variant의 원천 추적·식별 회귀 테스트."""

from datetime import date
from pathlib import Path

from rate_monitor.collectors.nh_local import parser as nh
from rate_monitor.domain.enums import JoinChannel, ProductType

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nh_local"


def test_real_ejoy_option_locator_is_same_brc_deposit_screen() -> None:
    brc = "333072"
    source = (FIXTURES / "deposit_detail_333072.html").read_text(encoding="utf-8")
    options, warnings = nh.extract_ejoy_options(source, brc=brc)

    assert warnings == []
    assert len(options) == 4
    assert all(option["source_brc"] == brc for option in options)
    assert all(
        option["source_locator"].startswith(f"{brc}/SFDPW0163R/")
        for option in options
    )
    assert all(option["source_record_hash"] for option in options)


def test_derived_variant_keeps_target_identity_and_option_trace_separate() -> None:
    brc = "333072"
    outlet = nh.NhOutlet(
        brc,
        "강릉농협 강동지점",
        "강원특별자치도 강릉시 강동면 와천로 463",
    )
    deposit = (FIXTURES / "deposit_detail_333072.html").read_text(encoding="utf-8")
    options, warnings = nh.extract_ejoy_options(deposit, brc=brc)
    assert warnings == []

    rows, parse_warnings = nh.parse_detail(
        deposit,
        outlet=outlet,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=date(2026, 8, 17),
        ejoy_options=options,
    )
    assert not any("e-joy evidence metadata invalid" in warning for warning in parse_warnings)

    derived = [
        row
        for row in rows
        if row.source_product_key == "정기예탁금"
        and row.join_channel == JoinChannel.INTERNET
        and row.max_rate is not None
    ]
    assert derived
    for row in derived:
        assert row.product_name == "정기예탁금"
        assert row.base_source_locator.startswith(f"{brc}/SFDPW0163R/")
        assert row.option_source_locator.startswith(f"{brc}/SFDPW0163R/")
        assert row.base_source_locator != row.option_source_locator
        assert row.extra["max_rate_method"] == (
            "base_plus_source_declared_ejoy_add_rate"
        )
        assert row.extra["base_source_record_hash"]
        assert row.extra["option_source_record_hash"]

    option_rows = [row for row in rows if row.source_product_key == nh.EJOY_PRODUCT_NAME]
    assert option_rows
    assert all(row.max_rate is None for row in option_rows)
