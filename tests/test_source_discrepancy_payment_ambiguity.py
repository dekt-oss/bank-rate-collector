from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rate_monitor.services.source_discrepancy_service import (
    _dimension_ambiguity_record,
    _representatives,
    _rows_by_base_with_ambiguities,
    _select_official_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "source-discrepancy" / "20260823-official-savings-bank.json"
DAEBAEK_CAPTURE_SHA256 = "27fac90b077761ed4a04475b45452acf878574d4c7ef89fd92cb152e21747a6a"


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


def test_official_wildcard_cannot_bypass_payment_method_ambiguity() -> None:
    branch_s = _row(payment_method="S", rate="2.10")
    branch_f = _row(payment_method="F", rate="3.05")
    internet = _row(payment_method=None, rate="2.50")
    internet["join_channel"] = "internet"

    representatives, ambiguous = _representatives([branch_s, branch_f, internet])
    candidates_by_base = _rows_by_base_with_ambiguities(representatives, ambiguous)
    candidates = next(iter(candidates_by_base.values()))

    matched, meta = _select_official_candidate(
        {"join_channel": "any", "interest_method": "simple"},
        candidates,
    )

    assert matched is None
    assert meta["status"] == "ambiguous_variant"
    assert len(meta["candidate_variants"]) == 3
    assert {item["join_channel"] for item in meta["candidate_variants"]} == {
        "branch",
        "internet",
    }


def test_dimension_ambiguity_preserves_non_ambiguous_counterpart() -> None:
    candidates = [
        _row(payment_method="S", rate="2.10"),
        _row(payment_method="F", rate="3.05"),
    ]
    _, ambiguous = _representatives(candidates)
    key, blocked = next(iter(ambiguous.items()))
    counterpart = _row(payment_method=None, rate="2.10")
    counterpart["source_id"] = "fsb"

    record = _dimension_ambiguity_record(
        key,
        blocked,
        side="secondary",
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
        counterpart=counterpart,
    )

    assert record["counterpart_side"] == "primary"
    assert record["counterpart"]["source_id"] == "fsb"
    assert record["counterpart"]["join_channel"] == "branch"
    assert record["counterpart"]["payment_method"] is None
    assert record["counterpart"]["base_rate"] == "2.10"
    assert record["counterpart"]["max_rate"] == "2.10"


def test_daebaek_live_evidence_keeps_capture_checksum() -> None:
    payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    records = [
        record
        for record in payload["records"]
        if record.get("institution") == "대백저축은행"
        and record.get("capture_method") == "live_http_artifact"
    ]

    assert len(records) == 4
    assert {record.get("capture_artifact_sha256") for record in records} == {
        DAEBAEK_CAPTURE_SHA256
    }
