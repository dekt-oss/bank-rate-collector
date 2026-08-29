from rate_monitor.collectors.cu.funding import select_latest_disclosures


def test_cu_disclosure_year_accepts_nyeon_without_do_suffix() -> None:
    rows = [
        {
            "cuIngno": "02022",
            "disclosureNo": 18387,
            "disclosureTy": "2",
            "disclosureName": "2024년 상반기결산공시",
            "regDate": "2024-08-01",
            "shortFileName": "summary.pdf",
            "bogoTy": "Y",
            "chkYn3": "Y",
        }
    ]

    selected = select_latest_disclosures(rows, cu_ingno="02022", periods=1)

    assert len(selected) == 1
    assert selected[0].source_effective_month == "2024-06"
    assert selected[0].disclosure_no == 18387
