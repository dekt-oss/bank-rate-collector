from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from rate_monitor.services.source_discrepancy_triage import annotate_discrepancy_triage


def _source(
    *,
    source_id: str,
    institution: str,
    product: str,
    term_months: int,
    rate: str,
    effective_at: str | None,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "institution": institution,
        "product": product,
        "product_type": "term_deposit",
        "term_months": term_months,
        "base_rate": rate,
        "max_rate": rate,
        "source_effective_at": effective_at,
        "raw_artifact_path": f"data/raw/{source_id}.json",
        "base_source_locator": f"{source_id}:row",
    }


def _match(
    *,
    institution: str,
    product: str,
    rate_primary: str,
    rate_secondary: str,
    primary_date: str | None,
    secondary_date: str | None,
    status: str,
    term_months: int = 12,
) -> dict[str, object]:
    delta = format(Decimal(rate_primary) - Decimal(rate_secondary), "f")
    return {
        "status": status,
        "primary": _source(
            source_id="fsb",
            institution=institution,
            product=product,
            term_months=term_months,
            rate=rate_primary,
            effective_at=primary_date,
        ),
        "secondary": _source(
            source_id="finlife_savings_bank",
            institution=institution,
            product=product,
            term_months=term_months,
            rate=rate_secondary,
            effective_at=secondary_date,
        ),
        "base_rate_comparison": {
            "status": "mismatch",
            "primary": rate_primary,
            "secondary": rate_secondary,
            "delta_primary_minus_secondary": delta,
        },
        "max_rate_comparison": {
            "status": "mismatch",
            "primary": rate_primary,
            "secondary": rate_secondary,
            "delta_primary_minus_secondary": delta,
        },
    }


def _report(matches: list[dict[str, object]]) -> dict[str, object]:
    return {
        "generated_at": "2026-08-20T03:00:00+00:00",
        "scope": {"canonical_mutated": False},
        "summary": {},
        "matches": matches,
        "official_evidence_groups": [],
    }


def test_official_conflict_is_p0_and_does_not_select_authority() -> None:
    report = _report(
        [
            _match(
                institution="키움예스저축은행",
                product="e-회전yes정기예금(1년단위 변동금리상품) (인터넷뱅킹, 스마트뱅킹)",
                rate_primary="3.70",
                rate_secondary="4.05",
                primary_date="2026-08-20",
                secondary_date="2026-08-10",
                status="rate_mismatch_date_diff",
            )
        ]
    )
    report["official_evidence_groups"] = [
        {
            "evidence_group": "kiwoomyes:e-revolving:12m",
            "institution": "키움예스저축은행",
            "official_product": "e-회전yes정기예금",
            "comparison_product": (
                "e-회전yes정기예금(1년단위 변동금리상품) "
                "(인터넷뱅킹, 스마트뱅킹)"
            ),
            "product_type": "term_deposit",
            "term_months": 12,
            "status": "conflict",
            "reconciliation_signal": "official_conflict",
            "official_max_rates": ["3.90", "4.05"],
            "source_support": {
                "primary": "blocked_by_official_conflict",
                "secondary": "blocked_by_official_conflict",
            },
        }
    ]

    annotated = annotate_discrepancy_triage(report)
    item = annotated["triage"]["queue"][0]

    assert item["priority"] == "P0"
    assert item["classification"] == "official_conflict"
    assert item["official_evidence"]["reconciliation_signal"] == "official_conflict"
    assert annotated["scope"]["triage_mutates_canonical"] is False
    assert annotated["scope"]["triage_selects_authority"] is False


def test_consistent_official_evidence_supporting_primary_is_p0() -> None:
    report = _report(
        [
            _match(
                institution="청주저축은행",
                product="정기예금",
                rate_primary="3.80",
                rate_secondary="4.00",
                primary_date="2026-08-10",
                secondary_date="2026-08-10",
                status="rate_mismatch",
            )
        ]
    )
    report["official_evidence_groups"] = [
        {
            "evidence_group": "cheongju:deposit:12m",
            "institution": "청주저축은행",
            "official_product": "정기예금",
            "comparison_product": "정기예금",
            "product_type": "term_deposit",
            "term_months": 12,
            "status": "consistent",
            "reconciliation_signal": "primary_supported",
            "official_max_rates": ["3.80"],
            "source_support": {
                "primary": "supported",
                "secondary": "not_supported",
            },
        }
    ]

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["priority"] == "P0"
    assert item["classification"] == "official_evidence_discrepancy"
    assert "FINLIFE" in item["suggested_action"]


def test_same_date_material_gap_is_p1_without_official_evidence() -> None:
    report = _report(
        [
            _match(
                institution="금화저축은행",
                product="정기적금",
                rate_primary="3.00",
                rate_secondary="3.30",
                primary_date="2026-08-20",
                secondary_date="2026-08-20",
                status="rate_mismatch",
            )
        ]
    )

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["priority"] == "P1"
    assert item["score"] == 61
    assert item["classification"] == "same_effective_date_conflict"


def test_very_stale_large_gap_escalates_to_p0() -> None:
    report = _report(
        [
            _match(
                institution="대원저축은행",
                product="정기적금",
                rate_primary="3.00",
                rate_secondary="4.00",
                primary_date="2020-09-21",
                secondary_date="2026-07-20",
                status="rate_mismatch_date_diff",
            )
        ]
    )

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["priority"] == "P0"
    assert item["score"] == 88
    assert item["classification"] == "stale_source"
    codes = {component["code"] for component in item["score_components"]}
    assert "source_effective_age_ge_365d" in codes
    assert "max_rate_gap_ge_1_00pp" in codes


def test_small_recent_date_gap_stays_p3() -> None:
    report = _report(
        [
            _match(
                institution="CK저축은행",
                product="정기예금",
                rate_primary="4.00",
                rate_secondary="4.01",
                primary_date="2026-08-20",
                secondary_date="2026-08-05",
                status="rate_mismatch_date_diff",
            )
        ]
    )

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["priority"] == "P3"
    assert item["score"] == 29
    assert item["classification"] == "freshness_gap"


def test_queue_is_deterministic_and_counts_institution_clusters() -> None:
    low = _match(
        institution="민국저축은행",
        product="정기예금",
        rate_primary="3.95",
        rate_secondary="4.00",
        primary_date="2026-08-20",
        secondary_date="2026-08-11",
        status="rate_mismatch_date_diff",
    )
    high = _match(
        institution="대신저축은행",
        product="정기적금",
        rate_primary="3.00",
        rate_secondary="4.00",
        primary_date="2025-11-03",
        secondary_date="2026-07-20",
        status="rate_mismatch_date_diff",
        term_months=24,
    )
    same_bank = deepcopy(low)
    same_bank["primary"]["product"] = "톡톡정기예금"
    same_bank["secondary"]["product"] = "톡톡정기예금"

    triage = annotate_discrepancy_triage(_report([low, high, same_bank]))["triage"]

    assert [item["rank"] for item in triage["queue"]] == [1, 2, 3]
    assert triage["queue"][0]["institution"] == "대신저축은행"
    assert triage["summary"]["queue_size"] == 3
    assert triage["summary"]["institutions"] == 2
    min_guk = [item for item in triage["queue"] if item["institution"] == "민국저축은행"]
    assert {item["institution_mismatch_count"] for item in min_guk} == {2}
