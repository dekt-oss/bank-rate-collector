from __future__ import annotations

from decimal import Decimal

import pytest

from rate_monitor.collectors.cu.funding import CuFundingContractError, DisclosureRecord
from rate_monitor.collectors.cu.total_assets_evidence import (
    parse_summary_size_pair,
    select_disclosure_for_effective_month,
)


def _disclosure(*, year: int = 2025, disclosure_type: str = "1") -> DisclosureRecord:
    return DisclosureRecord(
        cu_ingno="02002",
        disclosure_no=22820,
        disclosure_type=disclosure_type,
        disclosure_name=f"{year}년도 결산정기공시",
        reg_date="2026-02-10",
        short_file_name="summary.pdf",
        year=year,
        month=12 if disclosure_type == "1" else 6,
    )


def _summary_html(
    *,
    year: int = 2025,
    prior: int = 2024,
    unit: str = "백만원",
    deposit_label: str = "예 수 부 채",
    deposit: str = "1,720,194",
    assets_label: str = "자 산 합 계",
    assets: str = "1,936,064",
    duplicate_assets: bool = False,
) -> str:
    extra_asset = (
        f"<tr><td>{assets_label}</td><td>{assets}</td><td>100.00</td></tr>"
        if duplicate_assets
        else ""
    )
    return f"""
    <html><body>
      <div>단위 : {unit}</div>
      <table>
        <tr><th>구분</th><th>{year}년도</th><th>{prior}년도</th><th>증감</th></tr>
        <tr><th></th><th>금액</th><th>구성비</th><th>금액</th></tr>
        <tr><td>{assets_label}</td><td>{assets}</td><td>100.00</td><td>1,498,216</td></tr>
        {extra_asset}
        <tr><td>{deposit_label}</td><td>{deposit}</td><td>88.85</td><td>1,313,185</td></tr>
        <tr><td>부 채 계</td><td>1,761,416</td><td>90.98</td><td>1,341,937</td></tr>
      </table>
    </body></html>
    """


def _parse(text: str, *, disclosure: DisclosureRecord | None = None):
    return parse_summary_size_pair(
        text,
        disclosure=disclosure or _disclosure(),
        institution_id="inst-1",
        institution_name="광안신협",
        source_locator="https://example.test/summary",
    )


def _list_row(
    *,
    disclosure_no: int,
    year: int,
    disclosure_type: str,
    reg_date: str,
) -> dict[str, object]:
    kind = "결산정기공시" if disclosure_type == "1" else "반기공시"
    return {
        "cuIngno": "02002",
        "disclosureNo": str(disclosure_no),
        "disclosureTy": disclosure_type,
        "disclosureName": f"{year}년도 {kind}",
        "regDate": reg_date,
        "shortFileName": f"{disclosure_no}.pdf",
        "bogoTy": "Y",
        "chkYn3": "Y",
    }


def test_size_pair_parser_reads_exact_rows_from_same_disclosure() -> None:
    pair = _parse(_summary_html())

    assert pair.cu_ingno == "02002"
    assert pair.source_effective_month == "2025-12"
    assert pair.deposit_liabilities_total == Decimal("1720194.000000")
    assert pair.total_assets == Decimal("1936064.000000")
    assert pair.deposit_source_text == "1,720,194"
    assert pair.total_assets_source_text == "1,936,064"
    assert len(pair.raw_sha256) == 64


def test_size_pair_parser_accepts_half_year_period() -> None:
    pair = _parse(
        _summary_html(year=2026, prior=2025, deposit="6,460", assets="7,155"),
        disclosure=_disclosure(year=2026, disclosure_type="2"),
    )

    assert pair.source_effective_month == "2026-06"
    assert pair.deposit_liabilities_total == Decimal("6460.000000")
    assert pair.total_assets == Decimal("7155.000000")


def test_size_pair_parser_rejects_wrong_unit() -> None:
    with pytest.raises(CuFundingContractError, match="백만원"):
        _parse(_summary_html(unit="억원"))


def test_size_pair_parser_rejects_missing_total_assets() -> None:
    with pytest.raises(CuFundingContractError, match="자산합계 row는 정확히 1개"):
        _parse(_summary_html(assets_label="유동자산"))


def test_size_pair_parser_rejects_duplicate_total_assets() -> None:
    with pytest.raises(CuFundingContractError, match="자산합계 row는 정확히 1개"):
        _parse(_summary_html(duplicate_assets=True))


def test_size_pair_parser_rejects_missing_deposit_liabilities() -> None:
    with pytest.raises(CuFundingContractError, match="예수부채 row는 정확히 1개"):
        _parse(_summary_html(deposit_label="부채계"))


def test_size_pair_parser_rejects_header_year_mismatch() -> None:
    with pytest.raises(CuFundingContractError, match="header 불일치"):
        _parse(_summary_html(year=2024, prior=2023), disclosure=_disclosure(year=2025))


def test_effective_month_selector_does_not_substitute_newer_disclosure() -> None:
    rows = [
        _list_row(
            disclosure_no=300,
            year=2026,
            disclosure_type="2",
            reg_date="2026-08-10",
        ),
        _list_row(
            disclosure_no=220,
            year=2025,
            disclosure_type="1",
            reg_date="2026-02-10",
        ),
    ]

    disclosure, warnings = select_disclosure_for_effective_month(
        rows,
        cu_ingno="02002",
        source_effective_month="2025-12",
    )

    assert disclosure.disclosure_no == 220
    assert disclosure.source_effective_month == "2025-12"
    assert warnings == []


def test_effective_month_selector_uses_latest_correction_within_required_period() -> None:
    rows = [
        _list_row(
            disclosure_no=220,
            year=2025,
            disclosure_type="1",
            reg_date="2026-02-10",
        ),
        _list_row(
            disclosure_no=225,
            year=2025,
            disclosure_type="1",
            reg_date="2026-02-12",
        ),
    ]

    disclosure, _warnings = select_disclosure_for_effective_month(
        rows,
        cu_ingno="02002",
        source_effective_month="2025-12",
    )

    assert disclosure.disclosure_no == 225


def test_effective_month_selector_fails_closed_when_required_period_is_absent() -> None:
    rows = [
        _list_row(
            disclosure_no=300,
            year=2026,
            disclosure_type="2",
            reg_date="2026-08-10",
        )
    ]

    with pytest.raises(CuFundingContractError, match="required=2025-12"):
        select_disclosure_for_effective_month(
            rows,
            cu_ingno="02002",
            source_effective_month="2025-12",
        )


def test_effective_month_selector_rejects_non_disclosure_month() -> None:
    with pytest.raises(CuFundingContractError, match="month 형식 오류"):
        select_disclosure_for_effective_month(
            [],
            cu_ingno="02002",
            source_effective_month="2025-09",
        )
