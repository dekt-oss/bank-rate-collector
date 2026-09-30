from __future__ import annotations

import sqlite3
from pathlib import Path

from rate_monitor.services.size_peer_strategy_payload import (
    _active_sectors_and_common_month,
    build_size_peer_strategy_payload,
)
from rate_monitor.services.strategy_service import _size_peer_with_pair_coverage
from tests.test_size_peer_strategy_payload import _busan_outlet, _current_product, _fixture


def _cu_financial_pair(
    conn: sqlite3.Connection,
    *,
    institution_id: str,
    source_key: str,
    month: str,
    funding: str,
    assets: str,
) -> None:
    for metric, value in (
        ("deposit_liabilities_total", funding),
        ("total_assets", assets),
    ):
        conn.execute(
            """
            INSERT INTO institution_funding_observations
            (institution_id, source_id, source_institution_key, source_crno, sector,
             metric_code, source_effective_month, value, unit, identity_status, valid_to)
            VALUES (?, 'cu_disclosure_funding', ?, NULL, 'cu', ?, ?, ?,
                    'million_krw', 'mapped_exact_cu_ingno', NULL)
            """,
            (institution_id, source_key, metric, month, value),
        )


def test_cu_is_promoted_only_on_common_vintage_and_remote_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _fixture(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO institutions VALUES (?, 'cu', ?, 1)",
            (
                ("cu-mobile", "모바일신협"),
                ("cu-any", "ANY신협"),
            ),
        )
        _cu_financial_pair(
            conn,
            institution_id="cu-mobile",
            source_key="100001",
            month="2025-12",
            funding="1820000",
            assets="2070000",
        )
        _cu_financial_pair(
            conn,
            institution_id="cu-any",
            source_key="100002",
            month="2025-12",
            funding="1810000",
            assets="2065000",
        )
        # Even if a generic outlet row exists, CU rate disclosure geography is only a
        # query condition and must not become official Busan branch-locality evidence.
        _busan_outlet(
            conn,
            outlet_id="out-cu-mobile",
            institution_id="cu-mobile",
            district="동구",
            fsb_link=False,
        )
        _busan_outlet(
            conn,
            outlet_id="out-cu-any",
            institution_id="cu-any",
            district="중구",
            fsb_link=False,
        )
        _current_product(
            conn,
            institution_id="cu-mobile",
            sector="cu",
            source_id="cu",
            channel="mobile",
            last_seen="2026-09-03 09:00:00",
            outlet_id="out-cu-mobile",
        )
        _current_product(
            conn,
            institution_id="cu-any",
            sector="cu",
            source_id="cu",
            channel="any",
            last_seen="2026-09-03 09:00:00",
            outlet_id="out-cu-any",
        )
        conn.commit()
    finally:
        conn.close()

    payload = build_size_peer_strategy_payload(db_path)

    assert payload["status"] == "ready"
    assert payload["financial_as_of"] == "2025-12"
    assert payload["eligibility_as_of"] == "2026-09-03"
    assert payload["supported_sectors"] == ["savings_bank", "nh_local", "cu"]
    assert payload["unsupported_sectors"] == ["kfcc"]
    assert payload["coverage_note"] == "현재 총자산 비교 가능 업권: 저축은행 · 농·축협 · 신협"
    assert payload["eligibility_source_as_of"] == {
        "cu": "2026-09-03",
        "fsb": "2026-09-05",
        "nh_local": "2026-09-04",
    }

    enriched = _size_peer_with_pair_coverage(db_path, payload)
    assert enriched["financial_pair_coverage"] == {
        "savings_bank": {
            "source_id": "data_go_savings_bank_funding",
            "financial_as_of": "2025-12",
            "pair_complete_institutions": 2,
        },
        "nh_local": {
            "source_id": "data_go_agri_coop_funding",
            "financial_as_of": "2025-12",
            "pair_complete_institutions": 2,
        },
        "cu": {
            "source_id": "cu_disclosure_funding",
            "financial_as_of": "2025-12",
            "pair_complete_institutions": 2,
        },
    }
    assert enriched["coverage_note"].endswith(
        "공통월 pair: 저축은행 2 · 농·축협 2 · 신협 2"
    )

    remote_ids = {
        row["institution_id"] for row in payload["modes"]["remote"]["display_rows"]
    }
    assert "cu-mobile" in remote_ids
    assert "cu-any" not in remote_ids

    branch_ids = {
        row["institution_id"]
        for row in payload["modes"]["branch_busan"]["display_rows"]
    }
    assert "cu-mobile" not in branch_ids
    assert "cu-any" not in branch_ids


def test_cu_without_exact_common_vintage_does_not_break_existing_size_peer(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "rates.db"
    _fixture(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO institutions VALUES ('cu-newer', 'cu', '최신신협', 1)"
        )
        _cu_financial_pair(
            conn,
            institution_id="cu-newer",
            source_key="100003",
            month="2026-06",
            funding="1600000",
            assets="1800000",
        )
        _current_product(
            conn,
            institution_id="cu-newer",
            sector="cu",
            source_id="cu",
            channel="internet",
            last_seen="2026-09-03 09:00:00",
        )
        conn.commit()
    finally:
        conn.close()

    payload = build_size_peer_strategy_payload(db_path)

    assert payload["status"] == "ready"
    assert payload["financial_as_of"] == "2025-12"
    assert payload["supported_sectors"] == ["savings_bank", "nh_local"]
    assert payload["unsupported_sectors"] == ["cu", "kfcc"]
    assert payload["coverage_note"] == "현재 총자산 비교 가능 업권: 저축은행 · 농·축협"

    enriched = _size_peer_with_pair_coverage(db_path, payload)
    assert set(enriched["financial_pair_coverage"]) == {"savings_bank", "nh_local"}
    assert "신협" not in enriched["coverage_note"]
    assert "공통월 pair: 저축은행 2 · 농·축협 2" in enriched["coverage_note"]


def test_cu_cannot_roll_baseline_financial_month_backward() -> None:
    rows = [
        {
            "sector": sector,
            "source_effective_month": month,
            "metric_code": metric,
            "value": "1",
        }
        for sector, months in (
            ("savings_bank", ("2025-12", "2026-03")),
            ("nh_local", ("2025-12", "2026-03")),
            ("cu", ("2025-12",)),
        )
        for month in months
        for metric in ("deposit_liabilities_total", "total_assets")
    ]

    supported, financial_as_of = _active_sectors_and_common_month(rows)  # type: ignore[arg-type]

    assert financial_as_of == "2026-03"
    assert supported == ("savings_bank", "nh_local")
