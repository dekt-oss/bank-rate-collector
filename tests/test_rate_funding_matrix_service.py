from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from rate_monitor.services import rate_funding_matrix_service as matrix


def _funding_row(institution_id: str, growth: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        institution_id=institution_id,
        sector="nh_local",
        balance=Decimal("1000"),
        change_6m_pct=Decimal(growth) if growth is not None else None,
    )


def test_matrix_fails_closed_when_historical_rate_is_missing(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "db.sqlite3"
    db.touch()
    monkeypatch.setattr(
        matrix,
        "build_institution_funding_read_model_from_db",
        lambda *_args, **_kwargs: [_funding_row("a", "0.05"), _funding_row("b", "0.02")],
    )
    monkeypatch.setattr(matrix, "_historical_rates", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(matrix, "_institution_names", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(matrix, "_current_rate_institution_count", lambda *_args, **_kwargs: 2)

    result = matrix._sector_matrix(db, sector="nh_local", analysis_month="2025-12")

    assert result["available"] is False
    assert result["status"] == "historical_rate_unavailable"
    assert result["paired_institutions"] == 0
    assert result["current_rate_institutions_not_carried_back"] == 2
    assert result["median_rate_pct"] is None
    assert result["points"] == []


def test_matrix_uses_only_exact_pairs_and_same_sector_medians(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "db.sqlite3"
    db.touch()
    monkeypatch.setattr(
        matrix,
        "build_institution_funding_read_model_from_db",
        lambda *_args, **_kwargs: [
            _funding_row("a", "0.06"),
            _funding_row("b", "0.02"),
            _funding_row("missing-growth", None),
        ],
    )
    monkeypatch.setattr(
        matrix,
        "_historical_rates",
        lambda *_args, **_kwargs: {
            "a": Decimal("3.20"),
            "b": Decimal("3.00"),
            "missing-growth": Decimal("9.99"),
        },
    )
    monkeypatch.setattr(
        matrix,
        "_institution_names",
        lambda *_args, **_kwargs: {"a": "A농협", "b": "B농협"},
    )
    monkeypatch.setattr(matrix, "_current_rate_institution_count", lambda *_args, **_kwargs: 3)

    result = matrix._sector_matrix(db, sector="nh_local", analysis_month="2025-12")

    assert result["available"] is True
    assert result["paired_institutions"] == 2
    assert result["funding_growth_6m_institutions"] == 2
    assert result["median_rate_pct"] == "3.10"
    assert result["median_growth_6m_pct"] == "0.04"
    assert {point["institution_id"] for point in result["points"]} == {"a", "b"}


def test_representative_rate_applies_strategy_source_precedence_and_product_max(monkeypatch) -> None:
    monkeypatch.setattr(matrix, "dedupe_sources", lambda: ("secondary",))
    rows = [
        {"institution_id": "a", "product_id": "a-primary-1", "source_id": "primary", "rate_value": 3.10},
        {"institution_id": "a", "product_id": "a-primary-2", "source_id": "primary", "rate_value": 3.20},
        {"institution_id": "a", "product_id": "a-secondary", "source_id": "secondary", "rate_value": 9.99},
        {"institution_id": "b", "product_id": "b-secondary", "source_id": "secondary", "rate_value": 3.30},
    ]

    result = matrix._representative_rates(rows)

    assert result == {"a": Decimal("3.2"), "b": Decimal("3.3")}


def test_matrix_contract_prohibits_current_rate_carryback(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "db.sqlite3"
    db.touch()
    positions = {
        "display_order": [],
        "sectors": {},
    }
    result = matrix.build_rate_funding_matrix(db, funding_positions=positions)

    assert result["available"] is False
    assert result["contract"]["rate_field"] == "max_rate"
    assert result["contract"]["rate_representative"] == "institution_product_representative_max"
    assert result["contract"]["source_precedence"] == "presentation.db_only_sources"
    assert result["contract"]["current_rate_carryback"] is False
    assert result["contract"]["missing_rate_as_zero"] is False
    assert result["contract"]["nearest_month_interpolation"] is False
    assert result["contract"]["coverage_quality_threshold"] is None
