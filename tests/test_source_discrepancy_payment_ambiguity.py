from __future__ import annotations

from rate_monitor.services.source_discrepancy_service import _representatives


def _row(*, payment_method: str | None, rate: str) -> dict[str, object]:
    return {
        "source_id": "finlife_savings_bank",
        "institution": "청주저축은행",
        "product": "정기적금",
        "product_type": "installment_savings",
        "term_months": 6,
        "join_channel": "branch",
        "interest_method": "simple",
        "payment_method": payment_method,
        "base_rate": rate,
        "max_rate": rate,
        "source_effective_at": "2026-08-20",
    }


def test_different_payment_methods_with_different_rates_fail_closed() -> None:
    representatives, ambiguous = _representatives(
        [
            _row(payment_method="S", rate="2.10"),
            _row(payment_method="F", rate="3.05"),
        ]
    )

    assert representatives == {}
    assert len(ambiguous) == 1
    candidates = next(iter(ambiguous.values()))
    assert {item["payment_method"] for item in candidates} == {"S", "F"}


def test_different_payment_methods_with_same_rate_remain_comparable() -> None:
    representatives, ambiguous = _representatives(
        [
            _row(payment_method="S", rate="2.10"),
            _row(payment_method="F", rate="2.10"),
        ]
    )

    assert ambiguous == {}
    assert len(representatives) == 1
    assert next(iter(representatives.values()))["max_rate"] == "2.10"


def test_same_payment_method_can_still_choose_highest_representative() -> None:
    representatives, ambiguous = _representatives(
        [
            _row(payment_method="S", rate="2.10"),
            _row(payment_method="S", rate="2.20"),
        ]
    )

    assert ambiguous == {}
    assert next(iter(representatives.values()))["max_rate"] == "2.20"
