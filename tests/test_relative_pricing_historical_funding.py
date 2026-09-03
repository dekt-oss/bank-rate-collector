import hashlib
import sqlite3
from datetime import date, datetime
from decimal import Decimal

import pytest

from rate_monitor.services.relative_pricing_historical_funding import (
    FUNDING_PARTIAL,
    FUNDING_READY,
    FUNDING_UNAVAILABLE,
    build_historical_relative_pricing_funding,
    load_historical_funding_points_as_known_at,
)

RATE_AS_OF = date(2026, 8, 31)


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db(tmp_path):
    path = tmp_path / "funding.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE institution_funding_observations (
            institution_id TEXT,
            source_id TEXT NOT NULL,
            source_institution_key TEXT NOT NULL,
            sector TEXT NOT NULL,
            metric_code TEXT NOT NULL,
            source_effective_month TEXT NOT NULL,
            value TEXT NOT NULL,
            identity_status TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            revision INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return path


def _insert(
    path,
    *,
    institution_id="a",
    source_id="data_go_kr_fss",
    source_key="src-a",
    month="2026-08",
    value="100",
    identity_status="mapped_exact_fss_code",
    observed_at="2026-08-20 00:00:00",
    valid_from="2026-08-20 00:00:00",
    valid_to=None,
    revision=1,
):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO institution_funding_observations (
            institution_id, source_id, source_institution_key, sector,
            metric_code, source_effective_month, value, identity_status,
            observed_at, valid_from, valid_to, revision
        ) VALUES (?, ?, ?, 'savings_bank', 'deposit_liabilities_total',
                  ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            institution_id,
            source_id,
            source_key,
            month,
            value,
            identity_status,
            observed_at,
            valid_from,
            valid_to,
            revision,
        ),
    )
    conn.commit()
    conn.close()


