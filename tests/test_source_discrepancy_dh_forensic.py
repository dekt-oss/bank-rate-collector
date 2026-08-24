from __future__ import annotations

from pathlib import Path

from scripts.source_discrepancy_dh_forensic import (
    _official_evidence,
    _scan_finlife,
    _scan_fsb,
)


def test_scan_finlife_preserves_branch_and_mobile_12m_records() -> None:
    payload = {
        "result": {
            "baseList": [
                {
                    "fin_co_no": "0010000",
                    "fin_prdt_cd": "DHB",
                    "kor_co_nm": "DH저축은행",
                    "fin_prdt_nm": "정기예금",
                    "join_way": "영업점",
                    "dcls_strt_day": "20260820",
                },
                {
                    "fin_co_no": "0010000",
                    "fin_prdt_cd": "DHM",
                    "kor_co_nm": "DH저축은행",
                    "fin_prdt_nm": "정기예금(비대면)",
                    "join_way": "스마트폰",
                    "dcls_strt_day": "20260820",
                },
            ],
            "optionList": [
                {
                    "fin_co_no": "0010000",
                    "fin_prdt_cd": "DHB",
                    "save_trm": "12",
                    "intr_rate_type_nm": "단리",
                    "intr_rate": 3.85,
                    "intr_rate2": 3.85,
                },
                {
                    "fin_co_no": "0010000",
                    "fin_prdt_cd": "DHM",
                    "save_trm": "12",
                    "intr_rate_type_nm": "복리",
                    "intr_rate": 3.70,
                    "intr_rate2": 3.70,
                },
                {
                    "fin_co_no": "0010000",
                    "fin_prdt_cd": "DHB",
                    "save_trm": "24",
                    "intr_rate_type_nm": "단리",
                    "intr_rate": 2.30,
                    "intr_rate2": 2.30,
                },
            ],
        }
    }

    rows = _scan_finlife(payload, "fresh.json")

    assert len(rows) == 2
    assert {row["product"] for row in rows} == {"정기예금", "정기예금(비대면)"}
    assert {str(row["term_months"]) for row in rows} == {"12"}
    assert {row["raw_path"] for row in rows} == {"fresh.json"}


def test_scan_fsb_preserves_12m_simple_and_compound_columns() -> None:
    payload = {
        "REC": [
            {
                "BANK_NAME": "DH     ",
                "URL": "https://www.dhsavingsbank.co.kr",
                "FINAN_COMP_CODE": "0010000",
                "FINAN_PROD_CODE": "310001",
                "PRODUCT_NAME": "정기예금",
                "PRODUCT_URL": "https://www.dhsavingsbank.co.kr/ProdList_001.act?rnum=17",
                "START_DATE": "20260821",
                "JUNG_12M_DAN": "3.70",
                "TOP_12M_DAN": "3.70",
                "JUNG_12M_BOK": "3.70",
                "TOP_12M_BOK": "3.70",
            },
            {
                "BANK_NAME": "DH     ",
                "URL": "https://www.dhsavingsbank.co.kr",
                "FINAN_COMP_CODE": "0010000",
                "FINAN_PROD_CODE": "310002",
                "PRODUCT_NAME": "정기예금(비대면)",
                "PRODUCT_URL": "https://www.dhsavingsbank.co.kr/ProdList_001.act?rnum=18",
                "START_DATE": "20260821",
                "JUNG_12M_DAN": "3.60",
                "TOP_12M_DAN": "3.60",
                "JUNG_12M_BOK": "3.60",
                "TOP_12M_BOK": "3.60",
            },
        ]
    }

    rows = _scan_fsb(payload, "ratedepo.json")

    assert len(rows) == 2
    branch = next(row for row in rows if row["product"] == "정기예금")
    mobile = next(row for row in rows if row["product"] == "정기예금(비대면)")
    assert branch["simple_rate"] == "3.70"
    assert branch["compound_rate"] == "3.70"
    assert mobile["simple_rate"] == "3.60"
    assert mobile["compound_rate"] == "3.60"


def test_official_evidence_hashes_file_and_keeps_12m_context(tmp_path: Path) -> None:
    html = tmp_path / "official.html"
    html.write_text(
        "<table><tr><td>12개월</td><td>3.85</td><td>3.91</td></tr></table>",
        encoding="utf-8",
    )

    evidence = _official_evidence(html, "https://example.test/product")

    assert evidence["resolved"] is True
    assert evidence["sha256"]
    assert evidence["content_length"] > 0
    assert evidence["twelve_month_contexts"]
    assert "3.85" in evidence["twelve_month_contexts"][0]
