from pathlib import Path


funding_path = Path("src/rate_monitor/collectors/cu/funding.py")
test_path = Path("tests/test_cu_funding.py")
funding = funding_path.read_text(encoding="utf-8")
tests = test_path.read_text(encoding="utf-8")
changed = False

anchor = '''def _record_from_row(row: dict[str, Any], expected_cu: str) -> DisclosureRecord | None:\n'''
helper = '''def _parse_disclosure_reg_date(raw: str, *, cu_ingno: str, disclosure_no: int) -> date:\n    try:\n        return date.fromisoformat(raw)\n    except ValueError as exc:\n        raise CuFundingContractError(\n            "신협 공시목록 regDate 형식 오류: "\n            f"cuIngno={cu_ingno} disclosureNo={disclosure_no} regDate={raw!r}"\n        ) from exc\n\n\n'''
if helper not in funding:
    if anchor not in funding:
        raise SystemExit("regDate helper insertion anchor missing")
    funding = funding.replace(anchor, helper + anchor, 1)
    changed = True

old = '''    newest_explicit_reg_date = max(record.reg_date for record in candidates)\n    warnings: list[str] = []\n    for disclosure_no, name, reg_date in ambiguous:\n        if not reg_date or reg_date >= newest_explicit_reg_date:\n            raise CuFundingContractError(\n                "최신권 공시의 연도를 검증할 수 없다: "\n                f"cuIngno={cu_ingno} disclosureNo={disclosure_no} "\n                f"regDate={reg_date!r} name={name!r}"\n            )\n'''
new = '''    warnings: list[str] = []\n    newest_explicit_reg_date: date | None = None\n    if ambiguous:\n        newest_explicit_reg_date = max(\n            _parse_disclosure_reg_date(\n                record.reg_date,\n                cu_ingno=cu_ingno,\n                disclosure_no=record.disclosure_no,\n            )\n            for record in candidates\n        )\n    for disclosure_no, name, reg_date in ambiguous:\n        ambiguous_date = _parse_disclosure_reg_date(\n            reg_date,\n            cu_ingno=cu_ingno,\n            disclosure_no=disclosure_no,\n        )\n        if newest_explicit_reg_date is None or ambiguous_date >= newest_explicit_reg_date:\n            raise CuFundingContractError(\n                "최신권 공시의 연도를 검증할 수 없다: "\n                f"cuIngno={cu_ingno} disclosureNo={disclosure_no} "\n                f"regDate={reg_date!r} name={name!r}"\n            )\n'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("regDate comparison block mismatch")

anchor_test = '''def test_historical_summary_mismatch_is_quarantined_but_latest_fails() -> None:\n'''
extra_test = '''def test_missing_year_quarantine_fails_closed_on_malformed_reg_date() -> None:\n    rows = [\n        _list_row(\n            disclosure_no=25111,\n            disclosure_type="2",\n            disclosure_name="2026년도 상반기 경영공시",\n            reg_date="2026-08-21",\n        ),\n        _list_row(\n            disclosure_no=7658,\n            disclosure_type="2",\n            disclosure_name="상반기결산공시",\n            reg_date="2021/09/09",\n        ),\n    ]\n\n    with pytest.raises(CuFundingContractError, match="regDate 형식 오류"):\n        _select_latest_disclosures_with_warnings(\n            rows,\n            cu_ingno="02002",\n            periods=12,\n        )\n\n\n'''
if extra_test not in tests:
    if anchor_test not in tests:
        raise SystemExit("regDate test insertion anchor missing")
    tests = tests.replace(anchor_test, extra_test + anchor_test, 1)
    changed = True

if not changed:
    print("CU regDate guard already applied")
else:
    funding_path.write_text(funding, encoding="utf-8")
    test_path.write_text(tests, encoding="utf-8")
    print("CU regDate guard applied")
