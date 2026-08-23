from __future__ import annotations

from rate_monitor.services.official_evidence_policy import annotate_official_evidence_policy


def _comparison(
    *,
    evidence_group: str,
    join_channel: str,
    interest_method: str,
    rate: str,
) -> dict[str, object]:
    return {
        "official": {
            "evidence_id": evidence_group,
            "evidence_group": evidence_group,
            "institution": "대백저축은행",
            "official_product": "애플정기예금",
            "product": "애플정기예금",
            "product_type": "term_deposit",
            "term_months": 12,
            "join_channel": join_channel,
            "interest_method": interest_method,
            "base_rate": rate,
            "max_rate": rate,
            "captured_at": "2026-08-23T17:12:00+09:00",
            "url": "https://example.invalid/official",
        },
        "sources": {"primary": None, "secondary": None},
    }


def test_different_variants_with_different_rates_are_not_official_conflicts() -> None:
    report = {
        "generated_at": "2026-08-23T08:12:00+00:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 2},
        "official_evidence": [
            _comparison(
                evidence_group="debec:internet:simple:12m",
                join_channel="internet",
                interest_method="simple",
                rate="4.10",
            ),
            _comparison(
                evidence_group="debec:mobile:simple:12m",
                join_channel="mobile",
                interest_method="simple",
                rate="3.80",
            ),
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    groups = annotated["official_evidence_groups"]

    assert len(groups) == 2
    assert {group["status"] for group in groups} == {"consistent"}
    assert annotated["summary"]["official_evidence_conflicts"] == 0
    assert {(group["join_channel"], group["official_max_rates"][0]) for group in groups} == {
        ("internet", "4.10"),
        ("mobile", "3.80"),
    }
