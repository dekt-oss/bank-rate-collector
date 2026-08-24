from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from rate_monitor.services.source_discrepancy_triage import annotate_discrepancy_triage


def _source(
    *,
    source_id: str,
    rate: str,
    effective_at: str | None,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "institution": "계약테스트저축은행",
        "product": "계약테스트상품",
        "product_type": "term_deposit",
        "term_months": 12,
        "join_channel": "branch",
        "interest_method": "simple",
        "base_rate": rate,
        "max_rate": rate,
        "source_effective_at": effective_at,
        "raw_artifact_path": f"data/raw/{source_id}.json",
        "base_source_locator": f"{source_id}:row",
    }


def _match(
    *,
    primary_rate: str = "3.00",
    secondary_rate: str = "3.10",
    primary_date: str | None = "2026-08-23",
    secondary_date: str | None = "2026-08-22",
    status: str = "rate_mismatch_date_diff",
) -> dict[str, object]:
    delta = format(Decimal(primary_rate) - Decimal(secondary_rate), "f")
    return {
        "status": status,
        "match": {
            "institution_key": "contract-test",
            "product_key": "계약테스트상품",
            "product_type": "term_deposit",
            "term_months": 12,
            "join_channel": "branch",
            "interest_method": "simple",
        },
        "primary": _source(
            source_id="fsb",
            rate=primary_rate,
            effective_at=primary_date,
        ),
        "secondary": _source(
            source_id="finlife_savings_bank",
            rate=secondary_rate,
            effective_at=secondary_date,
        ),
        "base_rate_comparison": {
            "status": "mismatch",
            "primary": primary_rate,
            "secondary": secondary_rate,
            "delta_primary_minus_secondary": delta,
        },
        "max_rate_comparison": {
            "status": "mismatch",
            "primary": primary_rate,
            "secondary": secondary_rate,
            "delta_primary_minus_secondary": delta,
        },
    }


def _official_group(signal: str) -> dict[str, object]:
    status = "conflict" if signal == "official_conflict" else "consistent"
    return {
        "evidence_group": f"contract:{signal}",
        "institution": "계약테스트저축은행",
        "official_product": "계약테스트상품",
        "comparison_product": "계약테스트상품",
        "product_type": "term_deposit",
        "term_months": 12,
        "join_channel": "branch",
        "interest_method": "simple",
        "status": status,
        "reconciliation_signal": signal,
        "official_max_rates": ["3.00"],
        "source_support": {
            "primary": "supported",
            "secondary": "not_supported",
        },
    }


def _report(
    match: dict[str, object],
    *,
    official_signal: str | None = None,
) -> dict[str, object]:
    return {
        "generated_at": "2026-08-24T00:00:00+00:00",
        "scope": {"canonical_mutated": False},
        "summary": {},
        "matches": [match],
        "official_evidence_groups": (
            [_official_group(official_signal)] if official_signal is not None else []
        ),
    }


