from __future__ import annotations

from rate_monitor.services.source_discrepancy_triage import annotate_discrepancy_triage


def test_triage_queue_preserves_variant_identity() -> None:
    report = {
        "generated_at": "2026-08-23T07:00:00+00:00",
        "scope": {"canonical_mutated": False},
        "summary": {},
        "official_evidence_groups": [],
        "matches": [
            {
                "status": "rate_mismatch_date_diff",
                "match": {
                    "institution_key": "dh",
                    "product_key": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "join_channel": "branch",
                    "interest_method": "compound",
                },
                "primary": {
                    "source_id": "fsb",
                    "institution": "DH저축은행",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "join_channel": "branch",
                    "interest_method": "compound",
                    "source_effective_at": "2026-08-21",
                    "raw_artifact_path": "raw/fsb.json",
                    "base_source_locator": "fsb:row",
                },
                "secondary": {
                    "source_id": "finlife_savings_bank",
                    "institution": "DH저축은행",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "join_channel": "branch",
                    "interest_method": "compound",
                    "source_effective_at": "2026-08-20",
                    "raw_artifact_path": "raw/fin.json",
                    "base_source_locator": "fin:row",
                },
                "base_rate_comparison": {
                    "status": "mismatch",
                    "primary": "3.70",
                    "secondary": "3.85",
                    "delta_primary_minus_secondary": "-0.15",
                },
                "max_rate_comparison": {
                    "status": "mismatch",
                    "primary": "3.70",
                    "secondary": "3.85",
                    "delta_primary_minus_secondary": "-0.15",
                },
            }
        ],
    }

    queue = annotate_discrepancy_triage(report)["triage"]["queue"]

    assert len(queue) == 1
    assert queue[0]["join_channel"] == "branch"
    assert queue[0]["interest_method"] == "compound"
    assert queue[0]["priority"] == "P3"
    assert report["scope"]["triage_selects_authority"] is False
