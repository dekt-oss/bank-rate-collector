from __future__ import annotations

from rate_monitor.services.source_discrepancy_triage import annotate_discrepancy_triage


def _match(
    *,
    join_channel: str,
    interest_method: str,
    primary_rate: str = "3.70",
    secondary_rate: str = "3.85",
) -> dict[str, object]:
    return {
        "status": "rate_mismatch_date_diff",
        "match": {
            "institution_key": "dh",
            "product_key": "정기예금",
            "product_type": "term_deposit",
            "term_months": 12,
            "join_channel": join_channel,
            "interest_method": interest_method,
        },
        "primary": {
            "source_id": "fsb",
            "institution": "DH저축은행",
            "product": "정기예금",
            "product_type": "term_deposit",
            "term_months": 12,
            "join_channel": join_channel,
            "interest_method": interest_method,
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
            "join_channel": join_channel,
            "interest_method": interest_method,
            "source_effective_at": "2026-08-20",
            "raw_artifact_path": "raw/fin.json",
            "base_source_locator": "fin:row",
        },
        "base_rate_comparison": {
            "status": "mismatch",
            "primary": primary_rate,
            "secondary": secondary_rate,
            "delta_primary_minus_secondary": "-0.15",
        },
        "max_rate_comparison": {
            "status": "mismatch",
            "primary": primary_rate,
            "secondary": secondary_rate,
            "delta_primary_minus_secondary": "-0.15",
        },
    }


def _official_group(
    *,
    evidence_group: str,
    join_channel: str,
    interest_method: str,
) -> dict[str, object]:
    return {
        "evidence_group": evidence_group,
        "institution": "DH저축은행",
        "official_product": "정기예금",
        "comparison_product": "정기예금",
        "product_type": "term_deposit",
        "term_months": 12,
        "join_channel": join_channel,
        "interest_method": interest_method,
        "status": "consistent",
        "reconciliation_signal": "primary_supported",
        "official_max_rates": ["3.70"],
        "source_support": {"primary": "supported", "secondary": "not_supported"},
    }


def _report(
    match: dict[str, object],
    groups: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "generated_at": "2026-08-23T07:00:00+00:00",
        "scope": {"canonical_mutated": False},
        "summary": {},
        "official_evidence_groups": groups or [],
        "matches": [match],
    }


def test_triage_queue_preserves_variant_identity() -> None:
    report = _report(_match(join_channel="branch", interest_method="compound"))

    queue = annotate_discrepancy_triage(report)["triage"]["queue"]

    assert len(queue) == 1
    assert queue[0]["join_channel"] == "branch"
    assert queue[0]["interest_method"] == "compound"
    assert queue[0]["priority"] == "P3"
    assert report["scope"]["triage_selects_authority"] is False


def test_official_evidence_never_crosses_channel_variant() -> None:
    report = _report(
        _match(join_channel="mobile", interest_method="simple"),
        [_official_group(evidence_group="branch", join_channel="branch", interest_method="simple")],
    )

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["official_evidence"] is None
    assert item["official_variant_match"]["status"] == "no_compatible_variant"
    assert item["classification"] != "official_evidence_discrepancy"


def test_unknown_source_variant_does_not_guess_between_official_channels() -> None:
    report = _report(
        _match(join_channel="unknown", interest_method="simple"),
        [
            _official_group(evidence_group="branch", join_channel="branch", interest_method="simple"),
            _official_group(evidence_group="mobile", join_channel="mobile", interest_method="simple"),
        ],
    )

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["official_evidence"] is None
    assert item["official_variant_match"]["status"] == "ambiguous_variant"
    assert set(item["official_variant_match"]["candidate_groups"]) == {"branch", "mobile"}


def test_exact_official_variant_beats_wildcard_group() -> None:
    report = _report(
        _match(join_channel="branch", interest_method="simple"),
        [
            _official_group(evidence_group="wildcard", join_channel="any", interest_method="simple"),
            _official_group(evidence_group="branch", join_channel="branch", interest_method="simple"),
        ],
    )

    item = annotate_discrepancy_triage(report)["triage"]["queue"][0]

    assert item["official_evidence"]["evidence_group"] == "branch"
    assert item["official_variant_match"]["mode"] == "exact_variant"
    assert item["classification"] == "official_evidence_discrepancy"
