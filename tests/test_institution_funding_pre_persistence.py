from __future__ import annotations

from decimal import Decimal

import pytest

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    FundingContractError,
    parse_points,
)


def _savings_contract():
    return next(contract for contract in CONTRACTS if contract.sector == "savings_bank")


def _row(
    *,
    fnco_cd: str,
    fnco_nm: str,
    amount: str,
    crno: str = "",
    bas_ym: str = "202603",
) -> dict[str, str]:
    return {
        "basYm": bas_ym,
        "fncoCd": fnco_cd,
        "fncoNm": fnco_nm,
        "crno": crno,
        "debtCptlSmryStfnpsAcitCd": "A11",
        "debtCptlSmryStfnpsAcitCdNm": "예수부채",
        "debtCptlAmt": amount,
    }


def test_sector_total_is_validated_then_excluded_before_persistence_candidates():
    rows = [
        _row(fnco_cd="001", fnco_nm="가저축은행", amount="1000000", crno="111"),
        _row(fnco_cd="002", fnco_nm="나저축은행", amount="2000000", crno="222"),
        _row(fnco_cd="030350S", fnco_nm="저축은행", amount="3000000"),
    ]

    points = parse_points(
        _savings_contract(),
        rows,
        endpoint="https://example.test/savings",
    )

    assert [point.source_institution_key for point in points] == ["001", "002"]
    assert sum((point.value for point in points), Decimal("0")) == Decimal("3.000000")


def test_sector_total_value_mismatch_fails_closed():
    rows = [
        _row(fnco_cd="001", fnco_nm="가저축은행", amount="1000000", crno="111"),
        _row(fnco_cd="002", fnco_nm="나저축은행", amount="2000000", crno="222"),
        _row(fnco_cd="030350S", fnco_nm="저축은행", amount="4000000"),
    ]

    with pytest.raises(FundingContractError, match="sector-total 합계 불일치"):
        parse_points(
            _savings_contract(),
            rows,
            endpoint="https://example.test/savings",
        )


@pytest.mark.parametrize(
    ("name", "crno"),
    [
        ("저축은행합계", ""),
        ("저축은행", "1101119999999"),
    ],
)
def test_sector_total_identity_drift_fails_closed(name: str, crno: str):
    rows = [
        _row(fnco_cd="001", fnco_nm="가저축은행", amount="1000000", crno="111"),
        _row(fnco_cd="002", fnco_nm="나저축은행", amount="2000000", crno="222"),
        _row(fnco_cd="030350S", fnco_nm=name, amount="3000000", crno=crno),
    ]

    with pytest.raises(FundingContractError, match="sector-total identity 계약 불일치"):
        parse_points(
            _savings_contract(),
            rows,
            endpoint="https://example.test/savings",
        )


def test_missing_sector_total_does_not_drop_real_institutions():
    rows = [
        _row(fnco_cd="001", fnco_nm="가저축은행", amount="1000000", crno="111"),
        _row(fnco_cd="002", fnco_nm="나저축은행", amount="2000000", crno="222"),
    ]

    points = parse_points(
        _savings_contract(),
        rows,
        endpoint="https://example.test/savings",
    )

    assert [point.source_institution_key for point in points] == ["001", "002"]