def _item(
    match: dict[str, object],
    *,
    official_signal: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    annotated = annotate_discrepancy_triage(
        _report(match, official_signal=official_signal)
    )
    return annotated["triage"]["queue"][0], annotated


@pytest.mark.parametrize(
    ("primary_date", "delta", "expected"),
    [
        # generated_at 2026-08-24 기준. 90일은 stale_source 경계다.
        ("2026-05-26", "0.19", "stale_source"),
        ("2026-05-27", "0.19", "freshness_gap"),
        # 0.20%p는 material_rate_gap 경계다.
        ("2026-08-23", "0.20", "material_rate_gap"),
        ("2026-08-23", "0.19", "freshness_gap"),
    ],
)
def test_classification_boundaries_are_explicit_and_deterministic(
    primary_date: str,
    delta: str,
    expected: str,
) -> None:
    primary_rate = Decimal("3.00")
    secondary_rate = primary_rate + Decimal(delta)
    item, annotated = _item(
        _match(
            primary_rate=format(primary_rate, "f"),
            secondary_rate=format(secondary_rate, "f"),
            primary_date=primary_date,
            secondary_date="2026-08-24",
        )
    )

    assert item["classification"] == expected
    assert annotated["scope"]["triage_mutates_canonical"] is False
    assert annotated["scope"]["triage_selects_authority"] is False


def test_same_effective_date_conflict_precedes_staleness_and_rate_gap() -> None:
    item, _ = _item(
        _match(
            primary_rate="2.00",
            secondary_rate="4.00",
            primary_date="2025-01-01",
            secondary_date="2025-01-01",
            status="rate_mismatch",
        )
    )

    assert item["classification"] == "same_effective_date_conflict"
    codes = {component["code"] for component in item["score_components"]}
    assert "max_rate_gap_ge_1_00pp" in codes
    assert "source_effective_age_ge_365d" in codes


def test_material_gap_precedes_unknown_effective_date_by_current_contract() -> None:
    material, _ = _item(
        _match(
            primary_rate="3.00",
            secondary_rate="3.20",
            primary_date=None,
            secondary_date="2026-08-24",
            status="rate_mismatch_date_unknown",
        )
    )
    minor, _ = _item(
        _match(
            primary_rate="3.00",
            secondary_rate="3.19",
            primary_date=None,
            secondary_date="2026-08-24",
            status="rate_mismatch_date_unknown",
        )
    )

    assert material["classification"] == "material_rate_gap"
    assert minor["classification"] == "unknown_effective_date"


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ("official_conflict", "official_conflict"),
        ("primary_supported", "official_evidence_discrepancy"),
        ("secondary_supported", "official_evidence_discrepancy"),
        ("neither_supported", "official_evidence_discrepancy"),
        ("both_supported", "official_evidence_discrepancy"),
        ("mixed_support", "official_evidence_discrepancy"),
    ],
)
def test_official_signal_precedence_is_classification_only_not_authority(
    signal: str,
    expected: str,
) -> None:
    item, annotated = _item(
        _match(
            primary_rate="2.00",
            secondary_rate="4.00",
            primary_date="2020-01-01",
            secondary_date="2026-08-24",
        ),
        official_signal=signal,
    )

    assert item["classification"] == expected
    assert item["official_evidence"]["reconciliation_signal"] == signal
    assert annotated["scope"]["triage_mutates_canonical"] is False
    assert annotated["scope"]["triage_selects_authority"] is False
    assert annotated["triage"]["authority_semantics"].startswith(
        "investigation_priority_only"
    )


def test_identical_input_produces_identical_queue_and_does_not_mutate_input() -> None:
    original = _report(
        _match(
            primary_rate="3.00",
            secondary_rate="4.00",
            primary_date="2025-11-03",
            secondary_date="2026-07-20",
        )
    )
    first_input = deepcopy(original)
    second_input = deepcopy(original)

    first = annotate_discrepancy_triage(first_input)
    second = annotate_discrepancy_triage(second_input)

    assert first["triage"] == second["triage"]
    assert original["scope"] == {"canonical_mutated": False}
    assert original.get("triage") is None


def test_current_queue_class_families_replay_without_authority_selection() -> None:
    # 현재 production queue의 두 대표 계열을 고정한다.
    # 대신 24/36m: 큰 gap + 90일 이상 stale effective date -> stale_source.
    daishin, daishin_report = _item(
        _match(
            primary_rate="3.00",
            secondary_rate="4.00",
            primary_date="2025-11-03",
            secondary_date="2026-07-20",
        )
    )
    # DH 12m variants: 0.10~0.15%p + 최근의 서로 다른 effective date -> freshness_gap.
    dh, dh_report = _item(
        _match(
            primary_rate="3.70",
            secondary_rate="3.85",
            primary_date="2026-08-21",
            secondary_date="2026-08-20",
        )
    )

    assert daishin["classification"] == "stale_source"
    assert dh["classification"] == "freshness_gap"
    for report in (daishin_report, dh_report):
        assert report["scope"]["triage_mutates_canonical"] is False
        assert report["scope"]["triage_selects_authority"] is False
