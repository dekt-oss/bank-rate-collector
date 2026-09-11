from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from rate_monitor.domain.schemas import ParsedRateRow
from rate_monitor.services.collection_service import _content_hash, _same_semantic_value


def _row(effective_at: date | None) -> ParsedRateRow:
    return ParsedRateRow(
        source_id="nh_local",
        source_role="secondary_official",
        trust_level="official_direct",
        sector="nh_local",
        source_institution_key="123456",
        source_outlet_key="123456",
        source_product_key="정기예탁금",
        institution_name="테스트농협",
        outlet_name="테스트농협",
        institution_type=None,
        sido="부산",
        sigungu="중구",
        address="부산 중구 테스트로 1",
        product_type="term_deposit",
        product_name="정기예탁금",
        term_months=12,
        term_days=None,
        join_channel="unknown",
        interest_method="unknown",
        payment_method=None,
        amount_min=None,
        amount_max=None,
        customer_scope=None,
        availability_scope="unknown",
        rate_scope="outlet",
        base_rate=Decimal("3.10"),
        max_rate=None,
        preference_raw="만기이자지급식 기준",
        source_row_ref="123456/정기예탁금/12",
        base_source_locator="123456/table/1",
        source_record_hash="record-hash",
        source_effective_at=effective_at,
    )


def test_source_effective_date_drift_does_not_change_rate_value_hash() -> None:
    first = _row(date(2026, 9, 9))
    next_day = replace(first, source_effective_at=date(2026, 9, 10))

    assert _content_hash(first) == _content_hash(next_day)


def test_actual_rate_or_preference_change_still_changes_hash() -> None:
    base = _row(date(2026, 9, 10))

    assert _content_hash(base) != _content_hash(replace(base, base_rate=Decimal("3.20")))
    assert _content_hash(base) != _content_hash(replace(base, preference_raw="다른 우대조건"))


def test_legacy_date_sensitive_current_row_is_semantically_reconciled() -> None:
    row = _row(date(2026, 9, 10))
    current = SimpleNamespace(
        base_rate=Decimal("3.10"),
        max_rate=None,
        raw_preference_text="만기이자지급식 기준",
    )

    assert _same_semantic_value(current, row) is True
    assert _same_semantic_value(
        SimpleNamespace(
            base_rate=Decimal("3.20"),
            max_rate=None,
            raw_preference_text="만기이자지급식 기준",
        ),
        row,
    ) is False
