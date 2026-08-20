from __future__ import annotations

from rate_monitor.services.source_official_contradiction_triage import (
    annotate_official_contradictions,
)


def _source(source_id: str, rate: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "institution": "대백저축은행",
        "product": "애플정기예금",
        "product_type": "term_deposit",
        "term_months": 12,
        "base_rate": rate,
        "max_rate": rate,
        "source_effective_at": "2026-08-20",
        "raw_artifact_path": f"data/raw/{source_id}.json",
        "base_source_locator": f"{source_id}:row",
    }


def _match(
    *,
    status: str = "agree",
    primary: str = "4.10",
    secondary: str = "4.10",
) -> dict[str, object]:
    delta = "0.00" if primary == secondary else "-0.20"
    cmp_status = "agree" if primary == secondary else "mismatch"
    return {
        "status": status,
        "effective_date_status": "same",
        "primary": _source("fsb", primary),
        "secondary": _source("finlife_savings_bank", secondary),
        "base_rate_comparison": {
            "status": cmp_status,
            "primary": primary,
            "secondary": secondary,
            "delta_primary_minus_secondary": delta,
        },
        "max_rate_comparison": {
            "status": cmp_status,
            "primary": primary,
            "secondary": secondary,
            "delta_primary_minus_secondary": delta,
        },
    }


def _group(
    signal: str,
    *,
    status: str = "consistent",
    institution: str = "대백저축은행",
    official_product: str = "애플정기예금복리식(인터넷뱅킹)",
    comparison_product: str = "애플정기예금",
    official_rate: str = "3.80",
) -> dict[str, object]:
    support = {
        "neither_supported": {"primary": "not_supported", "secondary": "not_supported"},
        "official_conflict": {
            "primary": "blocked_by_official_conflict",
            "secondary": "blocked_by_official_conflict",
        },
        "mixed_support": {"primary": "partial", "secondary": "not_supported"},
        "primary_supported": {"primary": "supported", "secondary": "not_supported"},
    }[signal]
    return {
        "evidence_group": "group-1",
        "institution": institution,
        "official_product": official_product,
        "comparison_product": comparison_product,
        "product_type": "term_deposit",
        "term_months": 12,
        "status": status,
        "official_base_rates": [official_rate],
        "official_max_rates": [official_rate],
        "source_support": support,
        "reconciliation_signal": signal,
        "records": [{"evidence_id": "e-1", "url": "https://example.invalid/official"}],
    }


def _report(
    *,
    match: dict[str, object] | None = None,
    groups: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "scope": {"canonical_mutated": False},
        "summary": {},
        "matches": [match or _match()],
        "official_evidence_groups": groups or [],
    }


def test_source_consensus_rejected_by_official_is_p0() -> None:
    report = _report(groups=[_group("neither_supported")])

    annotated = annotate_official_contradictions(report)
    item = annotated["official_contradictions"]["queue"][0]

    assert item["priority"] == "P0"
    assert item["score"] == 100
    assert item["classification"] == "source_consensus_official_contradiction"
    assert item["source_consensus_max_rate"] == "4.10"
    assert item["official_max_rates"] == ["3.80"]
    assert item["consensus_official_absolute_delta"] == "0.30"
    assert annotated["scope"]["official_contradiction_mutates_canonical"] is False
    assert annotated["scope"]["official_contradiction_selects_authority"] is False


def test_official_internal_conflict_is_p0_even_without_source_consensus() -> None:
    report = _report(
        match=_match(status="rate_mismatch", primary="3.70", secondary="4.05"),
        groups=[
            _group(
                "official_conflict",
                status="conflict",
                institution="대백저축은행",
                official_product="e-회전yes정기예금",
                comparison_product="애플정기예금",
                official_rate="3.90",
            )
        ],
    )
    report["official_evidence_groups"][0]["official_max_rates"] = ["3.90", "4.05"]

    item = annotate_official_contradictions(report)["official_contradictions"]["queue"][0]

    assert item["priority"] == "P0"
    assert item["score"] == 95
    assert item["classification"] == "official_internal_conflict"
    assert item["source_consensus_max_rate"] is None


def test_primary_supported_is_not_an_official_contradiction_queue_item() -> None:
    report = _report(groups=[_group("primary_supported")])

    annotated = annotate_official_contradictions(report)

    assert annotated["official_contradictions"]["summary"]["queue_size"] == 0
    assert annotated["official_contradictions"]["queue"] == []


def test_mixed_support_is_p1() -> None:
    report = _report(groups=[_group("mixed_support")])

    item = annotate_official_contradictions(report)["official_contradictions"]["queue"][0]

    assert item["priority"] == "P1"
    assert item["score"] == 70
    assert item["classification"] == "official_partial_contradiction"


def test_queue_order_is_deterministic() -> None:
    consensus = _group("neither_supported")
    consensus["evidence_group"] = "consensus"
    conflict = _group("official_conflict", status="conflict")
    conflict["evidence_group"] = "conflict"
    conflict["official_max_rates"] = ["3.90", "4.05"]

    report = _report(groups=[conflict, consensus])
    queue = annotate_official_contradictions(report)["official_contradictions"]["queue"]

    assert [item["rank"] for item in queue] == [1, 2]
    assert queue[0]["classification"] == "source_consensus_official_contradiction"
    assert queue[1]["classification"] == "official_internal_conflict"
