from dataclasses import dataclass

import pytest

from rate_monitor.collectors.data_go_funding.reconciliation import (
    FundingSourceCollision,
    _single_source_id,
)


@dataclass(frozen=True)
class _Observation:
    source_id: str


def test_single_source_per_sector_month_is_accepted() -> None:
    source_id = _single_source_id(
        sector="cu",
        month="2026-06",
        items=[_Observation("cu_disclosure_funding"), _Observation("cu_disclosure_funding")],
    )

    assert source_id == "cu_disclosure_funding"


def test_two_sources_for_same_sector_month_fail_closed() -> None:
    with pytest.raises(FundingSourceCollision, match="source collision"):
        _single_source_id(
            sector="cu",
            month="2026-06",
            items=[
                _Observation("cu_disclosure_funding"),
                _Observation("data_go_credit_union_funding"),
            ],
        )