def test_historical_loader_uses_revision_known_at_cutoff_not_current_revision(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(
        db,
        value="100",
        valid_from="2026-08-20 00:00:00",
        valid_to="2026-09-02 00:00:00",
        revision=1,
    )
    _insert(
        db,
        value="110",
        observed_at="2026-09-02 00:00:00",
        valid_from="2026-09-02 00:00:00",
        revision=2,
    )

    points = load_historical_funding_points_as_known_at(
        db,
        sector="savings_bank",
        analysis_month="2026-08",
        knowledge_as_of=RATE_AS_OF,
    )

    assert [(point.month, point.balance) for point in points] == [
        ("2026-08", Decimal("100"))
    ]


def test_future_observation_is_not_carried_backward_even_with_early_valid_from(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(
        db,
        value="999",
        observed_at="2026-09-01 00:00:00",
        valid_from="2026-08-01 00:00:00",
    )

    assert load_historical_funding_points_as_known_at(
        db,
        sector="savings_bank",
        analysis_month="2026-08",
        knowledge_as_of=RATE_AS_OF,
    ) == []


def test_non_exact_identity_is_not_admitted_to_historical_funding_population(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db, identity_status="unmapped")

    result = build_historical_relative_pricing_funding(
        db,
        sector="savings_bank",
        cohort_institution_ids=("a",),
        rate_as_of=RATE_AS_OF,
        funding_month="2026-08",
    )

    assert result.status == FUNDING_UNAVAILABLE
    assert result.funding_known_institution_ids == ()
    assert result.funding_missing_institution_ids == ("a",)


def test_exact_month_only_never_uses_nearest_previous_month(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db, month="2026-07", value="95")

    result = build_historical_relative_pricing_funding(
        db,
        sector="savings_bank",
        cohort_institution_ids=("a",),
        rate_as_of=RATE_AS_OF,
        funding_month="2026-08",
    )

    assert result.status == FUNDING_UNAVAILABLE
    assert result.rows == ()
    assert result.as_payload()["nearest_month_interpolation"] is False


def test_partial_cohort_keeps_missing_funding_null_semantics(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db, institution_id="a", source_key="src-a", month="2025-08", value="80")
    _insert(db, institution_id="a", source_key="src-a", month="2026-02", value="90")
    _insert(db, institution_id="a", source_key="src-a", month="2026-08", value="100")

    result = build_historical_relative_pricing_funding(
        db,
        sector="savings_bank",
        cohort_institution_ids=("a", "b"),
        rate_as_of=RATE_AS_OF,
        funding_month="2026-08",
    )

    assert result.status == FUNDING_PARTIAL
    assert result.funding_known_institution_ids == ("a",)
    assert result.funding_missing_institution_ids == ("b",)
    assert result.funding_join_count == 1
    assert result.funding_unjoined_count == 1
    assert result.funding_join_ratio == Decimal("0.5")
    assert result.rows[0].change_6m_pct == Decimal("0.1111111111111111111111111111")
    assert result.rows[0].change_12m_pct == Decimal("0.25")


def test_rate_and_funding_dates_are_preserved_separately_when_lagged(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db, month="2026-03", value="100")

    result = build_historical_relative_pricing_funding(
        db,
        sector="savings_bank",
        cohort_institution_ids=("a",),
        rate_as_of=RATE_AS_OF,
        funding_month="2026-03",
    )
    payload = result.as_payload()

    assert result.status == FUNDING_READY
    assert payload["rate_as_of"] == "2026-08-31"
    assert payload["funding_as_of"] == "2026-03"
    assert payload["time_alignment"] == "lagged_funding_month"


def test_funding_month_after_rate_snapshot_is_rejected(tmp_path) -> None:
    db = _db(tmp_path)

    with pytest.raises(ValueError, match="funding_month cannot be later than rate_as_of"):
        build_historical_relative_pricing_funding(
            db,
            sector="savings_bank",
            cohort_institution_ids=("a",),
            rate_as_of=RATE_AS_OF,
            funding_month="2026-09",
        )


def test_future_knowledge_cutoff_is_rejected(tmp_path) -> None:
    db = _db(tmp_path)

    with pytest.raises(ValueError, match="knowledge_as_of cannot be later than rate_as_of"):
        build_historical_relative_pricing_funding(
            db,
            sector="savings_bank",
            cohort_institution_ids=("a",),
            rate_as_of=RATE_AS_OF,
            funding_month="2026-08",
            knowledge_as_of=datetime(2026, 9, 1),
        )


def test_duplicate_canonical_institution_month_from_two_source_keys_fails_closed(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db, institution_id="a", source_key="source-1", value="100")
    _insert(db, institution_id="a", source_key="source-2", value="101")

    with pytest.raises(ValueError, match="duplicate usable exact funding point"):
        build_historical_relative_pricing_funding(
            db,
            sector="savings_bank",
            cohort_institution_ids=("a",),
            rate_as_of=RATE_AS_OF,
            funding_month="2026-08",
        )


def test_multiple_revisions_valid_at_same_cutoff_is_hard_error(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db, value="100", revision=1)
    _insert(db, value="101", revision=2)

    with pytest.raises(ValueError, match="multiple funding revisions valid"):
        load_historical_funding_points_as_known_at(
            db,
            sector="savings_bank",
            analysis_month="2026-08",
            knowledge_as_of=RATE_AS_OF,
        )


def test_historical_read_preserves_immutable_snapshot_bytes(tmp_path) -> None:
    db = _db(tmp_path)
    _insert(db)
    before = _sha256(db)

    build_historical_relative_pricing_funding(
        db,
        sector="savings_bank",
        cohort_institution_ids=("a",),
        rate_as_of=RATE_AS_OF,
        funding_month="2026-08",
    )

    assert _sha256(db) == before
    assert not (tmp_path / "funding.sqlite3-wal").exists()
    assert not (tmp_path / "funding.sqlite3-shm").exists()
