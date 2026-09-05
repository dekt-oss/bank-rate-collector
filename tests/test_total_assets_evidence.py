from decimal import Decimal

import pytest

from rate_monitor.collectors.data_go_funding.aggregate_policy import (
    AGRI_COOP_REGION_TOTALS,
    AGRI_COOP_SECTOR_TOTALS,
)
from rate_monitor.collectors.data_go_funding.total_assets_evidence import (
    AGRI_COOP_SOURCE_ID,
    SAVINGS_BANK_SOURCE_ID,
    TotalAssetsEvidenceError,
    parse_total_assets_rows,
    partition_validated_total_assets,
)


def _savings_row(
    key: str,
    name: str,
    amount_krw: str,
    *,
    crno: str | None = "1101111234567",
) -> dict[str, str]:
    row = {
        "fncoCd": key,
        "fncoNm": name,
        "basYm": "202506",
        "astSmryStfnpsAcitCd": "A",
        "astSmryStfnpsAcitCdNm": "자산총계",
        "astSmryStfnpsAcitCdAmt": amount_krw,
    }
    if crno is not None:
        row["crno"] = crno
    return row


def _agri_row(
    key: str,
    name: str,
    amount_krw: str,
    *,
    crno: str | None = None,
) -> dict[str, str]:
    row = {
        "fncoCd": key,
        "fncoNm": name,
        "basYm": "202506",
        "astSmryBlnshDcd": "A",
        "astSmryBlnshDcdNm": "자산총계",
        "astSmryBlnshClsfAmt": amount_krw,
    }
    if crno is not None:
        row["crno"] = crno
    return row


def _agri_current_rows(*, sector_total_krw: str = "3000000") -> list[dict[str, str]]:
    rows = [
        _agri_row("0010027000001", "가농협", "1000000", crno="123"),
        _agri_row("0010027000002", "나농협", "2000000", crno="456"),
    ]
    first_region = True
    for key, name in AGRI_COOP_REGION_TOTALS.items():
        rows.append(_agri_row(key, name, "3000000" if first_region else "0"))
        first_region = False
    for key, name in AGRI_COOP_SECTOR_TOTALS.items():
        rows.append(_agri_row(key, name, sector_total_krw))
    return rows


def test_savings_assets_parser_preserves_and_validates_sector_total() -> None:
    rows = [
        _savings_row("001", "A저축은행", "1000000"),
        _savings_row("002", "B저축은행", "2000000"),
        _savings_row("030350S", "저축은행", "3000000", crno=None),
    ]
    points = parse_total_assets_rows(
        source_id=SAVINGS_BANK_SOURCE_ID,
        rows=rows,
        endpoint="https://example.invalid/savings",
    )
    assert len(points) == 3
    assert {point.value for point in points} == {
        Decimal("1.000000"),
        Decimal("2.000000"),
        Decimal("3.000000"),
    }

    partitions = partition_validated_total_assets(points)
    assert len(partitions) == 1
    partition = partitions[0]
    assert [point.source_institution_key for point in partition.institution_rows] == [
        "001",
        "002",
    ]
    assert [point.source_institution_key for point in partition.aggregate_rows] == [
        "030350S"
    ]
    assert partition.institution_total == Decimal("3.000000")
    assert partition.aggregate_total == Decimal("3.000000")


def test_savings_assets_sector_total_mismatch_fails_closed() -> None:
    points = parse_total_assets_rows(
        source_id=SAVINGS_BANK_SOURCE_ID,
        rows=[
            _savings_row("001", "A저축은행", "1000000"),
            _savings_row("030350S", "저축은행", "2000000", crno=None),
        ],
        endpoint="https://example.invalid/savings",
    )
    with pytest.raises(TotalAssetsEvidenceError, match="sector-total 합계 불일치"):
        partition_validated_total_assets(points)


def test_agri_assets_use_asset_specific_current_aggregate_hierarchy() -> None:
    points = parse_total_assets_rows(
        source_id=AGRI_COOP_SOURCE_ID,
        rows=_agri_current_rows(),
        endpoint="https://example.invalid/agri",
    )
    partitions = partition_validated_total_assets(points)
    assert len(partitions) == 1
    partition = partitions[0]
    assert len(partition.institution_rows) == 2
    assert len(partition.aggregate_rows) == 17
    assert partition.institution_total == Decimal("3.000000")
    # 16 regions sum to 3 and the sector total itself is also 3 => aggregate rows sum to 6.
    assert partition.aggregate_total == Decimal("6.000000")


def test_agri_assets_reject_funding_style_double_count_sector_total() -> None:
    points = parse_total_assets_rows(
        source_id=AGRI_COOP_SOURCE_ID,
        rows=_agri_current_rows(sector_total_krw="6000000"),
        endpoint="https://example.invalid/agri",
    )
    with pytest.raises(TotalAssetsEvidenceError, match="sector total 합계 불일치"):
        partition_validated_total_assets(points)


def test_assets_parser_requires_exact_a_asset_total_label() -> None:
    row = _savings_row("001", "A저축은행", "1000000")
    row["astSmryStfnpsAcitCdNm"] = "자산"
    with pytest.raises(TotalAssetsEvidenceError, match="코드명이 자산총계가 아니다"):
        parse_total_assets_rows(
            source_id=SAVINGS_BANK_SOURCE_ID,
            rows=[row],
            endpoint="https://example.invalid/savings",
        )


def test_assets_parser_rejects_conflicting_duplicate_natural_key() -> None:
    with pytest.raises(TotalAssetsEvidenceError, match="총자산이 서로 다르다"):
        parse_total_assets_rows(
            source_id=SAVINGS_BANK_SOURCE_ID,
            rows=[
                _savings_row("001", "A저축은행", "1000000"),
                _savings_row("001", "A저축은행", "2000000"),
            ],
            endpoint="https://example.invalid/savings",
        )
