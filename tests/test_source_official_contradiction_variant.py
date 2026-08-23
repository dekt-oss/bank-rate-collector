from __future__ import annotations

from rate_monitor.services.source_official_contradiction_triage import (
    annotate_official_contradictions,
)


def _match(join_channel: str, *, rate: str = "4.10") -> dict[str, object]:
    source = {
        "institution": "대백저축은행",
        "product": "애플정기예금",
        "product_type": "term_deposit",
        "term_months": 12,
        "join_channel": join_channel,
        "interest_method": "simple",
        "base_rate": rate,
        "max_rate": rate,
        "source_effective_at": "2026-08-20",
    }
    return {
        "status": "agree",
        "match": {
            "join_channel": join_channel,
            "interest_method": "simple",
        },
        "primary": {"source_id": "fsb", **source},
        "secondary": {"source_id": "finlife_savings_bank", **source},
        "base_rate_comparison": {
            "status": "agree",
            "primary": rate,
            "secondary": rate,
            "delta_primary_minus_secondary": "0.00",
        },
        "max_rate_comparison": {
            "status": "agree",
            "primary": rate,
            "secondary": rate,
            "delta_primary_minus_secondary": "0.00",
        },
    }


def _group(join_channel: str, *, rate: str = "3.80") -> dict[str, object]:
    return {
        "evidence_group": f"debec:{join_channel}:simple:12m",
        "institution": "대백저축은행",
        "official_product": "애플정기예금단리식",
        "comparison_product": "애플정기예금",
        "product_type": "term_deposit",
        "term_months": 12,
        "join_channel": join_channel,
        "interest_method": "simple",
        "status": "consistent",
        "official_base_rates": [rate],
        "official_max_rates": [rate],
        "source_support": {"primary": "not_supported", "secondary": "not_supported"},
        "reconciliation_signal": "neither_supported",
        "records": [],
    }


def _report(groups: list[dict[str, object]]) -> dict[str, object]:
    return {
        "scope": {"canonical_mutated": False},
        "summary": {},
        "matches": [_match("branch"), _match("mobile")],
        "official_evidence_groups": groups,
    }


def test_official_contradiction_pairs_only_same_channel_variant() -> None:
    queue = annotate_official_contradictions(_report([_group("mobile")]))[
        "official_contradictions"
    ]["queue"]

    assert len(queue) == 1
    item = queue[0]
    assert item["join_channel"] == "mobile"
    assert item["source_pair"]["join_channel"] == "mobile"
    assert item["source_variant_match"]["mode"] == "exact_variant"
    assert item["classification"] == "source_consensus_official_contradiction"


def test_wildcard_official_group_does_not_guess_between_source_variants() -> None:
    queue = annotate_official_contradictions(_report([_group("any")]))[
        "official_contradictions"
    ]["queue"]

    assert len(queue) == 1
    item = queue[0]
    assert item["source_pair"] is None
    assert item["source_variant_match"]["status"] == "ambiguous_variant"
    assert item["classification"] == "official_rejects_both_sources"
    assert item["source_consensus_max_rate"] is None
