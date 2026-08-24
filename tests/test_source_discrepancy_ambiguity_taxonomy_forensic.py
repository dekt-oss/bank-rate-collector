from __future__ import annotations

import json
from pathlib import Path

from scripts.source_discrepancy_ambiguity_taxonomy_forensic import build_report


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_fresh_raw_preserves_finlife_saving_service_and_f_s_options(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    finlife = {
        "result": {
            "baseList": [
                {
                    "fin_co_no": "001",
                    "fin_prdt_cd": "ASAN-X",
                    "kor_co_nm": "아산저축은행",
                    "fin_prdt_nm": "SB톡톡-정기예금",
                    "join_way": "스마트폰",
                    "dcls_month": "202608",
                    "dcls_strt_day": "20260820",
                },
                {
                    "fin_co_no": "002",
                    "fin_prdt_cd": "JINJU-X",
                    "kor_co_nm": "진주저축은행",
                    "fin_prdt_nm": "정기예금(진주)",
                    "join_way": "영업점,인터넷",
                    "dcls_month": "202608",
                    "dcls_strt_day": "20260820",
                },
            ],
            "optionList": [
                {
                    "fin_co_no": "001",
                    "fin_prdt_cd": "ASAN-X",
                    "save_trm": "12",
                    "intr_rate_type": "S",
                    "intr_rate_type_nm": "단리",
                    "rsrv_type": "S",
                    "rsrv_type_nm": "정액적립식",
                    "intr_rate": 4.0,
                    "intr_rate2": 4.0,
                },
                {
                    "fin_co_no": "001",
                    "fin_prdt_cd": "ASAN-X",
                    "save_trm": "12",
                    "intr_rate_type": "S",
                    "intr_rate_type_nm": "단리",
                    "rsrv_type": "F",
                    "rsrv_type_nm": "자유적립식",
                    "intr_rate": 4.1,
                    "intr_rate2": 4.1,
                },
                {
                    "fin_co_no": "002",
                    "fin_prdt_cd": "JINJU-X",
                    "save_trm": "12",
                    "intr_rate_type": "M",
                    "intr_rate_type_nm": "복리",
                    "rsrv_type": "S",
                    "rsrv_type_nm": "정액적립식",
                    "intr_rate": 2.3,
                    "intr_rate2": 2.3,
                },
                {
                    "fin_co_no": "002",
                    "fin_prdt_cd": "JINJU-X",
                    "save_trm": "12",
                    "intr_rate_type": "M",
                    "intr_rate_type_nm": "복리",
                    "rsrv_type": "F",
                    "rsrv_type_nm": "자유적립식",
                    "intr_rate": 1.3,
                    "intr_rate2": 1.3,
                },
            ],
        }
    }
    _write(raw_root / "savingProductsSearch_030300_page1.json", finlife)

    fsb = {
        "REC": [
            {
                "BANK_NAME": "아산",
                "FINAN_COMP_CODE": "001",
                "FINAN_PROD_CODE": "OTHER-A",
                "PRODUCT_NAME": "정기적금",
                "START_DATE": "20260820",
            },
            {
                "BANK_NAME": "진주",
                "FINAN_COMP_CODE": "002",
                "FINAN_PROD_CODE": "OTHER-J",
                "PRODUCT_NAME": "정기적금",
                "START_DATE": "20260820",
            },
        ]
    }
    _write(raw_root / "rateinst_p1.json", fsb)

    report = build_report(raw_root)

    assert report["scope"]["production_state_used"] is False
    assert report["scope"]["identity_changed"] is False
    assert report["summary"]["target_count"] == 2
    assert report["summary"]["targets_with_finlife_saving_service_record"] == 2
    assert report["summary"]["targets_with_fsb_exact_name_counterpart"] == 0

    asan = next(item for item in report["targets"] if item["institution"] == "아산저축은행")
    assert asan["finlife_product_codes"] == ["ASAN-X"]
    assert asan["finlife_payment_methods"] == ["F", "S"]
    assert asan["finlife_records"][0]["service"] == "savingProductsSearch"
    assert asan["finlife_records"][0]["fin_prdt_nm"] == "SB톡톡-정기예금"
    assert {option["rsrv_type_nm"] for option in asan["finlife_records"][0]["options"]} == {
        "자유적립식",
        "정액적립식",
    }

    jinju = next(item for item in report["targets"] if item["institution"] == "진주저축은행")
    assert jinju["finlife_product_codes"] == ["JINJU-X"]
    assert jinju["finlife_payment_methods"] == ["F", "S"]
    assert jinju["fsb_exact_target_records"] == []
